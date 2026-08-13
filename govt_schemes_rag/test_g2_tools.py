import json
from schemes_rag_tool import (
    match_eligible_schemes_tool,
    get_scheme_details_tool,
    get_disaster_relief_options_tool,
    get_subsidy_details_tool,
)

def print_result(title, result):
    print(f"\n{'='*50}\n{title}\n{'='*50}")
    print(json.dumps(result, indent=2))

def main():
    print("Testing G2 RAG Refactored Tools...")
    
    res1 = match_eligible_schemes_tool("small farmer in UP with 2 acres", top_n=2)
    print_result("1. Match Eligible Schemes", res1)
    
    res2 = get_scheme_details_tool("PM-KISAN", "How do I apply for this?")
    # Clean up large display text for test output
    if "tft_lcd_display_card" in res2:
        del res2["tft_lcd_display_card"]
    if "bhashini_voice_text" in res2:
        del res2["bhashini_voice_text"]
    print_result("2. Get Scheme Details", res2)
    
    res3 = get_disaster_relief_options_tool("my crops were destroyed by flood")
    print_result("3. Get Disaster Relief Options", res3)
    
    res4 = get_subsidy_details_tool("PM-KISAN")
    print_result("4. Get Subsidy Details", res4)

    res5 = get_subsidy_details_tool("MGNREGA")
    print_result("5. Get Subsidy Details (MGNREGA Exact Match Test)", res5)

if __name__ == "__main__":
    main()
