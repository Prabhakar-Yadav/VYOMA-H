import json
import os
import sys

# Colloquial tags mapped to scheme IDs.
# These are the casual English words that Bhashini NMT typically produces
# when translating farmer speech from Hindi/Telugu/etc.
COLLOQUIAL_TAGS = {
    "SCHEME_001": [  # PM-KISAN
        "2000 rupees", "money not received", "bank account", "installment",
        "kist", "6000 per year", "cash transfer", "account balance",
        "direct transfer", "money for farmer", "government money"
    ],
    "SCHEME_002": [  # PMFBY (Crop Insurance)
        "dried up", "yellow disease", "insects", "bugs", "pest attack",
        "drought", "no rain", "crop loss", "withered", "compensation",
        "claim", "flooded field", "ruined crop", "crop destroyed",
        "hailstorm damage", "heavy rain damage", "worm attack",
        "fungus on crop", "rotting crop", "standing crop damaged"
    ],
    "SCHEME_003": [  # KCC
        "loan", "credit card", "borrow money", "interest rate",
        "bank loan", "debt", "need money for seeds", "fertilizer loan",
        "cheap loan", "4 percent interest", "crop loan"
    ],
    "SCHEME_004": [  # PMKSY (Irrigation)
        "water problem", "tube well", "borewell", "drip irrigation",
        "sprinkler", "motor pump", "irrigation", "dry field",
        "no water in field", "water shortage", "pipeline for water"
    ],
    "SCHEME_005": [  # Soil Health Card
        "soil test", "fertilizer recommendation", "which fertilizer",
        "urea", "DAP", "soil health", "yield low", "barren land",
        "soil nutrients", "poor soil", "soil report"
    ],
    "SCHEME_006": [  # PM-KMY (Pension)
        "old age pension", "retirement money", "monthly pension",
        "pension for farmer", "3000 per month", "after 60 years"
    ],
    "SCHEME_007": [  # PM-KUSUM (Solar)
        "solar pump", "electricity problem", "power cut",
        "solar panel", "off grid", "sell electricity",
        "free electricity", "no electricity in field", "diesel pump replace"
    ],
    "SCHEME_008": [  # e-NAM
        "sell crop online", "mandi price", "best price for crop",
        "where to sell crop", "market rate", "fair price",
        "crop selling", "online mandi"
    ],
    "SCHEME_009": [  # SMAM (Machinery)
        "tractor subsidy", "harvester", "rotavator", "power tiller",
        "farm machine", "equipment subsidy", "hire machine",
        "rent tractor", "buy tractor cheap"
    ],
    "SCHEME_010": [  # PKVY (Organic)
        "organic farming", "no chemical", "natural farming",
        "cow dung manure", "vermicompost", "organic certificate",
        "chemical free farming"
    ],
    "SCHEME_011": [  # MGNREGA
        "100 days work", "wage employment", "job card",
        "daily wage", "digging work", "pond construction",
        "road work", "rural employment", "need work"
    ],
    "SCHEME_012": [  # PMFME (Food Processing)
        "food processing", "pickle making", "jaggery",
        "spice grinding", "milling unit", "small factory",
        "value addition", "food business"
    ],
    "SCHEME_013": [  # AIF (Infrastructure)
        "cold storage", "warehouse", "godown", "sorting grading",
        "post harvest", "storage facility", "store crop"
    ],
    "SCHEME_015": [  # PMMSY (Fisheries)
        "fish farming", "fish pond", "boat subsidy", "fishing net",
        "aquaculture", "fish hatchery", "cage culture"
    ],
    "SCHEME_016": [  # NAIS (Insurance)
        "crop insurance", "natural calamity", "hailstorm", "cyclone",
        "crop destroyed", "insurance claim", "premium subsidy"
    ],
    "SCHEME_022": [  # National Livestock Mission
        "goat farming", "poultry farming", "chicken", "pig farming",
        "sheep farming", "meat", "egg production", "animal subsidy"
    ],
    "SCHEME_023": [  # PMAY-G (Housing)
        "house construction", "pucca house", "new house",
        "kutcha house", "housing money", "build house",
        "roof leaking", "no house"
    ],
    "SCHEME_024": [  # DEDS (Dairy)
        "cow", "buffalo", "milk production", "dairy farm",
        "milking machine", "cattle subsidy", "milk business",
        "start dairy", "buy cow"
    ],
    "SCHEME_025": [  # Rashtriya Gokul Mission
        "desi cow breed", "indigenous cattle", "artificial insemination",
        "breed improvement", "cow breed", "better milk yield"
    ],
    "SCHEME_026": [  # NBHM (Beekeeping)
        "beekeeping", "honey production", "bee box", "bee colony",
        "honey business", "apiculture"
    ],
    "SCHEME_027": [  # PMUY (Ujjwala)
        "gas cylinder", "cooking gas", "LPG connection",
        "free gas", "smoke free kitchen", "chulha replacement"
    ],
    "SCHEME_028": [  # JJM (Water)
        "drinking water", "tap connection", "piped water",
        "clean water", "water at home", "no drinking water"
    ],
    "SCHEME_029": [  # Samagra Shiksha
        "school education", "free textbooks", "uniform",
        "mid day meal", "children education", "rural school"
    ],
    "SCHEME_030": [  # PM-JAY (Health)
        "free hospital", "cashless treatment", "health card",
        "ayushman card", "surgery", "medical treatment",
        "hospital bill", "free medicine"
    ],
    "SCHEME_032": [  # PMGKAY (Food)
        "free ration", "free rice", "free wheat", "food grains",
        "ration card", "fair price shop"
    ],
    "SCHEME_033": [  # PMJDY (Bank Account)
        "bank account", "zero balance account", "no bank account",
        "open account", "debit card", "accident insurance"
    ],
}

