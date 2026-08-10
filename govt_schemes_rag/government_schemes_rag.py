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
# Domain Mapping & Constants
# ---------------------------------------------------------------------------
SYNONYM_MAP: Dict[str, List[str]] = {
    "water": ["irrigation", "pmksy", "jal jeevan", "pump", "boring", "tubewell"],
    "drinking water": ["jal jeevan", "tap connection", "pipeline"],
    "money": ["subsidy", "financial assistance", "installment", "pension"],
    "loan": ["credit", "kcc", "subvention", "debt"],
    "electricity": ["solar", "kusum", "power", "grid", "ddugjy"],
    "sunlight": ["solar", "kusum", "energy"],
    "damage": [
        "loss",
        "compensation",
        "insurance",
        "pmfby",
        "calamity",
        "yellow disease",
    ],
    "insects": ["pesticide", "protection", "crop damage", "pest attack"],
    "drought": ["pmfby", "fasal bima", "crop loss", "compensation"],
    "flood": ["pmfby", "fasal bima", "crop loss", "compensation"],
    "claim": ["pmfby", "insurance", "compensation", "settlement"],
    "six thousand": ["6000", "pm-kisan", "pmkisan", "samman nidhi"],
    "two thousand": ["2000", "pm-kisan", "pmkisan", "samman nidhi"],
    "three thousand": ["3000", "pm-kmy", "maandhan", "pension"],
    "tractor": ["smam", "machinery", "mechanization", "harvester"],
    "cow": ["dairy", "deds", "gokul", "cattle", "bovine"],
    "buffalo": ["dairy", "deds", "cattle", "bovine"],
    "milk": ["dairy", "deds", "cattle", "milking"],
    "goat": ["livestock", "nlm", "sheep", "small ruminant"],
    "house": ["housing", "pmay", "awas", "construction", "pucca"],
    "gas": ["lpg", "ujjwala", "pmuy", "cylinder", "cooking"],
    "hospital": ["ayushman", "pm-jay", "health", "treatment", "cashless"],
    "land": ["property", "svamitva", "title deed", "property card", "patta"],
    "organic": [
        "natural farming",
        "nmnf",
        "pkvy",
        "chemical free",
        "cow dung",
    ],
}

SCHEME_ACRONYM_MAP: Dict[str, str] = {
    "kcc": "Kisan Credit Card Scheme low interest loan",
    "kusum": "PM KUSUM Pradhan Mantri Kisan Urja Suraksha solar pump",
    "pmfby": (
        "Pradhan Mantri Fasal Bima Yojana crop insurance compensation yellow"
        " disease damage"
    ),
    "pm-kisan": "PM KISAN Pradhan Mantri Kisan Samman Nidhi 6000 installment",
    "pmkisan": "PM KISAN Pradhan Mantri Kisan Samman Nidhi 6000 installment",
    "nais": "National Agriculture Insurance Scheme crop loss natural calamity",
    "acabc": (
        "Agri Clinics Agri Business Centres agriculture graduate startup"
    ),
    "svamitva": "SVAMITVA village property card drone survey title deed",
    "nlm": (
        "National Livestock Mission sheep goat poultry piggery fodder subsidy"
    ),
    "pmay": "Pradhan Mantri Awaas Yojana Gramin rural housing pucca house",
    "deds": (
        "Dairy Entrepreneurship Development Scheme cow buffalo milk subsidy"
        " NABARD"
    ),
    "rgm": "Rashtriya Gokul Mission indigenous cattle breed improvement AI",
    "pmuy": "Pradhan Mantri Ujjwala Yojana LPG gas cylinder cooking",
    "jjm": "Jal Jeevan Mission drinking water tap connection rural household",
    "ayushman": (
        "Ayushman Bharat PM-JAY health insurance cashless hospitalization"
        " 500000"
    ),
}

OUT_OF_DOMAIN_KEYWORDS = [
    "car",
    "electric car",
    "ev",
    "vehicle",
    "scooter",
    "space",
    "rocket",
    "delhi metro",
    "laptop",
    "iphone",
    "mobile phone",
    "cricket",
    "movie",
    "bitcoin",
    "share market",
    "stock market",
]

