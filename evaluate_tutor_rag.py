import os
import sys
import json
import time
from ai_tutor_rag import GoogleOKFAITutorEngine

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ---------------------------------------------------------------------------
# 50 Benchmark Queries Across Rural Education & School Curriculum
# ---------------------------------------------------------------------------

EVALUATION_QUERIES = [
    # Science & Nature (Class 5-8)
    {"id": 1, "category": "Science", "query": "How do plants make food using sunlight?"},
    {"id": 2, "category": "Science", "query": "What is photosynthesis and why is chlorophyll important?"},
    {"id": 3, "category": "Science", "query": "How does the water cycle cause rain?"},
    {"id": 4, "category": "Science", "query": "What are the three states of matter?"},
    {"id": 5, "category": "Science", "query": "What is the difference between physical and chemical changes?"},
    {"id": 6, "category": "Science", "query": "How do human lungs absorb oxygen?"},
    {"id": 7, "category": "Science", "query": "Why do stars twinkle in the night sky?"},
    {"id": 8, "category": "Science", "query": "What is electric current and how does a circuit work?"},
    {"id": 9, "category": "Science", "query": "How do magnets attract iron objects?"},
    {"id": 10, "category": "Science", "query": "What is friction and how does it affect motion?"},

    # Mathematics & Calculations (Class 5-8)
    {"id": 11, "category": "Mathematics", "query": "What is an Arithmetic Progression? Give daily life examples"},
    {"id": 12, "category": "Mathematics", "query": "How to calculate percentage profit on crop yield?"},
    {"id": 13, "category": "Mathematics", "query": "What is the formula for the area of a circle?"},
    {"id": 14, "category": "Mathematics", "query": "How to solve linear equations in one variable?"},
    {"id": 15, "category": "Mathematics", "query": "What is the difference between prime and composite numbers?"},
    {"id": 16, "category": "Mathematics", "query": "How to calculate simple interest on farm loans?"},
    {"id": 17, "category": "Mathematics", "query": "What is Pythagoras theorem in geometry?"},
    {"id": 18, "category": "Mathematics", "query": "How to convert fractions into decimals?"},
    {"id": 19, "category": "Mathematics", "query": "What is ratio and proportion in crop sharing?"},
    {"id": 20, "category": "Mathematics", "query": "How to calculate perimeter of a square field?"},

    # Health, Hygiene & Sanitation
    {"id": 21, "category": "Health & Sanitation", "query": "How to purify drinking water in villages?"},
    {"id": 22, "category": "Health & Sanitation", "query": "Why is boiling water effective against bacteria?"},
    {"id": 23, "category": "Health & Sanitation", "query": "Why should we wash hands with soap before eating?"},
    {"id": 24, "category": "Health & Sanitation", "query": "How to prevent mosquito breeding and malaria?"},
    {"id": 25, "category": "Health & Sanitation", "query": "What are waterborne diseases like cholera and typhoid?"},
    {"id": 26, "category": "Health & Sanitation", "query": "Why is balanced diet important for growing children?"},
    {"id": 27, "category": "Health & Sanitation", "query": "What vitamins are found in green vegetables?"},
    {"id": 28, "category": "Health & Sanitation", "query": "How to treat dehydration using oral rehydration salts?"},
    {"id": 29, "category": "Health & Sanitation", "query": "Why is personal hygiene necessary in rural areas?"},
    {"id": 30, "category": "Health & Sanitation", "query": "How to store food safely without refrigeration?"},

    # Soil, Agriculture & Environment
    {"id": 31, "category": "Agriculture & Soil", "query": "What are the different types of soil in India?"},
    {"id": 32, "category": "Agriculture & Soil", "query": "Why is humus good for soil fertility?"},
    {"id": 33, "category": "Agriculture & Soil", "query": "What is crop rotation and why is it beneficial?"},
    {"id": 34, "category": "Agriculture & Soil", "query": "How does drip irrigation save water in farming?"},
    {"id": 35, "category": "Agriculture & Soil", "query": "What is composting and organic fertilizer?"},
    {"id": 36, "category": "Agriculture & Soil", "query": "How do earthworms help in soil aeration?"},
    {"id": 37, "category": "Agriculture & Soil", "query": "What is soil erosion and how to prevent it?"},
    {"id": 38, "category": "Agriculture & Soil", "query": "What is Kharif and Rabi crop season?"},
    {"id": 39, "category": "Agriculture & Soil", "query": "Why do leguminous plants fix nitrogen in soil?"},
    {"id": 40, "category": "Agriculture & Soil", "query": "How does excessive chemical fertilizer damage land?"},

    # Basic Literacy & Social Science
    {"id": 41, "category": "Basic Literacy", "query": "What is the importance of reading and writing for farmers?"},
    {"id": 42, "category": "Basic Literacy", "query": "What is Gram Panchayat and how does it work?"},
    {"id": 43, "category": "Basic Literacy", "query": "What are the fundamental rights of Indian citizens?"},
    {"id": 44, "category": "Basic Literacy", "query": "Why is solar energy important for rural villages?"},
    {"id": 45, "category": "Basic Literacy", "query": "How does rainwater harvesting help in dry areas?"},
    {"id": 46, "category": "Basic Literacy", "query": "What is the role of bank accounts in government schemes?"},
    {"id": 47, "category": "Basic Literacy", "query": "Why is girl child education essential for village development?"},
    {"id": 48, "category": "Basic Literacy", "query": "What is deforestation and how does it impact climate?"},
    {"id": 49, "category": "Basic Literacy", "query": "How does digital literacy help farmers check market prices?"},
    {"id": 50, "category": "Basic Literacy", "query": "What are renewable energy sources like wind and solar?"}
]

