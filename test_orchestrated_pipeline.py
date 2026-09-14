"""Full ASR -> NMT -> Agent -> NMT -> TTS pipeline, run through the real gateway
(api_server/gateway.py) with every load/unload decision made by MemoryOrchestrator
(api_server/orchestrator.py) -- i.e. the actual load_balancer_plan.md rules acting on the
actual checkpoints, not a simulation. Every [ORCH] line is a real decision (load, evict,
preload, budget check) with real memory numbers read live from the gateway; every [PIPE]
line is this script's own pipeline progress.

This is gramsahayak/'s own end-to-end validation script -- run it after `setup/
download_models.py` to confirm a fresh install actually works. See gramsahayak/README.md.

Real agent, real tool-calling loop (agent/agent.py's GramSahayakAgent -- same SYSTEM_PROMPT,
same 5 mock + 2 real tools as the original vyoma_v5.ipynb this was extracted from), real ASR
transcription, real NMT translation, real batched TTS synthesis. The Embedder only loads if
the agent actually calls a tool needing vector search -- not exercised by today's mock tools,
but Rule 7 (on-demand only) is implemented and ready for when real retrieval tools replace them.

Run: source venv/bin/activate && cd gramsahayak && python test_orchestrated_pipeline.py --language hi
     python test_orchestrated_pipeline.py --all          # every language back to back, one session
     python test_orchestrated_pipeline.py --language hi --no-play   # save the .wav, skip playback
     python test_orchestrated_pipeline.py --language hi --with-image  # attach the sample photo
        (Q1, the plain pesticide question, has no photo -- the agent asking for one on that
        question is correct behavior, not a bug. --with-image switches to Q2 -- "what's wrong
        with this plant" -- WITH datasets/sample-images/pepper_diseased.png attached, so
        analyze_photo has something real to look at, using q2_<lang>.wav for non-English input.)
     python test_orchestrated_pipeline.py --language hi --stream-tts  # real incremental TTS
        playback over /tts/infer_stream instead of the default blocking /tts/infer -- see
        TTS_HTTP_STREAMING_RESULTS.md. Opt-in, not the default: /tts/infer remains the
        simpler, more proven fallback path if streaming ever causes a real-world problem.
     python test_orchestrated_pipeline.py --weather-conversation --language hi
        # 5-turn conversation: a plain pest question first (no location, no weather tool),
        # THEN weather-tool follow-ups once the farmer volunteers a location -- see
        # crop_weather_turns(). Tests the organic-follow-up prompt guidance and whether the
        # agent asks for a location before guessing. Real growing context across turns.
     python test_orchestrated_pipeline.py --weather-conversation --all
        # same 5-turn conversation, back to back in en/hi/ml/ta.

Audio is played live through this machine's default output device after each turn (via
sounddevice) -- the TTS worker runs in its own subprocess and only returns audio bytes over
HTTP, so playback happens here in the demo script, not inside the worker (--stream-tts is the
one exception: it plays live *during* the /tts/infer_stream call itself, inside
orchestrator.py's own timed TTS stage, not as a separate step afterward). Every turn's audio
is also always saved to sample_audio/pipeline_outputs/orchestrated_<lang>.wav regardless of
--no-play (--stream-tts ignores --no-play -- playback IS the point of that path).
"""
import argparse
import base64
import io
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
import soundfile as sf

try:
    import sounddevice as sd
    _HAS_SOUNDDEVICE = True
except (ImportError, OSError):
    _HAS_SOUNDDEVICE = False

AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AGENTS_DIR)

from api_server import config  # noqa: E402
from api_server import orchestrator as orchestrator_module  # noqa: E402
from api_server.orchestrator import MemoryOrchestrator  # noqa: E402
from agent import GramSahayakAgent  # noqa: E402
# clean_text lives in models/text_clean.py specifically so this import doesn't need torch at
# all -- models.tts_exports's own package __init__ eagerly imports a torch-based Parler class,
# so `from models.tts_exports.streaming import clean_text` would drag torch in as a side
# effect for every run, even one that never uses --stream-tts (the only thing that actually
# needs torch). play_http_stream is imported lazily below, inside _tts_call_streaming(), so
# only a --stream-tts run pays that cost.
from models.text_clean import clean_text  # noqa: E402
# number_expansion is equally torch-free (stdlib + num2words only) -- safe to import here
# for the same reason: the pre-NMT expansion below runs on every turn regardless of engine.
from models.number_expansion import expand_numbers_en  # noqa: E402

GATEWAY = f"http://{config.GATEWAY_HOST}:{config.GATEWAY_PORT}"

LANGUAGES = {
    "en": {"tts_name": "English", "asr_supported": False},
    "hi": {"tts_name": "Hindi", "asr_supported": True},
    "ml": {"tts_name": "Malayalam", "asr_supported": True},
    "ta": {"tts_name": "Tamil", "asr_supported": True},
    # 2026-08-17: added for the real analytics-demo suite (build_analytics_demo_suite.py /
    # run_analytics_demo_suite.py) -- the real ASR/TTS pipeline already supports these (see
    # config.WORKERS["asr"]["languages"]: hi/ta/ml/as/bn/gu/kn/mai/mr/pa/te/ur), this dict just
    # hadn't been extended past the original 4-language test set. Real, confirmed bug found
    # live: run_full_pipeline()'s own `cfg = LANGUAGES[language]` raised a bare KeyError for
    # every one of these three languages on turn 1 of every real session, silently killing
    # 3 of the analytics suite's 6 target languages before this fix.
    "as": {"tts_name": "Assamese", "asr_supported": True},
    "bn": {"tts_name": "Bengali", "asr_supported": True},
    "gu": {"tts_name": "Gujarati", "asr_supported": True},
    "kn": {"tts_name": "Kannada", "asr_supported": True},
    "mai": {"tts_name": "Maithili", "asr_supported": True},
    "mr": {"tts_name": "Marathi", "asr_supported": True},
    "pa": {"tts_name": "Punjabi", "asr_supported": True},
    "te": {"tts_name": "Telugu", "asr_supported": True},
    "ur": {"tts_name": "Urdu", "asr_supported": True},
}

Q1_TEXT_EN = (
    "What are the best pesticides I should use in my small farm to prevent potatoes "
    "from pests and rats?"
)
Q2_TEXT_EN = "What's wrong with this plant, and what should I do about it?"

# 5-turn conversation exercising a non-weather tool THEN weather tools (agent/tools/
# weather_tools/forecast_tools.py), threading real context across turns. Turn 1 is a plain
# crop-problem question with NO location mentioned at all -- deliberately: this is what tests
# the organic-follow-up prompt guidance (does the agent's pest answer end by offering to also
# check weather-driven spray timing?) and, since none of the weather tools have a location yet,
# whether the agent asks for one before calling them rather than guessing. Turn 3 is the only
# turn that varies per language -- a different real place + pincode per language (see
# CROP_TURN3_EN), so all 4 languages are testing genuinely different real locations, not the
# same one translated four ways.
#
# Non-English audio (sample_audio/pipeline_inputs/crop_turn{1..5}_{hi,ml,ta}.wav) was
# synthesized via this project's own NMT (EN->target) + TTS (target text->audio), then
# round-trip-verified through ASR. That round-trip surfaced a real, reproducible limitation
# worth knowing about: this TTS engine doesn't pronounce multi-digit numbers (a 6-digit
# pincode) intelligibly enough for ASR to transcribe them back as digits, in all 3 languages
# tested -- turns 1/2/4/5 transcribe cleanly, turn 3's pincode number specifically does not.
# Left as-is on purpose rather than swapped for something ASR handles better: it's a real,
# honest test of whether the agent's location fallback (the place name in the same sentence)
# saves the conversation when the pincode itself doesn't resolve.
CROP_TURN1_EN = "Something is eating holes in my potato leaves. What pest could this be, and what should I do about it?"
CROP_TURN2_EN = "Yes, please check when is a good time for me to spray."
CROP_TURN3_EN_BY_LANG = {
    "en": "I am in Punjab, my pincode is 143001.",
    "hi": "I am in Bhopal, my pincode is 251001.",
    "ml": "I am in Alappuzha district, my pincode is 688001.",
    "ta": "I am in Coimbatore, Tamil Nadu, my pincode is 641001.",
}
CROP_TURN4_EN = "What is the weather going to be like over the next few weeks?"
CROP_TURN5_EN = "Should I be worried about more pests attacking my potato crop?"


