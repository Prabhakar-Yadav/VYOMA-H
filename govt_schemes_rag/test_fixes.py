import logging
from government_schemes_rag import GovernmentSchemesRAGEngine
from config import ACRONYM_BOOST_MULTIPLIER

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestFixes")

def run_tests():
    engine = GovernmentSchemesRAGEngine()
    
    logger.info("=== Test 1: BM25 Empty/Short Query Safety ===")
    res_empty = engine.query_schemes("a")
    assert res_empty['status'] in ['fallback', 'success'], "Query crashed on short input"
    
    logger.info("\n=== Test 2: Phrase Acronym Matching ('soil health card') ===")
    res_shc = engine.query_schemes("i want a soil health card")
    top_match = res_shc.get("top_match", {})
    # RRF score should be exactly boosted once (around 0.0813)
    assert 0.08 < top_match.get('rrf_score', 0) < 0.09, "Score double-boosted or not boosted"
    assert "Soil Health Card" in top_match.get('scheme_name', ""), "Did not match correct scheme"
    
    logger.info("\n=== Test 3: Single Word Acronym Matching ('kcc') ===")
    res_kcc = engine.query_schemes("how to apply for kcc")
    top_match = res_kcc.get("top_match", {})
    assert 0.08 < top_match.get('rrf_score', 0) < 0.09, "Score double-boosted or not boosted"
    assert "Kisan Credit Card" in top_match.get('scheme_name', ""), "Did not match correct scheme"

    logger.info("\n=== Test 4: Word Boundary Safety ('stockccheck') ===")
    res_bound = engine.query_schemes("stockccheck")
    # Should fallback because 'kcc' is inside 'stockccheck'
    assert res_bound['status'] == 'fallback', "Matched KCC on invalid word boundary"
        
    logger.info("\nAll targeted tests completed successfully with asserts!")

if __name__ == "__main__":
    run_tests()