OUT_OF_DOMAIN_PATTERN = re.compile(
    r"\b(" + "|".join(OUT_OF_DOMAIN_KEYWORDS) + r")\b", re.IGNORECASE
)

INTENT_PATTERNS = {
    "documents_required": re.compile(
        r"\b(document|documents|doc|paper|papers|proof|certificate|khasra|patta|need|require|requirement)\b",
        re.IGNORECASE,
    ),
    "how_to_apply": re.compile(
        r"\b(apply|where|how|portal|register|enroll|procedure|process)\b",
        re.IGNORECASE,
    ),
    "eligibility_criteria": re.compile(
        r"\b(eligible|eligibility|who|criteria|qualification|age|land)\b",
        re.IGNORECASE,
    ),
    "benefit_details": re.compile(
        r"\b(benefit|benefits|amount|subsidy|rupees|money|pension|installment)\b",
        re.IGNORECASE,
    ),
}


# ---------------------------------------------------------------------------
# Core Helpers & Index Classes
# ---------------------------------------------------------------------------
def expand_query(raw_query: str) -> str:
    """Expands raw user query using synonyms and acronym maps."""
    query_lower = raw_query.lower()

    # Multi-word phrase expansion
    for phrase, expansions in SYNONYM_MAP.items():
        if " " in phrase and phrase in query_lower:
            raw_query += " " + " ".join(expansions)

    # Tokenize and expand single-word synonyms and acronyms
    tokens = fast_tokenizer(raw_query)
    expanded_terms = set(tokens)

    for token in tokens:
        if token in SCHEME_ACRONYM_MAP:
            expanded_terms.update(fast_tokenizer(SCHEME_ACRONYM_MAP[token]))
        if token in SYNONYM_MAP and " " not in token:
            expanded_terms.update(SYNONYM_MAP[token])

    return " ".join(expanded_terms)


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

                    # Anti-Magnetism Keyword Cleanup
                    cross_ref_keywords = (
                        list(SCHEME_ACRONYM_MAP.keys())
                        + ["mgnrega", "sbm-g", "aay", "secc"]
                        + data.get("cross_references", [])
                    )
                    for kw in cross_ref_keywords:
                        if kw.lower() not in name.lower():
                            searchable_text = re.sub(
                                rf"\b{kw}\b", "", searchable_text, flags=re.IGNORECASE
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
            except Exception:
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
    rrf_k: int = 60,
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

    def _extract_answer_by_intent(
        self, user_question: str, scheme: Dict[str, Any]
    ) -> str:
        """Uses compiled regex to select specific information requested by the user and caps length at 350 chars for TTS/LCD."""
        name = scheme["scheme_name"]

        if INTENT_PATTERNS["documents_required"].search(user_question):
            raw_text = scheme.get("documents_required", "")
            prefix = f"Documents required for {name}: "
        elif INTENT_PATTERNS["how_to_apply"].search(user_question):
            raw_text = scheme.get("how_to_apply", "")
            prefix = f"To apply for {name}: "
        elif INTENT_PATTERNS["eligibility_criteria"].search(user_question):
            raw_text = scheme.get("eligibility_criteria", "")
            prefix = f"Eligibility criteria for {name}: "
        elif INTENT_PATTERNS["benefit_details"].search(user_question):
            raw_text = scheme.get("benefit_details", "")
            prefix = f"Benefits under {name}: "
        else:
            raw_text = scheme.get("benefit_details", "")
            prefix = f"Under {name}: "

        if not raw_text:
            raw_text = scheme.get("benefit_details", "")

        full_response = f"{prefix}{raw_text}".strip()

        # Hard cap at 350 chars for clean Voice (TTS) & LCD display
        if len(full_response) > 350:
            full_response = full_response[:347].rsplit(" ", 1)[0] + "..."

        return full_response

    def predict_category(self, user_question: str) -> Tuple[Optional[str], float]:
        query_embedding = self.vector_index.model.encode(
            [user_question], show_progress_bar=False
        )
        query_embedding = np.array(query_embedding, dtype="float32")
        faiss.normalize_L2(query_embedding)
        similarities = np.dot(query_embedding, self.category_embeddings.T)[0]
        max_idx = np.argmax(similarities)
        return self.categories[max_idx], float(similarities[max_idx])

    def query_schemes(
        self, user_question: str, category: Optional[str] = None
    ) -> Dict[str, Any]:
        """Queries government schemes and returns structured dictionary for downstream agent integration."""
        start_time = time.time()

        target_category = category
        if not category:
            pred_cat, pred_score = self.predict_category(user_question)
            if pred_score > 0.55:
                target_category = pred_cat

        expanded_query = expand_query(user_question)

        vector_results = self.vector_index.search(expanded_query, top_k=5)
        bm25_results = self.bm25_index.search(expanded_query, top_k=5)
        fused_results = reciprocal_rank_fusion(vector_results, bm25_results)

        # Exact Acronym Priority Boost: If user explicitly typed a known acronym/name, boost its score 2.5x
        user_q_lower = user_question.lower()
        for item in fused_results:
            s_name = item["scheme"]["scheme_name"].lower()
            s_id = item["scheme"]["scheme_id"].lower()
            for acronym in SCHEME_ACRONYM_MAP.keys():
                if acronym in user_q_lower and (acronym in s_name or acronym in s_id):
                    item["rrf_score"] *= 2.5

        # Soft-Gating Boost
        if target_category:
            for item in fused_results:
                if item["scheme"].get("category") == target_category:
                    item["rrf_score"] *= 1.2

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
            top_cosine_score < 0.35 and top_bm25_score < 3.0
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

        answer = self._extract_answer_by_intent(user_question, best)

        return {
            "outcome": "scheme_found",
            "status": "success",
            "question": user_question,
            "text": answer,
            "explanation_text": answer,
            "scheme_name": best["scheme_name"],
            "scheme_id": best["scheme_id"],
            "confidence_score": top_cosine_score,
            "top_match": {
                "doc_id": best["scheme_id"],
                "scheme_name": best["scheme_name"],
                "similarity_score": top_cosine_score,
                "rrf_score": top_fused_item.get("rrf_score", 0.0),
            },
            "okf_v02_card": {
                "okf_version": "v0.2",
                "knowledge_id": best["scheme_id"],
                "title": best["scheme_name"],
                "category": f"Government Support - {best.get('category', 'General')}",
                "target_audience": "Farmers and Rural Citizens",
                "key_facts_and_explanations": best["benefit_details"],
                "action_steps": best["how_to_apply"],
                "safety_disclaimer": (
                    "Information based on official government scheme records."
                ),
            },
            "tft_lcd_display_card": (
                f"=== SCHEME: {best['scheme_name'][:25]} ===\n"
                f"ID: {best['scheme_id']} | Score: {round(top_cosine_score, 4)}\n"
                f"----------------------------------------\n"
                f"{answer}\n"
                f"----------------------------------------"
            ),
            "bhashini_voice_text": f"Regarding {best['scheme_name']}: {answer}",
            "latency_seconds": latency,
        }


# ---------------------------------------------------------------------------
# Test Runner Block
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    engine = GovernmentSchemesRAGEngine()

    sample_queries = [
        "How can small farmers get 6000 rupees direct benefit transfer?",
        "I need a subsidy for a solar pump for water",
        "What is the crop insurance for drought and flood loss?",
        "How to get low interest loan using KCC card?",
        "random irrelevant question about space rockets",
    ]

    logger.info("Executing sample benchmark pass...")
    for q in sample_queries:
        res = engine.query_schemes(q)
        match_info = res.get("top_match", {})
        matched_name = match_info.get("scheme_name", "None")
        matched_id = match_info.get("doc_id", "N/A")
        score = match_info.get("similarity_score", 0.0)

        logger.info(
            f"Query: '{q}' -> Status: {res['status'].upper()} | Match: {matched_name}"
            f" ({matched_id}) | Score: {score} | Latency: {res['latency_seconds']}s"
        )