"""
Gram Sahayak Agent Tool Wrapper: Government Schemes RAG

This module provides a direct python tool interface for GramSahayakAgent tool calls.
It loads the GovernmentSchemesRAGEngine once and exposes `query_government_schemes()`.

Usage in Agent:
    from schemes_rag_tool import query_government_schemes

    result = query_government_schemes("How can small farmers get 6000 rupees?")
"""

import logging
from typing import Optional, Dict, Any
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

def query_government_schemes(query: str, category: Optional[str] = None) -> Dict[str, Any]:
    """
    Agent Tool Function: Query 500+ Indian Government Schemes for agricultural, financial,
    insurance, housing, livestock, and welfare assistance.

    Args:
        query (str): The farmer's question in English or translated text.
        category (Optional[str]): Optional category filter (e.g., 'Financial Assistance', 'Insurance').

    Returns:
        Dict[str, Any]: Structured result dictionary containing:
            - status (str): 'success' or 'fallback'
            - text (str): Concise answer capped at 350 chars for voice/LCD
            - bhashini_voice_text (str): Speech-optimized text for TTS
            - tft_lcd_display_card (str): Display card text for TFT-LCD screen
            - scheme_name (str): Matched scheme name
            - scheme_id (str): Matched scheme ID
            - confidence_score (float): Cosine similarity score
            - latency_seconds (float): Search execution time
    """
    engine = get_rag_engine()
    return engine.query_schemes(user_question=query, category=category)

if __name__ == "__main__":
    # Self-test
    logger.info("Testing agent tool wrapper...")
    res = query_government_schemes("How to get 6000 rupees in bank account?")
    print(f"Tool Result -> Scheme: {res.get('scheme_name')} | Status: {res.get('status')} | Score: {res.get('confidence_score')}")
    print(f"Voice Text: {res.get('bhashini_voice_text')}")
