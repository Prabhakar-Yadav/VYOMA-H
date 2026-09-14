"""GramSahayak's real tool-calling agent, extracted from vyoma_v5.ipynb (cells 15-19) into an
importable module instead of notebook-only cells -- so `test_orchestrated_pipeline.py` (and
any future deployment code) can load the actual agent, not a placeholder single chat() call.

2026-08-11: the four original MOCK domain tools (query_entomologist, query_botanist,
query_disease_diagnosis_index, query_govt_scheme) are RETIRED, replaced by real RAG tools
backed by datasets/rag/{g1,g2}.sqlite (sqlite-vec + granite-embedding:30m, int8 quantized --
see RAG-BUILD-LOG.md and G1-G2-VECTORDB-PLAN.md for the full build/design/decisions):
`tools/g1_rag_tools.py` (plant_disease_lookup, plant_entomology_lookup,
get_treatment_details, get_guidelines_and_safety) and `tools/g2_rag_tools.py`
(get_scheme_details, match_eligible_schemes, get_disaster_relief_options,
get_subsidy_details). query_botanist had no real G1/G2 tool it mapped to (general agronomic
Q&A, not diagnosis) and is simply dropped, not replaced -- see RAG-BUILD-LOG.md "decisions"
for why.

2026-08-12: `pesticide_usage_and_dose` renamed to `get_treatment_details` (same tool, clearer
name) and `get_guidelines_and_safety` added -- see tools/g1_rag_tools.py's own docstrings for
the real coverage-gap review and boost-bug fix behind both changes.

2026-08-14: `analyze_photo` dispatch now calls `tools.photo_analysis.analyze_photo_unified` --
a TRUE single ollama.chat() call for every photo, pesticide included (superseded the
`analyze_photo_hybrid` two-call-for-pesticide design after real testing showed its extra
call cost more than it saved -- see tools/photo_analysis.py's own module docstring/comments
for the full history, including a misclassification bug and a bracket-artifact bug fixed
along the way, and the accepted hallucination-risk tradeoff behind the unified design). Still
dev-local-test only, not yet in the production checkout -- see JETSON_RECOVERY_2026-08-12.md.

Also REAL (unchanged by the above): `analyze_photo` (vision pass over an attached photo),
`pesticide_lookup` (real FSSAI toxicity/MRL/registration data -- kept alongside
get_treatment_details rather than merged into it, since they answer genuinely different
questions: FSSAI data is "is this legal/how toxic", the CIB&RC-backed tool is "how much do
I use and when can I harvest" -- see RAG-BUILD-LOG.md), and five weather tools
(`get_weather_forecast`, `query_spray_window`, `query_sowing_window`,
`query_pest_pressure_window`, `query_crop_suitability` --
gramsahayak/agent/tools/weather_tools/forecast_tools.py, real NASA POWER climatology).

What's genuinely different from the notebook: this wraps the same logic in a class
(`GramSahayakAgent`) instead of module-level globals + a `_CURRENT_IMAGE_PATH` global mutated
between calls, so multiple turns / multiple callers don't step on each other's state, and the
whole thing is one import instead of copy-pasted notebook cells.

Memory note: this is still just `ollama.chat()` against whatever model the orchestrator has
already loaded (`config.OLLAMA_MODELS[0]`, currently qwen3.5:2b) with `config.OLLAMA_NUM_CTX`
-- the orchestrator's load/unload/Rule-8-eviction handling is completely unaffected by
swapping the single chat() call for this real tool-calling loop. It's the same model process
either way; only what gets sent to it (and how many round-trips a single "turn" can take)
changes.
"""
import json
import os
import random
import sys
import threading
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
from prompts import SYSTEM_PROMPT, SYSTEM_PROMPTS
from status_messages import STATUS_MESSAGES
from tools.photo_analysis import analyze_photo_unified as _analyze_photo_impl
from tools.pesticide_lookup import find_pesticide
from tools.weather_tools.forecast_tools import (
    get_weather_forecast,
    query_spray_window,
    query_sowing_window,
    query_pest_pressure_window,
    query_crop_suitability,
)
from tools.g1_rag_tools import (
    plant_disease_lookup,
    plant_entomology_lookup,
    get_treatment_details,
    get_guidelines_and_safety,
)
from tools.g2_rag_tools import (
    get_scheme_details,
    match_eligible_schemes,
    get_disaster_relief_options,
    get_subsidy_details,
)

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

# 2026-08-14: context compaction thresholds -- see _compact_context_if_needed()'s own
# docstring for the real incident and full mechanism. ~85% of config.OLLAMA_NUM_CTX (32768),
# leaving real headroom (~4.7K tokens) for the compacted history block plus a new turn's own
# consumption, not a number picked to sit right at the ceiling.
#
# 2026-08-23: 28000 -> 14500, re-tuned alongside config.OLLAMA_NUM_CTX's own 8192 -> 16384 move
# (see that constant's own comment for the real memory numbers behind the ctx change). This
# constant had been silently orphaned in between: OLLAMA_NUM_CTX dropped 32768 -> 8192 on
# 2026-08-22 (real OOM/reboot) without this threshold being touched, leaving it at a stale value
# HIGHER than the entire context window it was meant to guard -- compaction could never have
# fired before Ollama's own truncation did. 14500 (~88.5% of 16384, requested directly) leaves
# ~1884 tokens of headroom for the compacted block + new turn -- real image-heavy turns averaged
# ~4078 tok/turn in the original incident (see comment below), noticeably MORE than that
# headroom, so a single post-compaction turn could still push past 16384 on its own. Left as
# requested, not silently widened -- flagging the arithmetic here rather than second-guessing it.
CONTEXT_COMPACTION_THRESHOLD_TOKENS = 14500
# Real image-heavy tool-calling turns averaged ~4078 tok/turn in the actual incident (32621
# tok / 8 turns) -- keeping the last 3 verbatim is ~12K tokens, comfortably inside the
# threshold's headroom alongside the compacted block and the upcoming new turn. NOT the
# generic "10-15 turns" default general chatbot research recommends -- that default assumes
# much lighter turns than this agent's (image analysis + multi-tool RAG lookups + long
# answers), which would blow the budget again almost immediately at that size.
CONTEXT_COMPACTION_KEEP_LAST_N_TURNS = 3

