"""Hybrid dense + sparse retrieval over an OKF bundle.

Implements the "hybrid dense-sparse vector search" layer from the Krishi-Vyom
technical document.

Why hybrid and not dense alone: agriculture queries carry both loose descriptive
language ("leaf turning yellow with sticky stuff") which needs semantic matching,
and exact tokens ("Diafenthiuron", "Bemisia tabaci", "50% WP") where a lexical
miss is unrecoverable. BM25 catches the second class; embeddings catch the first.

Fusion is Reciprocal Rank Fusion — it combines rankings rather than raw scores,
so it needs no per-corpus score normalisation tuning. That matters here because
the corpus will grow through the hackathon and a tuned normalisation would drift.
"""

from __future__ import annotations

import pickle
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from chunking import Chunk

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RRF_K = 60  # standard RRF damping constant

_TOKEN_RE = re.compile(r"[a-z0-9%ऀ-ॿঀ-৿଀-୿ఀ-౿]+")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokenizer that keeps % (for '50% WP') and Indic ranges."""
    return _TOKEN_RE.findall(text.lower())


@dataclass
class Hit:
    chunk: Chunk
    score: float           # fused RRF score — for RANKING only
    relevance: float       # absolute [0,1] relevance — for THRESHOLDING
    dense_score: float     # raw cosine similarity
    sparse_score: float    # BM25, normalised against the best hit for this query
    dense_rank: int | None = None
    sparse_rank: int | None = None


class HybridRetriever:
    def __init__(self, chunks: list[Chunk], model_name: str = DEFAULT_MODEL):
        self.chunks = chunks
        self.model_name = model_name
        self._bm25: BM25Okapi | None = None
        self._embeddings: np.ndarray | None = None
        self._embedder = None

    # --- index construction ----------------------------------------------------

    def _load_embedder(self):
        if self._embedder is None:
            from fastembed import TextEmbedding

            self._embedder = TextEmbedding(model_name=self.model_name)
        return self._embedder

    def build(self, verbose: bool = True) -> None:
        if verbose:
            print(f"Indexing {len(self.chunks)} chunks...")

        corpus = [tokenize(c.embed_text) for c in self.chunks]
        self._bm25 = BM25Okapi(corpus)
        if verbose:
            print("  sparse (BM25) index built")

        embedder = self._load_embedder()
        vectors = list(embedder.embed([c.embed_text for c in self.chunks]))
        matrix = np.asarray(vectors, dtype=np.float32)
        # Normalise once so cosine similarity is a plain dot product at query time.
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        self._embeddings = matrix / np.clip(norms, 1e-9, None)
        if verbose:
            print(f"  dense index built  ({self._embeddings.shape[1]}-dim, {self.model_name})")

    # --- persistence -----------------------------------------------------------

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            pickle.dump(
                {
                    "chunks": self.chunks,
                    "model_name": self.model_name,
                    "bm25": self._bm25,
                    "embeddings": self._embeddings,
                },
                fh,
            )

    @classmethod
    def load(cls, path: str | Path) -> HybridRetriever:
        with Path(path).open("rb") as fh:
            state = pickle.load(fh)
        retriever = cls(state["chunks"], state["model_name"])
        retriever._bm25 = state["bm25"]
        retriever._embeddings = state["embeddings"]
        return retriever

    # --- search ----------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 8,
        crop: str | None = None,
        concept_types: set[str] | None = None,
        visual_only: bool = False,
        boost_source: str | None = None,
        boost_factor: float = 1.15,
    ) -> list[Hit]:
        """Hybrid search with optional pre-filtering and source-type boosting.

        Filtering happens before ranking: if the vision model has already told us
        the crop is cotton, rice concepts are not candidates at all. This removes
        cross-crop confusion for free rather than hoping the ranker handles it.

        `boost_source` is deliberately a **boost and not a filter**. All corpora —
        crop practice, entomology, pathology, government guidelines, pesticide
        labels — live in one index, so a single search covers everything and the
        model never has to pick a corpus. When a query clearly points at one body
        of knowledge we raise its ranking, but the rest stay reachable.

        The asymmetry is the whole point: a wrong boost still finds the answer,
        just ranked lower. A wrong filter loses it entirely. Corpus boundaries do
        not match question boundaries — whitefly is an insect, a cotton pest and
        a virus vector at once — so any hard routing decision is a decision made
        before we know where the answer lives.
        """
        if self._bm25 is None or self._embeddings is None:
            raise RuntimeError("Index not built. Call build() or load() first.")

        candidates = [
            i
            for i, chunk in enumerate(self.chunks)
            if (crop is None or chunk.crop is None or chunk.crop == crop)
            and (concept_types is None or chunk.concept_type in concept_types)
            and (not visual_only or chunk.is_visual)
        ]
        if not candidates:
            return []

        sparse_all = self._bm25.get_scores(tokenize(query))
        sparse_ranked = sorted(candidates, key=lambda i: -sparse_all[i])

        embedder = self._load_embedder()
        qvec = np.asarray(next(iter(embedder.embed([query]))), dtype=np.float32)
        qvec /= max(float(np.linalg.norm(qvec)), 1e-9)
        dense_all = self._embeddings @ qvec
        dense_ranked = sorted(candidates, key=lambda i: -dense_all[i])

        sparse_rank = {idx: r for r, idx in enumerate(sparse_ranked)}
        dense_rank = {idx: r for r, idx in enumerate(dense_ranked)}

        # RRF fuses *rankings*, which makes it robust for ordering but useless as
        # a relevance gate: the top hit of any query scores ~2/(RRF_K+1) whether
        # the query is a leaf description or a photo of the sky. So we carry an
        # absolute relevance signal alongside it and threshold on that instead.
        best_sparse = max((sparse_all[i] for i in candidates), default=0.0)
        norm = best_sparse if best_sparse > 1e-9 else 1.0

        fused: dict[int, float] = {}
        relevance: dict[int, float] = {}
        for idx in candidates:
            fused[idx] = 1.0 / (RRF_K + sparse_rank[idx] + 1) + 1.0 / (
                RRF_K + dense_rank[idx] + 1
            )
            # Cosine carries semantic match; normalised BM25 carries exact-token
            # match, which is what rescues transliterated vernacular ("safed
            # makkhi") that the multilingual encoder handles poorly.
            relevance[idx] = 0.65 * float(dense_all[idx]) + 0.35 * float(
                sparse_all[idx] / norm
            )
            if boost_source and self.chunks[idx].source_type == boost_source:
                relevance[idx] *= boost_factor
                fused[idx] *= boost_factor

        ordered = sorted(candidates, key=lambda i: -fused[i])[:top_k]
        return [
            Hit(
                chunk=self.chunks[i],
                score=fused[i],
                relevance=relevance[i],
                dense_score=float(dense_all[i]),
                sparse_score=float(sparse_all[i] / norm),
                dense_rank=dense_rank[i],
                sparse_rank=sparse_rank[i],
            )
            for i in ordered
        ]
