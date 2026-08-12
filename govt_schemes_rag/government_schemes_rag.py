"""
Government Schemes RAG Engine

NOTE: This module manages local FAISS and BM25 indexing/retrieval for edge execution 
(NVIDIA Jetson Orin Nano). However, full offline capability still depends on the 
Bhashini NMT pipeline (which translates farmer queries to English) being deployed 
locally. If Bhashini relies on cloud endpoints, the system is NOT fully offline.
"""
import gc
import json
import logging
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Environmental Flags - Force local offline mode for Jetson edge deployment
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OMP_NUM_THREADS"] = "1"

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from config import (
    SYNONYM_MAP,
    SCHEME_ACRONYM_MAP,
    SCHEME_CANONICAL_NAMES,
    OUT_OF_DOMAIN_PATTERN,
    SIMILARITY_THRESHOLD,
    FALLBACK_COSINE_THRESHOLD,
    FALLBACK_BM25_THRESHOLD,
    ACRONYM_BOOST_MULTIPLIER,
    CATEGORY_SOFT_BOOST,
    RRF_K
)
from formatters import (
    extract_answer_by_intent,
    format_lcd_display_card,
    format_voice_text
)

# Configure clean logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("RAG_Engine")

# Silence noisy third-party loggers
for logger_name in [
    "sentence_transformers",
    "transformers",
    "urllib3",
    "httpx",
    "filelock",
]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

# Force UTF-8 encoding for Windows/Linux terminal compatibility
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def fast_tokenizer(text: str) -> List[str]:
    """Lightweight word-level regex tokenizer (low RAM footprint)."""
    return re.findall(r"\w+", text.lower())


# ---------------------------------------------------------------------------
# Core Helpers & Index Classes
# ---------------------------------------------------------------------------
def expand_query(raw_query: str) -> Tuple[str, str]:
    """
    Expands raw user query using synonyms and acronym maps.
    Returns (vector_query, bm25_query).
    bm25_query avoids broad synonyms to prevent BM25 dilution.
    """
    query_lower = raw_query.lower()

    # Vector query: get broad synonyms and full descriptive acronym map
    vector_query = raw_query
    for phrase, expansions in SYNONYM_MAP.items():
        if " " in phrase and phrase in query_lower:
            vector_query += " " + " ".join(expansions)

    tokens = fast_tokenizer(vector_query)
    vector_expanded_terms = set(tokens)

    # Check multi-word descriptive acronyms for vector query
    for phrase, expansion in SCHEME_ACRONYM_MAP.items():
        if " " in phrase and re.search(rf"\b{re.escape(phrase)}\b", query_lower):
            vector_expanded_terms.update(fast_tokenizer(expansion))

    for token in tokens:
        if token in SCHEME_ACRONYM_MAP:
            vector_expanded_terms.update(fast_tokenizer(SCHEME_ACRONYM_MAP[token]))
        if token in SYNONYM_MAP and " " not in token:
            vector_expanded_terms.update(SYNONYM_MAP[token])

    # BM25 query: only inject exact canonical names for acronyms, no broad synonyms
    bm25_tokens = fast_tokenizer(raw_query)
    bm25_expanded_terms = set(bm25_tokens)
    
    # Check multi-word canonical names
    for phrase, canonical in SCHEME_CANONICAL_NAMES.items():
        if " " in phrase and re.search(rf"\b{re.escape(phrase)}\b", query_lower):
            bm25_expanded_terms.update(fast_tokenizer(canonical))
            
    # Check single-word canonical names
    for token in bm25_tokens:
        if token in SCHEME_CANONICAL_NAMES:
            bm25_expanded_terms.update(fast_tokenizer(SCHEME_CANONICAL_NAMES[token]))

    # Fallback to raw query if BM25 expansion resulted in empty set
    bm25_final = " ".join(bm25_expanded_terms) if bm25_expanded_terms else raw_query

    return " ".join(vector_expanded_terms), bm25_final


def load_schemes_dataset(jsonl_path: str) -> List[Dict[str, Any]]:
    """Loads and sanitizes the JSONL scheme dataset."""
    schemes = []
    if not os.path.exists(jsonl_path):
        logger.error(f"Dataset file not found at: {jsonl_path}")
        raise FileNotFoundError(f"Scheme dataset missing: {jsonl_path}")

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line.strip())
                    s_id = data.get("scheme_id", "")
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
                        "scheme_id": s_id,
                        "scheme_name": name,
                        "category": data.get("category", "Other"),
                        "target_beneficiary": data.get("target_beneficiary", ""),
                        "benefit_details": data.get("benefit_details", ""),
                        "eligibility_criteria": data.get("eligibility_criteria", ""),
                        "how_to_apply": data.get("how_to_apply", ""),
                        "documents_required": data.get("documents_required", ""),
                        "searchable_text": searchable_text,
                    })
                except Exception as e:
                    logger.warning(f"Skipping malformed row: {e}")
                    continue
    return schemes


