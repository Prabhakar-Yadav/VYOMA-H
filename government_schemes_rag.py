import os
import sys
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import torch
torch.set_num_threads(2)

import json
import time
import re
import numpy as np
import faiss
from typing import List, Dict, Set, Any
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi

# Force UTF-8 encoding for Windows terminal compatibility
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def char_ngram_tokenizer(text: str, n_min: int = 3, n_max: int = 5) -> List[str]:
    """Generates sliding character n-grams (3-5 chars) for typo-resilient BM25 searching."""
    clean_text = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower())
    padded_text = f" {clean_text} "
    ngrams = []
    for n in range(n_min, n_max + 1):
        for i in range(len(padded_text) - n + 1):
            ngrams.append(padded_text[i:i + n])
    return ngrams


# Hinglish Agricultural Term Dictionary
SYNONYM_MAP: Dict[str, List[str]] = {
    # Water / Irrigation
    "paani": ["irrigation", "sinchai", "water", "pump", "boring"],
    "pani": ["irrigation", "sinchai", "water", "pump"],
    "tubewell": ["pmksy", "irrigation", "water", "boring"],
    "borwel": ["pmksy", "irrigation", "water", "boring"],
    # Financial / Loans
    "paisa": ["subsidy", "financial assistance", "installment", "kist"],
    "karza": ["loan", "credit", "kcc", "subvention"],
    "karz": ["loan", "credit", "kcc"],
    # Energy / Solar
    "bijli": ["solar", "kusum", "electricity", "grid"],
    "dhoop": ["solar", "kusum"],
    # Crop Damage & Insurance
    "kharaab": ["loss", "compensation", "insurance", "pmfby"],
    "keeda": ["pesticide", "protection", "crop damage"],
    "insurance": ["pmfby", "fasal bima", "compensation", "loss"],
    "drought": ["pmfby", "fasal bima", "crop loss", "compensation"],
    "flood": ["pmfby", "fasal bima", "crop loss", "compensation"],
    "bima": ["pmfby", "insurance", "crop loss"],
    "claim": ["pmfby", "insurance", "compensation", "settlement"],
    "time limit": ["pmfby", "duration", "timeline", "intimation"],
    # Mandi & Rates
    "mandi": ["e-nam", "enam", "market", "registration", "trade"],
    "bechne": ["e-nam", "market", "selling", "enam"],
    "bhav": ["enam", "e-nam", "market price", "bidding", "rate"],
    "dam": ["enam", "e-nam", "price", "market rate"],
    # Machinery / Tractors
    "tractor": ["smam", "machinery", "mechanization", "harvester"],
    "khareedne": ["subsidy", "purchase", "machinery"]
}

SCHEME_ACRONYM_MAP: Dict[str, str] = {
    "kcc": "Kisan Credit Card Scheme low interest loan",
    "kusum": "PM KUSUM Pradhan Mantri Kisan Urja Suraksha solar pump",
    "pmfby": "Pradhan Mantri Fasal Bima Yojana crop insurance compensation",
    "pm-kisan": "PM KISAN Pradhan Mantri Kisan Samman Nidhi 6000 installment",
    "pmkisan": "PM KISAN Pradhan Mantri Kisan Samman Nidhi 6000 installment"
}

OUT_OF_DOMAIN_KEYWORDS = [
    "car", "electric car", "ev", "vehicle", "scooter", "space", "rocket", "delhi metro", "laptop"
]


def expand_query(raw_query: str) -> str:
    """Expands query with Hindi/Hinglish domain terms in <1ms."""
    tokens = raw_query.lower().split()
    expanded_terms: Set[str] = set(tokens)
    for token in tokens:
        if token in SCHEME_ACRONYM_MAP:
            expanded_terms.add(SCHEME_ACRONYM_MAP[token])
        if token in SYNONYM_MAP:
            expanded_terms.update(SYNONYM_MAP[token])
    return " ".join(expanded_terms)


def load_schemes_dataset(jsonl_path: str) -> List[Dict[str, Any]]:
    schemes = []
    if not os.path.exists(jsonl_path):
        print(f"[Error] Dataset file not found: {jsonl_path}")
        return []
    
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line.strip())
                    s_id = data.get("scheme_id", "")
                    name = data.get("scheme_name", "")
                    beneficiary = data.get("target_beneficiary", "")
                    benefits = data.get("benefit_details", "")
                    eligibility = data.get("eligibility_criteria", "")
                    apply_info = data.get("how_to_apply", "")
                    docs = data.get("documents_required", "")
                    
                    searchable_text = f"{name} {beneficiary} {benefits} {eligibility} {apply_info} {docs}"
                    ngram_tokens = char_ngram_tokenizer(searchable_text)
                    
                    schemes.append({
                        "scheme_id": s_id,
                        "scheme_name": name,
                        "target_beneficiary": beneficiary,
                        "benefit_details": benefits,
                        "eligibility_criteria": eligibility,
                        "how_to_apply": apply_info,
                        "documents_required": docs,
                        "searchable_text": searchable_text,
                        "ngram_tokens": ngram_tokens
                    })
                except Exception:
                    continue
    return schemes


