"""
27-Case Benchmark Evaluation Suite for Gram Sahayak Schemes RAG Engine (2026 Edition)
(Targeted for Bhashini translated English queries across all 24 verified Central Government Schemes)
"""

import os
import sys
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from government_schemes_rag import GovernmentSchemesRAGEngine

# Silence verbose loggers
logging.getLogger("RAG_Engine").setLevel(logging.WARNING)

BENCHMARK_CASES = [
    # --- 1. Direct Income Support & Pension ---
    {
        "query": "How can a small farmer get 6000 rupees direct benefit transfer in their bank account under PM-KISAN?",
        "expected_id": "SCHEME_001",
        "desc": "PM-KISAN (6000 rupees annual assistance, AgriStack Farmer ID)"
    },
    {
        "query": "My 2000 rupees installment for farmer assistance has not arrived in my account",
        "expected_id": "SCHEME_001",
        "desc": "PM-KISAN (Missing installment / kist)"
    },
    {
        "query": "Is there a guaranteed monthly pension of 3000 rupees for senior citizen farmers after 60 years of age?",
        "expected_id": "SCHEME_002",
        "desc": "PM-KMY (Old age pension scheme)"
    },

    # --- 2. Credit, Insurance & Financial Inclusion ---
    {
        "query": "How to get a low interest 4 percent loan using Kisan Credit Card for buying seeds and fertilizer?",
        "expected_id": "SCHEME_003",
        "desc": "KCC (Low interest crop credit)"
    },
    {
        "query": "What is the collateral free loan limit of 2 lakh rupees on Kisan Credit Card?",
        "expected_id": "SCHEME_003",
        "desc": "KCC (2 lakh limit)"
    },
    {
        "query": "My crop dried up and was ruined by yellow pest disease, how do I claim PMFBY crop insurance compensation?",
        "expected_id": "SCHEME_004",
        "desc": "PMFBY (Crop loss & pest damage)"
    },
    {
        "query": "Hailstorm damaged my standing wheat crop, what is the deadline to report loss within 72 hours?",
        "expected_id": "SCHEME_004",
        "desc": "PMFBY (72h calamity loss intimation)"
    },
    {
        "query": "How can an unbanked rural citizen open a zero balance bank account with 2 lakh accidental insurance under Jan Dhan Yojana?",
        "expected_id": "SCHEME_005",
        "desc": "PMJDY (Jan Dhan zero balance account & 10000 overdraft)"
    },
    {
        "query": "How can villagers get legal Property Cards after drone survey mapping under SVAMITVA Scheme?",
        "expected_id": "SCHEME_006",
        "desc": "SVAMITVA (Abadi village drone survey & title deeds)"
    },

    # --- 3. Modernization & Sustainable Agriculture ---
    {
        "query": "How much subsidy is given to install a standalone solar agriculture pump to replace a diesel motor under PM-KUSUM?",
        "expected_id": "SCHEME_007",
        "desc": "PM-KUSUM (Solar agricultural pump subsidy)"
    },
    {
        "query": "What is the 1.44 lakh crore PM Dhan-Dhaanya Krishi Yojana plan for 100 low performing districts?",
        "expected_id": "SCHEME_008",
        "desc": "PM-DDKY (100 low-performing agricultural districts convergence)"
    },
    {
        "query": "What is the government subsidy on buying tractors, rotavators, and power tillers under SMAM?",
        "expected_id": "SCHEME_009",
        "desc": "SMAM (Agricultural machinery & CHC procurement)"
    },
    {
        "query": "How can I get government subsidy for drip irrigation and sprinkler systems in dry fields under PMKSY?",
        "expected_id": "SCHEME_010",
        "desc": "PMKSY (Per Drop More Crop micro-irrigation subsidy)"
    },
    {
        "query": "Is there a 3 percent interest subsidy on bank loans up to 2 crore for building cold storage warehouses?",
        "expected_id": "SCHEME_011",
        "desc": "AIF (Agriculture Infrastructure Fund cold storage)"
    },
    {
        "query": "Where can farmers sell their harvested crops online across APMC mandis using e-NAM portal?",
        "expected_id": "SCHEME_012",
        "desc": "e-NAM (National Agriculture Market online price discovery)"
    },
    {
        "query": "How to get soil tested for 12 nutrient parameters and receive crop fertilizer dosage recommendations on Soil Health Card?",
        "expected_id": "SCHEME_013",
        "desc": "SHC (Soil Health Card 12 nutrient parameters)"
    },
    {
        "query": "Is there financial assistance of 31500 rupees per hectare to adopt certified organic farming under PKVY?",
        "expected_id": "SCHEME_014",
        "desc": "PKVY (Certified organic farming clusters)"
    },

    # --- 4. Employment, Allied Agri & Food Processing ---
    {
        "query": "How can rural households get 100 days of guaranteed manual wage work and a job card under MGNREGA?",
        "expected_id": "SCHEME_015",
        "desc": "MGNREGA (100 days guaranteed wage employment)"
    },
    {
        "query": "How to get 35 percent capital subsidy up to 10 lakh rupees to set up a micro food processing pickle or flour mill under PMFME?",
        "expected_id": "SCHEME_016",
        "desc": "PMFME (Micro food processing enterprises subsidy)"
    },
    {
        "query": "What subsidy is available for digging new fish ponds, biofloc units, and buying fishing boats under PMMSY?",
        "expected_id": "SCHEME_017",
        "desc": "PMMSY (Fisheries & aquaculture development subsidy)"
    },
    {
        "query": "Is there a 50 percent capital subsidy for starting commercial goat, sheep, or poultry breeding farms under NLM?",
        "expected_id": "SCHEME_018",
        "desc": "NLM-EDP (National Livestock Mission 50% breeding subsidy)"
    },
    {
        "query": "How to get 5000 rupees subsidy per successful IVF pregnancy in indigenous Gir and Sahiwal cows under Rashtriya Gokul Mission?",
        "expected_id": "SCHEME_019",
        "desc": "RGM (Rashtriya Gokul Mission indigenous cattle breeding)"
    },
    {
        "query": "How can agriculture graduates get 45 days training and 36 to 44 percent subsidy on loans for agri-clinics under ACABC?",
        "expected_id": "SCHEME_020",
        "desc": "ACABC (Agri-Clinics & Agri-Business Centres scheme)"
    },

    # --- 5. Healthcare, Housing & Rural Utilities ---
    {
        "query": "How to get cashless medical hospitalization cover of 5 lakh rupees with Ayushman Card for all seniors 70 years and above under PM-JAY?",
        "expected_id": "SCHEME_021",
        "desc": "PM-JAY (Ayushman Bharat 5 lakh health insurance)"
    },
    {
        "query": "How to get free potable piped drinking water tap connection delivering 55 litres per day under Jal Jeevan Mission Har Ghar Jal?",
        "expected_id": "SCHEME_022",
        "desc": "JJM (Jal Jeevan Mission 55 L/person/day FHTC)"
    },
    {
        "query": "How can poor rural women get a free LPG gas connection and 300 rupees refill subsidy under PM Ujjwala Yojana?",
        "expected_id": "SCHEME_023",
        "desc": "PMUY (Free LPG gas connection & refill subsidy)"
    },
    {
        "query": "How much grant is given to build a permanent pucca house in rural villages under Pradhan Mantri Awaas Yojana Gramin?",
        "expected_id": "SCHEME_024",
        "desc": "PMAY-G (Rural pucca housing financial grant)"
    },

    # --- 6. Out-of-Domain Safety Rejection Test Cases (Negative Validation) ---
    {
        "query": "What is the price of an electric car and EV charging station in Mumbai?",
        "expected_id": None,
        "desc": "Out-of-Domain (EV car rejection)"
    },
    {
        "query": "Where can I invest in the stock market and buy cryptocurrency shares?",
        "expected_id": None,
        "desc": "Out-of-Domain (Crypto/stocks rejection)"
    },
    {
        "query": "Which cricket tournament and movie is playing in the theatre today?",
        "expected_id": None,
        "desc": "Out-of-Domain (Sports/movie rejection)"
    },
]


