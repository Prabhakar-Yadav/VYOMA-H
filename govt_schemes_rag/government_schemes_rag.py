import os
import sys
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import torch
torch.set_num_threads(2)

import json
import time
import re
import numpy as np
import faiss
from typing import List, Dict, Set, Any
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi

# Force UTF-8 encoding for Windows terminal compatibility
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def char_ngram_tokenizer(text: str, n_min: int = 3, n_max: int = 5) -> List[str]:
    """Generates sliding character n-grams (3-5 chars) for typo-resilient BM25 searching."""
    clean_text = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower())
    padded_text = f" {clean_text} "
    ngrams = []
    for n in range(n_min, n_max + 1):
        for i in range(len(padded_text) - n + 1):
            ngrams.append(padded_text[i:i + n])
    return ngrams


# English Synonym Map for RAG Expansion
SYNONYM_MAP: Dict[str, List[str]] = {
    # Water / Irrigation
    "water": ["irrigation", "pmksy", "jal jeevan", "pump", "boring", "tubewell"],
    "drinking water": ["jal jeevan", "tap connection", "pipeline"],
    # Financial / Loans
    "money": ["subsidy", "financial assistance", "installment", "pension"],
    "loan": ["credit", "kcc", "subvention", "debt"],
    # Energy / Solar
    "electricity": ["solar", "kusum", "power", "grid", "ddugjy"],
    "sunlight": ["solar", "kusum", "energy"],
    # Crop Damage & Insurance
    "damage": ["loss", "compensation", "insurance", "pmfby", "calamity"],
    "insects": ["pesticide", "protection", "crop damage"],
    "drought": ["pmfby", "fasal bima", "crop loss", "compensation"],
    "flood": ["pmfby", "fasal bima", "crop loss", "compensation"],
    "claim": ["pmfby", "insurance", "compensation", "settlement"],
    "time limit": ["pmfby", "duration", "timeline", "intimation"],
    # Financial Amounts
    "six thousand": ["6000", "pm-kisan", "pmkisan", "samman nidhi"],
    "two thousand": ["2000", "pm-kisan", "pmkisan", "samman nidhi"],
    "three thousand": ["3000", "pm-kmy", "maandhan", "pension"],
    # Farm Works
    "bunding": ["mgnrega", "earthwork", "employment", "wage"],
    "leveling": ["mgnrega", "earthwork", "land development", "employment"],
    # Mandi & Rates
    "market": ["e-nam", "enam", "mandi", "registration", "trade"],
    "selling": ["e-nam", "market", "trade", "enam"],
    "price": ["enam", "e-nam", "market rate", "bidding", "mandi"],
    # Machinery
    "tractor": ["smam", "machinery", "mechanization", "harvester"],
    # Dairy / Livestock
    "cow": ["dairy", "deds", "gokul", "cattle", "bovine"],
    "buffalo": ["dairy", "deds", "cattle", "bovine"],
    "milk": ["dairy", "deds", "cattle", "milking"],
    "goat": ["livestock", "nlm", "sheep", "small ruminant"],
    "sheep": ["livestock", "nlm", "goat", "wool"],
    "chicken": ["poultry", "livestock", "nlm", "egg"],
    "animal": ["livestock", "cattle", "dairy", "veterinary", "animal husbandry"],
    # Housing
    "house": ["housing", "pmay", "awas", "construction", "pucca"],
    # Beekeeping
    "bee": ["beekeeping", "honey", "nbhm", "apiculture", "bee colony"],
    "honey": ["beekeeping", "nbhm", "apiculture", "bee colony"],
    # Gas
    "gas": ["lpg", "ujjwala", "pmuy", "cylinder", "cooking"],
    "stove": ["lpg", "ujjwala", "cooking", "smoke free"],
    # Health
    "hospital": ["ayushman", "pm-jay", "health", "treatment", "cashless"],
    "treatment": ["ayushman", "pm-jay", "health", "hospitalization", "disease", "medicine"],
    # Education
    "school": ["education", "samagra shiksha", "scholarship", "uniform", "textbook"],
    # Land
    "land": ["property", "svamitva", "title deed", "property card", "patta"],
    # Organic
    "organic": ["natural farming", "nmnf", "pkvy", "chemical free", "cow dung"],
    # Coconut
    "coconut": ["palm", "cpis", "coconut insurance"],
}

