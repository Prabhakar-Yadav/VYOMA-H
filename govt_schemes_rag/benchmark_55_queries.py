import os
import sys
import time
import json

from government_schemes_rag import GovernmentSchemesRAGEngine
from test_tencent_agent_memory import TencentAgentMemoryHub

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# The 55 Test Queries Suite
TEST_QUERIES_55 = [
    # 🌾 Category 1: Direct Financial Benefit & Cash Transfer (PM-KISAN)
    ("How can small kisaan get 6000 rupees direct benefit transfer?", "SCHEME_001", "success"),
    ("6000 rupaye kist kab aayegi bank account me", "SCHEME_001", "success"),
    ("PM kisan kist pending problem solution status check", "SCHEME_001", "success"),
    ("chota kisan 2000 rupaye ki kist ke liye registration kaise kare", "SCHEME_001", "success"),
    ("what are the eligibility documents required for PM KISAN Samman Nidhi", "SCHEME_001", "success"),
    ("pmkisan gov in portal login and ekyc process", "SCHEME_001", "success"),
    
    # ☀️ Category 2: Solar Pumps & Electricity (PM-KUSUM)
    ("Mujhe pani ke liye solar pump subsidy chahiye", "SCHEME_007", "success"),
    ("bijli ke bill se bachne ke liye kisan kya kare", "SCHEME_007", "success"),
    ("solar pump lagwane ke liye kitni subsidy milti hai", "SCHEME_007", "success"),
    ("khet me solar panel lagakar bijli company ko bechne ka tariqa", "SCHEME_007", "success"),
    ("PM KUSUM component B standalone solar agriculture pump set apply", "SCHEME_007", "success"),
    ("diesel pump set ko solar pump me badalne ke liye sarkari scheme", "SCHEME_007", "success"),
    
    # 🛡️ Category 3: Crop Insurance & Disaster Losses (PMFBY)
    ("What is the crop insurance for drought and flood loss?", "SCHEME_002", "success"),
    ("crop failure claim compensation process time limit", "SCHEME_002", "success"),
    ("fasal kharaab hone par kitna paisa milega bima se", "SCHEME_002", "success"),
    ("haali me hui baarish aur keede ke hamle se fasal nuksani ka daava", "SCHEME_002", "success"),
    ("PMFBY crop loss intimation within 72 hours helpline number", "SCHEME_002", "success"),
    ("prakritik aapda se fasal nasht hone par bima claim kaise kare", "SCHEME_002", "success"),
    
    # 💳 Category 4: Agricultural Credit & Loans (KCC)
    ("How to get low interest loan using KCC card?", "SCHEME_003", "success"),
    ("is 4 percent interest rate valid for 3 lakh loan under KCC", "SCHEME_003", "success"),
    ("kisaan credit card banane ke liye bank me kya jama karna hoga", "SCHEME_003", "success"),
    ("pashupalan aur murgipalan ke liye KCC loan kaise milta hai", "SCHEME_003", "success"),
    ("kcc card interest subvention scheme prompt repayment 3 percent discount", "SCHEME_003", "success"),
    ("karza maafi ya kum byaj par loan lene ka tareeka", "SCHEME_003", "success"),
    
    # 💧 Category 5: Irrigation & Water Infrastructure (PMKSY)
    ("sinchai ke liye drip irrigation aur pipe line lene par kya milta hai", "SCHEME_004", "success"),
    ("khet me tubewell ya borwel lagwane ke liye sarkari sahayata", "SCHEME_004", "success"),
    ("per drop more crop scheme micro irrigation subsidy percentage", "SCHEME_004", "success"),
    ("khet me talab ya farm pond banwane ke liye grant", "SCHEME_004", "success"),
    ("sprinkler set pump line subsidy for small farmers", "SCHEME_004", "success"),
    
    # 🏪 Category 6: Market Access, Prices & Selling (e-NAM)
    ("mandi me fasal bechne ke liye online registration kaise kare", "SCHEME_008", "success"),
    ("fasal ka sahi dam ya bhav pata karne ke liye portal", "SCHEME_008", "success"),
    ("national agriculture market online bidding system for APMC mandi", "SCHEME_008", "success"),
    ("apne rajya ke bahar dusri mandi me fasal bechne ka online tareeka", "SCHEME_008", "success"),
    ("e-nam portal par kisan apna khata kaise banaye", "SCHEME_008", "success"),
    
    # 👴 Category 7: Pensions & Social Security (PM-KMY / MGNREGA)
    ("pension scheme for senior citizens above 60 years in farming", "SCHEME_006", "success"),
    ("kisan maandhan yojana me har mahine 3000 pension kaise milegi", "SCHEME_006", "success"),
    ("mgnrega me khet ki meedh aur samatlikaran ka kaam", "SCHEME_011", "success"),
    ("18 se 40 varsh ke kisan ke liye monthly contribution pension plan", "SCHEME_006", "success"),
    
    # 🚀 Category 8: Organic Farming, Infrastructure & Startups (PKVY / AIF / RKVY)
    ("organic kheti ya jaivik kheti karne ke liye protsahan yojana", "SCHEME_010", "success"),
    ("cold storage aur godam banwane ke liye Agriculture Infrastructure Fund", "SCHEME_013", "success"),
    ("agri startup incubation RKVY RAFTAAR grant amount", "SCHEME_014", "success"),
    ("paramparagat krishi vikas yojana bio fertilizer subsidy", "SCHEME_010", "success"),
    
    # 🔤 Category 9: Heavy Phonetic Typos & Extreme Speech Variants (ASR Test)
    ("mujhe paani ke pamp par sabseedi kitni milegi", "SCHEME_007", "success"),
    ("fasal khraab hone par kitna pasia milega bima se", "SCHEME_002", "success"),
    ("kisaan ko har saal chha hajaar rupey kaise milte hain", "SCHEME_001", "success"),
    ("pashu ke liye karja chahiye kcc se", "SCHEME_003", "success"),
    ("pm kisam daubara ekyc kaise karen", "SCHEME_001", "success"),
    
    # 🛑 Category 10: Out-of-Domain & Ambiguous Edge Cases (Fallback Test)
    ("random irrelevant question about space rockets", "", "fallback"),
    ("what is the subsidy for buying a private electric car in Delhi", "", "fallback"),
    ("pension scheme for senior citizens in private IT jobs", "", "fallback"),
    ("home loan interest rate in State Bank of India", "", "fallback"),
    ("how to register a new startup company in Bangalore", "", "fallback"),
    ("passport renewal fee and document checklist", "", "fallback"),
    ("best smartphone under 15000 rupees in India", "", "fallback"),
    ("tractor khareedne ke liye loan kaise milega", "SCHEME_009", "success")
]