def crop_weather_turns(language: str) -> list[str]:
    return [CROP_TURN1_EN, CROP_TURN2_EN, CROP_TURN3_EN_BY_LANG[language], CROP_TURN4_EN, CROP_TURN5_EN]
# Self-contained within this package (gramsahayak/datasets/sample-images/) -- this file sits
# directly at the package root (AGENTS_DIR == gramsahayak/), one level shallower than
# dev/agents/test_orchestrated_pipeline.py was relative to the wider blue-parrot repo, and
# gramsahayak/ carries its own copy of this fixture rather than reaching outside itself.
SAMPLE_IMAGE_PATH = Path(AGENTS_DIR) / "datasets" / "sample-images" / "pepper_diseased.png"

# 5-turn real-memory stress conversation (2026-08-11) -- image on turn 1, then a real
# follow-up (conversation memory + G1 RAG), a topic-switch to weather (Rule 1 eviction under
# a fresh topic), a spraying follow-up designed to plausibly need BOTH a weather tool
# (query_spray_window) and a G1 RAG tool in the same turn, then another topic-switch to a
# G2 government-scheme question. Audio for hi/ta/ml was pre-synthesized via this project's
# own NMT+TTS (make_multiturn_test_audio.py, run once on GX10) -- see
# sample_audio/multiturn_stress/<lang>/turn<N>.wav; English text below is both the literal
# EN-path query text AND what those audio files were translated from (kept identical on
# purpose, not just similar, so all 4 languages are testing the same real conversation).
MULTITURN_STRESS_EN = [
    "I'm a farmer in Nashik district. My potato plants have these dark spots on the leaves "
    "that seem to be spreading fast. What is this, and what should I do?",
    "How much of that should I use per acre, and how many times do I need to spray it?",
    "What's the weather going to be like in Nashik over the next two weeks?",
    "Given that forecast, is this a good time to spray the potato crop, or should I wait?",
    "Are there any government schemes that could help me get compensation if my crop gets "
    "badly damaged?",
]
MULTITURN_STRESS_IMAGE_PATH = Path(AGENTS_DIR) / "datasets" / "sample-images" / "late-blight-potatoes_file.jpg"


def multiturn_stress_audio_path(language: str, turn_index: int) -> Path:
    """turn_index is 1-based, matching MULTITURN_STRESS_EN's position."""
    return Path(AGENTS_DIR) / "sample_audio" / "multiturn_stress" / language / f"turn{turn_index}.wav"


def print_full_snapshot(orch, label):
    """Full per-component memory breakdown, not just the [ORCH] lines a turn already prints
    inline -- so a crash's LAST successful turn's snapshot is still visible in the log even
    if a later turn never completes. Same shape as rag/test_full_turn_memory.py's own
    end-of-run snapshot block, just callable after every turn instead of only at the end."""
    banner(f"MEMORY SNAPSHOT -- {label}")
    snap = orch.snapshot()
    for name, c in snap["components"].items():
        if c["state"] == "loaded":
            gb = orch._component_bytes(name, snap) / 1e9
            print(f"  {name:10s}: {gb:.3f}GB")
        else:
            print(f"  {name:10s}: {c['state']}")
    print(f"  {'TOTAL':10s}: {snap['total_bytes']/1e9:.3f}GB / {config.MODEL_BUDGET_BYTES/1e9:.1f}GB budget "
          f"({snap['utilization_pct']}%)")
    # Real OS-level reading, not the tracked/synthetic total above -- added after a real
    # confirmed crash where the tracked number looked comfortable (3.14GB/7.0GB) right before
    # the device went down. Watch this across turns for drift the tracked total can't see
    # (OS cache growth, a leftover process, fragmentation) -- see orchestrator.py's snapshot()
    # docstring for the full reasoning.
    print(f"  {'REAL':10s}: used={snap['real_used_bytes']/1e9:.3f}GB "
          f"available={snap['real_available_bytes']/1e9:.3f}GB "
          f"(of {snap['real_total_bytes']/1e9:.2f}GB physical)")


def print_stage_times(stage_times, label):
    """Real per-stage wall-clock for one turn (asr/nmt_in/agent/nmt_out/tts/total) -- see
    run_full_pipeline()'s own stage_times collection. Stages that didn't run this turn
    (e.g. no asr/nmt for language="en") are simply absent, not zero -- printed as '-'."""
    print(f"\n  STAGE TIMES -- {label}")
    order = ["asr_s", "nmt_in_s", "agent_s", "nmt_out_s", "tts_s", "total_s"]
    names = {"asr_s": "ASR", "nmt_in_s": "NMT(in)", "agent_s": "Agent",
             "nmt_out_s": "NMT(out)", "tts_s": "TTS", "total_s": "TOTAL"}
    for key in order:
        if key in stage_times:
            print(f"    {names[key]:10s}: {stage_times[key]:6.2f}s")
        else:
            print(f"    {names[key]:10s}: -")


def banner(title):
    print("\n" + "=" * 88)
    print(title)
    print("=" * 88)


def play_audio(path):
    """2026-08-16, real hard requirement (also applied to gramsahayak_app.py/live_demo*.py):
    "in no case should we have the TTS output not going out" -- previously had zero error
    handling at all, so a real sounddevice failure (this project's own already-documented
    real limitation on actual Jetson hardware -- sounddevice can't always reach the real
    speaker there, see --stream-tts's play_http_stream() path for the real workaround this
    drove) would raise a bare, uncaught exception and crash the WHOLE run over one turn's
    playback, not just that turn. Now: loud, clear failure instead of a crash or silence --
    the audio is still saved to `path` either way, so nothing is actually lost."""
    if not _HAS_SOUNDDEVICE:
        print(f"[PIPE] sounddevice not available -- skipping playback (audio saved at {path})")
        return
    try:
        audio, sr = sf.read(path, dtype="float32")
        print(f"[PIPE] playing audio ({len(audio) / sr:.1f}s)...")
        sd.play(audio, sr)
        sd.wait()
    except Exception as exc:
        print(f"[PIPE] !!! PLAYBACK FAILED ({type(exc).__name__}: {exc}) -- audio is still "
              f"saved at {path}, this is a known real sounddevice-on-Jetson limitation, "
              f"consider --stream-tts's play_http_stream() path instead !!!")


def wait_for_gateway(timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(f"{GATEWAY}/health", timeout=1.0).status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.3)
    return False