SCHEME_ACRONYM_MAP: Dict[str, str] = {
    "kcc": "Kisan Credit Card Scheme low interest loan",
    "kusum": "PM KUSUM Pradhan Mantri Kisan Urja Suraksha solar pump",
    "pmfby": "Pradhan Mantri Fasal Bima Yojana crop insurance compensation",
    "pm-kisan": "PM KISAN Pradhan Mantri Kisan Samman Nidhi 6000 installment",
    "pmkisan": "PM KISAN Pradhan Mantri Kisan Samman Nidhi 6000 installment",
    "nais": "National Agriculture Insurance Scheme crop loss natural calamity",
    "nfsm": "National Food Security Nutrition Mission rice wheat pulses millets seed",
    "nmnf": "National Mission Natural Farming chemical free organic cow",
    "cpis": "Coconut Palm Insurance Scheme storm cyclone flood",
    "acabc": "Agri Clinics Agri Business Centres agriculture graduate startup",
    "svamitva": "SVAMITVA village property card drone survey title deed",
    "nlm": "National Livestock Mission sheep goat poultry piggery fodder subsidy",
    "pmay": "Pradhan Mantri Awaas Yojana Gramin rural housing pucca house",
    "pmay-g": "Pradhan Mantri Awaas Yojana Gramin rural housing pucca house",
    "deds": "Dairy Entrepreneurship Development Scheme cow buffalo milk subsidy NABARD",
    "rgm": "Rashtriya Gokul Mission indigenous cattle breed improvement AI",
    "gokul": "Rashtriya Gokul Mission indigenous cattle breed improvement bovine",
    "nbhm": "National Beekeeping Honey Mission bee colony apiculture",
    "pmuy": "Pradhan Mantri Ujjwala Yojana LPG gas cylinder cooking",
    "ujjwala": "Pradhan Mantri Ujjwala Yojana LPG gas cylinder deposit free",
    "jjm": "Jal Jeevan Mission drinking water tap connection rural household",
    "pm-jay": "Ayushman Bharat Pradhan Mantri Jan Arogya Yojana health insurance 5 lakh",
    "ayushman": "Ayushman Bharat PM-JAY health insurance cashless hospitalization 500000",
    "ddugjy": "Deen Dayal Upadhyaya Gram Jyoti Yojana rural electricity power",
    "pmgkay": "Pradhan Mantri Garib Kalyan Anna Yojana free food grains ration",
    "pmjdy": "Pradhan Mantri Jan Dhan Yojana unbanked savings account overdraft",
    "apy": "Atal Pension Yojana unorganized sector monthly pension retirement",
    "pmjjby": "Pradhan Mantri Jeevan Jyoti Bima Yojana life insurance 2 lakh",
    "pmsby": "Pradhan Mantri Suraksha Bima Yojana accident insurance 2 lakh",
    "nrlm": "Deendayal Antyodaya Yojana National Rural Livelihoods Mission SHG women",
    "day-nrlm": "Deendayal Antyodaya Yojana National Rural Livelihoods Mission SHG women",
    "pmmy": "Pradhan Mantri Mudra Yojana small business loan collateral free shishu kishore tarun",
    "ssy": "Sukanya Samriddhi Yojana girl child education marriage tax benefit",
    "vishwakarma": "PM Vishwakarma traditional artisan craftspeople training credit",
    "pm-vishwakarma": "PM Vishwakarma traditional artisan craftspeople training credit",
}

OUT_OF_DOMAIN_KEYWORDS = [
    "car", "electric car", "ev", "vehicle", "scooter", "space", "rocket",
    "delhi metro", "laptop", "iphone", "mobile phone", "cricket", "movie",
    "bitcoin", "share market", "stock market",
]