def run_evaluation():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_json_path = os.path.join(base_dir, "tutor_evaluation_results.json")
    
    print("[Evaluation] Initializing Google OKF AI Tutor Engine...")
    tutor = GoogleOKFAITutorEngine()
    
    results = []
    total_latency = 0.0
    total_score = 0.0
    
    print("[Evaluation] Running 50 Benchmark Test Queries with Full Answers...\n")
    
    for item in EVALUATION_QUERIES:
        q_id = item["id"]
        category = item["category"]
        query_text = item["query"]
        
        res = tutor.query_tutor(query_text, dialect="Bhojpuri", top_k=1)
        top_match = res["top_match"]
        latency = res["latency_seconds"]
        score = top_match["similarity_score"]
        
        total_latency += latency
        total_score += score
        
        entry = {
            "query_id": q_id,
            "category": category,
            "query": query_text,
            "matched_doc_id": top_match["doc_id"],
            "similarity_score": score,
            "matched_topic": top_match["topic"],
            "explanation": res["explanation_text"],
            "latency_seconds": latency
        }
        results.append(entry)
        
        print("=========================================================")
        print(f"QUERY [{q_id:02d}/50]: \"{query_text}\"")
        print(f"CATEGORY: {category} | MATCH: {top_match['doc_id']} (Score: {score:.4f})")
        print(f"TEXTBOOK ANSWER:\n{res['explanation_text']}")
        print(f"LATENCY: {latency:.4f}s")
        print("=========================================================\n")

    avg_latency = total_latency / len(EVALUATION_QUERIES)
    avg_score = total_score / len(EVALUATION_QUERIES)
    
    summary_data = {
        "total_test_queries": len(EVALUATION_QUERIES),
        "average_similarity_score": round(avg_score, 4),
        "average_latency_seconds": round(avg_latency, 4),
        "evaluations": results
    }
    
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, indent=2, ensure_ascii=False)
        
    print("=========================================================")
    print("EVALUATION COMPLETED SUCCESSFULLY!")
    print(f"Total Queries Evaluated: {len(EVALUATION_QUERIES)}")
    print(f"Average Similarity Score: {avg_score:.4f}")
    print(f"Average Latency: {avg_latency:.4f} seconds")
    print(f"Report Saved To: {output_json_path}")
    print("=========================================================\n")

if __name__ == "__main__":
    run_evaluation()
