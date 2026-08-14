"""sqlite-vec storage layer -- int8-quantized dense vectors + metadata in one vec0
table per corpus (g1, g2), BM25 sparse index in a sibling pickle file (sqlite-vec is
dense-only; this project's own real test at
/home/davidacad10/.unsloth confirmed apsw is required -- stdlib sqlite3 in this venv
has no loadable-extension support at all, `enable_load_extension`/`load_extension`
are missing from Connection objects entirely, confirmed directly, not assumed).

Schema, one vec0 table per corpus:
    embedding   int8[384]   -- granite-embedding:30m, unit-scaled int8 quantized
    +chunk_id, +concept_id, +concept_title, +concept_type, +heading, +text,
    +trust_tier, +source_type, +crop, +label_id, +is_visual   -- auxiliary columns,
    stored but not searched, mirrors rag/chunking.py's Chunk dataclass exactly.

Filter vs boost (decision from G1-G2-VECTORDB-PLAN.md Β§6, implemented here):
    crop, concept_type   -> real SQL WHERE filters (pre-ranking candidate restriction)
    source_type          -> NEVER filtered here -- boost is applied post-query in
                             rag/retrieval.py, same asymmetry krishi-rag's own
                             retrieval.py documents (a wrong filter loses the answer
                             entirely; a wrong boost just ranks it lower).
"""

from __future__ import annotations

import apsw
import sqlite_vec

from rag.chunking import Chunk

EMBED_DIM = 384


def connect(db_path: str) -> apsw.Connection:
    db = apsw.Connection(db_path)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def create_schema(db: apsw.Connection) -> None:
    # crop/concept_type are real METADATA columns (no `+`) -- confirmed directly
    # (empirical test, not assumed from docs) that ONLY these support WHERE filtering
    # combined with a KNN MATCH query; `+`-prefixed AUXILIARY columns are storage-only
    # and are silently unfilterable in a KNN query (real error hit and fixed: "A LIMIT
    # or 'k = ?' constraint is required" was the symptom of trying to filter on an aux
    # column at all, not just a missing LIMIT). Everything else here doesn't need
    # DB-side filtering (source_type is a post-query boost, never a filter -- see
    # module docstring) so stays auxiliary, cheaper to store that way.
    db.cursor().execute(f"""
        create virtual table if not exists chunks using vec0(
            embedding int8[{EMBED_DIM}],
            crop text,
            concept_type text,
            +chunk_id text,
            +concept_id text,
            +concept_title text,
            +heading text,
            +text text,
            +trust_tier text,
            +source_type text,
            +label_id text,
            +is_visual integer
        )
    """)


def insert_chunk(db: apsw.Connection, chunk: Chunk, embedding_f32_bytes: bytes) -> None:
    db.cursor().execute(
        """
        insert into chunks(
            chunk_id, concept_id, concept_title, concept_type, heading, text,
            trust_tier, source_type, crop, label_id, is_visual, embedding
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, vec_quantize_int8(?, 'unit'))
        """,
        (
            chunk.chunk_id, chunk.concept_id, chunk.concept_title, chunk.concept_type,
            chunk.heading, chunk.text, chunk.trust_tier, chunk.source_type,
            # Real error hit and fixed: vec0 METADATA columns (unlike `+`-prefixed
            # auxiliary ones) reject NULL outright ("Expected text for TEXT metadata
            # column crop, received NULL") -- most chunks (entomology, pathology, most
            # guidelines) genuinely have no crop, so None has to become an empty-string
            # sentinel here, not a database NULL. knn_search()'s filter matches it back.
            chunk.crop or "",
            chunk.label_id, int(chunk.is_visual), embedding_f32_bytes,
        ),
    )


def knn_search(
    db: apsw.Connection,
    query_embedding_f32_bytes: bytes,
    top_k: int,
    crop: str | None = None,
    concept_types: set[str] | None = None,
) -> list[dict]:
    """Real SQL WHERE filtering combined with the MATCH KNN clause in one query --
    crop/concept_type are hard filters, decided in G1-G2-VECTORDB-PLAN.md Β§6.
    source_type is deliberately NOT a parameter here -- see module docstring."""
    # sqlite-vec KNN queries require an explicit `k = ?` constraint in the WHERE
    # clause -- confirmed directly, real error hit and fixed: neither a bare
    # `order by distance limit ?` nor a `+`-prefixed auxiliary-column filter (see
    # create_schema's comment) satisfies it. `crop`/`concept_type` real metadata-
    # column filters (also confirmed directly) combine into the same WHERE.
    where_parts = ["embedding match vec_quantize_int8(?, 'unit')", "k = ?"]
    params: list = [query_embedding_f32_bytes, top_k]
    if crop is not None:
        where_parts.append("(crop = '' or crop = ?)")
        params.append(crop)
    if concept_types:
        placeholders = ",".join("?" for _ in concept_types)
        where_parts.append(f"concept_type in ({placeholders})")
        params.extend(concept_types)

    sql = f"""
        select chunk_id, concept_id, concept_title, concept_type, heading, text,
               trust_tier, source_type, crop, label_id, is_visual, distance
        from chunks
        where {' and '.join(where_parts)}
        order by distance
    """
    cur = db.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.getdescription()]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def all_chunks(db: apsw.Connection) -> list[dict]:
    """Full scan -- used at BM25 build time (needs every chunk's text once) and by
    rag/ingest.py's incremental-append path (needs every existing concept_id to know
    what's already indexed, and every existing chunk's text to rebuild BM25 without
    re-embedding anything that hasn't changed)."""
    cur = db.cursor()
    cur.execute("""
        select chunk_id, concept_id, concept_title, concept_type, heading, text,
               trust_tier, source_type, crop, label_id, is_visual, rowid
        from chunks
    """)
    cols = [d[0] for d in cur.getdescription()]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def existing_concept_ids(db: apsw.Connection) -> set[str]:
    """Real distinct concept_ids already in the DB -- rag/ingest.py's append mode uses
    this to skip re-embedding/re-inserting anything already indexed."""
    cur = db.cursor()
    cur.execute("select distinct concept_id from chunks")
    return {row[0] for row in cur.fetchall()}


def delete_concept(db: apsw.Connection, concept_id: str) -> int:
    """Real DELETE by the `concept_id` auxiliary column -- confirmed working directly
    against a real vec0 table (2026-08-13, scratch-copy test, not assumed): unlike a
    KNN MATCH query, a plain DELETE has no restriction against filtering on a
    `+`-prefixed auxiliary column (that restriction, documented in create_schema()'s
    own comment, is specific to combining an aux-column filter with `MATCH ... k = ?`
    in the same query -- an ordinary DELETE isn't that). Used by rag/ingest.py's
    reingest mode to clear out a concept's old chunks before re-adding updated ones.
    Returns the number of rows deleted."""
    cur = db.cursor()
    cur.execute("select count(*) from chunks where concept_id = ?", (concept_id,))
    n = cur.fetchone()[0]
    with db:
        cur.execute("delete from chunks where concept_id = ?", (concept_id,))
    return n