def expand_query(raw_query: str) -> str:
    # 1. First replace known multi-word phrases directly in the raw query
    query_lower = raw_query.lower()
    for phrase, expansions in SYNONYM_MAP.items():
        if " " in phrase and phrase in query_lower:
            raw_query += " " + " ".join(expansions)

    tokens = raw_query.lower().split()
    expanded_terms = set(tokens)
    
    for token in tokens:
        if token in SCHEME_ACRONYM_MAP:
            expanded_terms.add(SCHEME_ACRONYM_MAP[token])
        if token in SYNONYM_MAP and " " not in token:
            expanded_terms.update(SYNONYM_MAP[token])
            
    return " ".join(expanded_terms)


def load_schemes_dataset(jsonl_path: str) -> List[Dict[str, Any]]:
    schemes = []
    if not os.path.exists(jsonl_path):
        print(f"[Error] Dataset file not found: {jsonl_path}")
        return []
    
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line.strip())
                    s_id = data.get("scheme_id", "")
                    name = data.get("scheme_name", "")
                    beneficiary = data.get("target_beneficiary", "")
                    benefits = data.get("benefit_details", "")
                    eligibility = data.get("eligibility_criteria", "")
                    apply_info = data.get("how_to_apply", "")
                    docs = data.get("documents_required", "")
                    category = data.get("category", "Other")
                    cross_refs = data.get("cross_references", [])
                    
                    searchable_text = f"{name} {beneficiary} {benefits} {eligibility} {apply_info} {docs}"
                    
                    # Anti-Magnetism: Prevent cross-references from pulling in wrong queries (Prabhakar's fix)
                    # e.g., PMAY-G mentions 'Ujjwala', PMUY mentions 'PMAY'. We remove them from the index 
                    # while keeping them in the display text.
                    cross_ref_keywords = list(SCHEME_ACRONYM_MAP.keys()) + ["mgnrega", "sbm-g", "aay", "secc"] + cross_refs
                    for kw in cross_ref_keywords:
                        if kw.lower() not in name.lower():
                            # Remove the keyword as a whole word, case-insensitive
                            searchable_text = re.sub(rf"\b{kw}\b", "", searchable_text, flags=re.IGNORECASE)
                            
                    ngram_tokens = char_ngram_tokenizer(searchable_text)
                    
                    schemes.append({
                        "scheme_id": s_id,
                        "scheme_name": name,
                        "category": category,
                        "target_beneficiary": beneficiary,
                        "benefit_details": benefits,
                        "eligibility_criteria": eligibility,
                        "how_to_apply": apply_info,
                        "documents_required": docs,
                        "searchable_text": searchable_text,
                        "ngram_tokens": ngram_tokens
                    })
                except Exception:
                    continue
    return schemes


class SchemesFAISSVectorIndex:
    def __init__(self, schemes: List[Dict[str, Any]]):
        self.schemes = schemes
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.dimension = 384
        self.index = None
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cache_index_path = os.path.join(base_dir, "schemes_faiss_index.bin")
        
        if os.path.exists(self.cache_index_path):
            try:
                self.index = faiss.read_index(self.cache_index_path)
            except Exception:
                self._build_index()
        else:
            self._build_index()
            
    def _build_index(self):
        searchable_texts = [s["searchable_text"] for s in self.schemes]
        embeddings = self.model.encode(searchable_texts, show_progress_bar=False, batch_size=32)
        embeddings = np.array(embeddings, dtype='float32')
        faiss.normalize_L2(embeddings)
        
        self.index = faiss.IndexFlatIP(self.dimension)
        self.index.add(embeddings)
        faiss.write_index(self.index, self.cache_index_path)

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_embedding = self.model.encode([query])
        query_embedding = np.array(query_embedding, dtype='float32')
        faiss.normalize_L2(query_embedding)
        
        distances, indices = self.index.search(query_embedding, top_k)
        results = []
        for i, idx in enumerate(indices[0]):
            if idx < len(self.schemes):
                results.append({
                    "scheme_id": self.schemes[idx]["scheme_id"],
                    "rank": i + 1,
                    "score": round(float(distances[0][i]), 4),
                    "scheme": self.schemes[idx]
                })
        return results