# 2026-08-16: real per-turn latency investigation follow-up -- "if the final answer is taking
# way too long... can we add some content there too". Real per-iteration gen= times observed
# in actual Jetson multiturn testing ranged 0.6-28s+ (THINKING_MODE_RESULTS.md), so a single
# fixed pre-call status can sit stale through a genuinely slow outlier call. 8s sits
# comfortably past the real median (most calls land well under this) but before the real slow
# tail, so run_turn()'s `_chat_with_followup()` watchdog only fires on the calls actually
# worth narrating further, not on every normal one.
_LONG_CALL_THRESHOLD_SEC = 8.0
# Marker prefix identifying the synthetic summary-turn (index 1-2 of `messages`, right after
# the system prompt) so a LATER compaction pass can find and extend it instead of creating a
# second, duplicate one -- see _compact_context_if_needed().
_CONTEXT_SUMMARY_MARKER = "[EARLIER CONVERSATION SO FAR]"


# 2026-08-14: real-time, farmer-facing status messages -- device screen showed nothing but a
# static "Running: Agent" for the whole 60-150s+ a real turn's tool-calling loop takes (see
# TIMING_RESULTS.md/this session's own real pipeline logs), no feedback at all while the agent
# is actually doing multiple real tool calls (image analysis, RAG lookups, ...) one after
# another. `run_turn(status_cb=...)` below calls this at each real stage transition; the
# caller (e.g. gramsahayak_app.py) supplies a `status_cb(stage, tool_name=None)` that displays
# whatever `get_status_message()` returns. Messages themselves are PRESET, not translated live
# per call (see status_messages.py's own docstring for why) -- generated once via this
# project's own real NMT engine by `build_status_messages.py`, not hand-translated/guessed.
def get_status_message(stage: str, tool_name: str | None = None, language: str = "en",
                        variant_index: int = 0) -> str:
    """Looks up the preset status string for one real stage/tool, in one language. `stage` is
    one of "asr"/"nmt_in"/"agent_thinking"/"agent_reviewing"/"agent_finalizing"/"nmt_out"/"tts",
    OR "tool" (with `tool_name` set to the real tool being called, e.g. "analyze_photo") for a
    per-tool-call message. Graceful fallback chain, never raises over a missing key: unknown
    tool -> the generic "fallback" entry; unknown/missing language for a real entry -> that
    entry's own English variants (still something meaningful to show, not a blank screen or a
    crash) -- a language this device doesn't support yet, or a tool added to TOOLS without a
    matching preset yet, should never take the whole status display down with it.

    `variant_index` (2026-08-16): each key now holds a LIST of phrasings, not one fixed string
    -- real feedback was that repeating the identical clip for a tool called twice in one turn
    (a real, valid case -- different real arguments, same tool name) felt robotic. Cycles via
    modulo, so any index is safe to pass regardless of how many variants actually exist."""
    key = f"tool:{tool_name}" if stage == "tool" and tool_name else stage
    entry = STATUS_MESSAGES.get(key) or STATUS_MESSAGES["fallback"]
    variants = entry.get(language) or entry["en"]
    return variants[variant_index % len(variants)]


# 2026-08-15: real per-turn latency investigation (device shows ~15s/tool, well above
# Bhashini's 6s target) -- one of the concrete mitigations tried: play a PRE-RECORDED status
# clip (see agent/build_status_audio.py) alongside get_status_message()'s text, instead of
# leaving the wait silent. Same design as the text presets: baked in ONCE, offline, via the
# real production TTS engine (no live synthesis per display -- that would add latency to the
# exact moment this exists to mask). Mirrors get_status_message()'s own graceful-fallback
# contract exactly -- a stage/tool with no key, or a language with no clip yet, degrades to the
# fallback/English clip rather than a missing/crashing playback, same reasoning as the text
# version: a tool added to TOOLS without a matching audio build yet, or a language this device
# doesn't support in audio form yet, should never take the whole status display down with it.
_STATUS_AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "status_audio")


def get_status_audio_path(stage: str, tool_name: str | None = None, language: str = "en",
                           variant_index: int = 0) -> str | None:
    """Same key derivation as get_status_message() ("tool:<name>" or the bare stage). Returns
    a real filesystem path to a WAV clip, or None if nothing exists for it (caller's cue to
    skip audio for this update rather than crash/block -- see build_status_audio.py's own
    docstring for why these are pre-baked files, not a live call). Fallback chain: this
    stage/tool's own clip in `language` -> the same key's English clip -> the generic
    "fallback" key's clip in `language` -> that key's English clip -> None.

    `variant_index` (2026-08-16): same real reason as get_status_message()'s own -- a repeated
    tool call in one turn should get a different clip, not the identical one again. The actual
    file index is resolved fresh at each fallback step (`% that step's own real variant count`,
    read from STATUS_MESSAGES, the same source build_status_audio.py used to name the files) --
    not assumed to match the ORIGINAL key/language's variant count, since a language with fewer
    built clips than English is a real, supported degradation, not an error.

    `tts` is pinned to v0 (2026-09-14): the liked Hindi tts_v0 clip, copied to every
    language folder -- only tts_v0 exists per language, so any passed variant_index
    for "tts" resolves to 0. Other stages keep the normal modulo behavior."""
    key = f"tool:{tool_name}" if stage == "tool" and tool_name else stage
    for lookup_key, lookup_lang in ((key, language), (key, "en"),
                                     ("fallback", language), ("fallback", "en")):
        entry = STATUS_MESSAGES.get(lookup_key) or STATUS_MESSAGES["fallback"]
        variants = entry.get(lookup_lang)
        if not variants:
            continue
        actual_index = 0 if lookup_key == "tts" else variant_index % len(variants)
        candidate = os.path.join(_STATUS_AUDIO_DIR, lookup_lang,
                                  f"{lookup_key.replace(':', '_')}_v{actual_index}.wav")
        if os.path.isfile(candidate):
            return candidate
    return None


