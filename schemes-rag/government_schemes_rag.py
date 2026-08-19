"""
Government Schemes RAG Engine (2026 Jetson Production Edition)

Architectural Invariant:
- Primary Dense Backend: Quantized INT8 ONNX Runtime on NVIDIA Jetson Orin Nano
- Upstream Pipeline Contract: Bhashini ASR -> Bhashini NMT -> Gram Sahayak RAG -> TTS
- Principled Ranking: Bounded Convex Combination of Normalized Dense, BM25, Acronym Prior, State Prior, and Category Prior
- Cache Integrity: SHA-256 Content-Hash Invalidation of dataset and vector index
- Hallucination Guarantee: 100% Deterministic template extraction with zero LLM generation on facts
"""
import gc
import hashlib
import json
import logging
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Threading constraints for ARM64 Jetson Orin Nano
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OMP_NUM_THREADS"] = "2"

import faiss
import numpy as np

from edge_onnx_retriever import QuantizedONNXEmbedder
from config import (
    SYNONYM_MAP,
    SCHEME_ACRONYM_MAP,
    SCHEME_CANONICAL_NAMES,
    OUT_OF_DOMAIN_PATTERN,
    SIMILARITY_THRESHOLD,
    FALLBACK_COSINE_THRESHOLD,
    FALLBACK_BM25_THRESHOLD,
    CATEGORY_SOFT_BOOST,
    RRF_K,
)
from formatters import (
    extract_answer_by_intent,
    format_lcd_display_card,
    format_voice_text,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("RAG_Engine")


def compute_file_sha256(filepath: str) -> str:
    """Computes SHA-256 hash of a file for cache invalidation."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def fast_tokenizer(text: str) -> List[str]:
    """
    Word-level tokenizer preserving hyphens and Indic transliterated terms.
    Supports Bhashini NMT translated outputs with preserved Indian governance terms.
    """
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())


def acronym_in_query(acronym: str, query_lower: str, query_tokens: set) -> bool:
    """Matches an acronym whether it contains a space or a hyphen, via word-boundary regex."""
    if " " in acronym or "-" in acronym:
        return bool(re.search(rf"\b{re.escape(acronym)}\b", query_lower))
    return acronym in query_tokens


def expand_query(raw_query: str) -> Tuple[str, str]:
    """Expands raw user query using synonyms and acronym maps. Returns (vector_query, bm25_query)."""
    query_lower = raw_query.lower()
    bm25_tokens = fast_tokenizer(raw_query)
    bm25_expanded_terms = set(bm25_tokens)

    for phrase, expansion in SCHEME_ACRONYM_MAP.items():
        if re.search(rf"\b{re.escape(phrase)}\b", query_lower):
            bm25_expanded_terms.update(fast_tokenizer(expansion))

    for token in bm25_tokens:
        if token in SYNONYM_MAP and " " not in token:
            bm25_expanded_terms.update(SYNONYM_MAP[token])

    bm25_final = " ".join(bm25_expanded_terms) if bm25_expanded_terms else raw_query
    return raw_query, bm25_final


def load_schemes_dataset(jsonl_path: str) -> List[Dict[str, Any]]:
    schemes = []
    if not os.path.exists(jsonl_path):
        logger.error(f"Dataset file not found at: {jsonl_path}")
        raise FileNotFoundError(f"Scheme dataset missing: {jsonl_path}")

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line.strip())
                    name = data.get("scheme_name", "")
                    searchable_text = data.get(
                        "searchable_text",
                        f"{name} {data.get('target_beneficiary', '')}"
                        f" {data.get('benefit_details', '')}"
                        f" {data.get('eligibility_criteria', '')}"
                        f" {data.get('how_to_apply', '')}"
                        f" {data.get('documents_required', '')}",
                    )
                    schemes.append({
                        "scheme_id": data.get("scheme_id", ""),
                        "scheme_name": name,
                        "category": data.get("category", "Other"),
                        "target_beneficiary": data.get("target_beneficiary", ""),
                        "benefit_details": data.get("benefit_details", ""),
                        "eligibility_criteria": data.get("eligibility_criteria", ""),
                        "how_to_apply": data.get("how_to_apply", ""),
                        "documents_required": data.get("documents_required", ""),
                        "contact_details": data.get("contact_details", ""),
                        "last_verified": data.get("last_verified", ""),
                        "searchable_text": searchable_text,
                    })
                except Exception as e:
                    logger.warning(f"Skipping malformed row: {e}")
                    continue
    return schemes


class SchemesFAISSVectorIndex:
    """
    FAISS Index FlatIP powered by Quantized INT8 ONNX Runtime on Jetson Orin Nano.
    Employs SHA-256 content-hash verification to prevent stale cache bugs.
    """
    def __init__(self, schemes: List[Dict[str, Any]], dataset_path: str):
        self.schemes = schemes
        self.dataset_path = dataset_path
        self.embedder = QuantizedONNXEmbedder()
        self.dimension = 384
        self.index = None

        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cache_index_path = os.path.join(base_dir, "schemes_faiss_index.bin")
        self.cache_hash_path = os.path.join(base_dir, "schemes_faiss_index.bin.sha256")

        current_hash = compute_file_sha256(self.dataset_path) if os.path.exists(self.dataset_path) else ""
        cached_hash = ""
        if os.path.exists(self.cache_hash_path):
            with open(self.cache_hash_path, "r", encoding="utf-8") as hf:
                cached_hash = hf.read().strip()

        if os.path.exists(self.cache_index_path) and current_hash == cached_hash:
            try:
                self.index = faiss.read_index(self.cache_index_path)
                if self.index.ntotal == len(self.schemes):
                    logger.info(f"Loaded verified FAISS index cache ({self.index.ntotal} schemes, SHA-256 match).")
                else:
                    logger.info("FAISS index count mismatch. Rebuilding...")
                    self._build_index(current_hash)
            except Exception as e:
                logger.warning(f"Failed to read FAISS cache. Rebuilding: {e}")
                self._build_index(current_hash)
        else:
            logger.info("Dataset SHA-256 modified or cache missing. Rebuilding FAISS index...")
            self._build_index(current_hash)

    def _build_index(self, current_hash: str):
        searchable_texts = [s["searchable_text"] for s in self.schemes]
        embeddings = self.embedder.encode(searchable_texts)
        faiss.normalize_L2(embeddings)
        self.index = faiss.IndexFlatIP(self.dimension)
        self.index.add(embeddings)
        faiss.write_index(self.index, self.cache_index_path)
        if current_hash:
            with open(self.cache_hash_path, "w", encoding="utf-8") as hf:
                hf.write(current_hash)
        logger.info(f"FAISS index built and saved ({self.index.ntotal} schemes).")

    def search(self, query: str, top_k: int = 15) -> List[Dict[str, Any]]:
        query_embedding = self.embedder.encode([query])
        faiss.normalize_L2(query_embedding)
        distances, indices = self.index.search(query_embedding, top_k)
        results = []
        for i, idx in enumerate(indices[0]):
            if idx < len(self.schemes):
                results.append({
                    "scheme_id": self.schemes[idx]["scheme_id"],
                    "rank": i + 1,
                    "score": float(distances[0][i]),
                    "scheme": self.schemes[idx],
                })
        return results


class SchemesSimpleBM25Index:
    """Fast vectorized BM25 sparse keyword index."""
    def __init__(self, schemes: List[Dict[str, Any]]):
        self.schemes = schemes
        self.corpus_tokens = [fast_tokenizer(s["searchable_text"]) for s in schemes]
        self.doc_lengths = [len(doc) for doc in self.corpus_tokens]
        self.avg_doc_len = sum(self.doc_lengths) / max(len(self.doc_lengths), 1)

        self.df = {}
        for doc in self.corpus_tokens:
            for word in set(doc):
                self.df[word] = self.df.get(word, 0) + 1

        self.k1 = 1.5
        self.b = 0.75
        self.N = len(schemes)

    def search(self, query: str, top_k: int = 15) -> List[Dict[str, Any]]:
        query_tokens = fast_tokenizer(query)
        scores = np.zeros(self.N, dtype=np.float32)

        for token in query_tokens:
            if token in self.df:
                df_val = self.df[token]
                idf = np.log((self.N - df_val + 0.5) / (df_val + 0.5) + 1.0)
                for idx, doc in enumerate(self.corpus_tokens):
                    tf = doc.count(token)
                    if tf > 0:
                        doc_len = self.doc_lengths[idx]
                        score = idf * ((tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * (doc_len / self.avg_doc_len))))
                        scores[idx] += score

        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for rank, idx in enumerate(top_indices):
            if scores[idx] > 0:
                results.append({
                    "scheme_id": self.schemes[idx]["scheme_id"],
                    "rank": rank + 1,
                    "score": float(scores[idx]),
                    "scheme": self.schemes[idx],
                })
        return results


class GovernmentSchemesRAGEngine:
    """
    Production Hybrid RAG Engine for Rural Governance (Jetson Orin Nano).
    Uses a Principled Convex Combination Hybrid Scoring Model:
    Score(d|q) = w_dense * S_dense + w_bm25 * S_bm25 + w_acronym * I_acronym + w_state * I_state + w_cat * S_cat
    """
    def __init__(self, jsonl_file: str = "schemes_dataset.jsonl"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.jsonl_path = os.path.join(base_dir, jsonl_file)

        logger.info("Initializing Government Schemes RAG Engine (2026 Jetson Edition)...")
        self.schemes = load_schemes_dataset(self.jsonl_path)
        logger.info(f"Loaded {len(self.schemes)} schemes.")

        self.vector_index = SchemesFAISSVectorIndex(self.schemes, self.jsonl_path)
        self.bm25_index = SchemesSimpleBM25Index(self.schemes)

        self.categories = list(set(
            s.get("category", "Other") for s in self.schemes if s.get("category", "Other") != "Other"
        ))
        self.category_embeddings = self.vector_index.embedder.encode(self.categories)
        faiss.normalize_L2(self.category_embeddings)

        self.scheme_lookup: Dict[str, Dict[str, Any]] = {}
        for s in self.schemes:
            s_name = s["scheme_name"].lower()
            s_id = s.get("scheme_id", "").lower()
            self.scheme_lookup[s_name] = s
            if s_id:
                self.scheme_lookup[s_id] = s

            match = re.search(r"\((.*?)\)", s_name)
            if match:
                acronym = match.group(1).strip().lower()
                self.scheme_lookup[acronym] = s
                name_without_acronym = s_name.replace(f"({match.group(1)})", "").strip()
                self.scheme_lookup[name_without_acronym] = s

        for alias, canonical in SCHEME_CANONICAL_NAMES.items():
            alias_lower = alias.lower()
            if alias_lower in self.scheme_lookup:
                continue
            canonical_pattern = re.compile(rf"\b{re.escape(canonical.lower())}\b")
            for s in self.schemes:
                s_name_lower = s["scheme_name"].lower()
                if canonical_pattern.search(s_name_lower):
                    self.scheme_lookup[alias_lower] = s
                    break

        gc.collect()
        logger.info(f"RAG Engine ready. {len(self.scheme_lookup)} alias lookup keys indexed.")

    def predict_category(self, user_question: str) -> Tuple[Optional[str], float]:
        query_embedding = self.vector_index.embedder.encode([user_question])
        faiss.normalize_L2(query_embedding)
        similarities = np.dot(query_embedding, self.category_embeddings.T)[0]
        max_idx = np.argmax(similarities)
        pred_cat = self.categories[max_idx]
        pred_score = float(similarities[max_idx])
        return pred_cat, pred_score

    def query_schemes(self, user_question: str, category: Optional[str] = None) -> Dict[str, Any]:
        start_time = time.time()

        vector_query, bm25_query = expand_query(user_question)
        top_cand = min(25, len(self.schemes))
        vector_results = self.vector_index.search(vector_query, top_k=top_cand)
        bm25_results = self.bm25_index.search(bm25_query, top_k=top_cand)

        # Collect unique candidates
        candidate_ids = set([r["scheme_id"] for r in vector_results] + [r["scheme_id"] for r in bm25_results])
        vector_score_map = {r["scheme_id"]: r["score"] for r in vector_results}
        bm25_score_map = {r["scheme_id"]: r["score"] for r in bm25_results}
        scheme_map = {s["scheme_id"]: s for s in self.schemes}

        # Min-Max Normalization
        v_scores = list(vector_score_map.values())
        b_scores = list(bm25_score_map.values())
        v_max = max(v_scores) if v_scores else 1.0
        v_min = min(v_scores) if v_scores else 0.0
        b_max = max(b_scores) if b_scores else 1.0
        b_min = min(b_scores) if b_scores else 0.0

        user_q_lower = user_question.lower()
        user_tokens = set(fast_tokenizer(user_q_lower))

        # Detect State Mention in Query
        state_detected = None
        for state_key, prefix in {
            "andaman": "an_", "nicobar": "an_", "andhra": "ap_", "arunachal": "arun_", "assam": "assam_",
            "bihar": "bihar_", "chandigarh": "ch_", "chhattisgarh": "cg_", "dadra": "dn_", "daman": "dd_",
            "diu": "dd_", "delhi": "del_", "goa": "goa_", "gujarat": "guj_", "haryana": "haryana_", "himachal": "hp_",
            "jammu": "jk_", "kashmir": "jk_", "jharkhand": "jh_", "karnataka": "kar_", "kerala": "ker_",
            "ladakh": "lk_", "lakshadweep": "ld_", "madhya pradesh": "mp_", "maharashtra": "maha_",
            "manipur": "mn_", "meghalaya": "ml_", "mizoram": "mz_", "nagaland": "nl_", "odisha": "od_",
            "puducherry": "py_", "punjab": "pun_", "rajasthan": "rj_", "sikkim": "sk_", "tamil nadu": "tn_",
            "telangana": "tg_", "tripura": "tr_", "uttar pradesh": "up_", "uttarakhand": "uk_", "west bengal": "wb_",
        }.items():
            if state_key in user_q_lower:
                state_detected = prefix
                break

        # Predicted Category Alignment
        pred_cat, pred_cat_score = self.predict_category(user_question)

        # PRINCIPLED CONVEX COMBINATION HYBRID SCORING
        # Weights: Dense (0.35) + BM25 (0.30) + Acronym Exact (0.20) + State Prior (0.10) + Category Prior (0.05) = 1.00
        W_DENSE = 0.35
        W_BM25 = 0.30
        W_ACRONYM = 0.20
        W_STATE = 0.10
        W_CAT = 0.05

        fused_scored_candidates = []

        for s_id in candidate_ids:
            scheme = scheme_map[s_id]
            s_name = scheme["scheme_name"].lower()
            s_id_lower = s_id.lower()

            # Normalized dense score in [0, 1]
            raw_v = vector_score_map.get(s_id, 0.0)
            norm_v = (raw_v - v_min) / (v_max - v_min + 1e-9) if v_max > v_min else max(0.0, raw_v)

            # Normalized BM25 score in [0, 1]
            raw_b = bm25_score_map.get(s_id, 0.0)
            norm_b = (raw_b - b_min) / (b_max - b_min + 1e-9) if b_max > b_min else 0.0

            # Acronym / Canonical Indicator in [0, 1]
            i_acronym = 0.0
            for acronym, canonical in SCHEME_CANONICAL_NAMES.items():
                if acronym_in_query(acronym, user_q_lower, user_tokens):
                    canon_lower = canonical.lower()
                    if (
                        re.search(rf"\b{re.escape(acronym)}\b", s_name)
                        or re.search(rf"\b{re.escape(acronym)}\b", s_id_lower)
                        or canon_lower in s_name
                        or canon_lower in s_id_lower
                    ):
                        if not state_detected and s_id_lower.startswith("scheme_"):
                            i_acronym = 1.0  # Perfect canonical Central match
                        else:
                            i_acronym = 0.75  # Regional / state derivative match
                        break

            # State Alignment Indicator in [0, 1]
            i_state = 0.0
            if state_detected and s_id_lower.startswith(state_detected):
                i_state = 1.0
            elif not state_detected and s_id_lower.startswith("scheme_"):
                i_state = 0.5  # Neutral central baseline

            # Category Alignment Score in [0, 1]
            s_cat = scheme.get("category", "")
            i_cat = float(pred_cat_score * CATEGORY_SOFT_BOOST) if (s_cat == pred_cat or s_cat == category) else 0.0
            i_cat = min(1.0, i_cat)

            # Convex combination (strictly bounded in [0, 1])
            final_score = (
                W_DENSE * norm_v
                + W_BM25 * norm_b
                + W_ACRONYM * i_acronym
                + W_STATE * i_state
                + W_CAT * i_cat
            )

            fused_scored_candidates.append({
                "scheme_id": s_id,
                "scheme": scheme,
                "final_score": round(float(final_score), 4),
                "vector_score": round(float(raw_v), 4),
                "bm25_score": round(float(raw_b), 4),
            })

        fused_scored_candidates.sort(key=lambda x: x["final_score"], reverse=True)

        if not fused_scored_candidates:
            return {"status": "error", "message": "No matching government schemes found."}

        top_item = fused_scored_candidates[0]
        best = top_item["scheme"]
        top_cosine = top_item["vector_score"]
        top_bm25 = top_item["bm25_score"]

        is_out_of_domain = bool(OUT_OF_DOMAIN_PATTERN.search(user_question))
        is_fallback = is_out_of_domain or (
            top_cosine < 0.45 and top_bm25 < 3.0
        ) or (top_item["final_score"] < 0.35 and top_bm25 == 0.0)

        latency = round(time.time() - start_time, 4)

        if is_fallback:
            fallback_msg = (
                "I could not find a matching government scheme for your question."
                " Please rephrase or ask about a specific scheme."
            )
            return {
                "outcome": "fallback",
                "status": "fallback",
                "confidence_score": top_cosine,
                "scheme_id": None,
                "scheme_name": None,
                "category": None,
                "message": fallback_msg,
                "lcd_card": fallback_msg,
                "voice_text": fallback_msg,
                "latency_sec": latency,
            }

        extracted_answer = extract_answer_by_intent(user_question, best)
        lcd_card = format_lcd_display_card(best, extracted_answer, top_item["final_score"])
        voice_text = format_voice_text(best, extracted_answer)

        return {
            "outcome": "success",
            "status": "success",
            "confidence_score": top_item["final_score"],
            "scheme_id": best.get("scheme_id"),
            "scheme_name": best.get("scheme_name"),
            "category": best.get("category"),
            "details": best,
            "extracted_answer": extracted_answer,
            "lcd_card": lcd_card,
            "voice_text": voice_text,
            "latency_sec": latency,
        }