class SchemesBM25Index:
    def __init__(self, schemes: List[Dict[str, Any]]):
        self.schemes = schemes
        corpus_tokens = [s["ngram_tokens"] for s in self.schemes]
        self.bm25 = BM25Okapi(corpus_tokens)

    def search(self, raw_query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_tokens = char_ngram_tokenizer(raw_query)
        scores = self.bm25.get_scores(query_tokens)
        top_indices = np.argsort(scores)[::-1][:top_k]
        
        results = []
        for rank, idx in enumerate(top_indices):
            results.append({
                "scheme_id": self.schemes[idx]["scheme_id"],
                "rank": rank + 1,
                "score": round(float(scores[idx]), 4),
                "scheme": self.schemes[idx]
            })
        return results


def reciprocal_rank_fusion(vector_results: List[Dict[str, Any]], 
                           bm25_results: List[Dict[str, Any]], 
                           rrf_k: int = 60) -> List[Dict[str, Any]]:
    rrf_scores = {}
    scheme_map = {}
    
    for item in vector_results:
        s_id = item["scheme_id"]
        rank = item["rank"]
        scheme_map[s_id] = item["scheme"]
        rrf_scores[s_id] = rrf_scores.get(s_id, 0.0) + (1.0 / (rrf_k + rank))
        
    for item in bm25_results:
        s_id = item["scheme_id"]
        rank = item["rank"]
        scheme_map[s_id] = item["scheme"]
        rrf_scores[s_id] = rrf_scores.get(s_id, 0.0) + (1.0 / (rrf_k + rank))
        
    sorted_schemes = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    final_results = []
    for s_id, score in sorted_schemes:
        final_results.append({
            "scheme_id": s_id,
            "rrf_score": round(score, 6),
            "scheme": scheme_map[s_id]
        })
    return final_results


class GovernmentSchemesRAGEngine:
    def __init__(self, jsonl_file: str = "schemes_dataset.jsonl"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        jsonl_path = os.path.join(base_dir, jsonl_file)
        
        print("[Init] Loading government schemes dataset...")
        self.schemes = load_schemes_dataset(jsonl_path)
        print(f"[Init] Loaded {len(self.schemes)} government schemes.")
        
        print("[Init] Building FAISS Vector Index (all-MiniLM-L6-v2)...")
        self.vector_index = SchemesFAISSVectorIndex(self.schemes)
        
        print("[Init] Building BM25 Keyword Index (n-gram tokens)...")
        self.bm25_index = SchemesBM25Index(self.schemes)
        
        self.categories = list(set([s.get("category", "Other") for s in self.schemes if s.get("category", "Other") != "Other"]))
        self.category_embeddings = self.vector_index.model.encode(self.categories, show_progress_bar=False)
        self.category_embeddings = np.array(self.category_embeddings, dtype='float32')
        faiss.normalize_L2(self.category_embeddings)

        # Warmup pass
        _ = self.vector_index.model.encode(["warmup query"], show_progress_bar=False)
        print("[Init] Government Schemes RAG Engine Ready!\n")

    def predict_category(self, user_question: str) -> Tuple[Optional[str], float]:
        query_embedding = self.vector_index.model.encode([user_question], show_progress_bar=False)
        query_embedding = np.array(query_embedding, dtype='float32')
        faiss.normalize_L2(query_embedding)
        similarities = np.dot(query_embedding, self.category_embeddings.T)[0]
        max_idx = np.argmax(similarities)
        return self.categories[max_idx], float(similarities[max_idx])

    def query_schemes(self, user_question: str, category: Optional[str] = None) -> Dict[str, Any]:
        """Queries government schemes and returns clean farmer-focused dictionary."""
        start_time = time.time()
        
        # Step 0: Category intent routing (Soft-gating fallback)
        target_category = category
        if not category:
            pred_cat, pred_score = self.predict_category(user_question)
            if pred_score > 0.85:
                category = pred_cat # Hard-gate if extremely confident
                target_category = pred_cat
            elif pred_score > 0.55:
                target_category = pred_cat # Soft-gate if somewhat confident
                
        # Step 1: Fast Query Expansion (<1ms)
        expanded_query = expand_query(user_question)
        
        # Step 2: Dual Hybrid Search (FAISS + BM25)
        vector_results = self.vector_index.search(expanded_query, top_k=5)
        bm25_results = self.bm25_index.search(expanded_query, top_k=5)
        
        # Step 3: Reciprocal Rank Fusion (RRF)
        fused_results = reciprocal_rank_fusion(vector_results, bm25_results)
        
        # Apply Soft-Gating Boost
        if target_category:
            for item in fused_results:
                if item["scheme"].get("category") == target_category:
                    item["rrf_score"] *= 1.2
            
            # Re-sort after boost
            fused_results.sort(key=lambda x: x["rrf_score"], reverse=True)
            
        # Hard Gating (if category was explicitly provided or confidence > 0.85)
        if category:
            fused_results = [r for r in fused_results if r["scheme"].get("category") == category]
        
        if not fused_results:
            return {"status": "error", "message": "No matching government schemes found."}
            
        best = fused_results[0]["scheme"]
        raw_score = vector_results[0]["score"] if vector_results else 0.0
        top_cosine_score = round(float(np.clip(raw_score, -1.0, 1.0)), 4)
        top_bm25_score = bm25_results[0]["score"] if bm25_results else 0.0
        
        # Step 4: Safety Fallback Gate
        query_words = set(re.findall(r'\b[a-z0-9-]+\b', user_question.lower()))
        is_out_of_domain = any(kw in query_words for kw in OUT_OF_DOMAIN_KEYWORDS)
        is_fallback = is_out_of_domain or (top_cosine_score < 0.35 and top_bm25_score < 5.0)
        
        if is_fallback:
            latency = round(time.time() - start_time, 4)
            fallback_msg = "I could not find a matching government scheme for your question. Please rephrase or ask about a specific scheme."
            return {
                "outcome": "fallback",
                "status": "fallback",
                "question": user_question,
                "text": fallback_msg,
                "bhashini_voice_text": fallback_msg,
                "tft_lcd_display_card": "=== SYSTEM ===\nScheme not found.\nPlease ask about a\nspecific govt scheme.",
                "confidence_score": top_cosine_score,
                "latency_seconds": latency
            }

        # Smart Intent Extractor — returns only what the farmer asked for
        q_lower = user_question.lower()
        if any(w in q_lower for w in ["document", "doc", "paper", "proof", "certificate"]):
            answer = f"Documents required for {best['scheme_name']}: {best['documents_required']}"
        elif any(w in q_lower for w in ["apply", "where", "how", "portal", "register"]):
            answer = f"To apply for {best['scheme_name']}: {best['how_to_apply']}"
        elif any(w in q_lower for w in ["eligible", "who", "criteria"]):
            answer = f"Eligibility criteria for {best['scheme_name']}: {best['eligibility_criteria']}"
        elif any(w in q_lower for w in ["benefit", "amount", "subsidy", "rupees"]):
            answer = f"Benefits under {best['scheme_name']}: {best['benefit_details']}"
        else:
            answer = f"Under {best['scheme_name']}: {best['benefit_details']} To apply: {best['how_to_apply']}"

        # Display Cards Output
        tft_lcd_display_card = (
            f"=== SCHEME: {best['scheme_name'][:25]} ===\n"
            f"ID: {best['scheme_id']} | Score: {round(top_cosine_score, 4)}\n"
            f"----------------------------------------\n"
            f"{answer}\n"
            f"----------------------------------------"
        )
        voice_text = f"Regarding {best['scheme_name']}: {answer}"
        
        okf_v02_card = {
            "okf_version": "v0.2",
            "knowledge_id": best["scheme_id"],
            "title": best["scheme_name"],
            "category": f"Government Support - {best.get('category', 'General')}",
            "target_audience": "Farmers and Rural Citizens",
            "key_facts_and_explanations": best["benefit_details"],
            "action_steps": best["how_to_apply"],
            "safety_disclaimer": "Information based on official government scheme records."
        }
        
        latency = round(time.time() - start_time, 4)
        
        return {
            "outcome": "scheme_found",
            "status": "success",
            "question": user_question,
            "text": answer,
            "explanation_text": answer,
            "top_match": {
                "doc_id": best["scheme_id"],
                "scheme_name": best["scheme_name"],
                "similarity_score": top_cosine_score,
                "rrf_score": best_candidate.get("rrf_score", 0.0)
            },
            "okf_v02_card": okf_v02_card,
            "tft_lcd_display_card": tft_lcd_display_card,
            "bhashini_voice_text": voice_text,
            "latency_seconds": latency
        }


if __name__ == "__main__":
    engine = GovernmentSchemesRAGEngine()
    
    test_queries = [
        "How can small farmers get 6000 rupees direct benefit transfer?",
        "When will the 6000 rupees installment arrive in bank account",
        "PM kisan installment pending problem solution status check",
        "How to register for the 2000 rupees installment for small farmers",
        "what are the eligibility documents required for PM KISAN Samman Nidhi",
        "pmkisan gov in portal login and ekyc process",
        "I need a subsidy for a solar pump for water",
        "What should a farmer do to save on electricity bills",
        "How much subsidy is available for installing a solar pump",
        "Procedure to sell electricity to the company by installing solar panels in the field",
        "PM KUSUM component B standalone solar agriculture pump set apply",
        "Government scheme to convert diesel pump set to solar pump",
        "What is the crop insurance for drought and flood loss?",
        "crop failure claim compensation process time limit",
        "How much money will I get from insurance if my crop is damaged",
        "PMFBY crop loss intimation within 72 hours helpline number",
        "How to claim insurance if crops are destroyed by natural disaster",
        "How to get low interest loan using KCC card?",
        "is 4 percent interest rate valid for 3 lakh loan under KCC",
        "What needs to be submitted in the bank to make a farmer credit card",
        "How to get KCC loan for animal husbandry and poultry",
        "What is provided for taking drip irrigation and pipeline for irrigation",
        "Government assistance for installing tubewell or borewell in the field",
        "How to do online registration to sell crops in the mandi",
        "Portal to find out the correct price or rate of the crop",
        "pension scheme for senior citizens above 60 years in farming",
        "How to get 3000 pension every month in kisan maandhan yojana",
        "Farm bunding and leveling work in MGNREGA",
        "Incentive scheme for doing organic farming or natural farming",
        "Agriculture Infrastructure Fund for building cold storage and godowns",
        "How much subsidy will I get on water pump",
        "How much money will I get from insurance if my crop is damaged",
        "How do farmers get six thousand rupees every year",
        "Need loan for cattle from KCC",
        "random irrelevant question about space rockets",
        "what is the subsidy for buying a private electric car in Delhi"
    ]
    
    for q in test_queries:
        res = engine.query_schemes(q)
        print("=========================================================")
        print(f"QUERY: \"{res['question']}\"")
        print(f"STATUS: {res['status'].upper()}")
        if res["status"] == "success":
            print(f"MATCH: {res['scheme_name']} ({res['scheme_id']}) | Score: {res['confidence_score']}")
            print(f"ANSWER:\n{res['text']}\n")
        else:
            print(f"CONFIDENCE: {res['confidence_score']} (Below Cutoff)")
            print(f"VOICE TEXT: {res.get('bhashini_voice_text', res['text'])}")
        print(f"LATENCY: {res['latency_seconds']} s")
        print("=========================================================\n")