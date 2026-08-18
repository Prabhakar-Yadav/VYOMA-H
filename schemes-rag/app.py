import sys
import logging
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from government_schemes_rag import GovernmentSchemesRAGEngine

# Configure simple logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("RAG_App")

# Global engine instance
rag_engine: Optional[GovernmentSchemesRAGEngine] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Loads RAG Engine on FastAPI startup."""
    global rag_engine
    if not rag_engine:
        logger.info("Initializing RAG Engine for Web API...")
        rag_engine = GovernmentSchemesRAGEngine("schemes_dataset.jsonl")
        logger.info("RAG Engine ready for Web API queries!")
    yield


# FastAPI Application Instance
app = FastAPI(
    title="Gram Sahayak RAG API",
    description="Single Unified App for Government Schemes RAG",
    lifespan=lifespan,
)


class QueryRequest(BaseModel):
    question: str
    category: Optional[str] = None


@app.post("/query")
def query_schemes_endpoint(request: QueryRequest) -> Dict[str, Any]:
    """Web API endpoint for query processing."""
    global rag_engine
    if not rag_engine:
        rag_engine = GovernmentSchemesRAGEngine("schemes_dataset.jsonl")

    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    return rag_engine.query_schemes(
        user_question=request.question,
        category=request.category
    )


def run_interactive_terminal():
    """Clean interactive terminal loop when running python app.py directly."""
    global rag_engine
    rag_engine = GovernmentSchemesRAGEngine("schemes_dataset.jsonl")
    
    while True:
        try:
            user_query = input("Ask a Question > ").strip()
            if not user_query:
                continue
            if user_query.lower() in ["exit", "quit", "q"]:
                break
                
            res = rag_engine.query_schemes(user_query)
            
            if res.get("status") == "success":
                print("\n" + "=" * 60)
                print(f"MATCH: {res.get('scheme_name')} ({res.get('scheme_id')})")
                print(f"CONFIDENCE SCORE: {res.get('confidence_score')}")
                print("-" * 60)
                print(f"ANSWER:\n{res.get('text')}")
                print("=" * 60 + "\n")
            else:
                print(f"\nSTATUS: {res.get('status').upper()}")
                print(f"RESPONSE:\n{res.get('text')}\n")
            
        except (KeyboardInterrupt, EOFError):
            break


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000)
    else:
        run_interactive_terminal()