def run_benchmark():
    print("==================================================================")
    print("🚀 RUNNING COMPREHENSIVE 55-QUERY BENCHMARK TEST SUITE")
    print("==================================================================\n")
    
    engine = GovernmentSchemesRAGEngine()
    
    total = len(TEST_QUERIES_55)
    passed = 0
    total_latency_ms = 0.0
    
    for q, expected_id, expected_status in TEST_QUERIES_55:
        res = engine.query_schemes(q)
        lat = res["latency_ms"]
        total_latency_ms += lat
        
        status_ok = (res["status"] == expected_status)
        match_ok = True
        if expected_status == "success" and expected_id:
            match_ok = (res.get("scheme_id") == expected_id)
            
        if status_ok and match_ok:
            passed += 1
            icon = "✅ PASS"
        else:
            icon = "❌ FAIL"
            
        print(f"[{icon}] Q: \"{q[:45]}...\" | Status: {res['status'].upper()} | Match: {res.get('scheme_name', 'N/A')[:30]} | Latency: {lat} ms")

    avg_lat = round(total_latency_ms / total, 2)
    accuracy = round((passed / total) * 100, 2)
    
    print("\n==================================================================")
    print(f"📊 BENCHMARK SUMMARY REPORT")
    print(f"Total Queries Tested : {total}")
    print(f"Passed               : {passed} / {total} ({accuracy}%)")
    print(f"Average Latency      : {avg_lat} ms")
    print("==================================================================")

if __name__ == "__main__":
    run_benchmark()
