#!/usr/bin/env python3
"""Incremental corpus growth for the G1/G2 sqlite-vec + BM25 indexes -- companion to
build_index.py, not a replacement for it. build_index.py always nukes-and-rebuilds a
corpus from scratch (see its own docstring); this script is for the real, ongoing
case build_index.py wasn't designed for: a team adding new documents to a corpus
that already has a built index, without re-embedding (and re-paying the Ollama
embedding cost for) everything that hasn't changed.

Three real, tested operations:

    append   -- scan the bundle directory, find any concept_id NOT yet in the DB,
                chunk + embed + insert ONLY those new chunks (existing chunks are
                never re-embedded or touched), then rebuild the BM25 pickle from the
                CURRENT FULL corpus (old + new chunks, read back from the DB, not
                re-embedded -- BM25 has no partial-update primitive, but rebuilding
                it is pure tokenization, no Ollama calls, cheap even at real scale).

    reingest -- for when you've EDITED an existing document, not added a new one:
                deletes that concept_id's existing chunks (real DELETE, confirmed
                working directly against the vec0 table -- see rag/store.py's
                delete_concept() docstring) and re-adds it fresh from the bundle
                directory, then rebuilds BM25 the same way. `append` deliberately
                does NOT do this automatically -- it treats "concept_id already in
                the DB" as "already indexed, skip it" so a normal append run is fast
                and never silently re-embeds things; editing an existing doc is an
                explicit, separate action.

    stats    -- real concept_type/source_type breakdown of the current DB (the same
                audit query used to find the G1 coverage gap that led to
                get_guidelines_and_safety) -- run this after appending to sanity-
                check what actually landed in the corpus.

Usage (from this toolkit's root, with its venv active):
    python3 rag/ingest.py append g1
    python3 rag/ingest.py append g2
    python3 rag/ingest.py reingest g1 --concepts /diseases/potato-late-blight,/treatments/mancozeb-75-wp
    python3 rag/ingest.py stats g1

See README.md for the full document-authoring workflow (frontmatter schema, real
concept_type/source_type values, directory conventions) -- this file only covers the
mechanics of getting new/edited .md files into the built index.
"""
from __future__ import annotations

import argparse
import os
import pickle
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # toolkit root

from rag import embed, okf, store
from rag.chunking import chunk_bundle, chunk_concept

AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOKEN_RE = re.compile(r"[a-z0-9%ऀ-ॿঀ-৿଀-୿ఀ-౿]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _paths(name: str) -> tuple[str, str, str]:
    bundle_dir = os.path.join(AGENTS_DIR, "datasets", "rag", name)
    db_path = os.path.join(AGENTS_DIR, "datasets", "rag", f"{name}.sqlite")
    bm25_path = os.path.join(AGENTS_DIR, "datasets", "rag", f"{name}_bm25.pkl")
    return bundle_dir, db_path, bm25_path


def _rebuild_bm25(db, bm25_path: str) -> int:
    """Real full-corpus rebuild of the sparse index -- no Ollama calls, pure
    tokenization over text already sitting in the DB (old + newly-inserted chunks
    alike), so this is cheap to re-run every time append/reingest runs, not
    something worth trying to make incremental itself."""
    all_rows = store.all_chunks(db)
    texts = [
        "\n".join(p for p in (r["concept_title"], r["heading"], r["text"]) if p)
        for r in all_rows
    ]
    from rank_bm25 import BM25Okapi
    corpus_tokens = [tokenize(t) for t in texts]
    bm25 = BM25Okapi(corpus_tokens)
    with open(bm25_path, "wb") as f:
        pickle.dump({"bm25": bm25, "chunk_ids": [r["chunk_id"] for r in all_rows]}, f)
    return len(all_rows)


def cmd_append(name: str) -> None:
    bundle_dir, db_path, bm25_path = _paths(name)
    if not os.path.exists(db_path):
        print(f"[{name}] no existing index at {db_path} -- run "
              f"`python3 rag/build_index.py` first for an initial build, or this "
              f"append will just be a full first-time build.")

    t0 = time.perf_counter()
    concepts = okf.load_bundle(bundle_dir)
    db = store.connect(db_path)
    store.create_schema(db)  # no-op if the table already exists
    already = store.existing_concept_ids(db)
    new_concepts = [c for c in concepts if c.concept_id not in already]
    print(f"[{name}] bundle has {len(concepts)} concepts, {len(already)} already "
          f"indexed, {len(new_concepts)} new ({time.perf_counter() - t0:.2f}s)")

    if not new_concepts:
        print(f"[{name}] nothing new to add. If you EDITED an existing doc instead "
              f"of adding a new one, use `reingest --concepts <id>`, not `append` -- "
              f"append only looks for concept_ids it hasn't seen before.")
        return

    t0 = time.perf_counter()
    new_chunks = chunk_bundle(new_concepts)
    texts = [c.embed_text for c in new_chunks]
    vectors = embed.embed_batch(texts)
    print(f"[{name}] chunked -> {len(new_chunks)} new chunks, embedded with "
          f"{embed.MODEL} ({time.perf_counter() - t0:.2f}s)")

    t0 = time.perf_counter()
    with db:
        for chunk, vec in zip(new_chunks, vectors):
            store.insert_chunk(db, chunk, embed.to_f32_bytes(vec))
    print(f"[{name}] inserted {len(new_chunks)} new rows into {db_path} "
          f"({time.perf_counter() - t0:.2f}s)")

    t0 = time.perf_counter()
    total = _rebuild_bm25(db, bm25_path)
    print(f"[{name}] BM25 rebuilt over {total} total chunks -> {bm25_path} "
          f"({time.perf_counter() - t0:.2f}s)")
    print(f"[{name}] done. {len(new_concepts)} concepts / {len(new_chunks)} chunks "
          f"added, corpus is now {total} chunks total.")


def cmd_reingest(name: str, concept_ids: list[str]) -> None:
    bundle_dir, db_path, bm25_path = _paths(name)
    if not os.path.exists(db_path):
        print(f"[{name}] no existing index at {db_path} -- nothing to reingest into. "
              f"Run `python3 rag/build_index.py` or `append` first.")
        return

    db = store.connect(db_path)
    concepts_by_id = {c.concept_id: c for c in okf.load_bundle(bundle_dir)}
    missing = [cid for cid in concept_ids if cid not in concepts_by_id]
    if missing:
        print(f"[{name}] these concept_ids aren't in the bundle directory at all "
              f"(typo, or wrong corpus?): {missing}")
        return

    total_deleted = total_inserted = 0
    for cid in concept_ids:
        deleted = store.delete_concept(db, cid)
        concept = concepts_by_id[cid]
        chunks = chunk_concept(concept)
        texts = [c.embed_text for c in chunks]
        vectors = embed.embed_batch(texts)
        with db:
            for chunk, vec in zip(chunks, vectors):
                store.insert_chunk(db, chunk, embed.to_f32_bytes(vec))
        print(f"[{name}] {cid}: removed {deleted} old chunks, added {len(chunks)} "
              f"fresh ones")
        total_deleted += deleted
        total_inserted += len(chunks)

    total = _rebuild_bm25(db, bm25_path)
    print(f"[{name}] done. {total_deleted} old chunks removed, {total_inserted} "
          f"fresh chunks added across {len(concept_ids)} concept(s), corpus is now "
          f"{total} chunks total.")


def cmd_stats(name: str) -> None:
    _, db_path, _ = _paths(name)
    if not os.path.exists(db_path):
        print(f"[{name}] no index at {db_path} yet.")
        return
    db = store.connect(db_path)
    rows = store.all_chunks(db)
    from collections import Counter
    ct = Counter(r["concept_type"] for r in rows)
    st = Counter(r["source_type"] for r in rows)
    concepts_by_ct: dict[str, set[str]] = {}
    for r in rows:
        concepts_by_ct.setdefault(r["concept_type"], set()).add(r["concept_id"])
    print(f"[{name}] {len(rows)} chunks, {len(set(r['concept_id'] for r in rows))} concepts")
    print(f"[{name}] concept_type -> (chunks, concepts):")
    for k in sorted(ct):
        print(f"    {k:20s} {ct[k]:4d} chunks, {len(concepts_by_ct[k]):3d} concepts")
    print(f"[{name}] source_type -> chunks:")
    for k in sorted(st):
        print(f"    {k:20s} {st[k]:4d}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_append = sub.add_parser("append", help="Add new (not-yet-indexed) concepts from the bundle directory.")
    p_append.add_argument("corpus", choices=["g1", "g2"])

    p_reingest = sub.add_parser("reingest", help="Re-index specific concept_ids (use after editing an existing .md file).")
    p_reingest.add_argument("corpus", choices=["g1", "g2"])
    p_reingest.add_argument("--concepts", required=True, help="Comma-separated concept_ids, e.g. /diseases/potato-late-blight,/treatments/mancozeb-75-wp")

    p_stats = sub.add_parser("stats", help="Print concept_type/source_type breakdown of the current index.")
    p_stats.add_argument("corpus", choices=["g1", "g2"])

    args = parser.parse_args()
    if args.cmd == "append":
        cmd_append(args.corpus)
    elif args.cmd == "reingest":
        cmd_reingest(args.corpus, [c.strip() for c in args.concepts.split(",") if c.strip()])
    elif args.cmd == "stats":
        cmd_stats(args.corpus)


if __name__ == "__main__":
    main()
