"""One-time build script: translates STATUS_MESSAGES_EN (below) through this project's own
real NMT engine (models/nmt/model_loader.py -- the same IndicTrans2 model the live pipeline
uses, not a guess/hand-translation) into all 12 real device languages, and writes the baked-in
preset config file `agent/status_messages.py` that `agent/agent.py`'s
`run_turn(status_cb=...)` and gramsahayak_app.py actually read at runtime.

Why baked-in presets, not a live translation call per status update: the whole point of a
status message is to show up INSTANTLY the moment a stage/tool starts -- an extra real NMT
call per status update would add real latency for a farmer-facing UI cue, working against
its own purpose. Translate once, here, offline; read a plain dict at runtime (zero model
calls, zero real cost per display).

2026-08-16, four rounds of real feedback shaped this content:
  1. "it looks robotic, kinda short blasts... we want a real-time vibe" -- each key now maps
     to a LIST of phrasings (was one stiff string). Picked RANDOMLY at runtime (agent.py's
     `pick_status_variant()`), not cycled in a fixed order, and never immediately repeated for
     the same key -- see that function's own docstring.
  2. "if the final answer is taking way too long... can we add some content there" -- two NEW
     keys, `agent_working_followup` (generic) and `agent_finalizing_followup` (specifically
     the final-answer-generation window), fired by a real background watchdog in
     agent.py's run_turn() if any single ollama.chat() call runs past a real threshold (see
     `_LONG_CALL_THRESHOLD_SEC` there).
  3. "have wording genuine to the tool use... instead of 'looking for treatment' it can be
     casual like 'we will now look for the best treatment options... I'll search the database
     for this now to gather more details rather than answer blind'" -- tool phrasings now
     genuinely explain WHAT the tool does and WHY (real data instead of a guess), not just a
     generic verb+noun label. Kept short enough to still be a quick spoken clip, not a lecture.
  4. "'listening to your question' on ASR is kinda whack... can't say 'nice question' though,
     this is a farmer's helper, has to stay on point... generic stages need more than 5-8
     variety, they fire every single turn." Two real, distinct constraints, not in tension:
     authentic/human wording is NOT the same as chatty/complimentary wording -- a farming
     assistant staying warm but on-point, never praising the question itself. The stages that
     fire on literally every turn (asr/nmt_in/agent_thinking/agent_reviewing/agent_finalizing/
     nmt_out/tts) now carry ~10 variants each so a real multi-turn session doesn't start
     repeating itself. TTS's own wording also now reflects what's actually true at that point
     -- the real research/reasoning is already DONE (agent_finalizing already happened before
     this) -- so it says "I've worked this out, let me read it to you" rather than a generic
     "getting ready to speak", matching the real, honest state of the turn.
  Also: nmt_in/nmt_out wording leans into the real mechanism a little ("translating this into
  AI-speak") rather than a dry "translating..." label -- a farmer-facing nod to what's
  actually happening, kept light/fun per direct request, not overdone.

Run (GX10, real GPU venv -- see image-audio-test-suite/build_suite.py's own docstring for why
this specific venv, not gramsahayak/venv):
    cd gramsahayak && ../venv/bin/python3 agent/build_status_messages.py
"""
import json
import os
import sys

_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_AGENT_DIR)
sys.path.insert(0, _ROOT_DIR)

from models.nmt.model_loader import NMTEngine  # noqa: E402