def run_benchmark():
    print("=" * 74)
    print("   Gram Sahayak - 2026 Master 27-Case Benchmark Evaluation Suite   ")
    print("=" * 74)

    start_init = time.time()
    engine = GovernmentSchemesRAGEngine("schemes_dataset.jsonl")
    init_time = round(time.time() - start_init, 2)
    print(f"Engine Ready in {init_time}s! Running 27 English benchmark queries...\n")

    correct_target = 0
    total_target = 0
    correct_fallback = 0
    total_fallback = 0
    latencies = []

    header = f"{'#':<3} | {'STATUS':<9} | {'LATENCY':<8} | {'CONF':<6} | {'MATCHED SCHEME':<35} | {'TEST DESCRIPTION'}"
    print(header)
    print("-" * 105)

    for i, tc in enumerate(BENCHMARK_CASES, 1):
        q = tc["query"]
        expected = tc["expected_id"]
        is_target_case = (expected is not None)

        if is_target_case:
            total_target += 1
        else:
            total_fallback += 1

        t0 = time.time()
        res = engine.query_schemes(q)
        lat_ms = (time.time() - t0) * 1000
        latencies.append(lat_ms)

        matched_id = res.get("scheme_id")
        matched_name = res.get("scheme_name") or "None (Fallback)"
        conf = res.get("confidence_score", 0.0)

        if is_target_case:
            passed = (res.get("status") == "success" and matched_id == expected)
            if passed:
                correct_target += 1
        else:
            passed = (res.get("status") == "fallback" and matched_id is None)
            if passed:
                correct_fallback += 1

        status_str = "[PASS]" if passed else "[FAIL]"
        matched_display = (matched_name[:32] + "...") if len(matched_name) > 35 else matched_name

        print(f"{i:<3} | {status_str:<9} | {lat_ms:>6.1f}ms | {conf:>6.3f} | {matched_display:<35} | {tc['desc']}")

    print("=" * 105)
    target_acc = (correct_target / total_target * 100) if total_target else 0
    fallback_acc = (correct_fallback / total_fallback * 100) if total_fallback else 0
    avg_lat = sum(latencies) / len(latencies) if latencies else 0

    print(f"Target Query Accuracy:       {correct_target} / {total_target} ({target_acc:.1f}%)")
    print(f"Out-of-Domain Fallback Rate: {correct_fallback} / {total_fallback} ({fallback_acc:.1f}%)")
    print(f"Average Search Latency:      {avg_lat:.2f} ms")
    print("=" * 105)


if __name__ == "__main__":
    run_benchmark()
