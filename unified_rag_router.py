import os
import sys
import json
import time
from typing import Dict, Any

from ai_tutor_rag import GoogleOKFAITutorEngine
from government_schemes_rag import GovernmentSchemesRAGEngine

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

class UnifiedRAGRouter:
    """
    Central Router connecting AI Tutor, Government Schemes, and Plant Disease RAG engines.
    """
    def __init__(self):
        print("[Unified Router] Initializing AI Tutor and Government Schemes RAG engines...")
        self.tutor_engine = GoogleOKFAITutorEngine()
        self.schemes_engine = GovernmentSchemesRAGEngine()
        
    def classify_and_route(self, query: str) -> Dict[str, Any]:
        start_time = time.time()
        query_lower = query.lower()
        
        # Keyword & Intent Routing Layer (Zero Model Latency)
        scheme_keywords = [
            "scheme", "pm-kisan", "pmkisan", "yojana", "subsidy", "kcc", "kisan credit", 
            "pension", "loan", "bima", "insurance", "enam", "e-nam", "mgnrega", "kusum", 
            "soil health card", "drip irrigation subsidy", "pmksy", "smam", "pmfme", "aif", "matsya"
        ]
        
        is_scheme_query = any(k in query_lower for k in scheme_keywords)
        
        if is_scheme_query:
            # Route to Government Schemes RAG
            res = self.schemes_engine.query_schemes(query, top_k=1)
            res["routed_engine"] = "GovernmentSchemesRAG"
            res["overall_latency_seconds"] = round(time.time() - start_time, 4)
            return res
        else:
            # Route to AI Tutor RAG (NCERT Science, Math, Health, Literacy)
            res = self.tutor_engine.query_tutor(query, dialect="Bhojpuri", top_k=1)
            res["routed_engine"] = "AITutorRAG"
            res["overall_latency_seconds"] = round(time.time() - start_time, 4)
            return res

if __name__ == "__main__":
    router = UnifiedRAGRouter()
    
    test_queries = [
        "How can small farmers get 6000 rupees direct benefit transfer under PM-KISAN?",
        "What is an Arithmetic Progression? Give daily life examples",
        "How to get 60% subsidy for solar irrigation pumps under KUSUM?",
        "How do plants make food using sunlight?"
    ]
    
    print("\n=========================================================")
    print("UNIFIED RAG ROUTER TEST EXECUTION")
    print("=========================================================")
    
    for q in test_queries:
        res = router.classify_and_route(q)
        print(f"\nQUERY: \"{q}\"")
        print(f"ROUTED TO: {res['routed_engine']}")
        if res['routed_engine'] == "GovernmentSchemesRAG":
            print(f"MATCH: {res['top_scheme']['scheme_name']} | Score: {res['top_scheme']['similarity_score']}")
            print(f"BENEFITS: {res['benefit_details']}")
        else:
            print(f"MATCH: {res['top_match']['doc_id']} ({res['top_match']['topic']}) | Score: {res['top_match']['similarity_score']}")
            print(f"EXPLANATION: {res['explanation_text']}")
        print(f"LATENCY: {res['overall_latency_seconds']}s")
        print("---------------------------------------------------------")