class SchemesFAISSVectorIndex:
    def __init__(self, schemes: List[Dict[str, Any]]):
        self.schemes = schemes
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
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
        embeddings = self.model.encode(searchable_texts, show_progress_bar=False, batch_size=32)
        embeddings = np.array(embeddings, dtype='float32')
        faiss.normalize_L2(embeddings)
        
        self.index = faiss.IndexFlatIP(self.dimension)
        self.index.add(embeddings)
        faiss.write_index(self.index, self.cache_index_path)

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_embedding = self.model.encode([query])
        query_embedding = np.array(query_embedding, dtype='float32')
        faiss.normalize_L2(query_embedding)
        
        distances, indices = self.index.search(query_embedding, top_k)
        results = []
        for i, idx in enumerate(indices[0]):
            if idx < len(self.schemes):
                results.append({
                    "scheme_id": self.schemes[idx]["scheme_id"],
                    "rank": i + 1,
                    "score": round(float(distances[0][i]), 4),
                    "scheme": self.schemes[idx]
                })
        return results


class SchemesBM25Index:
    def __init__(self, schemes: List[Dict[str, Any]]):
        self.schemes = schemes
        corpus_tokens = [s["ngram_tokens"] for s in self.schemes]
        self.bm25 = BM25Okapi(corpus_tokens)

    def search(self, raw_query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_tokens = char_ngram_tokenizer(raw_query)
        scores = self.bm25.get_scores(query_tokens)
        top_indices = np.argsort(scores)[::-1][:top_k]
        
        results = []
        for rank, idx in enumerate(top_indices):
            results.append({
                "scheme_id": self.schemes[idx]["scheme_id"],
                "rank": rank + 1,
                "score": round(float(scores[idx]), 4),
                "scheme": self.schemes[idx]
            })
        return results


def reciprocal_rank_fusion(vector_results: List[Dict[str, Any]], 
                           bm25_results: List[Dict[str, Any]], 
                           rrf_k: int = 60) -> List[Dict[str, Any]]:
    rrf_scores = {}
    scheme_map = {}
    
    for item in vector_results:
        s_id = item["scheme_id"]
        rank = item["rank"]
        scheme_map[s_id] = item["scheme"]
        rrf_scores[s_id] = rrf_scores.get(s_id, 0.0) + (1.0 / (rrf_k + rank))
        
    for item in bm25_results:
        s_id = item["scheme_id"]
        rank = item["rank"]
        scheme_map[s_id] = item["scheme"]
        rrf_scores[s_id] = rrf_scores.get(s_id, 0.0) + (1.0 / (rrf_k + rank))
        
    sorted_schemes = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    final_results = []
    for s_id, score in sorted_schemes:
        final_results.append({
            "scheme_id": s_id,
            "rrf_score": round(score, 6),
            "scheme": scheme_map[s_id]
        })
    return final_results


class GovernmentSchemesRAGEngine:
    def __init__(self, jsonl_file: str = "schemes_dataset.jsonl"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        jsonl_path = os.path.join(base_dir, jsonl_file)
        
        print("[Init] Loading government schemes dataset...")
        self.schemes = load_schemes_dataset(jsonl_path)
        print(f"[Init] Loaded {len(self.schemes)} government schemes.")
        
        print("[Init] Building FAISS Vector Index (all-MiniLM-L6-v2)...")
        self.vector_index = SchemesFAISSVectorIndex(self.schemes)
        
        print("[Init] Building BM25 Keyword Index (n-gram tokens)...")
        self.bm25_index = SchemesBM25Index(self.schemes)
        
        # Warmup pass
        _ = self.vector_index.model.encode(["warmup query"], show_progress_bar=False)
        print("[Init] Government Schemes RAG Engine Ready!\n")

    def query_schemes(self, user_question: str) -> Dict[str, Any]:
        """Queries government schemes and returns clean farmer-focused dictionary."""
        start_time = time.time()
        
        # Step 1: Fast Query Expansion (<1ms)
        expanded_query = expand_query(user_question)
        
        # Step 2: Dual Hybrid Search (FAISS + BM25)
        vector_results = self.vector_index.search(expanded_query, top_k=5)
        bm25_results = self.bm25_index.search(expanded_query, top_k=5)
        
        # Step 3: Reciprocal Rank Fusion (RRF)
        fused_results = reciprocal_rank_fusion(vector_results, bm25_results)
        
        if not fused_results:
            return {"status": "error", "message": "No matching government schemes found."}
            
        best = fused_results[0]["scheme"]
        raw_score = vector_results[0]["score"] if vector_results else 0.0
        top_cosine_score = round(float(np.clip(raw_score, -1.0, 1.0)), 4)
        top_bm25_score = bm25_results[0]["score"] if bm25_results else 0.0
        
        # Step 4: Safety Fallback Gate
        query_words = set(re.findall(r'\b[a-z0-9-]+\b', user_question.lower()))
        is_out_of_domain = any(kw in query_words for kw in OUT_OF_DOMAIN_KEYWORDS)
        is_fallback = is_out_of_domain or (top_cosine_score < 0.35 and top_bm25_score < 5.0)
        
        if is_fallback:
            latency = time.time() - start_time
            return {
                "status": "fallback",
                "question": user_question,
                "confidence_score": top_cosine_score,
                "lcd_text": "=== NOTICE ===\nLow confidence match.\nPlease rephrase your query.",
                "voice_text": "Kisan bhai! Aapka sawal kripya spast roop se dobara poochein.",
                "latency_ms": round(latency * 1000, 2)
            }
            
        # Format for 2.8" TFT LCD Display
        lcd_text = (
            f"=== SCHEME: {best['scheme_name'][:30]} ===\n"
            f"ID: {best['scheme_id']} | Cosine: {top_cosine_score}\n"
            f"Beneficiary: {best['target_beneficiary'][:35]}\n"
            f"----------------------------------------\n"
            f"Benefits: {best['benefit_details']}\n"
            f"Eligibility: {best['eligibility_criteria']}\n"
            f"Apply: {best['how_to_apply']}\n"
            f"Docs: {best['documents_required']}\n"
            f"----------------------------------------"
        )

        # Format for Bhashini Voice Output
        voice_text = (
            f"Kisan bhai! {best['scheme_name']} ke taht: "
            f"{best['benefit_details']} Avedan karne ke liye {best['how_to_apply']}."
        )

        # Smart Intent Extractor (Extracts ONLY what the farmer asked for)
        q_lower = user_question.lower()
        if any(w in q_lower for w in ["document", "doc", "kagaz", "paper", "proof", "certificate"]):
            answer = f"Documents required for {best['scheme_name']}: {best['documents_required']}"
        elif any(w in q_lower for w in ["apply", "where", "how", "portal", "register", "avedan"]):
            answer = f"To apply for {best['scheme_name']}: {best['how_to_apply']}"
        elif any(w in q_lower for w in ["eligible", "who", "patra", "criteria"]):
            answer = f"Eligibility criteria for {best['scheme_name']}: {best['eligibility_criteria']}"
        else:
            answer = f"Under {best['scheme_name']}: {best['benefit_details']}"

        latency = time.time() - start_time
        
        return {
            "status": "success",
            "question": user_question,
            "scheme_id": best["scheme_id"],
            "scheme_name": best["scheme_name"],
            "answer": answer,
            "lcd_text": lcd_text,
            "voice_text": voice_text,
            "confidence_score": top_cosine_score,
            "latency_ms": round(latency * 1000, 2)
        }


if __name__ == "__main__":
    engine = GovernmentSchemesRAGEngine()
    
    test_queries = [
        "How can small kisaan get 6000 rupees direct benefit transfer?",
        "Mujhe pani ke liye solar pump subsidy chahiye",
        "What is the crop insurance for drought and flood loss?",
        "How to get low interest loan using KCC card?",
        "What documents are required for PM-KISAN?",
        "random irrelevant question about space rockets",
        "mandi me fasal bechne ke liye online registration kaise kare",
        "what is the subsidy for buying a private electric car in Delhi"
    ]
    
    for q in test_queries:
        res = engine.query_schemes(q)
        print("=========================================================")
        print(f"QUERY: \"{res['question']}\"")
        print(f"STATUS: {res['status'].upper()}")
        if res["status"] == "success":
            print(f"MATCH: {res['scheme_name']} ({res['scheme_id']}) | Score: {res['confidence_score']}")
            print(f"ANSWER:\n{res['answer']}\n")
        else:
            print(f"CONFIDENCE: {res['confidence_score']} (Below Cutoff)")
            print(f"VOICE TEXT: {res['voice_text']}")
        print(f"LATENCY: {res['latency_ms']} ms")
        print("=========================================================\n")