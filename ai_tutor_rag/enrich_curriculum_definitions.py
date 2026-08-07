import os
import sys
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLEAN_PATH = os.path.join(BASE_DIR, "clean_curriculum.jsonl")

# High-precision NCERT definitions to enrich the dataset
ENRICHED_CONCEPTS = [
    {
        "instruction": "What is photosynthesis and why is chlorophyll important?",
        "input": "",
        "response": "Photosynthesis is the fundamental biological process by which green plants synthesize carbohydrates (food) from carbon dioxide and water in the presence of sunlight. Chlorophyll is the green pigment located inside plant chloroplasts that traps solar energy from sunlight and converts it into chemical energy, enabling plants to release fresh oxygen gas.",
        "source": "NCERT Class 7 Science Chapter 1",
        "subject": "Science",
        "grade": "Class 7"
    },
    {
        "instruction": "What are the three states of matter and their properties?",
        "input": "",
        "response": "The three fundamental states of matter are Solids, Liquids, and Gases. Solids have a definite shape and fixed volume with tightly packed particles. Liquids have a fixed volume but take the shape of their container with loosely packed particles. Gases have no fixed shape or volume, and their particles move freely with high kinetic energy.",
        "source": "NCERT Class 6 Science Chapter 4",
        "subject": "Science",
        "grade": "Class 6"
    },
    {
        "instruction": "Why do stars twinkle in the night sky?",
        "input": "",
        "response": "Stars twinkle due to atmospheric refraction of starlight. As light from a distant star travels through different layers of Earth's atmosphere with varying optical densities and temperatures, the light bends continuously. This causes the apparent position and brightness of the star to fluctuate rapidly, creating the twinkling effect.",
        "source": "NCERT Class 10 Science Chapter 11",
        "subject": "Science",
        "grade": "Class 8"
    },
    {
        "instruction": "Why should we wash hands with soap before eating?",
        "input": "",
        "response": "Washing hands with soap and clean water removes disease-causing germs, bacteria, and viruses from skin surfaces. Soap molecules break down the fatty outer membrane of micro-organisms, washing them away and preventing waterborne and gastrointestinal infections like cholera and diarrhea.",
        "source": "NCERT General Hygiene",
        "subject": "Health & Sanitation",
        "grade": "General Literacy"
    }
]

def enrich_dataset():
    print("[Enrichment] Adding high-precision NCERT definitions to clean_curriculum.jsonl...")
    
    existing = []
    if os.path.exists(CLEAN_PATH):
        with open(CLEAN_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        existing.append(json.loads(line.strip()))
                    except Exception:
                        continue
                        
    # Prepend enriched concepts to ensure priority matching
    combined = ENRICHED_CONCEPTS + existing
    
    with open(CLEAN_PATH, 'w', encoding='utf-8') as out_f:
        for item in combined:
            out_f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"[Enrichment] Total records in clean_curriculum.jsonl: {len(combined)}")

if __name__ == "__main__":
    enrich_dataset()
