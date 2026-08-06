"""GramSahayak's real tool-calling agent, extracted from vyoma_v5.ipynb (cells 15-19) into an
importable module instead of notebook-only cells -- so `test_orchestrated_pipeline.py` (and
any future deployment code) can load the actual agent, not a placeholder single chat() call.

This is the same agent structure the notebooks have been iterating on: a tool-calling loop
over Ollama's `/api/chat`, five MOCK domain tools (entomologist/botanist/weather/disease/govt-
scheme -- stand-ins for real vector-search lookups against the datasets named in each one's
docstring, not implemented yet) plus two REAL tools (`analyze_photo`, a vision pass over an
attached photo; `pesticide_lookup`, real FSSAI data, no mock). Nothing about the tool-calling
logic itself is a simplification -- this is the real loop, same SYSTEM_PROMPT, same TOOLS
schema, same iteration/timeout handling as the notebook.

What's genuinely different from the notebook: this wraps the same logic in a class
(`GramSahayakAgent`) instead of module-level globals + a `_CURRENT_IMAGE_PATH` global mutated
between calls, so multiple turns / multiple callers don't step on each other's state, and the
whole thing is one import instead of copy-pasted notebook cells. The mock tools are still
verbatim from the notebook -- no logic changed, just moved.

Memory note: this is still just `ollama.chat()` against whatever model the orchestrator has
already loaded (`config.OLLAMA_MODELS[0]`, currently qwen3.5:2b) with `config.OLLAMA_NUM_CTX`
-- the orchestrator's load/unload/Rule-8-eviction handling is completely unaffected by
swapping the single chat() call for this real tool-calling loop. It's the same model process
either way; only what gets sent to it (and how many round-trips a single "turn" can take)
changes.
"""
import json
import os
import sys
import time

