import os
import sys
import json
import time
from government_schemes_rag import GovernmentSchemesRAGEngine

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

SCHEME_TEST_QUERIES = [
    {"id": 1, "query": "How can small farmers get 6000 rupees direct benefit transfer?", "expected": "PM-KISAN"},
    {"id": 2, "query": "What is the crop insurance scheme for drought and flood loss?", "expected": "PMFBY"},
    {"id": 3, "query": "How to get low interest loan for seeds and fertilizers using KCC?", "expected": "Kisan Credit Card"},
    {"id": 4, "query": "What is the subsidy for setting up solar irrigation pumps under KUSUM?", "expected": "PM-KUSUM"},
    {"id": 5, "query": "How to register on e-NAM to sell crops directly online?", "expected": "e-NAM"},
    {"id": 6, "query": "How to get a Soil Health Card for fertilizer dosage recommendation?", "expected": "Soil Health Card"},
    {"id": 7, "query": "What is the monthly pension scheme of 3000 rupees for small farmers after age 60?", "expected": "PM-KMY"},
    {"id": 8, "query": "How to get subsidy for drip and sprinkler micro irrigation systems?", "expected": "PMKSY"},
    {"id": 9, "query": "How to get subsidy for purchasing tractors, rotavators, and farm machinery?", "expected": "SMAM"},
    {"id": 10, "query": "What is the assistance of 50,000 rupees per hectare for organic farming clusters?", "expected": "PKVY"},
    {"id": 11, "query": "How to get a Job Card for 100 days guaranteed manual work in village?", "expected": "MGNREGA"},
    {"id": 12, "query": "What is the capital subsidy of 35% up to 10 Lakh for micro food processing units?", "expected": "PMFME"},
    {"id": 13, "query": "How to get 3% interest subvention loan for building farm warehouses and cold storage?", "expected": "AIF"},
    {"id": 14, "query": "What is the seed funding grant up to 25 Lakh for agri-startups under RKVY-RAFTAAR?", "expected": "RKVY-RAFTAAR"},
    {"id": 15, "query": "What is the 60% subsidy scheme for fish farming, biofloc, and pond construction?", "expected": "PMMSY"},
    {"id": 16, "query": "How to get installment of 2000 rupees every 4 months under PM-KISAN?", "expected": "PM-KISAN"},
    {"id": 17, "query": "What is the premium rate of 1.5% for Rabi crops under PM crop insurance?", "expected": "PMFBY"},
    {"id": 18, "query": "Can fisheries and animal husbandry farmers get Kisan Credit Card (KCC)?", "expected": "Kisan Credit Card"},
    {"id": 19, "query": "How to sell extra solar electricity produced by KUSUM pumps to grid?", "expected": "PM-KUSUM"},
    {"id": 20, "query": "What is the website to check live crop mandi prices online across India?", "expected": "e-NAM"},
    {"id": 21, "query": "How to test soil sample for nitrogen, phosphorus, and potassium levels?", "expected": "Soil Health Card"},
    {"id": 22, "query": "Who is eligible for PM Kisan Maandhan 3000 rupees pension scheme?", "expected": "PM-KMY"},
    {"id": 23, "query": "What is the subsidy for establishing Custom Hiring Centres for farm equipment?", "expected": "SMAM"},
    {"id": 24, "query": "How to get 100 days wage employment for farm pond construction?", "expected": "MGNREGA"},
    {"id": 25, "query": "What is the loan for upgrading small jaggery, flour milling, or spice grinding business?", "expected": "PMFME"}
]

def run_schemes_evaluation():
    engine = GovernmentSchemesRAGEngine()
    results = []
    total_score = 0.0
    total_latency = 0.0
    
    print("[Schemes Evaluation] Running 25 Benchmark Test Queries...\n")
    
    for item in SCHEME_TEST_QUERIES:
        q_id = item["id"]
        q_text = item["query"]
        expected = item["expected"]
        
        res = engine.query_schemes(q_text, top_k=1)
        top = res["top_scheme"]
        score = top["similarity_score"]
        latency = res["latency_seconds"]
        
        total_score += score
        total_latency += latency
        
        entry = {
            "query_id": q_id,
            "query": q_text,
            "matched_scheme": top["scheme_name"],
            "scheme_id": top["scheme_id"],
            "similarity_score": score,
            "latency_seconds": latency
        }
        results.append(entry)
        
        print("=========================================================")
        print(f"QUERY [{q_id:02d}/25]: \"{q_text}\"")
        print(f"MATCH: {top['scheme_name']} ({top['scheme_id']}) | Score: {score:.4f}")
        print(f"BENEFITS: {res['benefit_details']}")
        print(f"APPLY: {res['how_to_apply']}")
        print(f"LATENCY: {latency:.4f}s")
        print("=========================================================\n")
        
    avg_score = total_score / len(SCHEME_TEST_QUERIES)
    avg_latency = total_latency / len(SCHEME_TEST_QUERIES)
    
    summary = {
        "total_test_queries": len(SCHEME_TEST_QUERIES),
        "average_similarity_score": round(avg_score, 4),
        "average_latency_seconds": round(avg_latency, 4),
        "evaluations": results
    }
    
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemes_evaluation_results.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
        
    print("=========================================================")
    print("GOVERNMENT SCHEMES RAG EVALUATION COMPLETED!")
    print(f"Total Queries Evaluated: {len(SCHEME_TEST_QUERIES)}")
    print(f"Average Similarity Score: {avg_score:.4f}")
    print(f"Average Latency: {avg_latency:.4f} seconds")
    print(f"Report Saved To: {out_path}")
    print("=========================================================\n")

if __name__ == "__main__":
    run_schemes_evaluation()
