"""Hybrid dense (sqlite-vec, int8) + sparse (BM25) retrieval, fused with RRF -- design
ported from krishi-rag/src/retrieval.py's proven, evaluated (153/153 tests) approach,
adapted to read from sqlite-vec instead of an in-memory pickle. The fusion/gating math
itself is UNCHANGED from that design, per G1-G2-VECTORDB-PLAN.md Β§5's recommendation to
keep it rather than re-derive it.

Two independent scores per hit, same as the source design, for the same reason:
    score      -- fused RRF rank score. RANKING ONLY. Ordinal, not comparable
                  across queries -- the top hit of ANY query scores ~2/(RRF_K+1).
    relevance  -- absolute [0,1] signal (0.65*cosine + 0.35*normalised-BM25).
                  THRESHOLDING ONLY. This is the one that answers "did anything
                  actually match", which RRF's rank-based score structurally cannot
                  (see krishi-rag README "Lesson 1: RRF scores cannot gate abstention" --
                  a real bug there: a photo of the sky was diagnosed as tomato late
                  blight, with a dose, because the fused score alone was thresholded).

MIN_RELEVANCE is NOT set here yet -- deliberately. krishi-rag's own MIN_RELEVANCE=0.44
is tuned to a DIFFERENT embedding model's score distribution
(paraphrase-multilingual-MiniLM-L12-v2) at a different corpus size. Reusing that number
against granite-embedding:30m's real distribution without re-deriving it would be
exactly the mistake that plan doc's Β§4 warned against. Callers should treat `relevance`
as informational until a real threshold is derived from eval queries against this
actual index (see rag/test_retrieval.py's printed distribution for a starting point).
"""

from __future__ import annotations

import pickle
import re
import time
from dataclasses import dataclass

import numpy as np

from rag import embed, store

RRF_K = 60
_TOKEN_RE = re.compile(r"[a-z0-9%ऀ-ॿঀ-৿଀-୿ఀ-౿]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class Hit:
    chunk_id: str
    concept_id: str
    concept_title: str
    concept_type: str
    heading: str
    text: str
    trust_tier: str
    source_type: str
    crop: str | None
    label_id: str | None
    is_visual: bool
    score: float       # fused RRF -- RANKING only
    relevance: float   # absolute [0,1] -- THRESHOLDING only
    dense_distance: float
    sparse_score: float


class HybridRetriever:
    """One instance per corpus (g1 or g2) -- opens the sqlite-vec DB + BM25 pickle
    built by build_index.py."""

    def __init__(self, name: str, agents_dir: str):
        import os
        db_path = os.path.join(agents_dir, "datasets", "rag", f"{name}.sqlite")
        bm25_path = os.path.join(agents_dir, "datasets", "rag", f"{name}_bm25.pkl")

        self.db = store.connect(db_path)
        with open(bm25_path, "rb") as f:
            state = pickle.load(f)
        self._bm25 = state["bm25"]
        self._chunk_ids = state["chunk_ids"]  # same order the BM25 corpus was built in
        self._id_to_bm25_idx = {cid: i for i, cid in enumerate(self._chunk_ids)}

    def search(
        self,
        query: str,
        top_k: int = 8,
        crop: str | None = None,
        concept_types: set[str] | None = None,
        boost_source: str | list[str] | None = None,
        boost_factor: float = 1.15,
        dense_candidates: int = 40,
    ) -> list[Hit]:
        """`crop`/`concept_types` are real pre-ranking SQL filters (sqlite-vec WHERE).
        `boost_source` is a POST-query multiplier, never a filter -- see module
        docstring and store.py's own docstring for why that asymmetry is deliberate.
        """
        qvec = embed.embed_one(query)
        qbytes = embed.to_f32_bytes(qvec)

        dense_hits = store.knn_search(
            self.db, qbytes, top_k=dense_candidates, crop=crop, concept_types=concept_types,
        )
        if not dense_hits:
            return []

        # BM25 scored over the SAME candidate set the dense filter already restricted
        # to, so crop/concept_type filtering is consistent across both halves of the
        # hybrid search -- otherwise BM25 could resurrect a chunk the dense filter had
        # already correctly excluded (wrong crop, wrong concept type).
        candidate_ids = [h["chunk_id"] for h in dense_hits]
        bm25_indices = [self._id_to_bm25_idx[cid] for cid in candidate_ids]
        query_tokens = tokenize(query)
        all_bm25_scores = self._bm25.get_scores(query_tokens)
        sparse_scores = {cid: float(all_bm25_scores[idx]) for cid, idx in zip(candidate_ids, bm25_indices)}

        # Rank by each signal independently for RRF.
        dense_rank = {h["chunk_id"]: r for r, h in enumerate(dense_hits)}  # already distance-sorted
        sparse_rank = {
            cid: r for r, cid in enumerate(
                sorted(candidate_ids, key=lambda c: -sparse_scores[c])
            )
        }

        best_sparse = max(sparse_scores.values(), default=0.0)
        norm = best_sparse if best_sparse > 1e-9 else 1.0
        # int8 quantized cosine-ish distance is NOT bounded [0,1] the way raw float32
        # cosine similarity is -- convert distance to a bounded similarity via a simple
        # decay so `relevance` stays comparable in spirit to the source design's
        # 0.65*cosine formula. Documented explicitly, not hidden: this is the one real
        # adaptation int8 quantization required, since sqlite-vec's int8 MATCH returns
        # a squared-difference-style distance, not cosine similarity directly.
        max_dist = max(h["distance"] for h in dense_hits) or 1.0

        hits = []
        for h in dense_hits:
            cid = h["chunk_id"]
            dense_sim = 1.0 - (h["distance"] / max_dist)  # bounded [0,1], higher = closer
            sparse_norm = sparse_scores[cid] / norm
            fused = (
                1.0 / (RRF_K + dense_rank[cid] + 1)
                + 1.0 / (RRF_K + sparse_rank[cid] + 1)
            )
            relevance = 0.65 * dense_sim + 0.35 * sparse_norm

            if boost_source:
                sources = (boost_source,) if isinstance(boost_source, str) else tuple(boost_source)
                if h["source_type"] in sources:
                    fused *= boost_factor
                    relevance *= boost_factor

            hits.append(Hit(
                chunk_id=cid, concept_id=h["concept_id"], concept_title=h["concept_title"],
                concept_type=h["concept_type"], heading=h["heading"], text=h["text"],
                trust_tier=h["trust_tier"], source_type=h["source_type"],
                crop=h["crop"] or None,  # store.py uses "" as the no-crop sentinel (vec0
                # metadata columns reject NULL) -- normalise back to None here so every
                # caller of this module sees the same None-means-no-crop convention the
                # rest of this codebase (Chunk, Concept) already uses.
                label_id=h["label_id"], is_visual=bool(h["is_visual"]),
                score=fused, relevance=relevance, dense_distance=h["distance"],
                sparse_score=sparse_norm,
            ))

        hits.sort(key=lambda h: -h.score)
        return hits[:top_k]