# Generic category-level tags that get added based on the scheme's category field
CATEGORY_TAGS = {
    "insurance": ["claim", "loss", "compensation", "damage", "premium", "cover"],
    "livestock": ["animal", "cow", "buffalo", "cattle", "veterinary", "pashu"],
    "dairy": ["animal", "cow", "buffalo", "cattle", "milk", "dudh"],
    "financial": ["money", "rupees", "account", "bank", "payment", "paisa"],
    "pension": ["old age", "retirement", "monthly money", "senior citizen"],
    "employment": ["job", "work", "rojgar", "daily wage", "training"],
    "energy": ["electricity", "bijli", "solar", "power", "pump"],
    "fisheries": ["fish", "machli", "pond", "talaab", "boat", "fishing"],
    "irrigation": ["water", "paani", "sinchai", "pump", "borewell"],
    "education": ["school", "padhai", "children", "books", "scholarship"],
    "health": ["hospital", "doctor", "treatment", "medicine", "ilaaj"],
    "housing": ["house", "ghar", "makaan", "roof", "construction"],
    "food": ["ration", "rice", "wheat", "grain", "food", "khaana"],
}


def enrich_dataset(input_file="schemes_dataset.jsonl", output_file="enriched_schemes_dataset.jsonl"):
    if not os.path.exists(input_file):
        print(f"Error: '{input_file}' not found in current directory!")
        print(f"Current directory: {os.getcwd()}")
        return

    enriched_count = 0
    total_count = 0

    with open(input_file, 'r', encoding='utf-8') as infile, \
         open(output_file, 'w', encoding='utf-8') as outfile:

        for line in infile:
            if not line.strip():
                continue
            total_count += 1
            scheme = json.loads(line.strip())

            # Build base searchable text from existing fields
            base_text = " ".join([
                scheme.get("scheme_name", ""),
                scheme.get("target_beneficiary", ""),
                scheme.get("benefit_details", ""),
                scheme.get("eligibility_criteria", ""),
                scheme.get("how_to_apply", ""),
                scheme.get("documents_required", ""),
                scheme.get("category", ""),
            ])

            # Inject scheme-specific colloquial tags
            scheme_id = scheme.get("scheme_id", "")
            injected_tags = list(COLLOQUIAL_TAGS.get(scheme_id, []))

            # Inject generic category-based tags
            category = scheme.get("category", "").lower()
            for cat_keyword, cat_tags in CATEGORY_TAGS.items():
                if cat_keyword in category:
                    injected_tags.extend(cat_tags)

            # Remove duplicates
            injected_tags = list(set(injected_tags))

            # Store enriched searchable text as a new field with Name Priming Boost
            scheme_name = scheme.get("scheme_name", "")
            name_boost = f"{scheme_name} {scheme_id} " * 3
            tags_string = " ".join(injected_tags)
            scheme["searchable_text"] = f"{name_boost} {base_text} {tags_string}".strip()

            if injected_tags:
                enriched_count += 1

            outfile.write(json.dumps(scheme, ensure_ascii=False) + "\n")

    print(f"Done! Processed {total_count} schemes.")
    print(f"Injected colloquial tags into {enriched_count} schemes.")
    print(f"Saved enriched dataset to: {output_file}")
    print(f"\nNext step: Update government_schemes_rag.py to load '{output_file}' instead of '{input_file}'")


if __name__ == "__main__":
    # Run from the same directory as schemes_dataset.jsonl
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    enrich_dataset()
