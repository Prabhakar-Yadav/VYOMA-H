"""
High-Throughput Edge FastAPI Gateway for Gram Sahayak on NVIDIA Jetson Orin Nano.
Includes real-time RSS and Swap memory watchdog to prevent Linux OOM exit code 137.
"""
import gc
import logging
import os
import psutil
import time
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from government_schemes_rag import GovernmentSchemesRAGEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Gateway_API")

app = FastAPI(
    title="Gram Sahayak Edge Gateway",
    version="2.0.0",
    description="Sub-45ms Edge RAG & Voice Gateway for Rural Governance on Jetson Orin Nano"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global engine singleton
engine: Optional[GovernmentSchemesRAGEngine] = None


class QueryRequest(BaseModel):
    query: str = Field(..., description="User query text (in English, translated via Bhashini NMT)")
    state: Optional[str] = Field(default=None, description="Optional State/UT filter code")
    category: Optional[str] = Field(default=None, description="Optional category filter")


class QueryResponse(BaseModel):
    status: str
    outcome: str
    confidence_score: float
    scheme_id: Optional[str] = None
    scheme_name: Optional[str] = None
    category: Optional[str] = None
    extracted_answer: Optional[str] = None
    lcd_card: str
    voice_text: str
    latency_ms: float
    memory_rss_mb: float


@app.on_event("startup")
def startup_event():
    global engine
    logger.info("Starting up Gram Sahayak Gateway on Jetson Orin Nano...")
    engine = GovernmentSchemesRAGEngine("schemes_dataset.jsonl")
    logger.info("Engine loaded and warm.")


def get_memory_stats() -> Dict[str, float]:
    """Inspects Linux kernel memory and swap metrics."""
    process = psutil.Process(os.getpid())
    rss_mb = process.memory_info().rss / (1024 * 1024)
    vms_mb = process.memory_info().vms / (1024 * 1024)
    swap = psutil.swap_memory()
    return {
        "process_rss_mb": round(rss_mb, 2),
        "process_vms_mb": round(vms_mb, 2),
        "total_swap_used_mb": round(swap.used / (1024 * 1024), 2),
        "total_swap_percent": round(swap.percent, 1),
    }


@app.get("/health")
def health_check():
    """Real-time health and memory watchdog endpoint."""
    mem = get_memory_stats()
    # If swap > 85%, trigger proactive garbage collection to avoid OOM killer
    if mem["total_swap_percent"] > 85.0:
        gc.collect()
        logger.warning(f"High Swap Memory detected ({mem['total_swap_percent']}%). Proactive GC triggered.")

    return {
        "status": "healthy",
        "device": "NVIDIA Jetson Orin Nano (8GB)",
        "memory": mem,
        "indexed_schemes": len(engine.schemes) if engine else 0,
    }


@app.post("/query", response_model=QueryResponse)
def query_endpoint(req: QueryRequest):
    """Processes user query through the hybrid RAG pipeline."""
    if engine is None:
        raise HTTPException(status_code=503, detail="RAG Engine is still initializing.")

    t0 = time.time()
    result = engine.query_schemes(req.query, category=req.category)
    duration_ms = (time.time() - t0) * 1000

    mem = get_memory_stats()

    return QueryResponse(
        status=result.get("status", "success"),
        outcome=result.get("outcome", "success"),
        confidence_score=result.get("confidence_score", 0.0),
        scheme_id=result.get("scheme_id"),
        scheme_name=result.get("scheme_name"),
        category=result.get("category"),
        extracted_answer=result.get("extracted_answer"),
        lcd_card=result.get("lcd_card", ""),
        voice_text=result.get("voice_text", ""),
        latency_ms=round(duration_ms, 2),
        memory_rss_mb=mem["process_rss_mb"],
    )


@app.post("/reload_index")
def reload_index():
    """Hot-reloads the dataset and indices without restarting the server."""
    global engine
    logger.info("Hot-reloading schemes database...")
    engine = GovernmentSchemesRAGEngine("schemes_dataset.jsonl")
    gc.collect()
    return {"status": "success", "message": f"Reloaded {len(engine.schemes)} schemes successfully."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