def pick_status_variant(key: str, last_used: dict | None = None) -> int:
    """2026-08-16, real feedback: "we can always do a random sample so that it will feel
    genuinely different" -- picks a RANDOM variant index for this key (not sequential
    cycling), while never immediately repeating the exact one just used for this same key, if
    `last_used` (a caller-owned dict) already has an entry for it. Scope of `last_used` is the
    caller's choice -- run_turn() uses a fresh, per-turn dict (a tool called twice in the SAME
    turn won't repeat), gramsahayak_app.py uses one instance-level dict that lives for the
    whole session (so "asr"/"nmt_in"/etc., which only fire once per turn, still vary turn to
    turn instead of saying the exact same thing every single time).

    Variant COUNT is read from STATUS_MESSAGES' own English list for `key` -- real, not
    guessed, and language-independent (every language gets the same number of variants per
    key, built together by build_status_messages.py) so this doesn't need a language passed
    in just to know how many options exist. Falls back to index 0 (the only real option) if
    there's 0 or 1 variant for this key."""
    entry = STATUS_MESSAGES.get(key) or STATUS_MESSAGES["fallback"]
    num_variants = len(entry.get("en") or [""])
    if num_variants <= 1:
        return 0
    choices = list(range(num_variants))
    if last_used is not None and last_used.get(key) in choices:
        choices.remove(last_used[key])
    idx = random.choice(choices)
    if last_used is not None:
        last_used[key] = idx
    return idx


