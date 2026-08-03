import os
import sys
import json
import time
import sqlite3
from typing import List, Dict, Any, Optional

# Set UTF-8 encoding for Windows terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class TencentAgentMemoryHub:
    """
    Implementation of TencentDB-Agent-Memory Hub for AI Agents.
    Organizes agent memory into 4 Core Memory Assets:
    1. LLM-Wiki Asset: Structured Knowledge & Scheme Records (Stored in local SQLite)
    2. Chat Memory Asset: Farmer Context (Location, Land Size, Crop Type)
    3. Skill Asset: Executable Calculations & Verification Routines
    4. Code-Graph Asset: Intent Routing & Component Connections
    """
    def __init__(self, db_file: str = "tencent_agent_memory.db"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.db_path = os.path.join(base_dir, db_file)
        self._init_sqlite_tables()
        
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite_tables(self):
        """Initializes TencentDB Agent Memory Asset Tables in local SQLite (100% Offline)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # 1. LLM-Wiki Memory Asset Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS llm_wiki_assets (
                asset_id TEXT PRIMARY KEY,
                query_category TEXT,
                farmer_question TEXT,
                scheme_name TEXT,
                target_beneficiary TEXT,
                benefit_details TEXT,
                eligibility_criteria TEXT,
                how_to_apply TEXT,
                documents_required TEXT
            )
        """)
        
        # 2. Chat Memory Asset Table (Farmer Profile & Session Context)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_memory_assets (
                session_id TEXT PRIMARY KEY,
                farmer_name TEXT,
                district TEXT,
                state TEXT,
                land_size_hectares REAL,
                primary_crop TEXT,
                last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 3. Skill Asset Table (Executable Tools)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS skill_assets (
                skill_name TEXT PRIMARY KEY,
                skill_type TEXT,
                description TEXT,
                parameters TEXT
            )
        """)
        
        conn.commit()
        conn.close()
        print(f"[TencentDB Agent Memory] Initialized local SQLite Memory Hub at {self.db_path}")

    def ingest_llm_wiki_asset(self, jsonl_file: str = "raw_schemes_dataset_50.jsonl") -> int:
        """Ingests raw JSONL farmer Q&A dataset into LLM-Wiki Memory Asset."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(base_dir, jsonl_file)
        
        if not os.path.exists(file_path):
            print(f"[Error] Dataset file not found: {file_path}")
            return 0
            
        conn = self._get_connection()
        cursor = conn.cursor()
        count = 0
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for idx, line in enumerate(f):
                if line.strip():
                    data = json.loads(line.strip())
                    asset_id = f"WIKI_{idx+1:03d}"
                    cursor.execute("""
                        INSERT OR REPLACE INTO llm_wiki_assets (
                            asset_id, query_category, farmer_question, scheme_name,
                            target_beneficiary, benefit_details, eligibility_criteria,
                            how_to_apply, documents_required
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        asset_id,
                        data.get("query_category", "General"),
                        data.get("farmer_question", ""),
                        data.get("scheme_name", ""),
                        data.get("target_beneficiary", ""),
                        data.get("benefit_details", ""),
                        data.get("eligibility_criteria", ""),
                        data.get("how_to_apply", ""),
                        data.get("documents_required", "")
                    ))
                    count += 1
                    
        conn.commit()
        conn.close()
        print(f"[TencentDB Agent Memory] Ingested {count} items into LLM-Wiki Asset!")
        return count

    def set_farmer_chat_memory(self, session_id: str, name: str, district: str, state: str, land_ha: float, crop: str):
        """Updates Chat Memory Asset with farmer persona context."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO chat_memory_assets (
                session_id, farmer_name, district, state, land_size_hectares, primary_crop
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, name, district, state, land_ha, crop))
        conn.commit()
        conn.close()

    def query_memory_hub(self, user_question: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Queries LLM-Wiki Asset using fast SQLite FTS / keyword search combined with Chat Memory context."""
        start_time = time.time()
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Retrieve Chat Memory context if session provided
        farmer_context = None
        if session_id:
            cursor.execute("SELECT * FROM chat_memory_assets WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if row:
                farmer_context = dict(row)
                
        # Query LLM-Wiki Memory Assets
        tokens = [t.lower() for t in user_question.split() if len(t) > 3]
        results = []
        
        cursor.execute("SELECT * FROM llm_wiki_assets")
        all_wiki = [dict(r) for r in cursor.fetchall()]
        
        scored_wiki = []
        for wiki in all_wiki:
            text = f"{wiki['farmer_question']} {wiki['scheme_name']} {wiki['benefit_details']} {wiki['how_to_apply']} {wiki['documents_required']}".lower()
            score = sum(1 for t in tokens if t in text)
            if score > 0:
                scored_wiki.append((score, wiki))
                
        scored_wiki.sort(key=lambda x: x[0], reverse=True)
        
        latency = time.time() - start_time
        
        if not scored_wiki:
            conn.close()
            return {
                "status": "fallback",
                "question": user_question,
                "farmer_context": farmer_context,
                "voice_text": "Kisan bhai! Aapka sawal kripya spast roop se dobara poochein.",
                "latency_ms": round(latency * 1000, 2)
            }
            
        best_match = scored_wiki[0][1]
        conn.close()
        
        # Check farmer land size eligibility if Chat Memory context exists
        eligibility_warning = ""
        if farmer_context and farmer_context.get("land_size_hectares"):
            land = farmer_context["land_size_hectares"]
            if "up to 2 hectares" in best_match["eligibility_criteria"].lower() and land > 2.0:
                eligibility_warning = f" (Note: Your registered land size of {land} ha exceeds the 2.0 ha limit for this scheme)."

        return {
            "status": "success",
            "question": user_question,
            "farmer_context": farmer_context,
            "matched_asset_id": best_match["asset_id"],
            "query_category": best_match["query_category"],
            "scheme_name": best_match["scheme_name"],
            "benefit_details": best_match["benefit_details"],
            "how_to_apply": best_match["how_to_apply"] + eligibility_warning,
            "documents_required": best_match["documents_required"],
            "lcd_text": f"=== SCHEME: {best_match['scheme_name'][:25]} ===\nCategory: {best_match['query_category']}\nApply: {best_match['how_to_apply'][:35]}",
            "voice_text": f"Kisan bhai! {best_match['scheme_name']} ke taht: {best_match['benefit_details']} Avedan karne ke liye {best_match['how_to_apply']}.",
            "latency_ms": round(latency * 1000, 2)
        }


if __name__ == "__main__":
    memory_hub = TencentAgentMemoryHub()
    memory_hub.ingest_llm_wiki_asset("raw_schemes_dataset_50.jsonl")
    
    # Set sample Chat Memory for Farmer Ram Singh
    memory_hub.set_farmer_chat_memory(
        session_id="SESS_001",
        name="Ram Singh",
        district="Patna",
        state="Bihar",
        land_ha=1.5,
        crop="Paddy"
    )
    
    test_questions = [
        "How do I check if my name is on the list to receive the ₹6,000 yearly income support?",
        "How much premium do I have to pay out of my own pocket to insure one acre under PMFBY?",
        "What financial help can I get to install a drip or sprinkler irrigation system?",
        "How can I get a subsidy to buy a solar water pump for irrigation?",
        "How can I get a 50 percent subsidy to start a goat or poultry livestock farming business?"
    ]
    
    for q in test_questions:
        res = memory_hub.query_memory_hub(q, session_id="SESS_001")
        print("=========================================================")
        print(f"QUERY: \"{res['question']}\"")
        print(f"STATUS: {res['status'].upper()}")
        if res["status"] == "success":
            print(f"FARMER: {res['farmer_context']['farmer_name']} ({res['farmer_context']['district']}, {res['farmer_context']['state']})")
            print(f"MATCHED ASSET: {res['matched_asset_id']} | CATEGORY: {res['query_category']}")
            print(f"SCHEME: {res['scheme_name']}")
            print(f"HOW TO APPLY: {res['how_to_apply']}")
            print(f"DOCUMENTS: {res['documents_required']}")
        print(f"LATENCY: {res['latency_ms']} ms")
        print("=========================================================\n")
