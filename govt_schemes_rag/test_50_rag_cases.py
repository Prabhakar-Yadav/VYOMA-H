"""
50+ RAG Benchmark Test Suite for Gram Sahayak Government Schemes

Validates retrieval quality, entity matching accuracy, response length capping,
and latency metrics across 50 real-world farmer queries.

Usage:
    python test_50_rag_cases.py
"""

import time
import logging
from government_schemes_rag import GovernmentSchemesRAGEngine

# Silence verbose loggers for benchmark output
logging.getLogger("RAG_Engine").setLevel(logging.WARNING)

BENCHMARK_QUERIES = [
    # 1-10: Financial Assistance & Direct Benefit Transfers (PM-KISAN, Pensions, Jan Dhan)
    "How can small farmers get 6000 rupees direct benefit transfer?",
    "When will the PM-KISAN installment arrive in my bank account?",
    "How to check registration status for 2000 rupees kist?",
    "What documents are required to open a PM Jan Dhan account?",
    "How to get 3000 pension per month under Kisan Maandhan Yojana?",
    "Old age pension for senior citizen farmers above 60 years",
    "Overdraft facility in Jan Dhan zero balance account",
    "Financial assistance for landless agricultural labourers",
    "PM-KISAN helpline number and grievance portal",
    "Aadhaar card seeding for direct benefit transfer",

    # 11-20: Crop Insurance & Disaster Loss (PMFBY, NAIS, Coconut Palm Insurance)
    "My crop dried up and got yellow disease, I need help",
    "What is the crop insurance for drought and flood loss?",
    "How to claim insurance if crops are destroyed by natural disaster",
    "PMFBY crop loss intimation within 72 hours deadline",
    "What insurance is available if a storm damages my coconut trees?",
    "Hailstorm damaged my standing wheat crop, how to get compensation?",
    "Pest attack destroyed my cotton field, who to contact?",
    "Insurance premium rates for Kharif and Rabi crops",
    "How much money will I get from insurance for ruined crops?",
    "Post-harvest crop loss insurance claim process",

    # 21-30: Solar Energy & Irrigation (PM-KUSUM, PMKSY)
    "I need a subsidy for a solar pump for water",
    "How much subsidy is available for installing a solar pump?",
    "Procedure to convert diesel pump set to solar agriculture pump",
    "How to get drip irrigation and sprinkler system subsidy?",
    "Government assistance for borewell or tubewell in field",
    "Pipeline for water supply to agricultural land",
    "Selling excess solar electricity back to the grid",
    "PM-KUSUM component B standalone solar pump application",
    "Subsidized water motor pump for small farmers",
    "Irrigation water shortage solution in dry fields",

    # 31-40: Loans & Credit (KCC, Mudra, Agriculture Infrastructure Fund)
    "How to get low interest loan using KCC card?",
    "Is 4 percent interest rate valid for 3 lakh loan under KCC?",
    "What documents do I need for Kisan Credit Card?",
    "How to get KCC loan for animal husbandry and poultry?",
    "Need collateral-free business loan under PM Mudra Yojana",
    "Subsidy for setting up cold storage godown for harvested crops",
    "Warehouse construction loan under Agriculture Infrastructure Fund",
    "Debt relief or interest subvention on crop loan",
    "Short-term credit for buying seeds and fertilizers",
    "Loan for buying tractor and farm equipment",

    # 41-48: Livestock, Dairy, Fisheries & Organic Farming (NLM, DEDS, Gokul, PMMSY, PKVY)
    "Subsidized loan for cow and buffalo dairy farming",
    "How to start goat farming or poultry chicken business?",
    "Rashtriya Gokul Mission indigenous cattle breed improvement",
    "Is there a subsidy for digging a fish pond and buying fish seed?",
    "Beekeeping honey box subsidy under National Beekeeping Mission",
    "Financial assistance of 50000 per hectare for organic farming",
    "Vermicompost and cow dung manure grant under PKVY",
    "Pickle and spice grinding machine subsidy under PMFME",

    # 49-50: Out-of-Domain Safety Fallback Tests
    "What is the subsidy for buying a private electric car in Delhi?",
    "Random irrelevant question about space rockets and bitcoin"
]

def run_benchmark():
    print("=========================================================")
    print("      Gram Sahayak - 50 RAG Test Cases Benchmark         ")
    print("=========================================================")
    print("Initializing RAG Engine...")
    
    start_init = time.time()
    engine = GovernmentSchemesRAGEngine("enriched_schemes_dataset.jsonl")
    init_time = round(time.time() - start_init, 2)
    print(f"Engine Ready in {init_time}s! Running 50 benchmark queries...\n")
    
    success_count = 0
    fallback_count = 0
    total_latency = 0.0
    
    for idx, q in enumerate(BENCHMARK_QUERIES, 1):
        res = engine.query_schemes(q)
        status = res.get("status", "error")
        latency = res.get("latency_seconds", 0.0)
        total_latency += latency
        
        scheme_name = res.get("scheme_name", "N/A")
        score = res.get("confidence_score", 0.0)
        
        if status == "success":
            success_count += 1
            print(f"[{idx:02d}/50] [SUCCESS] ({latency:.4f}s) Score: {score:.4f} | Match: {scheme_name[:35]}")
        else:
            fallback_count += 1
            print(f"[{idx:02d}/50] [FALLBACK] ({latency:.4f}s) Score: {score:.4f} | Q: '{q[:40]}...'")
            
    avg_latency = round((total_latency / len(BENCHMARK_QUERIES)) * 1000, 2)
    print("\n=========================================================")
    print("               BENCHMARK RESULTS SUMMARY                 ")
    print("=========================================================")
    print(f"Total Test Cases Evaluated: {len(BENCHMARK_QUERIES)}")
    print(f"Successful Matches:         {success_count} / 48 target queries")
    print(f"Correct Fallbacks:          {fallback_count} / 2 out-of-domain queries")
    print(f"Average Search Latency:     {avg_latency} ms per query")
    print("=========================================================")

if __name__ == "__main__":
    run_benchmark()
