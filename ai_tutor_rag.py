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
from typing import List, Dict, Set, Any, Optional
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi

# Set UTF-8 encoding for Windows terminal output
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


# Hinglish / Regional Science & Math Term Dictionary
TUTOR_SYNONYM_MAP: Dict[str, List[str]] = {
    # Science & Biology
    "prakash": ["photosynthesis", "sunlight", "chlorophyll", "plant"],
    "dhoop": ["sunlight", "photosynthesis", "energy"],
    "paani": ["water", "purify", "drinking", "boiling", "filtration"],
    "pani": ["water", "purify", "drinking", "boiling"],
    "saaf": ["purify", "safe", "clean", "treatment"],
    "shuddh": ["purify", "pure", "clean"],
    "paachan": ["digestion", "digestive", "stomach", "food"],
    "khana": ["food", "nutrition", "digestion"],
    # Physics & Chemistry
    "bijli": ["electricity", "electric", "circuit", "current", "voltage"],
    "takar": ["force", "friction", "motion"],
    "garmi": ["heat", "temperature", "conduction", "radiation"],
    # Mathematics
    "ginti": ["arithmetic", "numbers", "progression", "sequence"],
    "samantar": ["arithmetic progression", "common difference", "sequence"],
    "jod": ["addition", "sum", "total"],
    "ghatana": ["subtraction", "difference"],
    "guna": ["multiplication", "product"],
    "bhag": ["division", "fraction"]
}

TUTOR_ACRONYM_MAP: Dict[str, str] = {
    "ap": "Arithmetic Progression sequence common difference",
    "ncert": "National Council of Educational Research and Training curriculum"
}

NON_EDUCATIONAL_KEYWORDS = [
    "movie", "film", "actor", "cricket match", "pubg", "casino", "gambling", "stock market"
]


def expand_tutor_query(raw_query: str) -> str:
    """Expands student query with scientific, mathematical, and Hinglish synonyms."""
    tokens = raw_query.lower().split()
    expanded_terms: Set[str] = set(tokens)
    
    for token in tokens:
        if token in TUTOR_ACRONYM_MAP:
            expanded_terms.add(TUTOR_ACRONYM_MAP[token])
        if token in TUTOR_SYNONYM_MAP:
            expanded_terms.update(TUTOR_SYNONYM_MAP[token])
            
    return " ".join(expanded_terms)


def create_okf_document(doc_id: str, subject: str, grade_level: str, topic: str, content: str) -> Dict[str, Any]:
    searchable_text = f"{topic} {content} {subject} {grade_level}"
    ngram_tokens = char_ngram_tokenizer(searchable_text)
    return {
        "doc_id": doc_id,
        "subject": subject,
        "grade_level": grade_level,
        "topic": topic,
        "content": content,
        "searchable_text": searchable_text,
        "ngram_tokens": ngram_tokens
    }


def load_real_jsonl_curriculum(jsonl_path: str) -> List[Dict[str, Any]]:
    okf_documents = []
    if not os.path.exists(jsonl_path):
        print(f"[Error] Curriculum dataset file not found: {jsonl_path}")
        return []
        
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for idx, line in enumerate(f):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
                instruction = data.get("instruction", "").strip()
                response = data.get("response", "").strip()
                
                if instruction and response:
                    doc = create_okf_document(
                        doc_id=f"NCERT_{idx+1:04d}",
                        subject=data.get("subject", "General NCERT"),
                        grade_level=f"Class {data.get('grade', '5-8')}",
                        topic=instruction,
                        content=response
                    )
                    okf_documents.append(doc)
            except Exception:
                continue
                
    return okf_documents