class _StatusAudioCounter:
    """2026-08-16, `--log-status`: a real status_cb that logs every real status event fired
    during a run (turn label, stage, tool_name, the exact rendered text) and tallies how many
    of them WOULD have played a clip on a real device vs text-only -- mirrors
    `gramsahayak_app.py`'s and `model_bench/live_demo_with_update.py`'s own `AUDIO_STAGES`
    filter (`{"asr", "agent_thinking", "tool", "tts"}`), duplicated here by hand same as those
    two real call sites are kept in sync with each other -- see either of their own comments.
    Deliberately mute: never invokes aplay/ffplay/any real playback, this only counts+logs
    what a real device run would have played, for a table after the fact."""

    AUDIO_STAGES = {"asr", "agent_thinking", "tool", "tts"}

    def __init__(self, language):
        self.language = language
        self.events = []  # list of dicts: turn_label, stage, tool_name, plays_audio, text, t

    def set_turn(self, turn_label):
        self._turn_label = turn_label

    def __call__(self, stage, tool_name=None, variant_index=0):
        from agent import get_status_message
        text = get_status_message(stage, tool_name, language=self.language, variant_index=variant_index)
        plays_audio = stage in self.AUDIO_STAGES
        self.events.append({
            "turn_label": getattr(self, "_turn_label", None),
            "stage": stage, "tool_name": tool_name, "plays_audio": plays_audio,
            "text": text, "t": time.time(),
        })
        tag = "AUDIO" if plays_audio else "text "
        tool_suffix = f"/{tool_name}" if tool_name else ""
        print(f"    [status:{tag}] {stage}{tool_suffix}: {text}")

    def summary_for_turn(self, turn_label):
        evs = [e for e in self.events if e["turn_label"] == turn_label]
        return len(evs), sum(1 for e in evs if e["plays_audio"])

    def print_summary(self):
        total, audio = len(self.events), sum(1 for e in self.events if e["plays_audio"])
        banner(f"STATUS EVENTS -- {total} total, {audio} would play audio "
               f"({total - audio} text-only)")


