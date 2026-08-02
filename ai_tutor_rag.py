import os
import sys
import json
import time
import re
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any, Optional

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def create_okf_document(
    doc_id: str,
    subject: str,
    grade_level: str,
    topic: str,
    content: str
) -> Dict[str, str]:
    return {
        "doc_id": doc_id,
        "subject": subject,
        "grade_level": grade_level,
        "topic": topic,
        "content": content,
        "searchable_text": f"{topic} {content}"
    }

def load_real_jsonl_curriculum(jsonl_path: str) -> List[Dict[str, str]]:
    okf_documents = []
    
    if not os.path.exists(jsonl_path):
        return []
        
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for idx, line in enumerate(f):
            try:
                data = json.loads(line.strip())
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

class FAISSVectorIndex:
    def __init__(self, documents: List[Dict[str, str]]):
        self.documents = documents
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.dimension = 384
        self.index = None
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cache_index_path = os.path.join(base_dir, "faiss_index.bin")
        
        if os.path.exists(self.cache_index_path):
            try:
                self.index = faiss.read_index(self.cache_index_path)
            except Exception:
                self._build_index()
        else:
            self._build_index()
    
    def _build_index(self):
        searchable_texts = [doc["searchable_text"] for doc in self.documents]
        embeddings = self.model.encode(
            searchable_texts,
            show_progress_bar=False,
            batch_size=64
        )
        embeddings = np.array(embeddings, dtype='float32')
        faiss.normalize_L2(embeddings)
        
        self.index = faiss.IndexFlatIP(self.dimension)
        self.index.add(embeddings)
        
        faiss.write_index(self.index, self.cache_index_path)
    
    def search(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
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
                    "subject": doc["subject"],
                    "grade_level": doc["grade_level"],
                    "topic": doc["topic"],
                    "content": doc["content"],
                    "similarity_score": round(float(distances[0][i]), 4)
                })
        
        return results

class GoogleOKFAITutorEngine:
    def __init__(self, jsonl_file: str = "clean_curriculum.jsonl"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        jsonl_path = os.path.join(base_dir, jsonl_file)
        
        documents = load_real_jsonl_curriculum(jsonl_path)
        self.vector_index = FAISSVectorIndex(documents)

    def query_tutor(self, user_question: str, dialect: str = "Bhojpuri", top_k: int = 3) -> Dict[str, Any]:
        start_time = time.time()
        results = self.vector_index.search(user_question, top_k=top_k)
        
        if not results:
            return {"status": "error", "message": "No matching documents found."}
        
        best = results[0]
        
        tft_lcd_display_card = (
            f"=== LESSON: {best['topic'][:30]} ===\n"
            f"Grade: {best['grade_level']} | Sub: {best['subject']}\n"
            f"Score: {best['similarity_score']}\n"
            f"----------------------------------------\n"
            f"{best['content']}\n"
            f"----------------------------------------\n"
            f"[Press Trigger to Ask Next Question]"
        )

        dialect_voice_text = f"Bacho! {best['topic']} ke baare me: {best['content']}"
        latency = time.time() - start_time
        
        return {
            "status": "success",
            "question": user_question,
            "top_match": {
                "doc_id": best["doc_id"],
                "subject": best["subject"],
                "grade_level": best["grade_level"],
                "topic": best["topic"],
                "similarity_score": best["similarity_score"]
            },
            "all_matches": results,
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
        "How to purify drinking water in villages?"
    ]
    
    for question in test_questions:
        res = tutor.query_tutor(question, dialect="Bhojpuri")
        print("\n=========================================================")
        print(f"QUERY: \"{res['question']}\"")
        print(f"TOP MATCH: {res['top_match']['doc_id']} (Score: {res['top_match']['similarity_score']})")
        print(f"TOPIC: {res['top_match']['topic']}")
        print(f"\nEXPLANATION:\n{res['explanation_text']}")
        print(f"\nLATENCY: {res['latency_seconds']}s")
        print("=========================================================")
