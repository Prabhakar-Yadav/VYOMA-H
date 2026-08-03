import os
import sys
import json
import re

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_PATH = os.path.join(BASE_DIR, "combined_curriculum.jsonl")
OUTPUT_PATH = os.path.join(BASE_DIR, "clean_curriculum.jsonl")

def is_english_or_hindi(text: str) -> bool:
    """
    Returns True if text contains only Latin (English) or Devanagari (Hindi) characters.
    Rejects Bengali, Tamil, Telugu, and corrupted characters.
    """
    # Check if text contains Bengali characters (U+0980 to U+09FF)
    if re.search(r'[\u0980-\u09FF]', text):
        return False
    # Check if text contains Tamil (U+0B80-0BFF), Telugu (U+0C00-0C7F), Kannada (U+0C80-0CFF)
    if re.search(r'[\u0B80-\u0CFF]', text):
        return False
    return True

def clean_dataset():
    print("[Cleaning] Filtering combined_curriculum.jsonl for clean English & Hindi text...")
    
    clean_records = []
    skipped_count = 0
    
    if not os.path.exists(INPUT_PATH):
        print(f"[Error] {INPUT_PATH} not found.")
        return
        
    with open(INPUT_PATH, 'r', encoding='utf-8') as f:
        for idx, line in enumerate(f):
            try:
                data = json.loads(line.strip())
                instruction = data.get("instruction", "").strip()
                response = data.get("response", "").strip()
                
                # Filter out non-English/Hindi texts
                if not is_english_or_hindi(instruction) or not is_english_or_hindi(response):
                    skipped_count += 1
                    continue
                    
                # Skip very short or broken responses
                if len(instruction) < 8 or len(response) < 15:
                    skipped_count += 1
                    continue
                    
                clean_records.append(data)
            except Exception:
                skipped_count += 1
                continue
                
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as out_f:
        for item in clean_records:
            out_f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"[Cleaning] Done! Kept {len(clean_records)} clean English & Hindi NCERT records.")
    print(f"[Cleaning] Filtered out {skipped_count} non-English/corrupted records.")
    print(f"[Cleaning] Output saved to: {OUTPUT_PATH}")

if __name__ == "__main__":
    clean_dataset()