def run_full_pipeline(language, orch, agent, play=True, with_image=False, stream_tts=False,
                       messages=None, audio_filename=None, turn_label=None, english_text_override=None,
                       audio_path_override=None, image_path_override=None, evict_nmt_first=True,
                       status_cb=None, tts_stream_cb=None, stream_chunk_opts=None):
    """`status_cb=` (2026-08-16, optional): `status_cb(stage, tool_name=None, variant_index=0)`,
    called at the same 4 real pipeline-stage boundaries gramsahayak_app.py's own `_show_status`
    fires at ("asr", "nmt_in", "nmt_out", "tts"), PLUS threaded straight into
    `agent.run_turn(status_cb=...)` for the agent's own real stage/tool/followup cues -- see
    that method's own docstring. `variant_index` is picked fresh here via
    `agent.pick_status_variant()` for the 4 pipeline-level stages (a fresh, function-local dict,
    so repeated calls across turns still vary -- pass a persistent dict via a closure in the
    caller's own status_cb if turn-to-turn variety matters more than that). Default `None`
    means zero behavior change for every existing caller of this function -- purely additive.

    `messages=` threads a real, growing conversation across multiple calls -- pass the
    returned dict's `"messages"` back in as the next call's `messages=` for a genuine
    follow-up (same shape `GramSahayakAgent.run_turn()` itself uses, see agent/agent.py's own
    docstring). Leave as None for an independent, fresh-context turn (unchanged default
    behavior -- this is what every existing caller of this function still gets).

    `audio_filename=` overrides the default q1/q2-based file selection -- lets a caller pick
    a specific real audio sample per turn (e.g. for a multi-turn follow-up sequence) instead
    of always transcribing the same Q1/Q2 fixture. Ignored for language="en" (no audio step
    at all).

    `english_text_override=` overrides Q1/Q2_TEXT_EN for the language="en" path specifically
    (no audio step exists for English, so there's nothing to transcribe an override into --
    this is the EN-only counterpart to `audio_filename`). Ignored for hi/ml/ta, where the
    real query always comes from actually transcribing+translating `audio_filename`'s audio,
    never from hardcoded text -- that's the actual thing being tested on those paths.

    `audio_path_override=`/`image_path_override=` -- full-path escape hatches for callers
    whose fixtures don't live under the fixed `sample_audio/pipeline_inputs/`
    (`audio_filename`) / `SAMPLE_IMAGE_PATH` (`with_image`) conventions those two assume --
    e.g. test_multiturn_stress's own per-language/per-turn audio layout. When given, these
    take priority over `audio_filename`/`with_image` respectively; leave both None for
    unchanged existing behavior.

    `tts_stream_cb=` (2026-08-22, optional): switches this turn's TTS from blocking
    /tts/infer (whole answer synthesized, THEN returned) to /tts/infer_stream, calling
    `tts_stream_cb(wav_bytes, sample_rate, chunk_index, meta)` once per synthesized chunk,
    AS it finishes, so the caller can start playing while later chunks still generate.
    `meta` is the worker's chunk dict plus `arrive_s` = seconds from POST to this chunk's
    arrival (client-measured; lets a caller reconstruct true time-to-first-audio). The
    callback runs on THIS function's thread inside the NDJSON read loop: it may block
    (that is the intended flow-control backpressure into the HTTP reader), and it may
    raise (e.g. the caller's TurnCancelled) to abort the turn mid-TTS -- the exception
    propagates exactly like one raised from status_cb does elsewhere. The full archive
    .wav is still assembled and returned unchanged (`audio_path`, stage_times, result
    shape identical to the non-streaming path), so callers can mix both modes freely.
    Still goes through orch.run_tts() -- every memory rule applies as before. This is a
    separate, app-facing path from the pre-existing `stream_tts=` flag above (which plays
    through sounddevice itself via play_http_stream and needs that optional package).

    `stream_chunk_opts=` -- optional dict merged into the /tts/infer_stream payload, e.g.
    {"max_chunk_chars": 120, "first_chunk_chars": 60} to tune chunk sizes for one call;
    absent keys fall back to the worker's config defaults (see config.py's stream_*
    comment in _TTS_ENGINE_CONFIGS["mms_tts"]). Only used when tts_stream_cb is given."""
    _status_variant_state = {}  # key -> last variant_index used, function-local (see status_cb= above)

    def _status(stage, tool_name=None):
        if status_cb is None:
            return
        from agent import pick_status_variant
        key = f"tool:{tool_name}" if stage == "tool" and tool_name else stage
        variant_index = pick_status_variant(key, _status_variant_state)
        try:
            status_cb(stage, tool_name, variant_index)
        except Exception as exc:
            print(f"    [status_cb] failed ({exc!r}) -- ignoring, turn continues")

    cfg = LANGUAGES[language]
    orch.reset_turn()
    if image_path_override is not None:
        image_path = Path(image_path_override)
        assert image_path.exists(), f"sample image not found: {image_path}"
        with_image = True  # for the Q1/Q2 default-audio selection below
    else:
        image_path = SAMPLE_IMAGE_PATH if with_image else None
        if with_image:
            assert image_path.exists(), f"sample image not found: {image_path}"
    label = f" [{turn_label}]" if turn_label else ""
    banner(f"FULL PIPELINE -- language={language} ({cfg['tts_name']}){label}"
           f"{' + image' if with_image else ''}")
    turn_t0 = time.perf_counter()
    stage_times = {}  # real wall-clock per stage, printed as a table after the turn (see caller)

    # Agent is loaded once for the whole session in main() now (ensure_agent_loaded_for_session()),
    # not per-turn here -- see orchestrator.py's module docstring "Agent policy" section for why
    # the old Rule 9 (per-turn async preload racing ASR's own load) was removed.

    question_key = "q2" if with_image else "q1"
    question_en = english_text_override if english_text_override is not None else (Q2_TEXT_EN if with_image else Q1_TEXT_EN)

    if language == "en":
        english_query = question_en
        print(f"[PIPE] English input -- skipping ASR and input-NMT")
        print(f"[PIPE] query: {english_query}")
    else:
        if audio_path_override is not None:
            audio_path = Path(audio_path_override)
        else:
            audio_name = audio_filename or f"{question_key}_{language}.wav"
            audio_path = Path(AGENTS_DIR) / "sample_audio" / "pipeline_inputs" / audio_name
        assert audio_path.exists(), f"sample audio not found: {audio_path}"
        with open(audio_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("utf-8")

        def _asr_call():
            r = requests.post(
                f"{GATEWAY}/asr/infer",
                json={"audio_base64": audio_b64, "language": language},
                timeout=60,
            )
            r.raise_for_status()
            return r.json()["text"]

        _status("asr")
        _t0 = time.perf_counter()
        raw_query = orch.run_asr(language, _asr_call, evict_nmt_first=evict_nmt_first)
        stage_times["asr_s"] = time.perf_counter() - _t0
        print(f"[PIPE] transcribed ({language}): {raw_query}")

        def _nmt_to_en_call():
            r = requests.post(
                f"{GATEWAY}/nmt/infer",
                json={"text": raw_query, "src_lang": language, "tgt_lang": "EN"},
                # 90s (was 30s until 2026-08-13): a real, confirmed-in-production crash --
                # EN->target answers routinely run 1000+ chars for a multi-iteration
                # tool-calling turn, and NMT infer time scales close to linearly with length
                # (confirmed directly: ~1.27s for ~60 chars -> a real 1817-char answer needed
                # ~38s, comfortably over the old 30s ceiling). The gateway's own proxy already
                # allows 180s (api_server/gateway.py); 90s gives real margin without silently
                # waiting the full 180s on a call that's actually hung, not just slow.
                timeout=90,
            )
            r.raise_for_status()
            return r.json()["translated_text"]

        # NMT is sticky-resident for the whole session now (2026-08-08 policy, mirroring Agent --
        # see orchestrator.py's module docstring "NMT policy"), so there's no eviction to worry
        # about here anymore -- it loads once (first use) and just stays loaded.
        _status("nmt_in")
        _t0 = time.perf_counter()
        english_query = orch.run_nmt(f"{language}->EN", _nmt_to_en_call)
        stage_times["nmt_in_s"] = time.perf_counter() - _t0
        print(f"[PIPE] translated to English: {english_query}")

    _new_messages = []  # captured by _agent_call, read back after run_agent() returns

    def _agent_call():
        # Real tool-calling agent (dev/agents/agent.py, extracted from vyoma_v5.ipynb) --
        # not a bare chat() call. Prints its own [agent iter N] timing + any tool calls it
        # makes, interleaved with the [ORCH]/[PIPE] lines above/below. image_path=None on the
        # Q1 (no --with-image) path -- the agent asking for a photo there is expected, correct
        # behavior for a question that never attached one, not a pipeline bug.
        #
        # messages=messages (the outer function's own parameter): None on an independent turn
        # (agent.run_turn() starts a fresh [system, user] list itself, same as before this
        # threading was added); the prior turn's returned list on a real follow-up, so the
        # agent genuinely sees the earlier Q&A -- growing context, not a stateless replay.
        turn_messages = agent.run_turn(english_query, image_path=image_path, messages=messages,
                                        verbose=True, status_cb=status_cb)
        _new_messages.extend(turn_messages)
        return turn_messages[-1].content

    # tts_language=: the turn's real target output language is already known here (it's
    # this whole turn's `cfg["tts_name"]`, fixed before the turn started, not something
    # that depends on the agent's answer). preload_tts defaults to False now (2026-08-12,
    # real confirmed GPU-contention finding -- see orchestrator.py's run_agent() docstring),
    # so the actual preload trigger is orch.preload_tts() right below, timed to overlap with
    # NMT-out's CPU-only translation instead of agent's own GPU-heavy generation.
    _t0 = time.perf_counter()
    english_answer = orch.run_agent(_agent_call, tts_language=cfg["tts_name"])
    stage_times["agent_s"] = time.perf_counter() - _t0
    orch.preload_tts(language=cfg["tts_name"])
    print(f"[PIPE] agent answer (English, raw): {english_answer}")
    # Strip markdown BEFORE NMT, not just before TTS (chunk_text() already does the latter,
    # via clean_text(), see streaming.py) -- added 2026-08-09 after finding NMT itself mangles
    # markdown it was never designed to understand: "**word**" translated as plain text can
    # come back with the two asterisks separated by NMT-introduced spacing ("* * word"),
    # which chunk_text()'s bold regex (`\*\*(.+?)\*\*`, requires the markers adjacent) can no
    # longer recognize as markdown by the time it runs post-translation -- confirmed directly
    # in real pipeline logs (e.g. "* * 1। उस खेत से..." reaching actual TTS input). Cleaning
    # the English answer first means NMT never sees markdown syntax to mangle in the first
    # place; chunk_text()'s own clean_text() call right before TTS is now just a harmless
    # no-op safety net for this text, not the only line of defense.
    english_answer = clean_text(english_answer)
    print(f"[PIPE] agent answer (English, markdown-stripped): {english_answer}")
    # Verbalize numbers BEFORE NMT, not after (added 2026-09-14): MMS-TTS checkpoints
    # lack digit characters in their vocabs (hi: no 5/6/7/9, en: no 7/8/9, gu: none at
    # all -- measured directly against every vocab.json), and the VITS tokenizer silently
    # DROPS those characters, so any digit NMT passes through is missing from the spoken
    # audio (a "7 drops" dose is heard as just "drops"). NMT was probed live and
    # translates English number-WORDS into native words with zero digit leaks
    # ("twenty-five" -> "पँचिश"/"ഇരുപത്തിയഞ്ച്"/"இருபத்தைந்து" for hi/ml/ta), so one
    # English-only expansion here covers all 15 TTS languages -- see
    # models/number_expansion.py for the full rationale and edge-case policies.
    english_answer = expand_numbers_en(english_answer)
    print(f"[PIPE] agent answer (English, numbers expanded): {english_answer}")

    if not english_answer.strip():
        # Real, documented qwen3.5 failure mode (see config.py's AGENT_THINK comment: "sometimes
        # return a completely EMPTY final `.content`") -- confirmed reproducible here on a real
        # multi-turn conversation near OLLAMA_NUM_CTX's ceiling (16383/16384 tokens at the point
        # this happened), not something the "medium" think-level mitigation fully eliminates
        # under enough accumulated context. NMT chokes on an empty string (real 500, not a
        # graceful no-op), so this isn't papered over by "translate nothing" either -- the
        # honest move is to skip NMT/TTS for THIS turn, log it loudly, and let the session
        # continue (so a memory-stress run still collects the rest of its data) rather than
        # crash the whole multi-turn conversation on one turn's model hiccup. NOT a silent
        # fix for the underlying empty-content bug itself -- that's a real, separate issue.
        print(f"[PIPE] *** WARNING: agent returned EMPTY content this turn -- skipping NMT/TTS, "
              f"conversation continues (this turn contributes no assistant reply to `messages`) ***")

        # 2026-08-23: one automatic retry with thinking disabled. Empty content happens
        # when thinking tokens consume the entire num_predict budget; think=False is
        # the proven-good configuration (0 empties in 40+ turns). Guarantees any caller
        # (GramSahayakUX included) never announces silence to a farmer.
        try:
            print("[PIPE] [retry] empty answer -- retrying once with think=False ...", flush=True)
            agent.think = False
            _retry = agent.run_turn(english_query, image_path=image_path,
                                    messages=None, verbose=True)
            _retry_text = (_retry[-1].content or "").strip() if _retry else ""
            if _retry_text:
                english_answer = _retry_text
                _new_messages.clear()
                _new_messages.extend(_retry)
                print(f"[PIPE] [retry] recovered answer ({len(english_answer)} chars)", flush=True)
            else:
                print("[PIPE] [retry] still empty -- continuing without audio", flush=True)
            agent.think = True
        except Exception as _re_exc:
            print(f"[PIPE] [retry] failed: {_re_exc!r} -- continuing", flush=True)
            agent.think = True

        stage_times["total_s"] = time.perf_counter() - turn_t0
        return {
            "english_query": english_query,
            "english_answer": "",
            "target_text": "",
            "audio_path": None,
            "messages": _new_messages,
            "empty_response": True,
            "stage_times": stage_times,
        }

    if language == "en":
        target_text = english_answer
    else:
        def _nmt_to_target_call():
            r = requests.post(
                f"{GATEWAY}/nmt/infer",
                json={"text": english_answer, "src_lang": "EN", "tgt_lang": language, "long": True},
                timeout=90,  # see _nmt_to_en_call's comment above -- same real fix, same reason
            )
            r.raise_for_status()
            return r.json()["translated_text"]

        # Same as above -- NMT just stays resident, no eviction path left to reason about.
        _status("nmt_out")
        _t0 = time.perf_counter()
        target_text = orch.run_nmt(f"EN->{language}", _nmt_to_target_call)
        stage_times["nmt_out_s"] = time.perf_counter() - _t0
        print(f"[PIPE] translated answer ({language}): {target_text}")

    tts_batch_size = config.WORKERS["tts"]["default_batch_size"]

    def _tts_call():
        r = requests.post(
            f"{GATEWAY}/tts/infer",
            json={"text": target_text, "language": cfg["tts_name"], "batch_size": tts_batch_size},
            timeout=180,
        )
        r.raise_for_status()
        return r.json()

    def _tts_call_streaming():
        # Real incremental playback through the actual gateway -- /tts/infer_stream, not the
        # blocking /tts/infer _tts_call() above uses. See TTS_HTTP_STREAMING_RESULTS.md for
        # what this actually buys (real measured time-to-first-audio) and two real bugs found
        # getting it to be stall-free. Deliberately NOT the default path (--stream-tts opts
        # in) -- /tts/infer stays the simpler, more proven fallback if streaming ever causes
        # a problem in practice (context loss across batches, network reliability on a real
        # device, etc.) that hasn't shown up in dev-machine testing yet.
        if not _HAS_SOUNDDEVICE:
            raise RuntimeError(
                "--stream-tts needs the optional `sounddevice` package (playback is the "
                "whole point of this path) -- pip install sounddevice, or drop --stream-tts "
                "to use the non-streaming /tts/infer path instead."
            )
        from models.tts_exports.streaming import play_http_stream  # local: torch-heavy import,
                                                                     # only paid by --stream-tts
        handle = play_http_stream(
            GATEWAY, target_text, language=cfg["tts_name"], batch_size=tts_batch_size,
            backend="sounddevice", blocking=True, debug=False,
        )
        audio, sample_rate = handle.full_audio()
        buf = io.BytesIO()
        sf.write(buf, audio, sample_rate, format="WAV")
        return {
            "audio_base64": base64.b64encode(buf.getvalue()).decode("utf-8"),
            "sample_rate": sample_rate,
            "language": cfg["tts_name"],
            "engine": f"{config.WORKERS['tts']['engine']}_streaming",
            "num_chunks": len(handle.chunks),
        }

    def _tts_call_stream_chunks(cb=None):
        # NDJSON consumer for /tts/infer_stream (2026-08-22) -- the app-facing streaming
        # path. Unlike _tts_call_streaming() above (which plays through sounddevice itself,
        # inside the gramsahayak venv), this hands each finished chunk to the callback
        # (defaulting to tts_stream_cb) and stays audio-backend-agnostic -- the caller owns
        # playback. See the tts_stream_cb= docstring paragraph above for the full contract.
        import json as _json
        import wave as _wave

        if cb is None:
            cb = tts_stream_cb

        payload = {"text": target_text, "language": cfg["tts_name"]}
        if stream_chunk_opts:
            payload.update(stream_chunk_opts)

        req_t0 = time.perf_counter()
        first_params = None
        frames = []  # (pcm_bytes, meta) in arrival order
        with requests.post(f"{GATEWAY}/tts/infer_stream", json=payload,
                           stream=True, timeout=300) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                item = _json.loads(line)
                item["arrive_s"] = round(time.perf_counter() - req_t0, 3)
                chunk_wav = base64.b64decode(item["audio_base64"])
                with _wave.open(io.BytesIO(chunk_wav)) as w:
                    if first_params is None:
                        first_params = (w.getnchannels(), w.getsampwidth(), w.getframerate())
                    frames.append((w.readframes(w.getnframes()), item))
                if cb is not None:
                    cb(chunk_wav, item["sample_rate"], item["chunk_index"], item)

        if not frames:
            raise RuntimeError("tts/infer_stream returned zero chunks")

        out = io.BytesIO()
        with _wave.open(out, "wb") as wo:
            wo.setnchannels(first_params[0])
            wo.setsampwidth(first_params[1])
            wo.setframerate(first_params[2])
            for pcm, _meta in frames:
                wo.writeframes(pcm)
        return {
            "audio_base64": base64.b64encode(out.getvalue()).decode("utf-8"),
            "sample_rate": first_params[2],
            "language": cfg["tts_name"],
            "num_chunks": len(frames),
            "engine": f"{config.WORKERS['tts']['engine']}_stream_chunks",
        }

    _status("tts")
    _t0 = time.perf_counter()
    if tts_stream_cb is not None:
        # Zero-chunks-delivered fallback (2026-08-22): if /tts/infer_stream itself dies
        # before a single chunk reached the callback, rerun JUST this stage on the proven
        # blocking endpoint instead of failing the whole turn over TTS plumbing. A failure
        # after audio started playing is re-raised -- replaying from zero on top of
        # half-heard audio is worse than an error screen. TurnCancelled (raised by the
        # app's callback at its cancellation checkpoints) is never retried; it is
        # identified by class name because this module cannot import the app that
        # defines it.
        _delivered = [0]

        def _counting_cb(wav_bytes, sample_rate, chunk_index, meta):
            _delivered[0] += 1
            tts_stream_cb(wav_bytes, sample_rate, chunk_index, meta)

        def _tts_call_stream_or_blocking():
            try:
                return _tts_call_stream_chunks(cb=_counting_cb)
            except Exception as exc:
                if _delivered[0] or type(exc).__name__ == "TurnCancelled":
                    raise
                print(f"[PIPE] WARNING: tts/infer_stream failed with zero chunks "
                      f"delivered ({exc!r}) -- retrying this stage via blocking "
                      f"/tts/infer")
                return _tts_call()

        tts_result = orch.run_tts(cfg["tts_name"], _tts_call_stream_or_blocking,
                                  batch_size=tts_batch_size,
                                  text_char_count=len(target_text),
                                  evict_nmt_first=evict_nmt_first, session_language=language)
    elif stream_tts:
        tts_result = orch.run_tts(cfg["tts_name"], _tts_call_streaming, batch_size=tts_batch_size,
                                   text_char_count=len(target_text),
                                   evict_nmt_first=evict_nmt_first, session_language=language)
    else:
        tts_result = orch.run_tts(cfg["tts_name"], _tts_call, batch_size=tts_batch_size,
                                   text_char_count=len(target_text),
                                   evict_nmt_first=evict_nmt_first, session_language=language)
    stage_times["tts_s"] = time.perf_counter() - _t0

    out_dir = Path(AGENTS_DIR) / "sample_audio" / "pipeline_outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    # turn_label-based suffix so a multi-turn --followups run doesn't overwrite each turn's
    # audio with the next one -- without this, only the final turn's .wav would ever survive
    # at the fixed orchestrated_<lang>.wav path.
    suffix = f"_{turn_label.replace(' ', '_').replace('/', 'of')}" if turn_label else ""
    out_path = out_dir / f"orchestrated_{language}{suffix}.wav"
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(tts_result["audio_base64"]))
    # "batch_size" is parler-only (mms_tts never batches -- see tts_worker.py's module
    # docstring) and "engine" can differ per call now (mms_tts / parler / parler_fallback,
    # the last one when the requested language has no real MMS-TTS checkpoint -- see
    # config.MMS_TTS_UNSUPPORTED_INDIAN_LANGUAGES) -- .get() both rather than assuming
    # every response shares parler's shape.
    batch_note = f", batch_size={tts_result['batch_size']}" if "batch_size" in tts_result else ""
    print(
        f"[PIPE] audio written to {out_path} "
        f"(engine={tts_result.get('engine', '?')}, {tts_result['num_chunks']} chunks{batch_note})"
    )
    # stream_tts already played live, inside orch.run_tts()'s timed call above -- playing
    # play_audio(out_path) again here would be a second, redundant full playback.
    if play and not stream_tts:
        play_audio(out_path)
    stage_times["total_s"] = time.perf_counter() - turn_t0
    print(f"[PIPE] total turn wall-clock: {stage_times['total_s']:.2f}s")

    return {
        # raw_query (2026-08-17, additive): the original spoken-language ASR transcript, "" for
        # language="en" (no ASR step at all -- see the language=="en" branch above, english_query
        # IS the raw query there). Was computed internally but never returned before this --
        # added so a caller can pass it straight to MemoryOrchestrator.record_turn()'s own
        # `raw_query=` field without having to re-derive or re-run ASR itself.
        "raw_query": raw_query if language != "en" else english_query,
        "english_query": english_query,
        "english_answer": english_answer,
        "target_text": target_text,
        "audio_path": str(out_path),
        "messages": _new_messages,  # pass back in as the next call's messages= for a real follow-up
        "stage_times": stage_times,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=list(LANGUAGES), default="hi")
    parser.add_argument("--all", action="store_true", help="run every language back to back, one session")
    parser.add_argument("--no-play", action="store_true", help="save the .wav but skip live playback")
    parser.add_argument("--with-image", action="store_true",
                         help="use Q2 (\"what's wrong with this plant\") + the sample photo instead of Q1")
    parser.add_argument("--stream-tts", action="store_true",
                         help="use the new /tts/infer_stream path (real incremental playback, lower "
                              "time-to-first-audio -- see TTS_HTTP_STREAMING_RESULTS.md) instead of the "
                              "default blocking /tts/infer + play-after-complete path. Opt-in, not the "
                              "default -- /tts/infer stays the simpler, more proven fallback.")
    parser.add_argument("--followups", type=int, default=1,
                         help="run this many sequential turns in the SAME language (--language), "
                              "threading real conversation history (messages=, see agent.run_turn()'s "
                              "own docstring) across turns and cycling through different real audio "
                              "samples per turn -- for measuring reload latency/memory across a real "
                              "growing-context conversation, unlike --all (independent fresh-context "
                              "turns, different languages). Mutually exclusive with --all in practice "
                              "(--all takes priority if both are passed).")
    parser.add_argument("--weather-conversation", action="store_true",
                         help="run the 5-turn crop_weather_turns() conversation (pest question -> "
                              "spray window -> location given -> weather forecast -> pest pressure), "
                              "threading real context across turns, in --language (combine with --all "
                              "to run it in every language back to back instead of just one). Takes "
                              "priority over --followups/plain single-turn if passed; --with-image/"
                              "--stream-tts still apply as usual.")
    parser.add_argument("--multiturn-stress", action="store_true",
                         help="run the 5-turn MULTITURN_STRESS_EN conversation (potato leaf image -> "
                              "treatment follow-up -> weather forecast -> spray-timing follow-up "
                              "(likely dual weather+RAG tool call) -> govt scheme), using "
                              "pre-synthesized audio from sample_audio/multiturn_stress/<lang>/, with a "
                              "full orch.snapshot() memory breakdown printed after EVERY turn (not just "
                              "at the end) -- built for real Jetson memory-budget stress testing. "
                              "Combine with --all to run all 4 languages back to back in one session "
                              "(real language-switch behavior, not independent single-language runs). "
                              "Takes priority over --weather-conversation/--followups/plain single-turn.")
    parser.add_argument("--image-turn", type=int, default=1,
                         help="Diagnostic knob for --multiturn-stress (2026-08-12): which turn number "
                              "(1-5) gets the image attached, default 1 (the normal case). Real turn-1 "
                              "wall-clock time is dominated by generated-token *volume*, not decode speed "
                              "(confirmed: turn 1 generates far more tokens than turns 2-5, at the same "
                              "steady per-token rate) -- but turn 1 is ALSO always the image turn, so "
                              "'first turn' and 'has an image' have never been tested apart. Pass "
                              "--image-turn 2 to move the image to turn 2 instead (turn 1 becomes a plain "
                              "text question with no image): if turn 1 is now fast and turn 2 becomes the "
                              "slow one, the image/analyze_photo is the real driver; if turn 1 is still "
                              "slow with no image at all, it's genuinely a first-call-of-session cost, not "
                              "an image cost. Also swaps turn 1's and this turn's pre-recorded text+audio "
                              "so the spoken content actually matches wherever the image ends up (a real "
                              "hindi_v9 run found the agent silently skips analyze_photo if the audio at "
                              "the image's turn doesn't reference a photo at all -- e.g. turn 2's original "
                              "dosage-follow-up audio says nothing about seeing anything).")
    parser.add_argument("--no-evict-nmt-around-tts", action="store_true",
                         help="Disable the DEFAULT-ON memory fix (orchestrator.py's "
                              "run_tts(evict_nmt_first=True), 2026-08-11 -- turned on by default after a "
                              "REAL confirmed Jetson crash mid-TTS-synthesis, see run_tts()'s own "
                              "docstring) -- evicts NMT right before each turn's TTS synthesis, reloads it "
                              "async alongside ASR's Rule 10 preload afterward. Pass this flag to get the "
                              "old sticky-resident-through-TTS behavior back, e.g. for an A/B comparison.")
    parser.add_argument("--no-warmup", action="store_true",
                         help="Skip the agent's real prefix-cache warmup call (agent/warmup.py) before "
                              "turn 1. The cold-vs-warmed prefill gap this warmup exists to hide was "
                              "measured at 7435ms cold -> 1599ms warmed on real Jetson hardware -- but that "
                              "was measured under whatever power mode was active at the time, not "
                              "necessarily MAXN_SUPER. Pass this flag for an A/B comparison of turn 1's own "
                              "real cold prefill time under the CURRENT power mode, to check whether the "
                              "gap this warmup was built to close is still as large.")
    parser.add_argument("--agent-think", choices=["default", "false", "low", "medium", "high"],
                         default="default",
                         help="Override GramSahayakAgent's think= level for this run only -- never "
                              "touches config.AGENT_THINK. 'default' means 'don't pass think=', which "
                              "falls through to config.AGENT_THINK (\"medium\" as of this writing) the "
                              "same way GramSahayakAgent's own constructor already treats None. 'false' "
                              "maps to the real Python False (fastest, no thinking at all -- distinct "
                              "from unset, see agent.py's own docstring on this). Built for the real "
                              "2026-08-14/15 latency investigation: AGENT_THINK=\"medium\" was tuned for "
                              "qwen3.5:0.8b (whose think=\"low\" sometimes returned empty .content) but "
                              "the agent model reverted to qwen3.5:2b on 2026-08-12 and was never "
                              "re-benched at a lower think level -- agent.py's own docstring already notes "
                              "qwen3.5:2b's think=\"low\" was previously validated as reliable.")
    parser.add_argument("--agent-model", default=None,
                         help="Override which Ollama model plays the agent role for this run only -- "
                              "mutates orchestrator_module.OLLAMA_COMPONENTS['agent'] in-process (read "
                              "fresh on every real /agent/load and /agent/unload call, see orchestrator.py's "
                              "_load()) rather than config.OLLAMA_MODELS[0], so nothing in config.py "
                              "changes and a bad run needs no revert. Also passed to GramSahayakAgent's "
                              "own model= and to the warmup call below, so the whole run (warmup, tool-"
                              "calling loop, KV-cache) is consistently on the override model, not a mix.")
    parser.add_argument("--log-status", action="store_true",
                         help="Wire a real status_cb (2026-08-16) into --multiturn-stress so every real "
                              "status event (asr/nmt_in/nmt_out/tts pipeline stages, plus agent.py's own "
                              "agent_thinking/tool/agent_reviewing/agent_finalizing/followup stages) gets "
                              "logged with the exact text it would speak, whether it falls inside "
                              "AUDIO_STAGES (would actually play a clip on a real device -- mirrors "
                              "gramsahayak_app.py's and live_demo_with_update.py's own AUDIO_STAGES, kept "
                              "in sync by hand, see _StatusAudioCounter's own docstring), and a running "
                              "count printed after each turn -- muted by design, no aplay/ffplay ever "
                              "invoked here, this only counts+logs what WOULD have played. Only wired into "
                              "the --multiturn-stress path today.")
    args = parser.parse_args()

    if args.agent_model:
        orchestrator_module.OLLAMA_COMPONENTS["agent"] = args.agent_model
        print(f"[PIPE] *** --agent-model override: agent role is now '{args.agent_model}' for this "
              f"run only (config.OLLAMA_MODELS[0] left untouched) ***")
    AGENT_THINK_OVERRIDE = {"default": None, "false": False, "low": "low",
                             "medium": "medium", "high": "high"}[args.agent_think]
    if args.agent_think != "default":
        print(f"[PIPE] *** --agent-think override: think='{AGENT_THINK_OVERRIDE}' for this run only "
              f"(config.AGENT_THINK left untouched) ***")

    # Real audio fixtures available per language for --followups to cycle through (repeats via
    # modulo if --followups exceeds the list) -- "en" has none, that path skips ASR entirely.
    FOLLOWUP_AUDIO_FILES = {
        "hi": ["q1_hi.wav", "q2_hi.wav", "q3_hi.wav", "hindi_50w.wav"],
        "ta": ["q1_ta.wav", "q2_ta.wav"],
        "ml": ["q1_ml.wav", "q2_ml.wav"],
        "en": [],
    }
    FOLLOWUP_GAP_SECONDS = 10  # same real-pause rationale as --all's INTER_LANGUAGE_GAP_SECONDS

    # Real incident (2026-08-11): a live Streamlit/other session already had run_all.py bound
    # to GATEWAY_PORT when this ran. The subprocess.Popen below then failed to bind (harmless,
    # printed a bind-error and exited), but wait_for_gateway() only checks reachability, not
    # ownership -- it found the OTHER session's gateway already healthy and happily used it.
    # The rest of the run was real (genuine turns against a real gateway), but this function's
    # own `finally` used to unconditionally call orch.teardown(), which evicted the OTHER
    # session's loaded agent/NMT out from under it -- confirmed directly, not hypothetical.
    # Fix: check reachability BEFORE spawning; only spawn/own/teardown a gateway this run
    # didn't find already running. Mirrors rag/test_full_turn_memory.py's own "reuse whatever
    # gateway is already running... does NOT spawn its own run_all.py" convention, just
    # applied here as a runtime check instead of that script's hardcoded assumption.
    we_own_the_gateway = not wait_for_gateway(timeout=1.0)
    gateway_proc = None
    if we_own_the_gateway:
        gateway_proc = subprocess.Popen(
            [sys.executable, "run_all.py"], cwd=os.path.join(AGENTS_DIR, "api_server")
        )
    else:
        print("[PIPE] *** a gateway is already running on this port -- reusing it, NOT spawning "
              "or tearing down our own (won't disrupt whatever session already owns it) ***")
    try:
        if not wait_for_gateway():
            print("gateway did not become healthy in time", file=sys.stderr)
            return 1

        orch = MemoryOrchestrator()
        agent = GramSahayakAgent(model=args.agent_model, think=AGENT_THINK_OVERRIDE)

        # Agent loads once, here, before any turn -- and is never evicted mid-session by any
        # rule (Rules 8/9 removed 2026-08-07). See orchestrator.py's module docstring "Agent
        # policy" section for the full history/tradeoff.
        orch.ensure_agent_loaded_for_session()
        orch.ensure_embedder_loaded_for_session()

        # Real prefix-cache warmup (2026-08-12, replaces an earlier bare-"hi" warmup that
        # shared NO prefix with the real agent's own calls and was confirmed to help nothing).
        # agent/warmup.py uses the REAL SYSTEM_PROMPT + TOOLS + /api/chat -- the exact shape
        # agent.run_turn()'s own first call makes -- so the KV-cache prefix it leaves behind
        # actually matches. Confirmed directly on real Jetson hardware: cold prefill 7435ms
        # (5572 tok) -> warmed prefill 1599ms (5802 tok) for the next real call sharing this
        # prefix, ~4.6x faster, matching the documented "50-85% TTFT reduction" this class of
        # fix gets in the wider literature (prefix/prompt-cache warmup for agent system
        # prompts -- see agent/warmup.py's own docstring for the real numbers + references).
        # Excluded from turn 1's own stage_times on purpose, same reasoning as before.
        if args.no_warmup:
            print("[PIPE] *** --no-warmup: skipping prefix-cache warmup, turn 1 pays real cold "
                  "prefill cost (this is the point -- see the flag's own help text) ***")
        else:
            from agent.warmup import warmup_agent
            try:
                warmup_agent(model=args.agent_model or config.OLLAMA_MODELS[0],
                              num_ctx=config.OLLAMA_NUM_CTX, think=AGENT_THINK_OVERRIDE)
            except Exception as exc:
                # Don't let a slow/failed warmup take the whole run down with it -- it's a
                # precaution, not something the rest of the pipeline depends on succeeding.
                print(f"[PIPE] *** warmup failed ({exc}) -- continuing anyway, turn 1 will just pay "
                      f"whatever cold-prefill cost this would have hidden ***")

        banner("INITIAL STATE (nothing loaded)")
        orch._snapshot_line("startup")

        if args.multiturn_stress:
            languages = list(LANGUAGES) if args.all else [args.language]
            for li, lang in enumerate(languages):
                if li > 0:
                    print(f"\n[PIPE] waiting {FOLLOWUP_GAP_SECONDS}s before next language...")
                    time.sleep(FOLLOWUP_GAP_SECONDS)
                running_messages = None
                status_counter = _StatusAudioCounter(lang) if args.log_status else None

                # --image-turn diagnostic (2026-08-12): moving the image to a turn other than 1
                # only tests what it's meant to if that turn's spoken CONTENT actually references
                # something photo-worthy -- the original per-position audio doesn't, since it was
                # recorded assuming turn 1 always has the image (confirmed via a real hindi_v9 run:
                # the agent never called analyze_photo on turn 2 because turn 2's audio was the
                # dosage follow-up, which says nothing about a photo). So when --image-turn != 1,
                # swap which turn's pre-recorded text+audio plays at position 1 vs position
                # args.image_turn, keeping the image itself at args.image_turn's position -- turn
                # 1's original content ("black spots... what is this") now plays wherever the
                # image is, so the audio and the image actually agree with each other. Identity
                # (no swap) when --image-turn is left at the default 1.
                def _content_turn(position):
                    if args.image_turn == 1 or position not in (1, args.image_turn):
                        return position
                    return args.image_turn if position == 1 else 1

                for i in range(1, len(MULTITURN_STRESS_EN) + 1):
                    if i > 1:
                        note = f"(simulating {FOLLOWUP_GAP_SECONDS}s pause before follow-up question)"
                        print(f"\n[PIPE] waiting {FOLLOWUP_GAP_SECONDS}s {note}...")
                        time.sleep(FOLLOWUP_GAP_SECONDS)
                    content_turn = _content_turn(i)
                    text = MULTITURN_STRESS_EN[content_turn - 1]
                    audio_path = None if lang == "en" else multiturn_stress_audio_path(lang, content_turn)
                    if audio_path is not None:
                        assert audio_path.exists(), f"missing multiturn_stress audio: {audio_path}"
                    image_path = MULTITURN_STRESS_IMAGE_PATH if i == args.image_turn else None
                    turn_label = f"multiturn-stress {i}/{len(MULTITURN_STRESS_EN)}"
                    orch.set_turn_context(turn_label=turn_label, language=lang)
                    if status_counter is not None:
                        status_counter.set_turn(turn_label)
                    result = run_full_pipeline(
                        lang, orch, agent, play=not args.no_play, stream_tts=args.stream_tts,
                        messages=running_messages, audio_path_override=audio_path,
                        image_path_override=image_path, english_text_override=text,
                        turn_label=turn_label,
                        evict_nmt_first=not args.no_evict_nmt_around_tts,
                        status_cb=status_counter,
                    )
                    running_messages = result["messages"]
                    turn_done_label = f"after {lang} turn {i}/{len(MULTITURN_STRESS_EN)}"
                    print_stage_times(result.get("stage_times", {}), turn_done_label)
                    print_full_snapshot(orch, turn_done_label)
                    orch.print_events_table()  # incremental -- real partial table survives a crash
                    if status_counter is not None:
                        turn_total, turn_audio = status_counter.summary_for_turn(turn_label)
                        print(f"    [status] this turn: {turn_total} status events, "
                              f"{turn_audio} would play audio, {turn_total - turn_audio} text-only")
                if status_counter is not None:
                    status_counter.print_summary()
        elif args.weather_conversation:
            languages = list(LANGUAGES) if args.all else [args.language]
            for li, lang in enumerate(languages):
                if li > 0:
                    print(f"\n[PIPE] waiting {FOLLOWUP_GAP_SECONDS}s before next language...")
                    time.sleep(FOLLOWUP_GAP_SECONDS)
                running_messages = None
                turns = crop_weather_turns(lang)
                for i, text in enumerate(turns, 1):
                    if i > 1:
                        note = f"(simulating {FOLLOWUP_GAP_SECONDS}s pause before follow-up question)"
                        print(f"\n[PIPE] waiting {FOLLOWUP_GAP_SECONDS}s {note}...")
                        time.sleep(FOLLOWUP_GAP_SECONDS)
                    audio_file = None if lang == "en" else f"crop_turn{i}_{lang}.wav"
                    result = run_full_pipeline(
                        lang, orch, agent, play=not args.no_play, stream_tts=args.stream_tts,
                        messages=running_messages, audio_filename=audio_file, english_text_override=text,
                        turn_label=f"crop-weather {i}/{len(turns)}",
                    )
                    running_messages = result["messages"]
        elif args.all:
            languages = list(LANGUAGES)
            # 10s gap between languages -- real device usage never has turns land back-to-back
            # with zero pause; a farmer has to start speaking again after hearing the answer.
            # Without this, --all was an unrealistically best-case benchmark (no gap for
            # orchestrator.preload_asr()'s Rule 10 to actually overlap with -- it would just
            # have gone straight to run_asr() cold every time, same as before that preload
            # existed). Each --all turn is still an independent, fresh-context conversation
            # (no messages= threading) -- that's what --followups is for instead.
            for i, lang in enumerate(languages):
                if i > 0:
                    note = f"(simulating {FOLLOWUP_GAP_SECONDS}s pause before next spoken question)"
                    print(f"\n[PIPE] waiting {FOLLOWUP_GAP_SECONDS}s {note}...")
                    time.sleep(FOLLOWUP_GAP_SECONDS)
                run_full_pipeline(lang, orch, agent, play=not args.no_play, with_image=args.with_image,
                                   stream_tts=args.stream_tts, evict_nmt_first=not args.no_evict_nmt_around_tts)
        elif args.followups > 1:
            audio_files = FOLLOWUP_AUDIO_FILES.get(args.language, [])
            running_messages = None
            for i in range(args.followups):
                if i > 0:
                    note = f"(simulating {FOLLOWUP_GAP_SECONDS}s pause before follow-up question)"
                    print(f"\n[PIPE] waiting {FOLLOWUP_GAP_SECONDS}s {note}...")
                    time.sleep(FOLLOWUP_GAP_SECONDS)
                audio_file = audio_files[i % len(audio_files)] if audio_files else None
                result = run_full_pipeline(
                    args.language, orch, agent, play=not args.no_play, with_image=args.with_image,
                    stream_tts=args.stream_tts, messages=running_messages, audio_filename=audio_file,
                    turn_label=f"follow-up {i + 1}/{args.followups}",
                    evict_nmt_first=not args.no_evict_nmt_around_tts,
                )
                running_messages = result["messages"]  # real growing context into the next turn
        else:
            run_full_pipeline(args.language, orch, agent, play=not args.no_play,
                               with_image=args.with_image, stream_tts=args.stream_tts,
                               evict_nmt_first=not args.no_evict_nmt_around_tts)

        if we_own_the_gateway:
            banner("SESSION TEARDOWN")
            orch.teardown()
        else:
            print("\n[PIPE] *** not tearing down -- this run reused a gateway it doesn't own; "
                  "leaving its state exactly as any normal turn in that other session would ***")

    finally:
        if gateway_proc is not None:
            gateway_proc.terminate()
            try:
                gateway_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                gateway_proc.kill()

    return 0


if __name__ == "__main__":
    sys.exit(main())