# Keys match exactly what agent.py's status_cb / gramsahayak_app.py pass: pipeline stages by
# name, and tool status keyed "tool:<tool_name>" for every real tool in agent.py's TOOLS list
# (see that file's own "name" fields -- kept in sync by hand, not derived automatically,
# since TOOLS is a static schema list, not something this build script should import agent.py
# itself just to read 15 strings out of -- that would pull in ollama/ordinal heavy deps for a
# translation-only build step).
STATUS_MESSAGES_EN = {
    # --- pipeline stages (non-tool). These fire on literally every turn, so they carry the
    # most real variety (~10 each) -- a real multi-turn session would otherwise hear the exact
    # same "listening..."/"translating..." cue every single time, which is its own kind of
    # robotic even with the wording itself improved. Deliberately warm but NOT complimentary
    # (never "nice question" or similar) -- this is a farmer's working tool, not a chatbot, so
    # authenticity means sounding like a real person focused on helping, not making small talk. ---
    "asr": [
        "Alright, I'm listening — go ahead and ask your question.",
        "Go ahead, I'm listening carefully...",
        "I'm here, take your time and tell me...",
        "Okay, go ahead, I'm listening...",
        "Listening now — ask away whenever you're ready...",
        "I'm ready, go ahead and speak...",
        "Alright, tell me what's going on...",
        "Go ahead, I'm here to help...",
        "I'm listening, take your time...",
        "Okay, go ahead — I'm ready to help...",
    ],
    "nmt_in": [
        "Let me translate this into AI-speak for a moment, so nothing gets missed...",
        "Just turning your words into something the AI can properly work with...",
        "One moment — getting this ready so the AI understands it exactly right...",
        "Let me put this into the AI's own language real quick...",
        "Translating this over carefully, so your question comes through clearly...",
        "Give me a second to get this understood properly...",
        "Let me make sure this comes through exactly as you meant it...",
        "One moment, making sure nothing gets lost in translation...",
        "Let me get this ready for the AI to work with...",
        "Just a second — translating this so it's understood properly...",
    ],
    "agent_thinking": [
        "Let me think this through properly before I decide what to check...",
        "Okay, working out the best way to look into your question...",
        "Give me a moment to figure out exactly what you need...",
        "Let me work out what I actually need to check here...",
        "Thinking through the best way to get you a real answer...",
        "Let me figure out the right way to approach this...",
        "Working out what I need to look into for you...",
        "Give me a second to plan out how to help with this...",
        "Let me think about the best way to handle this...",
        "Working through the right approach for your question...",
    ],
    # 2026-08-14: split from the single "agent_thinking" after real testing showed it firing
    # 6 times in one turn (once per ollama.chat() call -- before every tool AND after every
    # tool result comes back), dominating screen time since the model's own reasoning between
    # tool calls (4-33s per real test) is slower than the tool calls themselves (0.09-5.9s).
    # Genuinely different moments, not just variety for its own sake: this fires on the
    # SECOND+ call of a turn, when at least one real tool result is already in hand -- the
    # agent is reviewing what it found and deciding the next real step (call another tool, or
    # answer), not still parsing the raw question for the first time.
    "agent_reviewing": [
        "Alright, let me weigh what I've found so far before deciding what's next...",
        "Just going through everything I've gathered, to see if I need more...",
        "Let me check if what I've found is enough, or if I should dig further...",
        "Looking over what's come back so far before I go any further...",
        "Making sense of everything I've found before the next step...",
        "Let me see what I've got, and figure out what's still missing...",
        "Going through the results so far to decide the next step...",
        "Let me check what I've learned before continuing...",
        "Reviewing everything I've found before I move on...",
        "Let me weigh this properly before deciding what comes next...",
    ],
    # 2026-08-16, new: the ONE place in agent.py's run_turn() where we know FOR CERTAIN the
    # next call is producing the final answer, not deciding on another tool (the forced-final
    # branch after max_tool_iterations is exhausted -- see run_turn()'s own comment). The
    # ordinary mid-loop case (model decides on its own to stop calling tools) can't get this
    # treatment for real -- by the time we'd know, the answer's already been generated
    # synchronously, there's no gap left to fill with a status update.
    "agent_finalizing": [
        "I've checked everything I can — let me put together a proper, detailed answer now...",
        "Okay, I have what I need — writing this up as a full answer for you...",
        "All the checking's done — let me pull this into a real answer, not a guess...",
        "I've got everything I need now — putting it all together properly for you...",
        "That's everything I can check — now let me answer this the right way...",
        "The research is done — let me collate this into a proper answer for you...",
        "I've got what I need — now let me bring it all together for you...",
        "Everything checks out — let me write up a complete answer now...",
        "I've done the digging — now let me put it into a real answer for you...",
        "All checked — let me get this into a proper, complete answer...",
    ],
    # 2026-08-16, new: fired by a real background watchdog (agent.py's run_turn(), see
    # `_LONG_CALL_THRESHOLD_SEC`) if ANY ollama.chat() call in the mid-loop tool-calling phase
    # (agent_thinking or agent_reviewing) is taking noticeably longer than typical. A real,
    # live "still on it" cue for the genuine long-tail case, not a fixed pre-announcement. Kept
    # smaller than the every-turn stages above since this only fires on the real outlier-slow
    # call, not every turn.
    "agent_working_followup": [
        "Sorry for the wait, still working through this...",
        "This one's taking a bit longer, bear with me...",
        "Still working through this properly, almost there...",
        "Hang tight, just need a little more time here...",
        "Still on it — this one's just taking a bit longer than usual...",
    ],
    # 2026-08-16, new: same watchdog mechanism as agent_working_followup, but specific to the
    # forced-final call -- directly answers a real ask ("if the final answer is taking way too
    # long... can we add some content there too").
    "agent_finalizing_followup": [
        "This one needs a bit more detail — almost there, hang tight...",
        "Still writing up a thorough answer for you, won't be long...",
        "Just making sure this answer is complete before I give it to you...",
        "Almost done — I want to get this answer right for you...",
        "Still putting the finishing touches on a proper answer...",
    ],
    "nmt_out": [
        "Let me translate this back into your language now, so it's clear for you...",
        "Almost there — turning this answer into your own words...",
        "Just translating this back carefully, so nothing gets lost...",
        "Let me put this answer into your language properly now...",
        "One moment — bringing this answer back to you, in your language...",
        "Let me get this answer into words you'll understand clearly...",
        "Translating this back now, so it makes sense to you...",
        "Just a moment — putting this into your own language...",
        "Let me bring this answer back to you properly...",
        "One moment, translating your answer back now...",
    ],
    # 2026-08-16 rewrite: real feedback -- TTS has a real ~4-12s load/synthesis wait (see
    # THINKING_MODE_RESULTS.md/GEMMA4_E2B_ROBUSTNESS_RESULTS.md for real numbers), and the
    # wording should reflect what's ACTUALLY true at this point in the turn: the real
    # research/reasoning already finished (agent_finalizing already happened before this
    # stage) -- so this says "I've worked it out, let me read it to you" rather than a vaguer
    # "getting ready to speak", which undersold how much was already genuinely done.
    "tts": [
        "I've got the answer worked out — let me get it ready to tell you now...",
        "Alright, I've done the research — let me collate this and speak it out to you...",
        "Your answer's ready — just preparing to read it out to you now...",
        "I've worked this all out — let me get it ready to say out loud...",
        "Everything's sorted — just setting this up to speak to you now...",
        "The answer's ready — one moment while I get it ready to speak...",
        "I've put it all together — let me read this out to you now...",
        "Got your answer ready — just a moment while I prepare to speak it...",
        "All done on my end — let me get this ready to tell you now...",
        "Answer's ready — setting up to speak this out to you now...",
    ],
    "fallback": [
        "Still working on your question, one moment...",
        "Bear with me, working on this for you...",
        "Just a moment, still on it...",
        "Working through this properly for you...",
        "Hang on, almost there...",
        "Still on it, one moment more...",
        "A little more time needed, bear with me...",
        "Working on this, almost done...",
    ],
    # --- tool calls -- one per real tool in agent.py's TOOLS list. 2026-08-16 rewrite: real
    # feedback was to make these genuinely explain what the tool does and WHY, not just a
    # generic verb+noun label ("instead of 'looking for treatment', 'we will now look for the
    # best treatment options for the issues found — I'll search the database for this now to
    # gather more details rather than answer blind'"). 6 variants each -- tools are the ones
    # most likely to get called more than once in a real turn (a real, valid case -- same
    # tool, different real arguments), so they get the most real variety. ---
    "tool:analyze_photo": [
        "Let me take a proper look at your photo, so I can see the real symptoms myself...",
        "Looking closely at the picture you sent, instead of guessing from words alone...",
        "Taking another good look at this photo, to be sure I've got it right...",
        "Studying the photo carefully — a real look tells me more than a description...",
        "Let me examine this image properly before I say anything...",
        "Having a closer look at the picture, so I don't miss anything...",
    ],
    "tool:plant_disease_lookup": [
        "I'll search our disease records now for something that actually matches this...",
        "Let me check real plant-disease records instead of guessing what this is...",
        "Comparing this against known diseases, so I give you a real match, not a guess...",
        "Searching through our disease database for the closest real match...",
        "Let me look this up properly against known plant diseases first...",
        "Checking our records a bit further to be sure about this diagnosis...",
    ],
    "tool:plant_entomology_lookup": [
        "Let me look this pest up properly, instead of guessing what it is...",
        "Checking our real records on this insect before I tell you anything...",
        "Digging into our pest database, so I get this right for you...",
        "Let me search for real details on this bug rather than assume...",
        "Checking what we actually know about this pest first...",
        "Looking into this insect a bit further to be sure...",
    ],
    "tool:get_treatment_details": [
        "I'll now look for the best treatment options for the issue found — checking the real dose, not guessing...",
        "Let me search our database for the exact treatment and dosage, rather than answer blind...",
        "Checking the registered treatment details properly, so the dose I give you is correct...",
        "Let me find the right treatment and exact dose from our real records...",
        "Looking up the proper dosage for this now, instead of estimating...",
        "Checking the treatment details a bit further, to make sure this is accurate...",
    ],
    "tool:get_guidelines_and_safety": [
        "Let me check the real safety guidelines first, so my advice is actually safe to follow...",
        "Making sure this is safe before I tell you anything — checking properly now...",
        "Just double-checking the real safety details, not assuming they're fine...",
        "Let me look into the safety side of this properly first...",
        "Checking safe practice here for real, before I answer...",
        "Making sure I've got the safety guidance right, not guessed...",
    ],
    "tool:pesticide_lookup": [
        "Let me check the real registration details on this pesticide before I answer...",
        "Looking this product up properly, so I don't tell you something wrong...",
        "Checking our records on this pesticide now, rather than assume...",
        "Let me search for the real details on this chemical...",
        "Looking up this product's actual registration status now...",
        "Checking a bit further on this pesticide, to be sure...",
    ],
    "tool:get_scheme_details": [
        "Let me check the real details of this scheme, so I don't tell you something incorrect...",
        "Checking what this government scheme actually offers, not assuming...",
        "Looking into the real terms of this scheme for you now...",
        "Let me search for the actual scheme details, rather than guess...",
        "Checking the details of this scheme properly for you...",
        "Looking further into what this scheme really covers...",
    ],
    "tool:match_eligible_schemes": [
        "Let me search properly to see which schemes you could actually qualify for...",
        "Checking real eligibility details, instead of guessing what might apply to you...",
        "Looking through the schemes carefully to find real matches for your situation...",
        "Let me search for schemes that genuinely fit what you've told me...",
        "Checking which schemes you might really be eligible for now...",
        "Looking a bit further for other schemes that could genuinely apply...",
    ],
    "tool:get_disaster_relief_options": [
        "Let me check what disaster relief is actually available, rather than guess...",
        "Checking real relief options for you now, not assuming what applies...",
        "Looking into genuine relief support for this situation...",
        "Let me search for the actual relief programs that could help...",
        "Checking what real support exists for this kind of loss...",
        "Looking a bit further into disaster relief options for you...",
    ],
    "tool:get_subsidy_details": [
        "Let me check the real subsidy numbers for you, instead of estimating...",
        "Looking into what subsidy support is actually available now...",
        "Checking the real details on this subsidy, so the numbers are correct...",
        "Let me search for the actual subsidy details, rather than guess...",
        "Checking what this subsidy genuinely covers for you...",
        "Looking a little further into this subsidy to be sure...",
    ],
    "tool:get_weather_forecast": [
        "Let me pull up the real weather data for your area, instead of guessing...",
        "Checking the actual forecast now, so this is accurate...",
        "Looking at real weather data ahead, not just a rough idea...",
        "Let me check the genuine forecast for you now...",
        "Pulling up the real conditions ahead for your area...",
        "Checking a bit further into the actual forecast...",
    ],
    "tool:query_spray_window": [
        "Let me check the real weather conditions to find a genuinely safe time to spray...",
        "Checking actual wind and rain data, rather than guess a safe window...",
        "Looking at the real forecast to find you a proper spraying window...",
        "Let me work out the safest time to spray, based on real conditions...",
        "Checking the actual conditions for spraying now...",
        "Looking a bit further for a genuinely better spray window...",
    ],
    "tool:query_sowing_window": [
        "Let me check real weather patterns to find the right time for sowing...",
        "Checking actual conditions, instead of guessing the best sowing time...",
        "Looking into real data to work out good sowing timing for you...",
        "Let me work out the best sowing window from real conditions...",
        "Checking the genuine conditions for sowing now...",
        "Looking a little further for the right sowing time...",
    ],
    "tool:query_pest_pressure_window": [
        "Let me check real seasonal data on pest risk for this time of year...",
        "Checking actual pest-pressure data, rather than guess how risky this is...",
        "Looking into real patterns to see how risky pests are right now...",
        "Let me work out the genuine pest risk for this period...",
        "Checking real data on how likely pests are right now...",
        "Looking a bit further into pest risk, based on real data...",
    ],
    "tool:query_crop_suitability": [
        "Let me check real conditions to see if this crop would actually suit your land...",
        "Checking actual data instead of guessing whether this crop would grow well here...",
        "Looking into real conditions to see how well this crop matches your land...",
        "Let me work out if this crop genuinely fits your conditions...",
        "Checking real suitability data for this crop now...",
        "Looking a bit further into whether this crop would really work here...",
    ],
}