class SchemesFAISSVectorIndex:

    def __init__(self, schemes: List[Dict[str, Any]]):
        self.schemes = schemes
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.dimension = 384
        self.index = None

        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cache_index_path = os.path.join(base_dir, "schemes_faiss_index.bin")

        if os.path.exists(self.cache_index_path):
            try:
                self.index = faiss.read_index(self.cache_index_path)
            except Exception as e:
                logger.warning(f"Failed to read FAISS cache {self.cache_index_path}. Rebuilding index: {e}")
                self._build_index()
        else:
            self._build_index()

    def _build_index(self):
        searchable_texts = [s["searchable_text"] for s in self.schemes]
        embeddings = self.model.encode(
            searchable_texts, show_progress_bar=False, batch_size=32
        )
        embeddings = np.array(embeddings, dtype="float32")
        faiss.normalize_L2(embeddings)

        self.index = faiss.IndexFlatIP(self.dimension)
        self.index.add(embeddings)
        faiss.write_index(self.index, self.cache_index_path)

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_embedding = self.model.encode([query], show_progress_bar=False)
        query_embedding = np.array(query_embedding, dtype="float32")
        faiss.normalize_L2(query_embedding)

        distances, indices = self.index.search(query_embedding, top_k)
        results = []
        for i, idx in enumerate(indices[0]):
            if idx < len(self.schemes):
                results.append({
                    "scheme_id": self.schemes[idx]["scheme_id"],
                    "rank": i + 1,
                    "score": round(float(distances[0][i]), 4),
                    "scheme": self.schemes[idx],
                })
        return results


