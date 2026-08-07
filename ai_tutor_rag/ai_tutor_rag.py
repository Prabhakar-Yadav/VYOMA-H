import os
import sys
import json
import time
import re
import pickle
import hashlib
import numpy as np
import faiss
from typing import List, Dict, Set, Any
from sentence_transformers import SentenceTransformer, CrossEncoder
from rank_bm25 import BM25Okapi

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import torch
torch.set_num_threads(2)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

NON_EDUCATIONAL_KEYWORDS = ["movie", "film", "actor", "cricket match", "pubg", "casino", "gambling", "stock market"]

# ----------------------------------------------------------------------
# 1. Helpers & Utilities
# ----------------------------------------------------------------------
def char_ngram_tokenizer(text: str, n_min: int = 3, n_max: int = 5) -> List[str]:
    clean_text = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower())
    padded_text = f" {clean_text} "
    return [padded_text[i:i + n] for n in range(n_min, n_max + 1) for i in range(len(padded_text) - n + 1)]

def get_file_hash(filepath: str) -> str:
    """Fast stat-based metadata signature (size + mtime) to avoid full disk reads."""
    if not os.path.exists(filepath):
        return ""
    stat = os.stat(filepath)
    fast_sig = f"{stat.st_size}_{stat.st_mtime}"
    return hashlib.md5(fast_sig.encode()).hexdigest()

def is_cache_valid(cache_path: str, hash_path: str, expected_hash: str) -> bool:
    if os.path.exists(cache_path) and os.path.exists(hash_path):
        with open(hash_path, 'r') as f:
            return f.read().strip() == expected_hash
    return False

def save_hash(hash_path: str, dataset_hash: str):
    with open(hash_path, 'w') as f:
        f.write(dataset_hash)

