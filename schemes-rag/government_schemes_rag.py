"""
Government Schemes RAG Engine

NOTE: This module manages local FAISS and BM25 indexing/retrieval for edge execution
(NVIDIA Jetson Orin Nano). It operates on Bhashini NMT translated English inputs.
"""
import gc
import json
import logging
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

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
    RRF_K,
)
from formatters import (
    extract_answer_by_intent,
    format_lcd_display_card,
    format_voice_text,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("RAG_Engine")

for logger_name in ["sentence_transformers", "transformers", "urllib3", "httpx", "filelock"]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def fast_tokenizer(text: str) -> List[str]:
    """Word-level tokenizer. Keeps internal hyphens (pm-kisan, pm-jay) as single tokens."""
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())


def acronym_in_query(acronym: str, query_lower: str, query_tokens: set) -> bool:
    """Matches an acronym whether it contains a space or a hyphen, via word-boundary regex."""
    if " " in acronym or "-" in acronym:
        return bool(re.search(rf"\b{re.escape(acronym)}\b", query_lower))
    return acronym in query_tokens


def expand_query(raw_query: str) -> Tuple[str, str]:
    """Expands raw user query using synonyms and acronym maps. Returns (vector_query, bm25_query)."""
    query_lower = raw_query.lower()

    vector_query = raw_query
    for phrase, expansions in SYNONYM_MAP.items():
        if " " in phrase and phrase in query_lower:
            vector_query += " " + " ".join(expansions)

    tokens = fast_tokenizer(vector_query)
    vector_expanded_terms = set(tokens)

    for phrase, expansion in SCHEME_ACRONYM_MAP.items():
        if " " in phrase and re.search(rf"\b{re.escape(phrase)}\b", query_lower):
            vector_expanded_terms.update(fast_tokenizer(expansion))

    for token in tokens:
        if token in SCHEME_ACRONYM_MAP:
            vector_expanded_terms.update(fast_tokenizer(SCHEME_ACRONYM_MAP[token]))
        if token in SYNONYM_MAP and " " not in token:
            vector_expanded_terms.update(SYNONYM_MAP[token])

    bm25_tokens = fast_tokenizer(raw_query)
    bm25_expanded_terms = set(bm25_tokens)

    for phrase, canonical in SCHEME_CANONICAL_NAMES.items():
        if " " in phrase and re.search(rf"\b{re.escape(phrase)}\b", query_lower):
            bm25_expanded_terms.update(fast_tokenizer(canonical))

    for token in bm25_tokens:
        if token in SCHEME_CANONICAL_NAMES:
            bm25_expanded_terms.update(fast_tokenizer(SCHEME_CANONICAL_NAMES[token]))

    bm25_final = " ".join(bm25_expanded_terms) if bm25_expanded_terms else raw_query
    return " ".join(vector_expanded_terms), bm25_final


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
                logger.warning(f"Failed to read FAISS cache. Rebuilding: {e}")
                self._build_index()
        else:
            self._build_index()

    def _build_index(self):
        searchable_texts = [s["searchable_text"] for s in self.schemes]
        embeddings = self.model.encode(searchable_texts, show_progress_bar=False, batch_size=32)
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
    rrf_scores, scheme_map, vector_score_map, bm25_score_map = {}, {}, {}, {}

    for item in vector_results:
        s_id = item["scheme_id"]
        scheme_map[s_id] = item["scheme"]
        vector_score_map[s_id] = item["score"]
        rrf_scores[s_id] = rrf_scores.get(s_id, 0.0) + (1.0 / (rrf_k + item["rank"]))

    for item in bm25_results:
        s_id = item["scheme_id"]
        scheme_map[s_id] = item["scheme"]
        bm25_score_map[s_id] = item["score"]
        rrf_scores[s_id] = rrf_scores.get(s_id, 0.0) + (1.0 / (rrf_k + item["rank"]))

    sorted_schemes = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return [
        {
            "scheme_id": s_id,
            "rrf_score": round(score, 6),
            "scheme": scheme_map[s_id],
            "vector_score": vector_score_map.get(s_id, 0.0),
            "bm25_score": bm25_score_map.get(s_id, 0.0),
        }
        for s_id, score in sorted_schemes
    ]


