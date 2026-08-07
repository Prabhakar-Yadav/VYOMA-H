import sys
sys.stdout.reconfigure(encoding='utf-8')
from government_schemes_rag import GovernmentSchemesRAGEngine

engine = GovernmentSchemesRAGEngine()

tests = [
    ("PM-KISAN 6000 rupees", "SCHEME_001"),
    ("dairy loan for cow buffalo", "SCHEME_024"),
    ("ghar banane ke liye subsidy", "SCHEME_023"),
    ("gas cylinder for women", "SCHEME_027"),
    ("ayushman health insurance", "SCHEME_030"),
    ("shahad ki kheti beekeeping", "SCHEME_026"),
    ("coconut palm insurance cyclone", "SCHEME_019"),
    ("livestock goat sheep farming subsidy", "SCHEME_022"),
    ("drinking water tap connection village", "SCHEME_028"),
    ("random question about cricket match", None),
]

passed = 0
for q, expected in tests:
    r = engine.query_schemes(q)
    got = r.get("scheme_id", None)
    outcome = r["outcome"]
    ok = (expected is None and outcome == "fallback") or got == expected
    if ok:
        passed += 1
    tag = "PASS" if ok else "FAIL"
    name = r.get("scheme_name", "-")[:35]
    print(f"  {tag} | {q[:42]:42s} | exp={expected} got={got} | {name}")

print(f"\n{passed}/{len(tests)} passed")