def load_real_jsonl_curriculum(jsonl_path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(jsonl_path):
        return []
    documents = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for idx, line in enumerate(f):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                instruction, response = data.get("instruction", "").strip(), data.get("response", "").strip()
                if instruction and response:
                    doc_id = f"NCERT_{idx+1:04d}"
                    subject, grade = data.get("subject", "General NCERT"), f"Class {data.get('grade', '5-8')}"
                    searchable = f"{instruction} {response} {subject} {grade}"
                    documents.append({
                        "doc_id": doc_id, "subject": subject, "grade_level": grade,
                        "topic": instruction, "content": response,
                        "searchable_text": searchable, "ngram_tokens": char_ngram_tokenizer(searchable)
                    })
            except Exception:
                continue
    return documents

# ----------------------------------------------------------------------
# 2. Vector & Keyword Indexers
# ----------------------------------------------------------------------
class TutorFAISSVectorIndex:
    def __init__(self, documents: List[Dict[str, Any]], dataset_hash: str):
        self.documents = documents
        self.model = SentenceTransformer('BAAI/bge-small-en-v1.5')
        self.dimension = 384
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cache_path = os.path.join(base_dir, "tutor_bge_faiss_index.bin")
        self.hash_path = os.path.join(base_dir, "tutor_bge_faiss_index.hash")
        
        if is_cache_valid(self.cache_path, self.hash_path, dataset_hash):
            try:
                self.index = faiss.read_index(self.cache_path)
            except Exception:
                self._build_index(dataset_hash)
        else:
            self._build_index(dataset_hash)

    def _build_index(self, dataset_hash: str):
        texts = [doc["searchable_text"] for doc in self.documents]
        embeddings = np.array(self.model.encode(texts, show_progress_bar=False, batch_size=64), dtype='float32')
        faiss.normalize_L2(embeddings)
        self.index = faiss.IndexFlatIP(self.dimension)
        self.index.add(embeddings)
        faiss.write_index(self.index, self.cache_path)
        save_hash(self.hash_path, dataset_hash)

    def search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        instruction = "Represent this sentence for searching relevant passages: "
        query_emb = np.array(self.model.encode([instruction + query]), dtype='float32')
        faiss.normalize_L2(query_emb)
        distances, indices = self.index.search(query_emb, top_k)
        
        return [{
            "doc_id": self.documents[idx]["doc_id"], "rank": i + 1,
            "score": round(float(distances[0][i]), 4), "doc": self.documents[idx]
        } for i, idx in enumerate(indices[0]) if idx < len(self.documents)]


class TutorBM25Index:
    def __init__(self, documents: List[Dict[str, Any]], dataset_hash: str):
        self.documents = documents
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cache_path = os.path.join(base_dir, "tutor_bm25_index.pkl")
        self.hash_path = os.path.join(base_dir, "tutor_bm25_index.hash")
        
        if is_cache_valid(self.cache_path, self.hash_path, dataset_hash):
            try:
                with open(self.cache_path, "rb") as f:
                    self.bm25 = pickle.load(f)
            except Exception:
                self._build_index(dataset_hash)
        else:
            self._build_index(dataset_hash)

    def _build_index(self, dataset_hash: str):
        self.bm25 = BM25Okapi([doc["ngram_tokens"] for doc in self.documents])
        with open(self.cache_path, "wb") as f:
            pickle.dump(self.bm25, f)
        save_hash(self.hash_path, dataset_hash)

    def search(self, raw_query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        scores = self.bm25.get_scores(char_ngram_tokenizer(raw_query))
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [{
            "doc_id": self.documents[idx]["doc_id"], "rank": rank + 1,
            "score": round(float(scores[idx]), 4), "doc": self.documents[idx]
        } for rank, idx in enumerate(top_indices)]

# ----------------------------------------------------------------------
# 3. Engine & Dynamic Cross-Encoder Reranking
# ----------------------------------------------------------------------
def reciprocal_rank_fusion(vector_res: List[Dict], bm25_res: List[Dict], rrf_k: int = 60) -> List[Dict]:
    rrf_scores, doc_map = {}, {}
    for item in vector_res + bm25_res:
        d_id = item["doc_id"]
        doc_map[d_id] = item["doc"]
        rrf_scores[d_id] = rrf_scores.get(d_id, 0.0) + (1.0 / (rrf_k + item["rank"]))
        
    return [{"doc_id": d_id, "rrf_score": round(score, 6), "doc": doc_map[d_id]} 
            for d_id, score in sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)]


class GoogleOKFAITutorEngine:
    def __init__(self, jsonl_file: str = "clean_curriculum.jsonl"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        jsonl_path = os.path.join(base_dir, jsonl_file)
        
        print("[Init] Loading NCERT K-12 Literacy curriculum dataset...")
        self.documents = load_real_jsonl_curriculum(jsonl_path)
        self.dataset_hash = get_file_hash(jsonl_path)
        print(f"[Init] Loaded {len(self.documents)} curriculum lesson cards.")
        
        print("[Init] Building FAISS Vector Index for AI Tutor...")
        self.vector_index = TutorFAISSVectorIndex(self.documents, self.dataset_hash)
        
        print("[Init] Building BM25 Keyword Index for AI Tutor...")
        self.bm25_index = TutorBM25Index(self.documents, self.dataset_hash)
        
        print("[Init] AI Tutor Hybrid RAG Engine Ready!\n")
        _ = self.vector_index.model.encode(["warmup query"], show_progress_bar=False)
        print("[Init] AI Tutor Hybrid RAG Engine Ready!\n")

    def query_tutor(self, user_question: str) -> Dict[str, Any]:
        start_time = time.time()
        
        # Step 1: Hybrid First-Pass Retrieval (Top 10 candidates)
        t0 = time.perf_counter()
        vector_res = self.vector_index.search(user_question, top_k=10)
        bm25_res = self.bm25_index.search(user_question, top_k=10)
        fused = reciprocal_rank_fusion(vector_res, bm25_res)[:10]
        print(f"[PROFILE] Retrieval + RRF: {(time.perf_counter() - t0)*1000:.1f}ms")

        if not fused:
            return {"status": "error", "message": "No matching lessons."}

        # Step 2: Extract top candidate directly from RRF (Skipping heavy Cross-Encoder for Jetson Nano)
        best_candidate = fused[0]
        best = best_candidate["doc"]

        # Scores calculation
        vec_score = next((v["score"] for v in vector_res if v["doc_id"] == best["doc_id"]), 0.0)
        bm25_score = next((b["score"] for b in bm25_res if b["doc_id"] == best["doc_id"]), 0.0)
        top_cosine = round(float(np.clip(vec_score, -1.0, 1.0)), 4)

        # Step 3: Safety Fallback Check
        is_ood = any(kw in user_question.lower() for kw in NON_EDUCATIONAL_KEYWORDS)
        low_confidence = (top_cosine < 0.35 and bm25_score < 5.0)

        if is_ood or low_confidence:
            latency = round(time.time() - start_time, 4)
            fallback_msg = "This topic is outside my current school curriculum knowledge. Please ask a science or math question."
            return {
                "outcome": "fallback",
                "status": "fallback",
                "question": user_question,
                "text": fallback_msg,
                "bhashini_voice_text": fallback_msg,
                "tft_lcd_display_card": "=== SYSTEM ===\nTopic outside curriculum.\nPlease ask a science\nor math question.",
                "confidence_score": top_cosine,
                "latency_seconds": latency
            }

        # Display Cards Output
        tft_lcd_display_card = (
            f"=== LESSON: {best['topic'][:30]} ===\n"
            f"Grade: {best['grade_level']} | Sub: {best['subject']}\n"
            f"ID: {best['doc_id']} | Score: {round(top_cosine, 4)}\n"
            f"----------------------------------------\n"
            f"{best['content']}\n"
            f"----------------------------------------"
        )

        voice_text = f"Here is what I found about {best['topic']}: {best['content']}"
        
        okf_v02_card = {
            "okf_version": "v0.2",
            "knowledge_id": best["doc_id"],
            "title": best["topic"],
            "category": f"Rural Literacy - {best['subject']}",
            "target_audience": best["grade_level"],
            "key_facts_and_explanations": best["content"],
            "safety_disclaimer": "Verbatim NCERT K-12 curriculum record with zero LLM hallucination."
        }

        latency = round(time.time() - start_time, 4)

        return {
            "outcome": "tutor_found",
            "status": "success",
            "question": user_question,
            "text": best["content"],
            "explanation_text": best["content"],
            "top_match": {
                "doc_id": best["doc_id"],
                "subject": best["subject"],
                "grade_level": best["grade_level"],
                "topic": best["topic"],
                "similarity_score": top_cosine,
                "rrf_score": best_candidate.get("rrf_score", 0.0)
            },
            "okf_v02_card": okf_v02_card,
            "tft_lcd_display_card": tft_lcd_display_card,
            "bhashini_voice_text": voice_text,
            "latency_seconds": latency
        }

# ----------------------------------------------------------------------
# 4. Execution Driver
# ----------------------------------------------------------------------
if __name__ == "__main__":
    tutor = GoogleOKFAITutorEngine()
    test_questions = [
        # 1. Clean Success
        "Why is my shadow so long when I walk home from school in the evening, but short at lunchtime?",
        "Why is my shadow so long when I walk home from school in the evening, but short at lunchtime?",
        # 2. Clean Fallback (OOD)
        "random movie show timings",
        "random movie show timings",
        # 3. Ambiguous Case (Curriculum Gap)
        "how do I fix a broken water pump",
        "how do I fix a broken water pump",
        # 4. Gibberish
        "water rain path go go",
        "water rain path go go"
    ]
    for q in test_questions:
        res = tutor.query_tutor(q)
        print("=========================================================")
        print(f"QUERY: \"{q}\"")
        print(f"STATUS: {res['status'].upper()}")
        if res["status"] == "success":
            print(f"TOP MATCH: {res['top_match']['doc_id']} ({res['top_match']['subject']} - {res['top_match']['grade_level']})")
            print(f"COSINE: {res['top_match']['similarity_score']} | RRF SCORE: {res['top_match']['rrf_score']}")
            print(f"TOPIC: {res['top_match']['topic']}")
            print(f"\nEXPLANATION:\n{res['explanation_text']}\n")
        else:
            print(f"CONFIDENCE: {res['confidence_score']} (Below Cutoff)")
            print(f"VOICE TEXT: {res.get('bhashini_voice_text', res.get('text'))}")
        print(f"LATENCY: {res['latency_seconds']}s ({round(res['latency_seconds']*1000, 2)} ms)")
        print("=========================================================\n")
