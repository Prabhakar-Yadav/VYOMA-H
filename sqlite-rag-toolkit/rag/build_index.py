#!/usr/bin/env python3
"""Build the G1 and G2 sqlite-vec indexes from datasets/rag/{g1,g2}/.

Run: source venv/bin/activate && cd gramsahayak && python3 rag/build_index.py

Produces (gitignored, rebuild any time -- same "generated, rebuild with build" contract
krishi-rag's own index/ directory already uses):
    datasets/rag/g1.sqlite  + datasets/rag/g1_bm25.pkl
    datasets/rag/g2.sqlite  + datasets/rag/g2_bm25.pkl
"""
from __future__ import annotations

import os
import pickle
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # gramsahayak/

from rag import embed, okf, store
from rag.chunking import chunk_bundle

AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOKEN_RE = re.compile(r"[a-z0-9%ऀ-ॿঀ-৿଀-୿ఀ-౿]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def build_one(name: str):
    bundle_dir = os.path.join(AGENTS_DIR, "datasets", "rag", name)
    db_path = os.path.join(AGENTS_DIR, "datasets", "rag", f"{name}.sqlite")
    bm25_path = os.path.join(AGENTS_DIR, "datasets", "rag", f"{name}_bm25.pkl")

    if os.path.exists(db_path):
        os.remove(db_path)

    t0 = time.perf_counter()
    concepts = okf.load_bundle(bundle_dir)
    chunks = chunk_bundle(concepts)
    print(f"[{name}] {len(concepts)} concepts -> {len(chunks)} chunks "
          f"({time.perf_counter() - t0:.2f}s)")

    t0 = time.perf_counter()
    texts = [c.embed_text for c in chunks]
    vectors = embed.embed_batch(texts)
    print(f"[{name}] embedded {len(vectors)} chunks with {embed.MODEL} "
          f"({time.perf_counter() - t0:.2f}s)")

    t0 = time.perf_counter()
    db = store.connect(db_path)
    store.create_schema(db)
    with db:
        for chunk, vec in zip(chunks, vectors):
            store.insert_chunk(db, chunk, embed.to_f32_bytes(vec))
    print(f"[{name}] sqlite-vec (int8) index written to {db_path} "
          f"({time.perf_counter() - t0:.2f}s)")

    t0 = time.perf_counter()
    from rank_bm25 import BM25Okapi
    corpus_tokens = [tokenize(t) for t in texts]
    bm25 = BM25Okapi(corpus_tokens)
    with open(bm25_path, "wb") as f:
        pickle.dump({"bm25": bm25, "chunk_ids": [c.chunk_id for c in chunks]}, f)
    print(f"[{name}] BM25 index written to {bm25_path} ({time.perf_counter() - t0:.2f}s)")

    return len(concepts), len(chunks)


def main():
    total_t0 = time.perf_counter()
    g1_concepts, g1_chunks = build_one("g1")
    g2_concepts, g2_chunks = build_one("g2")
    print(f"\nTotal build time: {time.perf_counter() - total_t0:.2f}s")
    print(f"G1: {g1_concepts} concepts, {g1_chunks} chunks")
    print(f"G2: {g2_concepts} concepts, {g2_chunks} chunks")


if __name__ == "__main__":
    main()
