"""
Gram Sahayak Agent Tool Wrapper: Government Schemes RAG

This module provides direct python tool interfaces for GramSahayakAgent tool calls.
It loads the GovernmentSchemesRAGEngine once and exposes 4 distinct tools:
- match_eligible_schemes_tool
- get_scheme_details_tool
- get_disaster_relief_options_tool
- get_subsidy_details_tool
"""

import logging
from typing import Optional, Dict, Any, List
from government_schemes_rag import GovernmentSchemesRAGEngine

logger = logging.getLogger("GramSahayak_RAGTool")

# Singleton instance
_rag_engine_instance: Optional[GovernmentSchemesRAGEngine] = None

def get_rag_engine() -> GovernmentSchemesRAGEngine:
    """Returns the singleton RAG engine instance (loads on first call)."""
    global _rag_engine_instance
    if _rag_engine_instance is None:
        logger.info("Initializing Government Schemes RAG Tool Engine...")
        _rag_engine_instance = GovernmentSchemesRAGEngine(jsonl_file="enriched_schemes_dataset.jsonl")
    return _rag_engine_instance

def match_eligible_schemes_tool(farmer_profile: str, top_n: int = 3) -> Dict[str, Any]:
    """
    Agent Tool: Match eligible schemes based on farmer profile.
    Returns the top N schemes and the exact verbatim eligibility criteria.
    """
    engine = get_rag_engine()
    return engine.match_eligible_schemes(farmer_profile, top_n)

def get_scheme_details_tool(scheme_name: str, user_question: str) -> Dict[str, Any]:
    """
    Agent Tool: Answer a specific question about a known scheme.
    Uses BM25 exact anchor matching to guarantee retrieval.
    """
    engine = get_rag_engine()
    return engine.get_scheme_details(scheme_name, user_question)

def get_disaster_relief_options_tool(disaster_context: str) -> Dict[str, Any]:
    """
    Agent Tool: Get disaster relief, crop loss, or insurance options.
    Returns verbatim application and benefit details.
    """
    engine = get_rag_engine()
    return engine.get_disaster_relief_options(disaster_context)

def get_subsidy_details_tool(scheme_name: str) -> Dict[str, Any]:
    """
    Agent Tool: Retrieve raw, deterministic subsidy and financial benefit details.
    """
    engine = get_rag_engine()
    return engine.get_subsidy_details(scheme_name)

if __name__ == "__main__":
    # Self-test
    logger.info("Testing agent tool wrappers...")
    engine = get_rag_engine()
    
    res1 = match_eligible_schemes_tool("small farmer in UP with 2 acres")
    print("Match Eligible:", res1)
    
    res2 = get_scheme_details_tool("PM-KISAN", "How do I apply?")
    print("Scheme Details:", res2)
    
    res3 = get_disaster_relief_options_tool("my crops were destroyed by flood")
    print("Disaster Relief:", res3)
    
    res4 = get_subsidy_details_tool("PM-KISAN")
    print("Subsidy Details:", res4)