class GovernmentSchemesRAGEngine:
    def __init__(self, jsonl_file: str = "schemes_dataset.jsonl"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        jsonl_path = os.path.join(base_dir, jsonl_file)

        logger.info("Initializing Government Schemes RAG Engine...")
        self.schemes = load_schemes_dataset(jsonl_path)
        logger.info(f"Loaded {len(self.schemes)} schemes.")

        self.vector_index = SchemesFAISSVectorIndex(self.schemes)
        self.bm25_index = SchemesSimpleBM25Index(self.schemes)

        self.categories = list(set(
            s.get("category", "Other") for s in self.schemes if s.get("category", "Other") != "Other"
        ))
        self.category_embeddings = self.vector_index.model.encode(self.categories, show_progress_bar=False)
        self.category_embeddings = np.array(self.category_embeddings, dtype="float32")
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

            if "/" in s_name:
                for part in [p.strip() for p in s_name.split("/")]:
                    self.scheme_lookup[part] = s
                    part_clean = re.sub(r"\(.*?\)", "", part).strip()
                    if part_clean:
                        self.scheme_lookup[part_clean] = s

        # Backfill any canonical-name alias not yet indexed, using a word-boundary
        # match (not a bare substring check) to avoid short acronyms like "aif" or
        # "nlm" accidentally matching inside an unrelated scheme name.
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
        query_embedding = self.vector_index.model.encode([user_question], show_progress_bar=False)
        query_embedding = np.array(query_embedding, dtype="float32")
        faiss.normalize_L2(query_embedding)
        similarities = np.dot(query_embedding, self.category_embeddings.T)[0]
        max_idx = np.argmax(similarities)
        pred_cat = self.categories[max_idx]
        pred_score = float(similarities[max_idx])
        logger.info(f"Category '{pred_cat}' predicted with score: {pred_score:.4f}")
        return pred_cat, pred_score

    def query_schemes(self, user_question: str, category: Optional[str] = None) -> Dict[str, Any]:
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

        user_q_lower = user_question.lower()
        user_tokens = set(fast_tokenizer(user_q_lower))
        boosted_schemes = set()

        for item in fused_results:
            s_name = item["scheme"]["scheme_name"].lower()
            s_id = item["scheme"]["scheme_id"].lower()
            if s_id in boosted_schemes:
                continue

            for acronym in SCHEME_CANONICAL_NAMES.keys():
                if acronym_in_query(acronym, user_q_lower, user_tokens) and (
                    acronym in s_name or acronym in s_id
                ):
                    item["rrf_score"] *= ACRONYM_BOOST_MULTIPLIER
                    boosted_schemes.add(s_id)
                    break

        if target_category:
            for item in fused_results:
                if item["scheme"].get("category") == target_category:
                    item["rrf_score"] *= CATEGORY_SOFT_BOOST

        fused_results.sort(key=lambda x: x["rrf_score"], reverse=True)

        if not fused_results:
            return {"status": "error", "message": "No matching government schemes found."}

        top_fused_item = fused_results[0]
        best = top_fused_item["scheme"]
        top_cosine_score = round(float(np.clip(top_fused_item.get("vector_score", 0.0), -1.0, 1.0)), 4)
        top_bm25_score = round(float(top_fused_item.get("bm25_score", 0.0)), 4)

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
                    "=== SYSTEM ===\nScheme not found.\nPlease ask about a\nspecific govt scheme."
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
            "full_scheme_details": {
                "scheme_id": best["scheme_id"],
                "scheme_name": best["scheme_name"],
                "category": best.get("category", ""),
                "target_beneficiary": best.get("target_beneficiary", ""),
                "benefit_details": best.get("benefit_details", ""),
                "eligibility_criteria": best.get("eligibility_criteria", ""),
                "how_to_apply": best.get("how_to_apply", ""),
                "documents_required": best.get("documents_required", ""),
                "contact_details": best.get("contact_details", ""),
                "last_verified": best.get("last_verified", ""),
            },
            "tft_lcd_display_card": format_lcd_display_card(best, answer, top_cosine_score),
            "bhashini_voice_text": format_voice_text(best, answer),
            "latency_seconds": latency,
        }

    def match_eligible_schemes(self, farmer_profile: str, top_n: int = 3) -> Dict[str, Any]:
        start_time = time.time()
        vector_query, bm25_query = expand_query(farmer_profile)
        vector_results = self.vector_index.search(vector_query, top_k=top_n * 2)
        bm25_results = self.bm25_index.search(bm25_query, top_k=top_n * 2)
        fused_results = reciprocal_rank_fusion(vector_results, bm25_results)
        fused_results.sort(key=lambda x: x["rrf_score"], reverse=True)

        results = [
            {
                "scheme_name": item["scheme"]["scheme_name"],
                "eligibility_reason": item["scheme"].get(
                    "eligibility_criteria", "Eligibility criteria not found in dataset."
                ),
                "rrf_score": item["rrf_score"],
            }
            for item in fused_results[:top_n]
        ]
        return {"status": "success", "matches": results, "latency_seconds": round(time.time() - start_time, 4)}

    def get_scheme_details(self, scheme_name: str, user_question: str) -> Dict[str, Any]:
        start_time = time.time()
        exact = self.scheme_lookup.get(scheme_name.lower().strip())

        if exact:
            answer = extract_answer_by_intent(user_question, exact)
            return {
                "outcome": "scheme_found",
                "status": "success",
                "question": user_question,
                "text": answer,
                "scheme_name": exact["scheme_name"],
                "scheme_id": exact["scheme_id"],
                "confidence_score": 1.0,
                "top_match": {
                    "doc_id": exact["scheme_id"],
                    "scheme_name": exact["scheme_name"],
                    "similarity_score": 1.0,
                    "rrf_score": 1.0,
                },
                "full_scheme_details": {
                    "scheme_id": exact["scheme_id"],
                    "scheme_name": exact["scheme_name"],
                    "category": exact.get("category", ""),
                    "target_beneficiary": exact.get("target_beneficiary", ""),
                    "benefit_details": exact.get("benefit_details", ""),
                    "eligibility_criteria": exact.get("eligibility_criteria", ""),
                    "how_to_apply": exact.get("how_to_apply", ""),
                    "documents_required": exact.get("documents_required", ""),
                    "contact_details": exact.get("contact_details", ""),
                    "last_verified": exact.get("last_verified", ""),
                },
                "tft_lcd_display_card": format_lcd_display_card(exact, answer, 1.0),
                "bhashini_voice_text": format_voice_text(exact, answer),
                "latency_seconds": round(time.time() - start_time, 4),
            }

        return self.query_schemes(user_question=f"{scheme_name} {user_question}")

    def get_disaster_relief_options(self, disaster_context: str) -> Dict[str, Any]:
        start_time = time.time()
        vector_query, bm25_query = expand_query(disaster_context)
        vector_results = self.vector_index.search(vector_query, top_k=5)
        bm25_results = self.bm25_index.search(bm25_query, top_k=5)
        fused_results = reciprocal_rank_fusion(vector_results, bm25_results)
        fused_results.sort(key=lambda x: x["rrf_score"], reverse=True)

        results = [
            {
                "scheme_name": item["scheme"]["scheme_name"],
                "how_to_apply": item["scheme"].get("how_to_apply", "Application details not found."),
                "benefit_details": item["scheme"].get("benefit_details", "Benefit details not found."),
            }
            for item in fused_results[:3]
        ]
        return {"status": "success", "options": results, "latency_seconds": round(time.time() - start_time, 4)}

    def get_subsidy_details(self, scheme_name: str) -> Dict[str, Any]:
        start_time = time.time()
        exact = self.scheme_lookup.get(scheme_name.lower().strip())

        if exact:
            return {
                "status": "success",
                "scheme_name": exact["scheme_name"],
                "raw_benefit_details": exact.get("benefit_details", "No benefit details found in dataset."),
                "latency_seconds": round(time.time() - start_time, 4),
            }

        vector_query, bm25_query = expand_query(scheme_name)
        vector_results = self.vector_index.search(vector_query, top_k=3)
        bm25_results = self.bm25_index.search(bm25_query, top_k=3)
        fused_results = reciprocal_rank_fusion(vector_results, bm25_results)
        fused_results.sort(key=lambda x: x["rrf_score"], reverse=True)

        if not fused_results:
            return {"status": "error", "message": "Scheme not found."}

        best = fused_results[0]["scheme"]
        return {
            "status": "success",
            "scheme_name": best["scheme_name"],
            "raw_benefit_details": best.get("benefit_details", "No benefit details found in dataset."),
            "latency_seconds": round(time.time() - start_time, 4),
        }