# This file lives one level deeper than it used to (gramsahayak/agent/agent.py, not
# dev/agents/agent.py) -- api_server/ and models/ are siblings of agent/, not of this file
# itself, so both this file's own directory (for `prompts`/`tools`, flat-import style
# matching the rest of this codebase) AND its parent (for `api_server`) need to be on
# sys.path.
_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))       # gramsahayak/agent/
_ROOT_DIR = os.path.dirname(_AGENT_DIR)                        # gramsahayak/
for _p in (_ROOT_DIR, _AGENT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ollama

from api_server import config
from prompts import SYSTEM_PROMPT
from tools.photo_analysis import analyze_photo as _analyze_photo_impl
from tools.pesticide_lookup import find_pesticide

# Same model as the agent (config.OLLAMA_MODELS[0], currently qwen3.5:2b), not a separate
# vision model -- confirmed via `ollama show qwen3.5:2b` that it genuinely supports vision
# (Capabilities: completion, vision, tools, thinking), so there's no need for a second model.
# This matters for memory, not just simplicity: `tools/photo_analysis.py`'s own default
# ("gemma4:e2b") is a real, separate 7.2GB Ollama model -- if analyze_photo ever actually used
# it, that would be a second Ollama-resident model the orchestrator's budget math has never
# accounted for anywhere (config.OLLAMA_MODELS only lists the agent + embedder), and 7.2GB
# alone is already over the entire 7.0GB Jetson budget. Sharing the agent's own model avoids
# that risk entirely -- vision analysis never needs a model swap or a second resident model.
DEFAULT_VISION_MODEL = None  # resolved to config.OLLAMA_MODELS[0] in __init__ if left as None
MAX_MAJOR_USES = 5  # pesticide_lookup's major_uses truncation, same constant as cell 17


# ---------------------------------------------------------------------------
# MOCK domain tools -- verbatim from vyoma_v5.ipynb cell 16. Each docstring names the real
# dataset/index it will eventually read (pest_identification_index, agronomic_practices_index,
# NASA POWER/IMD gridded rainfall, disease_diagnosis_index, govt_scheme_index) -- once those
# are real, most will need nomic-embed-text for vector search, which is exactly why the
# Embedder is modeled as its own on-demand-schedulable component (Rule 7) rather than being
# bundled into the Agent's baseline footprint.
# ---------------------------------------------------------------------------

def query_entomologist(query: str) -> dict:
    """MOCK — will read `pest_identification_index` (CIB&RC IPM division, ICAR-NCIPM, IP102)."""
    return {
        "query": query,
        "matched_pest": "Thrips (Thrips parvispinus)",
        "description": "Tiny slender insects that rasp leaf/flower surfaces, causing "
                        "silvery streaks and curling; common on chilli and pepper.",
        "ipm_guidance": "Blue/yellow sticky traps, avoid excess nitrogen, spot-treat "
                         "hotspots rather than blanket spraying.",
        "source": "MOCK ICAR-NCIPM",
    }


def query_botanist(crop: str, topic: str = "general") -> dict:
    """MOCK — will read `agronomic_practices_index` (ICAR-CRIDA, KVK Package of Practices)."""
    return {
        "crop": crop,
        "topic": topic,
        "growth_requirements": "Warm season crop, well-drained loamy soil, pH 6.0-6.8, "
                                "regular but not waterlogged irrigation.",
        "common_stress_signs": "Leaf curl and yellowing under water stress; blossom-end "
                                "rot under calcium/water inconsistency.",
        "source": "MOCK KVK Package of Practices",
    }


def query_harvest_weather_risk(crop: str, district: str, harvest_window_days: int = 7) -> dict:
    """MOCK — will read NASA POWER / IMD Pune gridded rainfall, no vector index (pure stats)."""
    return {
        "crop": crop,
        "district": district,
        "window_days": harvest_window_days,
        "rain_risk_pct": 35,
        "recommendation": "Moderate rain risk in the harvest window — consider "
                           "harvesting 1-2 days early if the crop is at maturity.",
        "source": "MOCK NASA POWER + IMD Pune gridded",
    }


def query_disease_diagnosis_index(description: str) -> dict:
    """MOCK — will read `disease_diagnosis_index` (PlantVillage, PlantDoc, ICAR pathology bulletins)."""
    return {
        "query": description,
        "matches": [
            {
                "disease": "Bacterial leaf spot",
                "confidence": 0.78,
                "symptoms": "Small water-soaked spots turning brown with yellow halo.",
                "treatment": "Copper-based bactericide, avoid overhead irrigation, "
                              "remove infected debris.",
            },
            {
                "disease": "Early blight",
                "confidence": 0.41,
                "symptoms": "Concentric dark rings on older leaves.",
                "treatment": "Mancozeb-based fungicide, crop rotation.",
            },
        ],
        "source": "MOCK disease_diagnosis_index",
    }


def query_govt_scheme(state: str, land_size_acres: float, crop: str) -> dict:
    """MOCK — will read `govt_scheme_index` (myScheme)."""
    return {
        "state": state,
        "land_size_acres": land_size_acres,
        "crop": crop,
        "eligible_schemes": [
            {
                "name": "PM-KISAN",
                "benefit": "₹6,000/year in three installments to landholding farmers.",
                "how_to_apply": "Register via pmkisan.gov.in or nearest CSC with land records.",
            },
            {
                "name": "PMFBY (crop insurance)",
                "benefit": "Insurance payout on crop loss due to weather/pest, premium "
                            "subsidised by government.",
                "how_to_apply": "Apply through bank/CSC before the crop-season cutoff.",
            },
        ],
        "source": "MOCK myScheme.gov.in",
    }


# ---------------------------------------------------------------------------
# REAL tools -- verbatim from cell 17 (pesticide_lookup); analyze_photo (cell 15) is wrapped
# per-call inside GramSahayakAgent.run_turn() instead of via a module-level mutable global,
# since a class instance can just close over that call's image_path directly.
# ---------------------------------------------------------------------------

def pesticide_lookup(pesticide_name: str) -> dict:
    """REAL — reads `datasets/json/pesticides.json` (283 FSSAI-scraped records) via
    exact/substring/fuzzy name matching. No mock, no vector index needed."""
    record = find_pesticide(pesticide_name)
    if record is None:
        return {
            "pesticide_name": pesticide_name,
            "found": False,
            "message": "No matching pesticide found in the FSSAI dataset.",
        }

    major_uses = record["major_uses"]
    truncated = len(major_uses) > MAX_MAJOR_USES
    result = {"found": True, **record, "major_uses": major_uses[:MAX_MAJOR_USES]}
    if truncated:
        result["major_uses_note"] = (
            f"showing {MAX_MAJOR_USES} of {len(major_uses)} registered crops/commodities"
        )
    return result


# ---------------------------------------------------------------------------
# TOOLS schema + dispatch -- verbatim from cell 18. analyze_photo's dispatch entry is
# overridden per-turn inside run_turn() (it needs that turn's image_path bound in).
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "analyze_photo",
            "description": (
                "Look at the photo the farmer just shared. Call this FIRST whenever a "
                "photo is attached, before any other tool — no need to guess whether "
                "it's a crop/plant photo or a pesticide/product photo, this tool looks "
                "at the image itself to decide that, then returns the matching result: "
                "for a crop/plant/leaf/field photo, a plain-text visual finding "
                "(symptoms, severity); for a pesticide/product photo (bottle, packet, "
                "label), a structured extraction with 'Brand/product name', 'Active "
                "ingredients' (one chemical name per line, or 'not visible' if the "
                "ingredient text couldn't be read), 'Manufacturer', and 'Notes' — it "
                "NEVER guesses a chemical name just because it recognizes the brand, "
                "since a wrong one could lead to an unsafe dose; for anything else "
                "(not clearly a crop or a pesticide product), a plain factual "
                "description of what's actually in the photo, so you can decide what "
                "to do — no specific lookup tool applies to that case. "
                "Runs a separate vision pass (classification, then the matching detailed "
                "pass) over the attached image, using this same model's own vision "
                "capability -- no separate model involved. "
                "See SYSTEM_PROMPT for what to do with each kind of result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus_question": {
                        "type": "string",
                        "description": "What to look for if it turns out to be a crop/plant "
                                        "photo, based on what the farmer asked (e.g. 'what "
                                        "disease is this' or 'is this pest damage'). Ignored "
                                        "for the pesticide-product and other cases.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_entomologist",
            "description": "Identify an insect/pest from a description and get IPM "
                            "(integrated pest management) guidance for it.",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "Description of the insect or pest symptoms/behavior."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_botanist",
            "description": "Get botanical/agronomic facts about a crop: growth "
                            "requirements, soil/water needs, common stress signs.",
            "parameters": {
                "type": "object",
                "required": ["crop"],
                "properties": {
                    "crop": {"type": "string", "description": "Crop name, e.g. 'chilli', 'tomato'."},
                    "topic": {"type": "string", "description": "Specific aspect to focus on (default: general)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_harvest_weather_risk",
            "description": "Get weather-driven risk (e.g. rain during harvest) for a "
                            "crop's upcoming harvest window in a given district.",
            "parameters": {
                "type": "object",
                "required": ["crop", "district"],
                "properties": {
                    "crop": {"type": "string", "description": "Crop being harvested."},
                    "district": {"type": "string", "description": "District/location for the weather lookup."},
                    "harvest_window_days": {"type": "integer", "description": "Days ahead to assess (default 7)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_disease_diagnosis_index",
            "description": "Search crop disease records by symptom description or "
                            "disease name; returns ranked candidate matches with treatment.",
            "parameters": {
                "type": "object",
                "required": ["description"],
                "properties": {
                    "description": {"type": "string", "description": "Symptom description or disease name to search for."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_govt_scheme",
            "description": "Look up government schemes (subsidies, insurance, direct "
                            "benefit) the farmer may be eligible for, given basic farm details.",
            "parameters": {
                "type": "object",
                "required": ["state", "land_size_acres", "crop"],
                "properties": {
                    "state": {"type": "string", "description": "Farmer's state."},
                    "land_size_acres": {"type": "number", "description": "Land holding size in acres."},
                    "crop": {"type": "string", "description": "Primary crop grown."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pesticide_lookup",
            "description": (
                "Look up a pesticide or active ingredient by name in India's official "
                "FSSAI pesticide dataset (283 records scraped from sites.fssai.gov.in, "
                "CIB&RC classification) — real regulatory data. For a matched pesticide "
                "it returns: functional class (e.g. insecticide, fungicide, plant growth "
                "regulator), CIB&RC toxicity classification (e.g. 'Highly toxic', "
                "'Moderately toxic'), WHO hazard classification, ADI (Acceptable Daily "
                "Intake), residue definition, and a 'major_uses' list with one entry per "
                "commodity/crop it has a ruling for — each giving the MRL (Maximum "
                "Residue Limit), food category, registration/adoption status (including "
                "oral LD50 and which formulated products are registered), and the Codex "
                "MRL for comparison. "
                "Matching is forgiving so small spelling differences from a farmer's "
                "spoken or transcribed query still resolve: it tries an exact name match "
                "first, then a substring match (e.g. 'chlorpy' matches 'Chlorpyrifos'), "
                "then a fuzzy/typo-tolerant match (e.g. 'imidaclorprid' still matches "
                "'Imidacloprid') over the ~283 pesticide names in the dataset. Returns "
                "found=false with no record if nothing matches even fuzzily. "
                "Call this whenever the farmer names a specific pesticide/chemical and "
                "asks how toxic/hazardous it is, whether it's legally registered, "
                "whether it has a legal residue limit (MRL) for their crop, or what its "
                "registration status is. Also call this ONCE PER CHEMICAL NAME after "
                "analyze_photo returns a label extraction with one or more active "
                "ingredients (pass only the plain chemical name it listed, not a "
                "percentage or formulation code)."
            ),
            "parameters": {
                "type": "object",
                "required": ["pesticide_name"],
                "properties": {
                    "pesticide_name": {
                        "type": "string",
                        "description": "Pesticide or active ingredient name to search for, "
                                        "e.g. 'Chlorpyrifos', 'Imidacloprid'. Partial names, "
                                        "brand-ish phrasing, and minor misspellings are OK — "
                                        "the lookup fuzzy-matches against the dataset.",
                    }
                },
            },
        },
    },
]

# Static tools (everything except analyze_photo, which run_turn() binds per-call).
_STATIC_TOOL_DISPATCH = {
    "query_entomologist": query_entomologist,
    "query_botanist": query_botanist,
    "query_harvest_weather_risk": query_harvest_weather_risk,
    "query_disease_diagnosis_index": query_disease_diagnosis_index,
    "query_govt_scheme": query_govt_scheme,
    "pesticide_lookup": pesticide_lookup,
}


class GramSahayakAgent:
    """The real tool-calling agent -- same loop as vyoma_v5.ipynb's run_agent_turn(), wrapped
    so it can be imported and reused instead of copy-pasted between notebooks/scripts.

    Usage:
        agent = GramSahayakAgent()  # defaults: config.OLLAMA_MODELS[0], config.OLLAMA_NUM_CTX
        messages = agent.run_turn("What's eating my chilli plants?")
        print(messages[-1].content)

        # Follow-up in the same conversation:
        messages = agent.run_turn("And what should I spray?", messages=messages)

    Memory: this only ever calls `ollama.chat()` against whatever model the orchestrator has
    loaded -- it has no load/unload logic of its own. The orchestrator's Rule 8 (evict Agent
    before every TTS peak) still applies exactly as before; the model being asked to do a
    5-iteration tool-calling loop instead of a single chat call doesn't change how much VRAM
    it occupies while resident, only how long a turn takes and how many round-trips happen
    before `run_turn()` returns.

    think defaults to config.AGENT_THINK ("medium" as of this writing) -- confirmed directly
    on real Jetson hardware that qwen3.5:0.8b (the current OLLAMA_MODELS[0] -- see config.py
    for why it's not the larger 2b anymore) with think="low" unreliably produces an EMPTY
    final `.content` -- it generates real tokens, but they land entirely in `.thinking` and
    the model never actually closes its reasoning phase to emit a real answer. This silently
    broke the pipeline (`turn_messages[-1].content` came back "", which then hit NMT's
    `EN->hi` call with an empty string, one 500 error hiding a completely different real
    cause). "medium"/"high" didn't reproduce that failure across repeated testing (0/6 each)
    -- "medium" was picked as the default since it matched "high"'s reliability at roughly
    half the latency cost. See config.py's AGENT_THINK comment for the full real numbers
    behind this choice, and re-tune per model if OLLAMA_MODELS[0] ever changes -- qwen3.5:2b's
    think="low" was previously validated as reliable (run_pipeline_live_demo.py), this is
    0.8b-specific.
    """

    def __init__(self, model=None, vision_model=DEFAULT_VISION_MODEL, num_ctx=None,
                 keep_alive=-1, temperature=0.2, think=None, max_tool_iterations=5):
        self.model = model or config.OLLAMA_MODELS[0]
        # Defaults to the same model as .model (not a separate resident model) -- see
        # DEFAULT_VISION_MODEL's comment above for why that's a memory decision, not just
        # a convenience default.
        self.vision_model = vision_model or self.model
        self.num_ctx = num_ctx if num_ctx is not None else config.OLLAMA_NUM_CTX
        self.keep_alive = keep_alive
        self.temperature = temperature
        # None (not passed) -> config.AGENT_THINK; explicit False is a real, distinct value
        # (fastest, no thinking at all) so it must not be treated the same as "unset".
        self.think = think if think is not None else config.AGENT_THINK
        self.max_tool_iterations = max_tool_iterations

    def _chat_options(self):
        return {"num_ctx": self.num_ctx, "temperature": self.temperature}

    def _build_dispatch(self, image_path):
        """analyze_photo needs this turn's image_path bound in -- everything else is static."""
        def _analyze_photo(focus_question: str = "what is wrong or notable in this photo") -> str:
            from prompts import CLASSIFY_PROMPT, CROP_VISION_PROMPT, LABEL_VISION_PROMPT, GENERIC_VISION_PROMPT
            return _analyze_photo_impl(
                image_path, focus_question,
                CLASSIFY_PROMPT, CROP_VISION_PROMPT, LABEL_VISION_PROMPT, GENERIC_VISION_PROMPT,
                model=self.vision_model, keep_alive=self.keep_alive, num_ctx=self.num_ctx,
                temperature=self.temperature, think=self.think,
            )
        return {**_STATIC_TOOL_DISPATCH, "analyze_photo": _analyze_photo}

    def _print_timing(self, iteration, response, verbose):
        if not verbose:
            return
        def ms(ns):
            return f"{(ns or 0) / 1e6:.0f}ms"
        print(
            f"    [agent iter {iteration}] load={ms(response.load_duration)} "
            f"prefill={ms(response.prompt_eval_duration)} ({response.prompt_eval_count} tok) "
            f"gen={ms(response.eval_duration)} ({response.eval_count} tok)"
        )

    def run_turn(self, user_text, image_path=None, messages=None, verbose=True):
        """Runs one full tool-calling turn (up to max_tool_iterations round-trips) and
        returns the updated `messages` list -- pass it back in as `messages=` for a
        multi-turn conversation, same shape as ollama.chat's own message list."""
        dispatch = self._build_dispatch(image_path)

        if messages is None:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        user_content = user_text
        if image_path:
            user_content += "\n\n[A photo is attached to this message.]"
        messages.append({"role": "user", "content": user_content})

        turn_start = time.perf_counter()

        for iteration in range(1, self.max_tool_iterations + 1):
            response = ollama.chat(
                model=self.model, messages=messages, tools=TOOLS,
                keep_alive=self.keep_alive, options=self._chat_options(),
                stream=False, think=self.think,
            )
            messages.append(response.message)
            self._print_timing(iteration, response, verbose)

            if not response.message.tool_calls:
                break

            for call in response.message.tool_calls:
                name = call.function.name
                args = call.function.arguments or {}
                fn = dispatch.get(name)
                if fn is None:
                    result = {"error": f"unknown tool '{name}'"}
                else:
                    try:
                        result = fn(**args)
                    except Exception as exc:
                        result = {"error": str(exc)}
                if verbose:
                    print(f"    -> {name}({args}) -> {json.dumps(result)[:160]}")
                content = result if isinstance(result, str) else json.dumps(result)
                messages.append({"role": "tool", "tool_name": name, "content": content})
        else:
            messages.append({
                "role": "user",
                "content": "You are out of tool calls for this turn — answer now with what you already know.",
            })
            response = ollama.chat(
                model=self.model, messages=messages, tools=TOOLS,
                keep_alive=self.keep_alive, options=self._chat_options(),
                stream=False, think=self.think,
            )
            messages.append(response.message)
            self._print_timing("final", response, verbose)

        if verbose:
            print(f"    agent turn wall-clock: {time.perf_counter() - turn_start:.2f}s")

        return messages