TARGET_LANGUAGES = None  # resolved below from the real, current ASR language list


def _target_languages():
    # 2026-08-16: STATUS_BUILD_LANGUAGES env override (comma-separated codes) -- real ask:
    # "get the Hi and EN one created first... implement in jetson and gx10... do the others
    # in parallel while we test". Lets a fast, scoped pass (e.g. just "hi") run for immediate
    # real testing, with the remaining languages filled in later without blocking that. Unset
    # -> unchanged default behavior (the real, full 12-language ASR list).
    override = os.environ.get("STATUS_BUILD_LANGUAGES")
    if override:
        return [c.strip() for c in override.split(",") if c.strip()]
    from api_server.config import WORKERS
    return list(WORKERS["asr"]["languages"])


def _load_existing_status_messages(out_path):
    """2026-08-16: real incremental-build support -- if status_messages.py already exists
    (e.g. from an earlier hi-only pass), merge new languages INTO it rather than starting from
    a blank dict and losing what a previous scoped run already produced. Safe as long as
    STATUS_MESSAGES_EN's own wording hasn't changed between passes (it's the single source of
    truth for "en" either way, re-written fresh every run) -- if it has changed, re-run this
    script with the full real language list to get a clean, fully consistent rebuild."""
    if not os.path.exists(out_path):
        return {}
    try:
        namespace = {}
        exec(compile(open(out_path, encoding="utf-8").read(), out_path, "exec"), namespace)
        return namespace.get("STATUS_MESSAGES", {})
    except Exception as exc:
        print(f"[BUILD] could not parse existing {out_path} ({exc}) -- starting fresh")
        return {}


