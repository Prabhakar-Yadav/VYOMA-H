"""
SQLite Exporter for Government Schemes Dataset

Converts enriched_schemes_dataset.jsonl into a compact SQLite database (schemes.db)
equipped with FTS5 (Full-Text Search 5) for ultra-fast zero-dependency keyword retrieval.

Usage:
    python export_to_sqlite.py
"""

import json
import os
import sqlite3

def export_jsonl_to_sqlite(jsonl_file="enriched_schemes_dataset.jsonl", db_file="schemes.db"):
    if not os.path.exists(jsonl_file):
        print(f"Error: {jsonl_file} not found!")
        return

    # Remove existing database file if present
    if os.path.exists(db_file):
        os.remove(db_file)

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Create main relational table
    cursor.execute("""
        CREATE TABLE schemes (
            scheme_id TEXT PRIMARY KEY,
            scheme_name TEXT NOT NULL,
            category TEXT,
            target_beneficiary TEXT,
            benefit_details TEXT,
            eligibility_criteria TEXT,
            how_to_apply TEXT,
            documents_required TEXT,
            searchable_text TEXT
        )
    """)

    # Create FTS5 virtual table for full-text search
    cursor.execute("""
        CREATE VIRTUAL TABLE schemes_fts USING fts5(
            scheme_id UNINDEXED,
            scheme_name,
            category,
            benefit_details,
            searchable_text
        )
    """)

    count = 0
    with open(jsonl_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line.strip())
            
            s_id = data.get("scheme_id", "")
            name = data.get("scheme_name", "")
            cat = data.get("category", "")
            beneficiary = data.get("target_beneficiary", "")
            benefits = data.get("benefit_details", "")
            eligibility = data.get("eligibility_criteria", "")
            apply_info = data.get("how_to_apply", "")
            docs = data.get("documents_required", "")
            search_text = data.get("searchable_text", f"{name} {benefits}")

            cursor.execute("""
                INSERT INTO schemes (scheme_id, scheme_name, category, target_beneficiary, benefit_details, eligibility_criteria, how_to_apply, documents_required, searchable_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (s_id, name, cat, beneficiary, benefits, eligibility, apply_info, docs, search_text))

            cursor.execute("""
                INSERT INTO schemes_fts (scheme_id, scheme_name, category, benefit_details, searchable_text)
                VALUES (?, ?, ?, ?, ?)
            """, (s_id, name, cat, benefits, search_text))

            count += 1

    conn.commit()
    conn.close()

    db_size = os.path.getsize(db_file) / (1024 * 1024)
    print(f"Successfully exported {count} schemes to SQLite database: {db_file}")
    print(f"Database file size: {db_size:.2f} MB")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    export_jsonl_to_sqlite()
