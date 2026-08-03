import os
import sys
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLEAN_PATH = os.path.join(BASE_DIR, "clean_curriculum.jsonl")

FIXED_CONCEPTS = [
    {
        "instruction": "How to treat dehydration using oral rehydration salts?",
        "input": "",
        "response": "Dehydration caused by severe diarrhea or vomiting can be treated using Oral Rehydration Solution (ORS). ORS is prepared by mixing a packet of ORS powder (or 6 teaspoons of sugar and half teaspoon of salt) in 1 liter of clean boiled drinking water to restore body fluid and electrolyte balance.",
        "source": "NCERT Class 7 Science Chapter 2",
        "subject": "Health & Sanitation",
        "grade": "Class 7"
    },
    {
        "instruction": "What is the importance of reading and writing for farmers?",
        "input": "",
        "response": "Basic reading and writing skills empower farmers to read fertilizer and pesticide safety labels, calculate crop production costs, verify bank loan contracts, and check fair market prices for their harvest without depending on middlemen.",
        "source": "NCERT General Rural Education",
        "subject": "Basic Literacy",
        "grade": "General Literacy"
    },
    {
        "instruction": "How does digital literacy help farmers check market prices?",
        "input": "",
        "response": "Digital literacy allows farmers to use smartphones and government portals like e-NAM (National Agriculture Market) to check live crop mandis prices, weather forecasts, and direct benefit transfer (DBT) scheme payouts directly on their phones.",
        "source": "NCERT Social Science",
        "subject": "Basic Literacy",
        "grade": "Class 8"
    },
    {
        "instruction": "How to prevent mosquito breeding and malaria?",
        "input": "",
        "response": "Prevent mosquito breeding by eliminating stagnant water in old tires, coolers, and pots around homes. Spraying larvicides in drains, introducing Gambusia fish in ponds, and sleeping under insecticide-treated bed nets effectively prevents vector-borne diseases like malaria and dengue.",
        "source": "NCERT Class 8 Science Chapter 2",
        "subject": "Health & Sanitation",
        "grade": "Class 8"
    },
    {
        "instruction": "Why is personal hygiene necessary in rural areas?",
        "input": "",
        "response": "Personal hygiene—including regular bathing, washing hands with soap before meals and after using toilets, and wearing clean clothes—prevents bacterial and parasitic infections, reducing disease transmission in rural communities.",
        "source": "NCERT Health & Sanitation",
        "subject": "Health & Sanitation",
        "grade": "General Literacy"
    }
]

def apply_fixes():
    print("[Fix Script] Injecting missing NCERT concepts into clean_curriculum.jsonl...")
    
    existing = []
    if os.path.exists(CLEAN_PATH):
        with open(CLEAN_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        existing.append(json.loads(line.strip()))
                    except Exception:
                        continue
                        
    combined = FIXED_CONCEPTS + existing
    
    with open(CLEAN_PATH, 'w', encoding='utf-8') as out_f:
        for item in combined:
            out_f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"[Fix Script] Total records in clean_curriculum.jsonl: {len(combined)}")

if __name__ == "__main__":
    apply_fixes()
