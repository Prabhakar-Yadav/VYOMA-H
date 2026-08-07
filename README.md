# Gram Sahayak - RAG Modules

This repository contains the core Retrieval-Augmented Generation (RAG) engines for **Gram Sahayak**, an edge-deployed multimodal AI assistant for rural India. These modules are specifically engineered to run efficiently on a Jetson Nano, interfacing with the Bhashini API for STT/TTS.

## 🏗 Architecture Overview

The system is split into two specialized, highly-optimized RAG engines:

1. **AI Tutor RAG (`ai_tutor_rag/`)**: A foundational literacy engine powered by NCERT K-12 data.
2. **Government Schemes RAG (`govt_schemes_rag/`)**: A precision agricultural schemes engine powered by OKF government datasets.

### Core Optimizations for Edge (Jetson Nano)
- **Pure English Backend**: All local dialect translations (Bhojpuri, Awadhi, etc.) are handled entirely by Bhashini upstream. The RAG modules operate purely in English, drastically reducing index size and preventing Hinglish cross-contamination.
- **Hybrid Search (FAISS + BM25)**: Both engines utilize a dual-index architecture to capture both semantic meaning and exact-match agricultural/academic vocabulary.
- **Reciprocal Rank Fusion (RRF)**: Merges vector and keyword scores for optimal retrieval.
- **Absolute Fallback Gates**: Fixes the inherent RRF vulnerability (relative-only scores) by establishing absolute metric floors (`top_cosine < 0.35` and `bm25_score < 5.0`). If a query fails these thresholds, the engine confidently triggers a safety fallback rather than hallucinating.
- **Cross-Encoder Purge**: The heavy Cross-Encoder reranker was completely stripped from the pipeline, slashing inference latency from ~800ms to <150ms per query.

### Domain-Specific Features

#### Government Schemes Anti-Magnetism & Routing
- **Regex Index Stripping**: Uses exact word boundary regex (`\b...\b`) to dynamically strip cross-references (e.g., removing mentions of "PMAY" from the "Ujjwala" scheme document) during index building. This cures "keyword magnetism" without destroying the UI display text.
- **Lightweight Zero-Shot Intent Routing**: Replaced a bloated HuggingFace Pipeline with simple `all-MiniLM-L6-v2` cosine similarities against category labels. Implements a 3-tiered dynamic gate:
  - `> 0.85`: Hard Category Filter
  - `> 0.55`: Soft-Gate (1.2x RRF Boost)
  - `< 0.55`: Open Search
- **Smart Intent Extractor**: Isolates exactly what the farmer asked for (e.g. documents, eligibility, application process, benefits) and dynamically constructs the response.

## 📂 Directory Structure

```
.
├── ai_tutor_rag/
│   ├── ai_tutor_rag.py              # Core Tutor RAG Engine
│   ├── clean_curriculum.jsonl       # NCERT K-12 Dataset (Pre-cleaned)
│   └── RURAL_LITERACY_BENCHMARK.md  # Research & Architecture Docs
│
└── govt_schemes_rag/
    ├── government_schemes_rag.py    # Core Schemes RAG Engine
    └── schemes_dataset.jsonl        # OKF Schemes Dataset
```

## 🚀 Usage

Both engines are designed to be imported as standalone modules into the main hardware orchestrator script (`stage.py`).

```python
from ai_tutor_rag.ai_tutor_rag import GoogleOKFAITutorEngine
from govt_schemes_rag.government_schemes_rag import GovernmentSchemesRAGEngine

# Initialize once at startup (Loads FAISS into RAM)
tutor_engine = GoogleOKFAITutorEngine(jsonl_file="clean_curriculum.jsonl")
schemes_engine = GovernmentSchemesRAGEngine(jsonl_file="schemes_dataset.jsonl")

# Query
response = tutor_engine.query_tutor("Why is my shadow so long in the evening?")
print(response["bhashini_voice_text"])
```

## 📝 License
Proprietary codebase for the VYOMA Innovation Challenge.
