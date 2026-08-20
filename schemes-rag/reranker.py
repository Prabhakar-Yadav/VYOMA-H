"""
Adaptive Cross-Encoder Reranker for Jetson Orin Nano.
Reranks top-K candidates from BM25+FAISS RRF with a strict latency budget guard.
"""
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Edge_Reranker")


class LatencyGuardedReranker:
    """
    Applies a lightweight Cross-Encoder model to rerank candidate documents.
    If the elapsed retrieval time exceeds max_budget_ms, it automatically bypasses
    cross-encoding to preserve the <45ms SLA.
    """
    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-TinyBERT-L-2-v2",
        max_budget_ms: float = 25.0,
    ):
        self.model_name = model_name
        self.max_budget_ms = max_budget_ms
        self.model = None

        try:
            from sentence_transformers import CrossEncoder
            self.model = CrossEncoder(self.model_name, max_length=128)
            logger.info(f"Cross-Encoder reranker '{self.model_name}' loaded successfully.")
        except Exception as e:
            logger.warning(f"Could not load Cross-Encoder ({e}). Operating in bypass mode.")

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        elapsed_retrieval_ms: float = 0.0,
        top_k: int = 3,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """
        Reranks candidate schemes. Returns (reranked_candidates, was_bypassed).
        """
        if not candidates or self.model is None:
            return candidates[:top_k], True

        # Check latency budget
        if elapsed_retrieval_ms > self.max_budget_ms:
            logger.info(
                f"Latency budget exceeded ({elapsed_retrieval_ms:.1f}ms > {self.max_budget_ms}ms). "
                "Bypassing Cross-Encoder to protect edge SLA."
            )
            return candidates[:top_k], True

        t0 = time.time()
        pairs = []
        for c in candidates:
            scheme = c.get("scheme", c)
            text = f"{scheme.get('scheme_name', '')} {scheme.get('benefit_details', '')} {scheme.get('eligibility_criteria', '')}"
            pairs.append((query, text))

        try:
            scores = self.model.predict(pairs)
            for idx, score in enumerate(scores):
                candidates[idx]["cross_score"] = float(score)

            reranked = sorted(candidates, key=lambda x: x.get("cross_score", 0.0), reverse=True)
            rerank_duration_ms = (time.time() - t0) * 1000
            logger.info(f"Cross-Encoder reranking completed in {rerank_duration_ms:.2f}ms")
            return reranked[:top_k], False
        except Exception as e:
            logger.warning(f"Reranking failed ({e}). Returning original order.")
            return candidates[:top_k], True
