import os
import sys
import json
import re

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from datasets import load_dataset

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHIKSHAEDGE_PATH = os.path.join(BASE_DIR, "curriculum_dataset.jsonl")
CLEAN_PATH = os.path.join(BASE_DIR, "clean_curriculum.jsonl")

def is_clean_english_or_hindi(text: str) -> bool:
    """
    Returns True if text contains clean English or Hindi characters.
    Rejects Bengali, Tamil, Telugu, and corrupted characters.
    """
    if re.search(r'[\u0980-\u09FF]', text): # Bengali
        return False
    if re.search(r'[\u0B80-\u0CFF]', text): # South Indian scripts
        return False
    if any(c in text for c in ['\\', 'tkbye', 'osQ', 'gSa', 'foKku', 'vè;k;']):
        return False
    return True

def fetch_and_build_clean_dataset():
    print("[Dataset Build] Streaming K12 Indian Curriculum Dataset from HuggingFace...")
    
    ds = load_dataset(
        "FoundryAILabs/k12-indian-curriculum-4.9m",
        split="train",
        streaming=True
    )
    
    k12_records = []
    target_grades = {5, 6, 7, 8}
    scanned = 0
    
    for row in ds:
        scanned += 1
        if scanned % 10000 == 0:
            print(f"         Scanned {scanned} records, kept {len(k12_records)} clean records...")
            
        grade = row.get("grade")
        if grade not in target_grades:
            continue
            
        instruction = (row.get("instruction") or "").strip()
        output = (row.get("output") or "").strip()
        
        if len(instruction) < 15 or len(output) < 25:
            continue
            
        if not is_clean_english_or_hindi(instruction) or not is_clean_english_or_hindi(output):
            continue
            
        record = {
            "instruction": instruction,
            "input": "",
            "response": output,
            "source": "K12-Indian-Curriculum-4.9M",
            "subject": row.get("subject", "General"),
            "grade": f"Class {grade}"
        }
        k12_records.append(record)
        
        if len(k12_records) >= 5000:
            print(f"         Reached 5,000 clean English NCERT records. Stopping stream.")
            break
            
    # Read existing ShikshaEdge clean records
    shikshaedge_records = []
    if os.path.exists(SHIKSHAEDGE_PATH):
        with open(SHIKSHAEDGE_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        d = json.loads(line)
                        inst = d.get("instruction", "")
                        resp = d.get("response", "")
                        if is_clean_english_or_hindi(inst) and is_clean_english_or_hindi(resp):
                            shikshaedge_records.append(d)
                    except Exception:
                        continue
                        
    # Combine clean records
    all_clean = shikshaedge_records + k12_records
    
    with open(CLEAN_PATH, 'w', encoding='utf-8') as out_f:
        for item in all_clean:
            out_f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"\n=========================================================")
    print(f"DONE! Saved {len(all_clean)} clean English/Hindi records to clean_curriculum.jsonl")
    print(f"Breakdown: {len(shikshaedge_records)} ShikshaEdge + {len(k12_records)} K12 English")
    print(f"=========================================================\n")

if __name__ == "__main__":
    fetch_and_build_clean_dataset()