class SchemesSimpleBM25Index:

    def __init__(self, schemes: List[Dict[str, Any]]):
        from rank_bm25 import BM25Okapi

        self.schemes = schemes
        corpus_tokens = [fast_tokenizer(s["searchable_text"]) for s in self.schemes]
        self.bm25 = BM25Okapi(corpus_tokens)

    def search(self, raw_query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_tokens = fast_tokenizer(raw_query)
        if not query_tokens:
            return []
        scores = self.bm25.get_scores(query_tokens)
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for rank, idx in enumerate(top_indices):
            results.append({
                "scheme_id": self.schemes[idx]["scheme_id"],
                "rank": rank + 1,
                "score": round(float(scores[idx]), 4),
                "scheme": self.schemes[idx],
            })
        return results


def reciprocal_rank_fusion(
    vector_results: List[Dict[str, Any]],
    bm25_results: List[Dict[str, Any]],
    rrf_k: int = RRF_K,
) -> List[Dict[str, Any]]:
    rrf_scores = {}
    scheme_map = {}

    for item in vector_results:
        s_id = item["scheme_id"]
        scheme_map[s_id] = item["scheme"]
        rrf_scores[s_id] = rrf_scores.get(s_id, 0.0) + (1.0 / (rrf_k + item["rank"]))

    for item in bm25_results:
        s_id = item["scheme_id"]
        scheme_map[s_id] = item["scheme"]
        rrf_scores[s_id] = rrf_scores.get(s_id, 0.0) + (1.0 / (rrf_k + item["rank"]))

    sorted_schemes = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return [
        {"scheme_id": s_id, "rrf_score": round(score, 6), "scheme": scheme_map[s_id]}
        for s_id, score in sorted_schemes
    ]


# ---------------------------------------------------------------------------
# Main RAG Engine Class
# ---------------------------------------------------------------------------
class GovernmentSchemesRAGEngine:

    def __init__(self, jsonl_file: str = "enriched_schemes_dataset.jsonl"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        jsonl_path = os.path.join(base_dir, jsonl_file)

        if not os.path.exists(jsonl_path):
            fallback_path = os.path.join(base_dir, "schemes_dataset.jsonl")
            if os.path.exists(fallback_path):
                logger.info(
                    f"Enriched dataset not found at {jsonl_path}, falling back to"
                    f" {fallback_path}"
                )
                jsonl_path = fallback_path

        logger.info("Initializing Government Schemes RAG Engine...")
        self.schemes = load_schemes_dataset(jsonl_path)
        logger.info(f"Loaded {len(self.schemes)} schemes.")

        self.vector_index = SchemesFAISSVectorIndex(self.schemes)
        self.bm25_index = SchemesSimpleBM25Index(self.schemes)

        self.categories = list(
            set([
                s.get("category", "Other")
                for s in self.schemes
                if s.get("category", "Other") != "Other"
            ])
        )
        self.category_embeddings = self.vector_index.model.encode(
            self.categories, show_progress_bar=False
        )
        self.category_embeddings = np.array(
            self.category_embeddings, dtype="float32"
        )
        faiss.normalize_L2(self.category_embeddings)

        gc.collect()
        logger.info("RAG Engine Initialization Complete!")

    def predict_category(self, user_question: str) -> Tuple[Optional[str], float]:
        query_embedding = self.vector_index.model.encode(
            [user_question], show_progress_bar=False
        )
        query_embedding = np.array(query_embedding, dtype="float32")
        faiss.normalize_L2(query_embedding)
        similarities = np.dot(query_embedding, self.category_embeddings.T)[0]
        max_idx = np.argmax(similarities)
        pred_cat = self.categories[max_idx]
        pred_score = float(similarities[max_idx])
        logger.info(f"Category '{pred_cat}' predicted with score: {pred_score:.4f}")
        return pred_cat, pred_score

    def query_schemes(
        self, user_question: str, category: Optional[str] = None
    ) -> Dict[str, Any]:
        """Queries government schemes and returns structured dictionary for downstream agent integration."""
        start_time = time.time()

        target_category = category
        if not category:
            pred_cat, pred_score = self.predict_category(user_question)
            if pred_score > SIMILARITY_THRESHOLD:
                target_category = pred_cat

        vector_query, bm25_query = expand_query(user_question)

        vector_results = self.vector_index.search(vector_query, top_k=5)
        bm25_results = self.bm25_index.search(bm25_query, top_k=5)
        fused_results = reciprocal_rank_fusion(vector_results, bm25_results)

        # Exact Acronym Priority Boost
        user_q_lower = user_question.lower()
        user_tokens = set(fast_tokenizer(user_q_lower))
        boosted_schemes = set()

        for item in fused_results:
            s_name = item["scheme"]["scheme_name"].lower()
            s_id = item["scheme"]["scheme_id"].lower()
            
            if s_id in boosted_schemes:
                continue

            # Check if any acronym from config matches the user query
            for acronym in SCHEME_CANONICAL_NAMES.keys():
                is_match = False
                if " " in acronym:
                    # Multi-word phrase: match using regex word boundaries
                    if re.search(rf"\b{re.escape(acronym)}\b", user_q_lower):
                        is_match = True
                else:
                    # Single-word: match against token set
                    if acronym in user_tokens:
                        is_match = True

                if is_match and (acronym in s_name or acronym in s_id):
                    item["rrf_score"] *= ACRONYM_BOOST_MULTIPLIER
                    boosted_schemes.add(s_id)
                    break # Apply boost only once per scheme

        # Soft-Gating Boost
        if target_category:
            for item in fused_results:
                if item["scheme"].get("category") == target_category:
                    item["rrf_score"] *= CATEGORY_SOFT_BOOST

        fused_results.sort(key=lambda x: x["rrf_score"], reverse=True)

        if not fused_results:
            return {
                "status": "error",
                "message": "No matching government schemes found.",
            }

        top_fused_item = fused_results[0]
        best = top_fused_item["scheme"]
        raw_score = vector_results[0]["score"] if vector_results else 0.0
        top_cosine_score = round(float(np.clip(raw_score, -1.0, 1.0)), 4)
        top_bm25_score = bm25_results[0]["score"] if bm25_results else 0.0

        # Safety Fallback
        is_out_of_domain = bool(OUT_OF_DOMAIN_PATTERN.search(user_question))
        is_fallback = is_out_of_domain or (
            top_cosine_score < FALLBACK_COSINE_THRESHOLD and top_bm25_score < FALLBACK_BM25_THRESHOLD
        )

        latency = round(time.time() - start_time, 4)

        if is_fallback:
            fallback_msg = (
                "I could not find a matching government scheme for your question."
                " Please rephrase or ask about a specific scheme."
            )
            return {
                "outcome": "fallback",
                "status": "fallback",
                "question": user_question,
                "text": fallback_msg,
                "bhashini_voice_text": fallback_msg,
                "tft_lcd_display_card": (
                    "=== SYSTEM ===\nScheme not found.\nPlease ask about a\nspecific"
                    " govt scheme."
                ),
                "scheme_name": None,
                "scheme_id": None,
                "confidence_score": top_cosine_score,
                "latency_seconds": latency,
            }

        answer = extract_answer_by_intent(user_question, best)

        return {
            "outcome": "scheme_found",
            "status": "success",
            "question": user_question,
            "text": answer,
            "scheme_name": best["scheme_name"],
            "scheme_id": best["scheme_id"],
            "confidence_score": top_cosine_score,
            "top_match": {
                "doc_id": best["scheme_id"],
                "scheme_name": best["scheme_name"],
                "similarity_score": top_cosine_score,
                "rrf_score": top_fused_item.get("rrf_score", 0.0),
            },
            "tft_lcd_display_card": format_lcd_display_card(best, answer, top_cosine_score),
            "bhashini_voice_text": format_voice_text(best, answer),
            "latency_seconds": latency,
        }