class TutorFAISSVectorIndex:
    def __init__(self, documents: List[Dict[str, Any]]):
        self.documents = documents
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.dimension = 384
        self.index = None
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cache_index_path = os.path.join(base_dir, "tutor_faiss_index.bin")
        
        if os.path.exists(self.cache_index_path):
            try:
                self.index = faiss.read_index(self.cache_index_path)
            except Exception:
                self._build_index()
        else:
            self._build_index()
    
    def _build_index(self):
        searchable_texts = [doc["searchable_text"] for doc in self.documents]
        embeddings = self.model.encode(searchable_texts, show_progress_bar=False, batch_size=64)
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
            if idx < len(self.documents):
                doc = self.documents[idx]
                results.append({
                    "doc_id": doc["doc_id"],
                    "rank": i + 1,
                    "score": round(float(distances[0][i]), 4),
                    "doc": doc
                })
        return results


class TutorBM25Index:
    def __init__(self, documents: List[Dict[str, Any]]):
        self.documents = documents
        corpus_tokens = [doc["ngram_tokens"] for doc in self.documents]
        self.bm25 = BM25Okapi(corpus_tokens)

    def search(self, raw_query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_tokens = char_ngram_tokenizer(raw_query)
        scores = self.bm25.get_scores(query_tokens)
        top_indices = np.argsort(scores)[::-1][:top_k]
        
        results = []
        for rank, idx in enumerate(top_indices):
            results.append({
                "doc_id": self.documents[idx]["doc_id"],
                "rank": rank + 1,
                "score": round(float(scores[idx]), 4),
                "doc": self.documents[idx]
            })
        return results


def reciprocal_rank_fusion(vector_results: List[Dict[str, Any]], 
                           bm25_results: List[Dict[str, Any]], 
                           rrf_k: int = 60) -> List[Dict[str, Any]]:
    rrf_scores = {}
    doc_map = {}
    
    for item in vector_results:
        d_id = item["doc_id"]
        rank = item["rank"]
        doc_map[d_id] = item["doc"]
        rrf_scores[d_id] = rrf_scores.get(d_id, 0.0) + (1.0 / (rrf_k + rank))
        
    for item in bm25_results:
        d_id = item["doc_id"]
        rank = item["rank"]
        doc_map[d_id] = item["doc"]
        rrf_scores[d_id] = rrf_scores.get(d_id, 0.0) + (1.0 / (rrf_k + rank))
        
    sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    final_results = []
    for d_id, score in sorted_docs:
        final_results.append({
            "doc_id": d_id,
            "rrf_score": round(score, 6),
            "doc": doc_map[d_id]
        })
    return final_results


class GoogleOKFAITutorEngine:
    def __init__(self, jsonl_file: str = "clean_curriculum.jsonl"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        jsonl_path = os.path.join(base_dir, jsonl_file)
        
        print("[Init] Loading NCERT K-12 Literacy curriculum dataset...")
        self.documents = load_real_jsonl_curriculum(jsonl_path)
        print(f"[Init] Loaded {len(self.documents)} curriculum lesson cards.")
        
        print("[Init] Building FAISS Vector Index for AI Tutor...")
        self.vector_index = TutorFAISSVectorIndex(self.documents)
        
        print("[Init] Building BM25 Keyword Index (n-gram tokens) for AI Tutor...")
        self.bm25_index = TutorBM25Index(self.documents)
        
        # Warmup pass
        _ = self.vector_index.model.encode(["warmup query"], show_progress_bar=False)
        print("[Init] AI Tutor Hybrid RAG Engine Ready!\n")

    def query_tutor(self, user_question: str, dialect: str = "Bhojpuri", top_k: int = 3) -> Dict[str, Any]:
        start_time = time.time()
        
        # Step 1: Fast Query Expansion (<1ms)
        expanded_query = expand_tutor_query(user_question)
        
        # Step 2: Hybrid Search (FAISS + BM25)
        vector_results = self.vector_index.search(expanded_query, top_k=5)
        bm25_results = self.bm25_index.search(expanded_query, top_k=5)
        
        # Step 3: Reciprocal Rank Fusion
        fused_results = reciprocal_rank_fusion(vector_results, bm25_results)
        
        if not fused_results:
            return {"status": "error", "message": "No matching curriculum lessons found."}
            
        best = fused_results[0]["doc"]
        raw_score = vector_results[0]["score"] if vector_results else 0.0
        top_cosine_score = round(float(np.clip(raw_score, -1.0, 1.0)), 4)
        top_bm25_score = bm25_results[0]["score"] if bm25_results else 0.0
        
        # Step 4: Safety Fallback Gate
        query_words = set(re.findall(r'\b[a-z0-9-]+\b', user_question.lower()))
        is_out_of_domain = any(kw in query_words for kw in NON_EDUCATIONAL_KEYWORDS)
        is_fallback = is_out_of_domain or (top_cosine_score < 0.32 and top_bm25_score < 4.0)
        
        if is_fallback:
            latency = time.time() - start_time
            return {
                "status": "fallback",
                "question": user_question,
                "confidence_score": top_cosine_score,
                "tft_lcd_display_card": "=== NOTICE ===\nLow confidence match.\nPlease ask a school curriculum question.",
                "bhashini_voice_text": "Bacho! Aapka sawal kripya spast roop se dobara poochein.",
                "latency_seconds": round(latency, 4)
            }
            
        # Format for 2.8" TFT LCD Display
        tft_lcd_display_card = (
            f"=== LESSON: {best['topic'][:30]} ===\n"
            f"Grade: {best['grade_level']} | Sub: {best['subject']}\n"
            f"ID: {best['doc_id']} | Cosine: {top_cosine_score}\n"
            f"----------------------------------------\n"
            f"{best['content']}\n"
            f"----------------------------------------"
        )

        dialect_voice_text = f"Bacho! {best['topic']} ke baare me: {best['content']}"
        
        # Official OKF v0.2 Knowledge Card
        okf_v02_card = {
            "okf_version": "v0.2",
            "knowledge_id": best["doc_id"],
            "title": best["topic"],
            "category": f"Rural Literacy - {best['subject']}",
            "target_audience": best["grade_level"],
            "key_facts_and_explanations": best["content"],
            "safety_disclaimer": "Verbatim NCERT K-12 curriculum record with zero LLM hallucination."
        }

        latency = time.time() - start_time
        
        return {
            "status": "success",
            "question": user_question,
            "top_match": {
                "doc_id": best["doc_id"],
                "subject": best["subject"],
                "grade_level": best["grade_level"],
                "topic": best["topic"],
                "similarity_score": top_cosine_score,
                "rrf_score": fused_results[0]["rrf_score"]
            },
            "okf_v02_card": okf_v02_card,
            "explanation_text": best["content"],
            "tft_lcd_display_card": tft_lcd_display_card,
            "bhashini_voice_text": dialect_voice_text,
            "dialect": dialect,
            "latency_seconds": round(latency, 4)
        }


if __name__ == "__main__":
    tutor = GoogleOKFAITutorEngine()
    
    test_questions = [
        "How do plants make food using sunlight?",
        "What is Arithmetic Progression? Give daily life examples",
        "How to purify drinking water in villages?",
        "paani ko saaf aur shuddh karne ka tarika",
        "prakash sanshleshan se पौधे apna khana kaise banate hain",
        "random movie show timings"
    ]
    
    for question in test_questions:
        res = tutor.query_tutor(question, dialect="Bhojpuri")
        print("=========================================================")
        print(f"QUERY: \"{res['question']}\"")
        print(f"STATUS: {res['status'].upper()}")
        if res["status"] == "success":
            print(f"TOP MATCH: {res['top_match']['doc_id']} ({res['top_match']['subject']} - {res['top_match']['grade_level']})")
            print(f"COSINE: {res['top_match']['similarity_score']} | RRF SCORE: {res['top_match']['rrf_score']}")
            print(f"TOPIC: {res['top_match']['topic']}")
            print(f"\nEXPLANATION:\n{res['explanation_text']}\n")
        else:
            print(f"CONFIDENCE: {res['confidence_score']} (Below Cutoff)")
            print(f"VOICE TEXT: {res['bhashini_voice_text']}")
        print(f"LATENCY: {res['latency_seconds']}s ({round(res['latency_seconds']*1000, 2)} ms)")
        print("=========================================================\n")
