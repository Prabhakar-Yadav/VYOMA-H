import re
from typing import Dict, List

# ---------------------------------------------------------------------------
# Tuning Constants
# ---------------------------------------------------------------------------
SIMILARITY_THRESHOLD = 0.55
FALLBACK_COSINE_THRESHOLD = 0.35
FALLBACK_BM25_THRESHOLD = 3.0
ACRONYM_BOOST_MULTIPLIER = 2.5
CATEGORY_SOFT_BOOST = 1.2
MAX_LCD_CHARS = 350
RRF_K = 60

# ---------------------------------------------------------------------------
# Vocab & Dictionaries (from enrich_dataset.py)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Vocab & Dictionaries (from government_schemes_rag.py)
# ---------------------------------------------------------------------------
SYNONYM_MAP: Dict[str, List[str]] = {
    "water": ["irrigation", "pmksy", "jal jeevan", "pump", "boring", "tubewell"],
    "drinking water": ["jal jeevan", "tap connection", "pipeline"],
    "money": ["subsidy", "financial assistance", "installment", "pension"],
    "loan": ["credit", "kcc", "subvention", "debt"],
    "electricity": ["solar", "kusum", "power", "grid", "ddugjy"],
    "sunlight": ["solar", "kusum", "energy"],
    "damage": ["loss", "compensation", "insurance", "pmfby", "calamity", "yellow disease"],
    "insects": ["pesticide", "protection", "crop damage", "pest attack"],
    "drought": ["pmfby", "fasal bima", "crop loss", "compensation"],
    "flood": ["pmfby", "fasal bima", "crop loss", "compensation"],
    "claim": ["pmfby", "insurance", "compensation", "settlement"],
    "six thousand": ["6000", "pm-kisan", "pmkisan", "samman nidhi"],
    "two thousand": ["2000", "pm-kisan", "pmkisan", "samman nidhi"],
    "three thousand": ["3000", "pm-kmy", "maandhan", "pension"],
    "tractor": ["smam", "machinery", "mechanization", "harvester"],
    "cow": ["dairy", "deds", "gokul", "cattle", "bovine"],
    "buffalo": ["dairy", "deds", "cattle", "bovine"],
    "milk": ["dairy", "deds", "cattle", "milking"],
    "goat": ["livestock", "nlm", "sheep", "small ruminant"],
    "house": ["housing", "pmay", "awas", "construction", "pucca"],
    "gas": ["lpg", "ujjwala", "pmuy", "cylinder", "cooking"],
    "hospital": ["ayushman", "pm-jay", "health", "treatment", "cashless"],
    "land": ["property", "svamitva", "title deed", "property card", "patta"],
    "organic": ["natural farming", "nmnf", "pkvy", "chemical free", "cow dung"],
}

# Full semantic map for FAISS vector expansion
SCHEME_ACRONYM_MAP: Dict[str, str] = {
    "kcc": "Kisan Credit Card Scheme low interest loan",
    "kusum": "PM KUSUM Pradhan Mantri Kisan Urja Suraksha solar pump",
    "pmfby": "Pradhan Mantri Fasal Bima Yojana crop insurance compensation yellow disease damage",
    "pm-kisan": "PM KISAN Pradhan Mantri Kisan Samman Nidhi 6000 installment",
    "pmkisan": "PM KISAN Pradhan Mantri Kisan Samman Nidhi 6000 installment",
    "nais": "National Agriculture Insurance Scheme crop loss natural calamity",
    "acabc": "Agri Clinics Agri Business Centres agriculture graduate startup",
    "svamitva": "SVAMITVA village property card drone survey title deed",
    "nlm": "National Livestock Mission sheep goat poultry piggery fodder subsidy",
    "pmay": "Pradhan Mantri Awaas Yojana Gramin rural housing pucca house",
    "deds": "Dairy Entrepreneurship Development Scheme cow buffalo milk subsidy NABARD",
    "rgm": "Rashtriya Gokul Mission indigenous cattle breed improvement AI",
    "pmuy": "Pradhan Mantri Ujjwala Yojana LPG gas cylinder cooking",
    "jjm": "Jal Jeevan Mission drinking water tap connection rural household",
    "ayushman": "Ayushman Bharat PM-JAY health insurance cashless hospitalization 500000",
    "soil health card": "Soil Health Card Scheme mitti soil testing fertilizer khad",
    "soil health": "Soil Health Card Scheme mitti soil testing fertilizer khad",
    "shc": "Soil Health Card Scheme mitti soil testing fertilizer khad",
    "jan dhan": "Pradhan Mantri Jan Dhan Yojana PMJDY bank account zero balance",
    "pmjdy": "Pradhan Mantri Jan Dhan Yojana PMJDY bank account zero balance",
}

# Canonical names for BM25 exact match without dilution
SCHEME_CANONICAL_NAMES: Dict[str, str] = {
    "kcc": "Kisan Credit Card Scheme",
    "kusum": "PM KUSUM Pradhan Mantri Kisan Urja Suraksha",
    "pmfby": "Pradhan Mantri Fasal Bima Yojana",
    "pm-kisan": "PM KISAN Pradhan Mantri Kisan Samman Nidhi",
    "pmkisan": "PM KISAN Pradhan Mantri Kisan Samman Nidhi",
    "nais": "National Agriculture Insurance Scheme",
    "acabc": "Agri Clinics Agri Business Centres",
    "svamitva": "SVAMITVA",
    "nlm": "National Livestock Mission",
    "pmay": "Pradhan Mantri Awaas Yojana Gramin",
    "deds": "Dairy Entrepreneurship Development Scheme",
    "rgm": "Rashtriya Gokul Mission",
    "pmuy": "Pradhan Mantri Ujjwala Yojana LPG",
    "jjm": "Jal Jeevan Mission",
    "ayushman": "Ayushman Bharat PM-JAY",
    "soil health card": "Soil Health Card Scheme",
    "soil health": "Soil Health Card Scheme",
    "shc": "Soil Health Card Scheme",
    "jan dhan": "Pradhan Mantri Jan Dhan Yojana PMJDY",
    "pmjdy": "Pradhan Mantri Jan Dhan Yojana PMJDY",
}

OUT_OF_DOMAIN_KEYWORDS = [
    "car", "electric car", "ev", "vehicle", "scooter",
    "space", "rocket", "delhi metro",
    "laptop", "iphone", "mobile phone",
    "cricket", "movie",
    "bitcoin", "share market", "stock market"
]

OUT_OF_DOMAIN_PATTERN = re.compile(
    r"\b(" + "|".join(OUT_OF_DOMAIN_KEYWORDS) + r")\b", re.IGNORECASE
)

INTENT_PATTERNS = {
    "documents_required": re.compile(
        r"\b(document|documents|doc|paper|papers|proof|certificate|khasra|patta|need|require|requirement)\b",
        re.IGNORECASE,
    ),
    "how_to_apply": re.compile(
        r"\b(apply|where|how|portal|register|enroll|procedure|process)\b",
        re.IGNORECASE,
    ),
    "eligibility_criteria": re.compile(
        r"\b(eligible|eligibility|who|criteria|qualification|age|land)\b",
        re.IGNORECASE,
    ),
    "benefit_details": re.compile(
        r"\b(benefit|benefits|amount|subsidy|rupees|money|pension|installment)\b",
        re.IGNORECASE,
    ),
}