# ---------------------------------------------------------------------------
# G1/G2 RAG tools (real, sqlite-vec-backed) and the weather tools are imported above,
# not defined here -- see tools/g1_rag_tools.py, tools/g2_rag_tools.py,
# tools/weather_tools/forecast_tools.py. The four MOCK domain tools this section used
# to hold (query_entomologist, query_botanist, query_disease_diagnosis_index,
# query_govt_scheme) are retired -- see this module's own docstring and
# RAG-BUILD-LOG.md.
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
            "name": "plant_disease_lookup",
            "description": (
                "Real RAG search (818 chunks, diseases/pathology/deficiencies) for a "
                "crop disease or nutrient deficiency matching a symptom description. "
                "Call this after analyze_photo returns a crop/plant visual finding, "
                "or directly if the farmer described symptoms in words. Returns "
                "matched condition(s) with symptom text and linked treatment "
                "concept_ids -- this tool NEVER states a dose itself, call "
                "get_treatment_details next with the matched condition/crop."
            ),
            "parameters": {
                "type": "object",
                "required": ["description"],
                "properties": {
                    "description": {"type": "string", "description": "Symptom description (from analyze_photo or the farmer's own words)."},
                    "crop": {"type": "string", "description": "Crop name if known -- narrows the search to that crop's conditions."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plant_entomology_lookup",
            "description": (
                "Real RAG search over insect/mite biology (life cycle, seasonal "
                "peaks, natural enemies, alternate hosts). Call this when the "
                "question is about pest behavior/biology specifically (e.g. \"when "
                "does this pest breed\", \"what eats this pest naturally\"), as a "
                "complement to plant_disease_lookup rather than instead of it."
            ),
            "parameters": {
                "type": "object",
                "required": ["description"],
                "properties": {
                    "description": {"type": "string", "description": "Description of the insect/pest symptoms or behavior."},
                    "crop": {"type": "string", "description": "Crop name if known."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_treatment_details",
            "description": (
                "Real CIB&RC-registered dose/dilution/pre-harvest-interval/safety "
                "lookup -- answers \"how much do I use and when can I "
                "harvest\", NOT toxicity/legality (use pesticide_lookup for that). "
                "Call after plant_disease_lookup names a condition (pass its linked "
                "treatment) or after analyze_photo/pesticide_lookup identifies a "
                "product by active-ingredient name. If a match's "
                "crop_confirmed_in_text is false, treat the dose as UNCONFIRMED for "
                "that crop and say so -- do not state it as safe."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pesticide_name": {"type": "string", "description": "Active ingredient/molecule name, e.g. 'Mancozeb'."},
                    "crop": {"type": "string", "description": "Crop the pesticide would be applied to -- important, registration is crop-specific."},
                    "symptom_or_disease": {"type": "string", "description": "The condition being treated, if a specific product name isn't known yet."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_guidelines_and_safety",
            "description": (
                "Real RAG search over general application practice guidance and "
                "pesticide-safety content (protective equipment, re-entry interval, "
                "storage/disposal, safe timing/technique) -- NOT tied to one specific "
                "disease or product. Call this for questions like \"is it safe to "
                "spray today\", \"what protective gear do I need\", \"how long "
                "before I can go back in the field\", \"how should I store this "
                "chemical\" -- things get_treatment_details and plant_disease_lookup "
                "don't cover."
            ),
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "The farmer's safety/practice question."},
                    "crop": {"type": "string", "description": "Crop name if relevant, if known."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scheme_details",
            "description": (
                "Real RAG search (17 government schemes) for a specific scheme's "
                "details: eligibility, benefit amount, application process, "
                "documents needed. Call when the farmer names a scheme or asks a "
                "specific question about one they've already heard of."
            ),
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "The farmer's question about the scheme."},
                    "scheme_name": {"type": "string", "description": "Scheme name if the farmer named one, e.g. 'PM-KISAN', 'PMFBY'."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "match_eligible_schemes",
            "description": (
                "SOFT topical match (not a real eligibility rules engine -- there is "
                "no structured eligibility table) between a farmer's profile and "
                "government schemes. Call when the farmer describes their situation "
                "and asks what schemes might help, without naming one. Always tell "
                "the farmer to confirm eligibility on the scheme's own application "
                "channel -- never state eligibility as settled from this alone."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {"type": "string", "description": "Farmer's state, if known."},
                    "land_size_acres": {"type": "number", "description": "Land holding size in acres, if known."},
                    "crop": {"type": "string", "description": "Primary crop grown, if known."},
                    "category": {"type": "string", "description": "Any other relevant category the farmer mentioned (e.g. 'women farmer', 'SC/ST', 'organic')."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_disaster_relief_options",
            "description": (
                "RAG search shaped toward disaster/crop-loss relief (e.g. PMFBY "
                "crop insurance). Call when the farmer describes a crop loss from "
                "weather, flood, drought, or other disaster and asks about "
                "compensation or relief. Use a calm, direct tone for this answer -- "
                "the farmer may be describing a real loss."
            ),
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "The farmer's description of the loss/disaster and what they're asking."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_subsidy_details",
            "description": (
                "RAG search shaped toward subsidy schemes (fertiliser, seed, farm "
                "equipment/mechanization, drip/sprinkler irrigation, infrastructure). "
                "Call when the farmer asks what financial help exists for a specific "
                "input or piece of equipment."
            ),
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "What the farmer wants a subsidy for, e.g. 'drip irrigation', 'tractor', 'seeds'."}
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
    {
        "type": "function",
        "function": {
            "name": "get_weather_forecast",
            "description": (
                "Get the typical weather for a location over the next N days — rain "
                "chance and amount, how it will feel (humidity/heat), wind risk, "
                "sunlight, and flood/heat-wave risk. This is climatology (what's normal "
                "for this time of year, from 10+ years of NASA POWER satellite data), "
                "NOT a live day-by-day forecast — say 'typically'/'usually expected', "
                "never 'it will rain on Tuesday'. Use this for general weather "
                "questions; use query_spray_window/query_sowing_window/"
                "query_pest_pressure_window instead when the farmer's question is "
                "really about a specific decision (when to spray, when to sow, pest risk)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "district": {"type": "string", "description": "Farmer's district — only if you're actually confident of it. Give just ONE of district/state/pincode, whichever you're most sure about; don't add the others too just to be thorough."},
                    "state": {"type": "string", "description": "Farmer's state — only if you're actually confident of it. Give just ONE of district/state/pincode."},
                    "pincode": {"type": "string", "description": "Farmer's 6-digit pincode — ONLY if the farmer actually stated it. NEVER guess or infer a pincode from a district/city name, even one you're fairly sure of — a wrong-but-plausible-looking pincode silently resolves to a different place with no warning. If you don't have a real pincode the farmer gave you, use district or state instead."},
                    "period": {"type": "integer", "description": "How many days ahead to cover (default 30)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_spray_window",
            "description": (
                "Find the best upcoming window to spray pesticide (needs BOTH dry AND "
                "calm weather — rain washes pesticide off, wind causes drift, so this "
                "checks both, not just rain), which days need no watering because rain "
                "is already expected, and a warning if flood-level rain is coming for "
                "rain-sensitive crops. Call this whenever the farmer asks when to spray, "
                "or whether it's safe to spray soon."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "district": {"type": "string", "description": "Farmer's district — only if you're actually confident of it. Give just ONE of district/state/pincode, whichever you're most sure about; don't add the others too just to be thorough."},
                    "state": {"type": "string", "description": "Farmer's state — only if you're actually confident of it. Give just ONE of district/state/pincode."},
                    "pincode": {"type": "string", "description": "Farmer's 6-digit pincode — ONLY if the farmer actually stated it. NEVER guess or infer a pincode from a district/city name, even one you're fairly sure of — a wrong-but-plausible-looking pincode silently resolves to a different place with no warning. If you don't have a real pincode the farmer gave you, use district or state instead."},
                    "period": {"type": "integer", "description": "How many days ahead to search (default 30)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_sowing_window",
            "description": (
                "Find the best upcoming sowing window for a crop, given whether it "
                "needs dry, moderate, or wet conditions, plus flood-risk and drought-"
                "risk warnings and a soil-moisture note. Call this whenever the farmer "
                "asks when to sow/plant a crop. If you don't already know whether their "
                "crop wants dry, moderate, or wet conditions, use your own agronomic "
                "knowledge of that crop to decide — don't ask the farmer to classify it "
                "themselves."
            ),
            "parameters": {
                "type": "object",
                "required": ["water_need"],
                "properties": {
                    "district": {"type": "string", "description": "Farmer's district — only if you're actually confident of it. Give just ONE of district/state/pincode, whichever you're most sure about; don't add the others too just to be thorough."},
                    "state": {"type": "string", "description": "Farmer's state — only if you're actually confident of it. Give just ONE of district/state/pincode."},
                    "pincode": {"type": "string", "description": "Farmer's 6-digit pincode — ONLY if the farmer actually stated it. NEVER guess or infer a pincode from a district/city name, even one you're fairly sure of — a wrong-but-plausible-looking pincode silently resolves to a different place with no warning. If you don't have a real pincode the farmer gave you, use district or state instead."},
                    "water_need": {
                        "type": "string", "enum": ["dry", "moderate", "wet"],
                        "description": "This crop's water preference, from your own agronomic knowledge "
                                        "(e.g. paddy='wet', groundnut='dry', most vegetables='moderate').",
                    },
                    "months": {"type": "integer", "description": "How many months ahead to search (default 2)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_pest_pressure_window",
            "description": (
                "Find upcoming periods where warm+humid weather typically favors insect "
                "pest activity/breeding, so the farmer knows when to scout their crop "
                "more closely. This is a GENERIC weather-based heuristic (warm+humid "
                "conditions favor pests in general), not a forecast for one named pest "
                "species — say 'extra scouting recommended', never name a specific pest "
                "as guaranteed to appear."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "district": {"type": "string", "description": "Farmer's district — only if you're actually confident of it. Give just ONE of district/state/pincode, whichever you're most sure about; don't add the others too just to be thorough."},
                    "state": {"type": "string", "description": "Farmer's state — only if you're actually confident of it. Give just ONE of district/state/pincode."},
                    "pincode": {"type": "string", "description": "Farmer's 6-digit pincode — ONLY if the farmer actually stated it. NEVER guess or infer a pincode from a district/city name, even one you're fairly sure of — a wrong-but-plausible-looking pincode silently resolves to a different place with no warning. If you don't have a real pincode the farmer gave you, use district or state instead."},
                    "period": {"type": "integer", "description": "How many days ahead to cover (default 30)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_crop_suitability",
            "description": (
                "Get the weather outlook for a crop's growing period together with "
                "risk framing for that specific crop's sensitivities (water need, heat "
                "sensitivity), to help assess whether the coming weather suits it. "
                "Returns the outlook plus notes on what to weigh — YOU still form the "
                "actual suitability judgment from that, this tool doesn't compute a "
                "score (no real crop-yield model exists yet). Call this when the farmer "
                "asks whether now/this season is good for growing a particular crop."
            ),
            "parameters": {
                "type": "object",
                "required": ["water_need"],
                "properties": {
                    "district": {"type": "string", "description": "Farmer's district — only if you're actually confident of it. Give just ONE of district/state/pincode, whichever you're most sure about; don't add the others too just to be thorough."},
                    "state": {"type": "string", "description": "Farmer's state — only if you're actually confident of it. Give just ONE of district/state/pincode."},
                    "pincode": {"type": "string", "description": "Farmer's 6-digit pincode — ONLY if the farmer actually stated it. NEVER guess or infer a pincode from a district/city name, even one you're fairly sure of — a wrong-but-plausible-looking pincode silently resolves to a different place with no warning. If you don't have a real pincode the farmer gave you, use district or state instead."},
                    "water_need": {
                        "type": "string", "enum": ["dry", "moderate", "wet"],
                        "description": "This crop's water preference, from your own agronomic knowledge.",
                    },
                    "heat_sensitive": {"type": "boolean", "description": "Whether this crop is known to be heat-sensitive."},
                    "months": {"type": "integer", "description": "How many months of the growing period to cover (default 2)."},
                },
            },
        },
    },
]

# Static tools (everything except analyze_photo, which run_turn() binds per-call).
_STATIC_TOOL_DISPATCH = {
    "plant_disease_lookup": plant_disease_lookup,
    "plant_entomology_lookup": plant_entomology_lookup,
    "get_treatment_details": get_treatment_details,
    "get_guidelines_and_safety": get_guidelines_and_safety,
    "get_scheme_details": get_scheme_details,
    "match_eligible_schemes": match_eligible_schemes,
    "get_disaster_relief_options": get_disaster_relief_options,
    "get_subsidy_details": get_subsidy_details,
    "pesticide_lookup": pesticide_lookup,
    "get_weather_forecast": get_weather_forecast,
    "query_spray_window": query_spray_window,
    "query_sowing_window": query_sowing_window,
    "query_pest_pressure_window": query_pest_pressure_window,
    "query_crop_suitability": query_crop_suitability,
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
                 keep_alive=-1, temperature=0.2, think=None, max_tool_iterations=5,
                 system_prompt=None):
        self.model = model or config.OLLAMA_MODELS[0]
        # Defaults to the same model as .model (not a separate resident model) -- see
        # DEFAULT_VISION_MODEL's comment above for why that's a memory decision, not just
        # a convenience default.
        self.vision_model = vision_model or self.model
        self.num_ctx = num_ctx if num_ctx is not None else config.OLLAMA_NUM_CTX
        self.keep_alive = keep_alive
        self.temperature = temperature
        # 2026-08-17 real fix: resolved PER AGENT MODEL now, same as system_prompt below --
        # this used to always fall back to config.AGENT_THINK (a single global value tied to
        # config.AGENT_MODEL_CHOICE) regardless of what `model=` was actually passed here. Real
        # bug that produced: passing --agent-model X without ALSO manually passing a matching
        # --agent-think meant X silently got whatever think level the STATIC default model
        # happened to be tuned for, not X's own -- e.g. LFM2.5-VL-1.6B (registry think=None)
        # would have gotten qwen3.5:2b's "medium" if qwen3.5:2b was still AGENT_MODEL_CHOICE at
        # the time. `.get("think", config.AGENT_THINK)` only falls back to the global default
        # when `self.model` has NO registry entry at all -- a model that IS registered with an
        # explicit think=None (like LFM2.5-VL-1.6B) correctly gets None, not the fallback,
        # since dict.get() only uses its default for a MISSING key, not a present key whose
        # value happens to be None. Explicit `think=` (not None) still always wins, same as
        # before -- this only changes what "unset" resolves to.
        if think is not None:
            self.think = think
        else:
            self.think = config.AVAILABLE_AGENT_MODELS.get(self.model, {}).get("think", config.AGENT_THINK)
        self.max_tool_iterations = max_tool_iterations
        # 2026-08-17: resolved PER AGENT MODEL, not a single hardcoded constant anymore -- see
        # prompts.py's own module docstring for the real reason (a real Jetson bench found
        # LFM2.5-VL-1.6B needs a stronger reminder about calling analyze_photo first than
        # qwen3.5:2b does). Explicit `system_prompt=` always wins (e.g. a test harness trying
        # something ad hoc); otherwise look up this model's own entry in
        # config.AVAILABLE_AGENT_MODELS, default to "default" (=SYSTEM_PROMPT, unchanged) if
        # the model has no entry or no "system_prompt" key -- so an unrecognized --agent-model
        # override never silently gets no system prompt at all, it just gets the same one
        # every model used before this change.
        if system_prompt is not None:
            self.system_prompt = system_prompt
        else:
            prompt_key = config.AVAILABLE_AGENT_MODELS.get(self.model, {}).get("system_prompt", "default")
            self.system_prompt = SYSTEM_PROMPTS.get(prompt_key, SYSTEM_PROMPT)
        self.last_tool_calls = []  # populated fresh by each run_turn() call -- see its own docstring
        # Real, evidence-based trigger (2026-08-14) -- a real chained 10-turn test hit
        # prompt_eval_count=32621 of this model's 32768-token num_ctx by turn 8, causing the
        # model to return a completely empty final answer (documented failure mode, see
        # run_turn()'s own comment) right before a separate real memory-exhaustion crash. Not
        # just a hint -- see _compact_context_if_needed()'s own docstring for the mechanism
        # this drives.
        self._last_context_tokens = 0

    def _chat_options(self):
        return {"num_ctx": self.num_ctx, "temperature": self.temperature}

    def _build_dispatch(self, image_path, user_text=None):
        """analyze_photo needs this turn's image_path bound in -- everything else is static.

        `user_text` (2026-08-14): this turn's real farmer text, bound in the same way as
        `image_path` -- NOT a tool-call argument the model itself has to author, so it costs
        nothing extra in the tool-calling model's own generation. Passed straight through to
        `analyze_photo_hybrid`, which caps its length before it ever reaches the vision
        prompt (see photo_analysis.py's `_USER_CONTEXT_MAX_CHARS`) -- so it's safe to pass the
        real, untrimmed turn text here rather than asking the tool-calling model to compose a
        separate summary (which would be an extra thing for it to get right, for a saving that
        only mattered if we hadn't capped it downstream anyway)."""
        def _analyze_photo(focus_question: str = "what is wrong or notable in this photo") -> str:
            # 2026-08-14: NOT passing think=self.think here anymore -- analyze_photo_unified
            # now hardcodes think=False internally regardless of what's passed (see its own
            # docstring), after a real 21m34s production incident traced to this call
            # inheriting the agent's think="medium" default. Leaving `self.think` out here too
            # so a future reader doesn't assume this line still controls anything.
            return _analyze_photo_impl(
                image_path, focus_question,
                user_context=user_text,
                model=self.vision_model, keep_alive=self.keep_alive, num_ctx=self.num_ctx,
                temperature=self.temperature,
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

    @staticmethod
    def _role_of(m):
        return m.get("role") if isinstance(m, dict) else getattr(m, "role", None)

    @staticmethod
    def _content_of(m):
        return m.get("content") if isinstance(m, dict) else getattr(m, "content", None)

    def _find_turn_boundaries(self, messages, start_index):
        """Returns [(start, end), ...] index pairs, each spanning ONE whole real turn --
        starting at a 'user'-role message, running up to (not including) the next 'user'
        message or end of list. Never splits mid-turn, so an assistant(tool_calls) message and
        its tool-result message(s) are always kept or dropped together -- the real constraint
        every context-compaction writeup agrees on (a split tool_call/tool_result pair is
        rejected by the model API, not just messy)."""
        boundaries = []
        turn_start = None
        for i in range(start_index, len(messages)):
            if self._role_of(messages[i]) == "user":
                if turn_start is not None:
                    boundaries.append((turn_start, i))
                turn_start = i
        if turn_start is not None:
            boundaries.append((turn_start, len(messages)))
        return boundaries

    def _extract_qa_text(self, messages, start, end):
        """Pulls just the farmer's question and the agent's final answer out of one whole
        turn -- skips every intermediate tool_calls/tool-result message (this agent's own
        reasoning scaffolding), matching the real request behind this feature: keep only the
        Q&A when a turn ages out of the verbatim tail, not the tool-calling detail. Both are
        already real English text -- `messages` only ever holds the post-NMT-in/pre-NMT-out
        English content (translation happens outside this class, see run_turn()'s own
        docstring), so there's no language mismatch to worry about here."""
        question = self._content_of(messages[start]) or ""
        answer = ""
        for i in range(end - 1, start, -1):
            if self._role_of(messages[i]) == "assistant":
                content = self._content_of(messages[i])
                if content:
                    answer = content
                    break
        return question, answer

    def _compact_context_if_needed(self, messages, verbose=True):
        """2026-08-14: real fix for a real incident, not a preventive guess -- a real 10-turn
        chained conversation test hit `prompt_eval_count=32621` of this model's 32768-token
        `num_ctx` by turn 8 (each real turn here is image analysis + multiple RAG tool calls +
        a long answer, averaging ~4078 tokens/turn, not the handful of tokens a plain text
        chatbot turn costs), and the model's response came back completely empty -- a real,
        previously-documented qwen3.5 failure mode this project already knew could happen near
        the context ceiling, now confirmed as the actual cause of a real failure, not a
        hypothetical.

        Design, informed by real research (not guessed): the standard production pattern for
        this is a hybrid -- keep the most recent N turns verbatim (a sliding window), compress
        everything older into a running summary, system prompt fixed at the top. The one
        universal constraint every real implementation of this gets a bug report for if they
        get it wrong: an assistant(tool_calls) message and its tool-result message(s) must
        never be split apart -- see _find_turn_boundaries()'s own docstring. This implementation
        only ever keeps or drops WHOLE turns, so that's structurally impossible here.

        Deliberately EXTRACTIVE, not a real LLM-generated summary (ConversationSummaryMemory-
        style): the standard "ask the model to summarize the old turns" approach costs a real
        extra generation call every time it fires -- real GPU time and memory pressure on a
        device already fighting both. Instead, this just concatenates each aged-out turn's
        real question + real final answer as plain text -- zero extra model calls, so
        compaction is a fast in-memory string operation, not something that needs a "this may
        take a few minutes" warning to the farmer -- it doesn't.

        Does NOT touch or lose any data needed for a full session transcript/DB log (see
        pocketinfer's SESSION_LOGGING_PLAN.md) -- that's built independently, per-turn, by the
        caller (gramsahayak_app.py), not derived from this `messages` list, so a farmer's full
        session is always recoverable there regardless of what gets compacted here for the
        model's own sake.

        Only ever called between turns (top of run_turn(), before this turn's own new user
        message is appended) -- never mid-turn, so there's no risk of compacting away a turn
        that's still in progress."""
        if not messages or self._last_context_tokens < CONTEXT_COMPACTION_THRESHOLD_TOKENS:
            return messages

        has_summary = (
            len(messages) > 2
            and self._role_of(messages[1]) == "user"
            and str(self._content_of(messages[1]) or "").startswith(_CONTEXT_SUMMARY_MARKER)
        )
        turn_start_index = 3 if has_summary else 1
        turns = self._find_turn_boundaries(messages, turn_start_index)
        if len(turns) <= CONTEXT_COMPACTION_KEEP_LAST_N_TURNS:
            # Nothing old enough to drop yet (e.g. the ceiling was reached mostly via one or
            # two very heavy turns, not many small ones) -- re-checked at the start of every
            # future turn, so this just waits one more turn rather than compacting nothing.
            return messages

        turns_to_compact = turns[:-CONTEXT_COMPACTION_KEEP_LAST_N_TURNS]
        turns_to_keep = turns[-CONTEXT_COMPACTION_KEEP_LAST_N_TURNS:]

        new_qa_blocks = []
        for start, end in turns_to_compact:
            q, a = self._extract_qa_text(messages, start, end)
            new_qa_blocks.append(f"Farmer asked: {q}\nYou answered: {a}")

        if has_summary:
            summary_text = self._content_of(messages[1]) + "\n\n" + "\n\n".join(new_qa_blocks)
        else:
            summary_text = (
                f"{_CONTEXT_SUMMARY_MARKER} (condensed -- earlier tool calls/reasoning "
                "omitted, just the real questions and answers so far, so you still remember "
                "what's already been discussed):\n\n" + "\n\n".join(new_qa_blocks)
            )

        kept_messages = []
        for start, end in turns_to_keep:
            kept_messages.extend(messages[start:end])

        new_messages = (
            [messages[0]]  # system prompt, unchanged
            + [
                {"role": "user", "content": summary_text},
                {"role": "assistant", "content": "Understood, continuing from where we left off."},
            ]
            + kept_messages
        )
        if verbose:
            print(f"    [context] compacted {len(turns_to_compact)} older turn(s) into the "
                  f"running summary (was {self._last_context_tokens} tok, kept last "
                  f"{CONTEXT_COMPACTION_KEEP_LAST_N_TURNS} turn(s) verbatim)")
        return new_messages

    def run_turn(self, user_text, image_path=None, messages=None, verbose=True, status_cb=None):
        """Runs one full tool-calling turn (up to max_tool_iterations round-trips) and
        returns the updated `messages` list -- pass it back in as `messages=` for a
        multi-turn conversation, same shape as ollama.chat's own message list.

        2026-08-14: also records `self.last_tool_calls` -- a list of {"name", "elapsed_s"}
        for every real tool call this turn made, in order, overwritten fresh at the start of
        each run_turn() call. Not part of the return value (keeps this method's signature
        unchanged for every existing caller, e.g. test_orchestrated_pipeline.py's
        `turn_messages = agent.run_turn(...)`) -- read `agent.last_tool_calls` right after
        run_turn() returns instead. Built for real per-tool-call timing/count instrumentation
        (test_image_pipeline.py) without adding a synthetic wrapper around dispatch from
        outside this class.

        `status_cb` (2026-08-14, optional): `status_cb(stage, tool_name=None, variant_index=0)`,
        called in REAL TIME right before each real stage of this turn -- "agent_thinking"
        before the turn's first ollama.chat() call, "agent_reviewing" before a mid-loop one,
        "agent_finalizing" before the one forced-final call (see the `else` branch below --
        the ONE point in this loop where we know FOR CERTAIN the next call produces the final
        answer, not another tool decision), "tool" (with `tool_name` set) right before each
        real tool actually runs. Lets a caller (gramsahayak_app.py) show a live, farmer-facing
        status message (get_status_message()) on the device screen DURING a turn's real
        60-150s+ processing time, not just a static "working..." the whole time. A caller that
        never passes this pays nothing extra -- `status_cb is None` is checked before every
        call. Any exception `status_cb` itself raises is swallowed, not re-raised -- a broken
        display callback must never take down a real turn.

        `variant_index` (2026-08-16): a RANDOM pick (pick_status_variant()) among this key's
        real phrasings, never immediately repeating the one just used for the same key THIS
        turn (a fresh, per-turn tracking dict -- a tool called twice in the same turn with
        different real arguments gets two different clips, not the identical one repeated).

        Also fires two NEW real-time-only stages via a background watchdog, not a fixed
        pre-turn schedule: "agent_working_followup" / "agent_finalizing_followup", if any
        single ollama.chat() call (mid-loop or the forced-final one, respectively) runs past
        `_LONG_CALL_THRESHOLD_SEC` -- a live "still on it" cue for the genuine long-tail case
        instead of a stale status sitting through an outlier-slow call."""
        self.last_tool_calls = []
        dispatch = self._build_dispatch(image_path, user_text)
        # 2026-08-23: voice-only turns (no new photo this turn) withhold analyze_photo --
        # real device logs showed the model calling analyze_photo({}) on such turns anyway
        # (~3s/turn: an ollama vision round-trip that can't do anything useful), and its
        # ~380-token schema description inflated every prefill for nothing. Removed from
        # BOTH the schema list the model sees and the dispatch dict (code view == model
        # view; its own "No image was attached" guard stays for direct API callers/tests).
        # Multi-turn note: prior turns' photo analyses live in history text, so a
        # no-new-photo follow-up loses nothing.
        if image_path:
            turn_tools = TOOLS
        else:
            turn_tools = [t for t in TOOLS if t["function"]["name"] != "analyze_photo"]
            dispatch.pop("analyze_photo", None)
            print(f"    [agent] voice-only turn -- analyze_photo withheld "
                  f"({len(TOOLS)} -> {len(turn_tools)} tools)", flush=True)
        _status_last_variant = {}  # key ("agent_thinking"/"tool:<name>"/...) -> last variant_index used this turn

        def _status(stage, tool_name=None):
            if status_cb is None:
                return
            key = f"tool:{tool_name}" if stage == "tool" and tool_name else stage
            variant_index = pick_status_variant(key, _status_last_variant)
            try:
                status_cb(stage, tool_name, variant_index)
            except Exception as exc:
                if verbose:
                    print(f"    [status_cb] failed ({exc!r}) -- ignoring, turn continues")

        def _chat_with_followup(followup_stage, **chat_kwargs):
            """Wraps a real ollama.chat() call with a background watchdog that fires ONE
            extra `_status(followup_stage)` if the call is still running after
            `_LONG_CALL_THRESHOLD_SEC` -- real per-iteration gen times ranged 0.6-28s+ in
            actual Jetson testing (THINKING_MODE_RESULTS.md), so a fixed pre-call status alone
            can sit stale through a genuinely slow outlier. Doesn't change the call itself --
            still fully blocking/synchronous (no streaming) -- just narrates a long wait
            better if one happens. The watchdog thread is always cancelled (via `done.set()`)
            before this returns, whether or not it fired."""
            done = threading.Event()

            def _watchdog():
                if not done.wait(timeout=_LONG_CALL_THRESHOLD_SEC):
                    _status(followup_stage)

            threading.Thread(target=_watchdog, daemon=True).start()
            try:
                return ollama.chat(**chat_kwargs)
            finally:
                done.set()

        if messages is None:
            messages = [{"role": "system", "content": self.system_prompt}]
        else:
            # Real threshold check, based on the PREVIOUS turn's actual token count -- see
            # _compact_context_if_needed()'s own docstring. Only meaningful for an ongoing
            # conversation (an already-None messages list has nothing to compact yet).
            messages = self._compact_context_if_needed(messages, verbose)

        user_content = user_text
        if image_path:
            user_content += "\n\n[A photo is attached to this message.]"
        messages.append({"role": "user", "content": user_content})

        turn_start = time.perf_counter()

        for iteration in range(1, self.max_tool_iterations + 1):
            # iteration 1: still working out what the question needs, nothing back yet.
            # iteration 2+: at least one real tool result already in `messages` -- reviewing
            # it and deciding the next real step, a genuinely different moment (see
            # build_status_messages.py's own comment on "agent_reviewing" for why this split
            # exists -- real test found "agent_thinking" alone fired 6x in one turn).
            _status("agent_thinking" if iteration == 1 else "agent_reviewing")
            response = _chat_with_followup(
                "agent_working_followup",
                model=self.model, messages=messages, tools=turn_tools,
                keep_alive=self.keep_alive, options=self._chat_options(),
                stream=False, think=self.think,
            )
            messages.append(response.message)
            self._print_timing(iteration, response, verbose)
            # Real cumulative size of THIS call's prompt+response -- read by the next
            # run_turn() call to decide whether to compact (see _compact_context_if_needed()).
            # Ollama's own count, not an estimate.
            self._last_context_tokens = (response.prompt_eval_count or 0) + (response.eval_count or 0)

            if not response.message.tool_calls:
                break

            for call in response.message.tool_calls:
                name = call.function.name
                args = call.function.arguments or {}
                _status("tool", name)
                fn = dispatch.get(name)
                _tool_t0 = time.perf_counter()
                if fn is None:
                    result = {"error": f"unknown tool '{name}'"}
                else:
                    try:
                        result = fn(**args)
                    except Exception as exc:
                        result = {"error": str(exc)}
                tool_elapsed = time.perf_counter() - _tool_t0
                self.last_tool_calls.append({"name": name, "elapsed_s": tool_elapsed})
                if verbose:
                    print(f"    -> {name}({args}) -> {json.dumps(result)[:160]} [{tool_elapsed:.2f}s]")
                content = result if isinstance(result, str) else json.dumps(result)
                messages.append({"role": "tool", "tool_name": name, "content": content})
        else:
            messages.append({
                "role": "user",
                "content": "You are out of tool calls for this turn — answer now with what you already know.",
            })
            # 2026-08-16: was "agent_reviewing" -- this branch only runs after the loop
            # exhausted every iteration, i.e. real tool results already exist in `messages`
            # AND no more tool calls are allowed, so this call is DEFINITELY producing the
            # final answer, not another tool decision. The one place in this whole loop where
            # that's actually knowable in advance -- see status_cb's own docstring above and
            # "agent_finalizing"'s entry in build_status_messages.py for why this couldn't be
            # extended to the (much more common) mid-loop case too.
            _status("agent_finalizing")
            # 2026-08-23: tools=None here, was TOOLS. Real failure on qwen3.5:0.8b
            # (empty-answer incident): after two rewarded tool-call rounds, the model --
            # still offered all 15 tools on this "answer now" call -- emitted a THIRD
            # pesticide_lookup instead of prose. Nothing executes tool_calls after the
            # loop and the pipeline reads turn_messages[-1].content verbatim, so that
            # response silently became an empty answer. Removing the tools removes the
            # temptation: this call's only possible job is producing text. Also makes
            # the prompt slightly cheaper (no tool schemas). The normal path -- the
            # model answering before iterations run out -- never touches this branch.
            response = _chat_with_followup(
                "agent_finalizing_followup",
                model=self.model, messages=messages, tools=None,
                keep_alive=self.keep_alive, options=self._chat_options(),
                stream=False, think=self.think,
            )
            messages.append(response.message)
            self._print_timing("final", response, verbose)
            self._last_context_tokens = (response.prompt_eval_count or 0) + (response.eval_count or 0)

        # ---- final-answer guard (2026-08-23) --------------------------------------
        # The pipeline reads turn_messages[-1].content verbatim, so an empty .content
        # here IS the app's "NO ANSWER PRODUCED" path. Two confirmed/possible causes:
        # the model emitted a tool call nobody executes after the loop, or everything
        # went into the thinking channel and generation ended with no content at all.
        # Either way this used to fail SILENTLY -- log exactly what came back, then
        # retry once with tools removed and a plain-text-only instruction appended
        # (a changed context suffix breaks a repeat of the same generation).
        _final_msg = messages[-1]
        if not str(self._content_of(_final_msg) or "").strip():
            _tc = getattr(_final_msg, "tool_calls", None) or []
            _names = [getattr(getattr(c, "function", None), "name", "?") for c in _tc]
            _th = getattr(_final_msg, "thinking", None)
            print(f"    [agent] FINAL MESSAGE EMPTY: tool_calls={_names} "
                  f"thinking_chars={len(_th) if _th else 0} "
                  f"-- retrying once without tools", flush=True)
            messages.append({"role": "user", "content":
                             "Respond now in plain text only — no more tool calls. "
                             "Answer the farmer's question directly with what you "
                             "already know."})
            _status("agent_finalizing")
            response = _chat_with_followup(
                "agent_finalizing_retry",
                model=self.model, messages=messages, tools=None,
                keep_alive=self.keep_alive, options=self._chat_options(),
                stream=False, think=self.think,
            )
            messages.append(response.message)
            self._print_timing("final-retry", response, verbose)
            if not str(self._content_of(response.message) or "").strip():
                print("    [agent] final-retry ALSO came back empty -- giving up; "
                      "the turn will surface as NO ANSWER PRODUCED", flush=True)
            self._last_context_tokens = ((response.prompt_eval_count or 0)
                                         + (response.eval_count or 0))

        if verbose:
            print(f"    agent turn wall-clock: {time.perf_counter() - turn_start:.2f}s")

        return messages
