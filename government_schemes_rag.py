import os
import sys
import json
import time
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any, Optional

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def load_schemes_dataset(jsonl_path: str) -> List[Dict[str, Any]]:
    schemes = []
    if not os.path.exists(jsonl_path):
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
                    
                    schemes.append({
                        "scheme_id": s_id,
                        "scheme_name": name,
                        "target_beneficiary": beneficiary,
                        "benefit_details": benefits,
                        "eligibility_criteria": eligibility,
                        "how_to_apply": apply_info,
                        "documents_required": docs,
                        "searchable_text": searchable_text
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
        embeddings = self.model.encode(
            searchable_texts,
            show_progress_bar=False,
            batch_size=32
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
            if idx < len(self.schemes):
                item = self.schemes[idx]
                results.append({
                    "scheme_id": item["scheme_id"],
                    "scheme_name": item["scheme_name"],
                    "target_beneficiary": item["target_beneficiary"],
                    "benefit_details": item["benefit_details"],
                    "eligibility_criteria": item["eligibility_criteria"],
                    "how_to_apply": item["how_to_apply"],
                    "documents_required": item["documents_required"],
                    "similarity_score": round(float(distances[0][i]), 4)
                })
        return results


class GovernmentSchemesRAGEngine:
    def __init__(self, jsonl_file: str = "schemes_dataset.jsonl"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        jsonl_path = os.path.join(base_dir, jsonl_file)
        
        self.schemes = load_schemes_dataset(jsonl_path)
        self.vector_index = SchemesFAISSVectorIndex(self.schemes)

    def query_schemes(self, user_question: str, top_k: int = 3) -> Dict[str, Any]:
        start_time = time.time()
        results = self.vector_index.search(user_question, top_k=top_k)
        
        if not results:
            return {"status": "error", "message": "No matching government schemes found."}
            
        best = results[0]
        
        # Format for 2.8" TFT LCD Display
        lcd_card = (
            f"=== SCHEME: {best['scheme_name'][:30]} ===\n"
            f"ID: {best['scheme_id']} | Score: {best['similarity_score']}\n"
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
        
        latency = time.time() - start_time
        
        return {
            "status": "success",
            "question": user_question,
            "top_scheme": {
                "scheme_id": best["scheme_id"],
                "scheme_name": best["scheme_name"],
                "similarity_score": best["similarity_score"]
            },
            "all_matches": results,
            "benefit_details": best["benefit_details"],
            "eligibility_criteria": best["eligibility_criteria"],
            "how_to_apply": best["how_to_apply"],
            "documents_required": best["documents_required"],
            "lcd_card": lcd_card,
            "bhashini_voice_text": voice_text,
            "latency_seconds": round(latency, 4)
        }


if __name__ == "__main__":
    engine = GovernmentSchemesRAGEngine()
    
    test_queries = [
        "How can small farmers get 6000 rupees direct benefit transfer?",
        "What is the crop insurance scheme for drought and flood loss?",
        "How to get low interest loan for seeds and fertilizers using KCC?",
        "What is the subsidy for setting up solar irrigation pumps under KUSUM?",
        "How to register on e-NAM to sell crops directly online?"
    ]
    
    for q in test_queries:
        res = engine.query_schemes(q)
        print("\n=========================================================")
        print(f"QUERY: \"{res['question']}\"")
        print(f"TOP MATCH: {res['top_scheme']['scheme_name']} ({res['top_scheme']['scheme_id']}) | Score: {res['top_scheme']['similarity_score']}")
        print(f"BENEFITS: {res['benefit_details']}")
        print(f"APPLY: {res['how_to_apply']}")
        print(f"LATENCY: {res['latency_seconds']}s")
        print("=========================================================")