def main():
    global TARGET_LANGUAGES
    TARGET_LANGUAGES = _target_languages()
    print(f"[BUILD] target languages this run: {TARGET_LANGUAGES} (STATUS_BUILD_LANGUAGES="
          f"{os.environ.get('STATUS_BUILD_LANGUAGES')!r})")

    out_path = os.path.join(_AGENT_DIR, "status_messages.py")
    result = _load_existing_status_messages(out_path)
    if result:
        print(f"[BUILD] merging into existing build ({len(result)} keys already present)")

    print("[BUILD] loading NMT engine...")
    nmt = NMTEngine()
    nmt.load()

    for key, en_variants in STATUS_MESSAGES_EN.items():
        result.setdefault(key, {})["en"] = list(en_variants)  # always refreshed to current wording
        for lang in TARGET_LANGUAGES:
            translated_variants = []
            for v in en_variants:
                translated = nmt.infer(v, "EN", lang)["translated_text"]
                translated_variants.append(translated)
                print(f"[BUILD] {key} [{lang}] v{len(translated_variants) - 1}: {translated}")
            result[key][lang] = translated_variants

    nmt.unload()

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(
            '"""Preset status messages shown/spoken while a turn is in progress -- one entry '
            'per pipeline stage / real tool, each a LIST of variant phrasings, in en + all 12 '
            'real device languages. Generated by build_status_messages.py via this project\'s '
            'own real NMT engine (IndicTrans2), NOT hand-translated -- re-run that script if '
            'STATUS_MESSAGES_EN there changes or a new tool is added to agent.py\'s TOOLS '
            'list. See agent.py\'s get_status_message() / pick_status_variant() for how this '
            'is actually read at runtime (graceful fallback if a key/language is missing, '
            'never a crash over a missing status string; variant picked RANDOMLY, never an '
            'immediate repeat for the same key).\n"""\n\n'
        )
        f.write("STATUS_MESSAGES = ")
        f.write(json.dumps(result, ensure_ascii=False, indent=4))
        f.write("\n")
    total_variants = sum(len(v) for v in STATUS_MESSAGES_EN.values())
    real_languages_now_present = sorted(set().union(*(entry.keys() for entry in result.values())))
    print(f"\n[BUILD] wrote {out_path} ({len(result)} keys, {total_variants} EN variants, "
          f"this run translated into {TARGET_LANGUAGES}, file now has real data for "
          f"{real_languages_now_present})")


if __name__ == "__main__":
    main()
