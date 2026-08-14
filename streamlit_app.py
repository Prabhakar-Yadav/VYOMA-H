"""Live Streamlit control room for the GramSahayak orchestrated pipeline -- the browser-driven
counterpart to test_orchestrated_pipeline.py. Nothing here is simulated: it launches the real
gateway (api_server/gateway.py), drives it through a real MemoryOrchestrator
(api_server/orchestrator.py), and calls the real GramSahayakAgent (agent/agent.py) -- same
load_balancer_plan.md rules, same tool-calling loop, same checkpoints. Built so the pipeline can
be watched and driven from a browser instead of only a terminal, which matters most on a
headless/remote box like GX10: audio in/out happens in the browser via st.audio_input/st.audio
(the user's own mic and speakers), not on the device's own hardware, and the memory/latency
panels update live without needing to tail a log file over SSH.

Run (from gramsahayak/, with the project venv active):
    streamlit run streamlit_app.py
    streamlit run streamlit_app.py --server.address 0.0.0.0   # to reach it from another machine

Reuses rather than reimplements: test_orchestrated_pipeline's own LANGUAGES table, sample
question text, bundled sample image, and crop_weather_turns() 5-turn conversation are imported
directly from it (see `import test_orchestrated_pipeline as tp` below) -- importing it is safe,
its pipeline only runs under `if __name__ == "__main__"`.

Not implemented: --stream-tts's live sounddevice playback -- that plays on whatever machine runs
the *script*, which is meaningless for a browser client. The web UI always uses the blocking
/tts/infer path and plays the finished clip back through the browser's own <audio> element
instead, which is the actual "real audio out" this was asked for.

Threading model: the gateway subprocess, MemoryOrchestrator, and GramSahayakAgent are held in
one process-wide PipelineSession (via @st.cache_resource) so they survive Streamlit's
rerun-the-whole-script-on-every-interaction model. Each pipeline turn runs in a background
thread so the UI stays responsive; `st.fragment(run_every=...)` panels (status bar, memory,
latency, logs, conversation) poll that shared session and repaint themselves live without a full
page rerun. Background threads only ever touch plain PipelineSession state (never call st.*
directly) -- Streamlit doesn't support st.* calls off the main script thread.
"""
import atexit
import base64
import collections
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))
if AGENTS_DIR not in sys.path:
    sys.path.insert(0, AGENTS_DIR)

from api_server import config  # noqa: E402
from api_server.orchestrator import MemoryOrchestrator, ALL_COMPONENTS  # noqa: E402
from agent import GramSahayakAgent  # noqa: E402
from models.text_clean import clean_text  # noqa: E402
import test_orchestrated_pipeline as tp  # noqa: E402 -- reused for LANGUAGES/sample text/image/crop_weather_turns()

GATEWAY = f"http://{config.GATEWAY_HOST}:{config.GATEWAY_PORT}"
LANGUAGES = tp.LANGUAGES
SAMPLE_INPUT_DIR = Path(AGENTS_DIR) / "sample_audio" / "pipeline_inputs"
FOLLOWUP_GAP_SECONDS = 5  # pause between the weather-demo's 5 turns -- same real-pause
# rationale as test_orchestrated_pipeline's own gaps (see its main()), just shorter for a
# browser demo where nobody's waiting on a real spoken follow-up.

st.set_page_config(page_title="GramSahayak Live Pipeline", layout="wide", page_icon="🦜")


# ----------------------------------------------------------------------------------------
# Shared process-wide state
# ----------------------------------------------------------------------------------------

class PipelineSession:
    """One instance for the whole Streamlit server process (see get_session() below) -- the
    gateway subprocess, orchestrator, and agent must be singletons; re-creating them on every
    Streamlit rerun (which happens on *every* widget interaction) would spawn a new
    gateway/agent per click."""

    def __init__(self):
        self.lock = threading.RLock()
        self.gateway_proc = None
        self.orch = None
        self.agent = None
        self.messages = None  # growing ollama conversation, threaded across turns (agent.run_turn's own shape)
        self.turns = []  # completed turn records, oldest first
        self.logs = collections.deque(maxlen=4000)
        self.memory_history = collections.deque(maxlen=2400)  # ~1hr at 1.5s/sample
        self.starting = False
        self.ready = False
        self.start_error = None
        self.busy = False
        self.busy_seen_by_ui = False  # render_status_bar()'s own bookkeeping -- lets it detect
        # the busy->idle transition and fire exactly one full-page rerun then, instead of the
        # sidebar polling on a timer (which would kill an in-progress mic recording -- see
        # render_sidebar()'s own docstring).
        self.current_stage = "idle"
        self.autorefresh_enabled = True  # forced off while "Record mic" is selected -- see
        # render_sidebar(). Confirmed (Streamlit issue #10805 and others) that a fragment's own
        # run_every isn't the only thing that can reset a widget's in-progress browser-side
        # state; sibling fragments' periodic reruns elsewhere on the page have their own
        # reported edge cases doing the same. Every run_every fragment on this page reads this
        # flag at decoration time (see e.g. render_status_bar below) so recording gets a page
        # with genuinely zero periodic reruns happening anywhere, not just in its own fragment.
        self.poller_started = False
        self.pending_recorded_audio = None  # durable server-side copy of the last real mic
        # capture, set the moment st.audio_input() returns non-None -- NOT read straight from
        # the widget at Send-click time, because iframe-based recorder widgets have a real,
        # previously-hit class of bug where the widget's own returned value can go back to
        # None on a later rerun triggered by an unrelated interaction (a different button
        # elsewhere in the same fragment), even though a real clip was already captured. This
        # is what Send actually reads for "Record mic" mode -- see render_sidebar().
        self.stop_event = threading.Event()

    def log(self, msg):
        with self.lock:
            self.logs.append(f"{time.strftime('%H:%M:%S')} {msg}")

    def set_stage(self, stage):
        with self.lock:
            self.current_stage = stage
        self.log(f"[APP] stage -> {stage}")


@st.cache_resource
def get_session():
    return PipelineSession()


_ATEXIT_REGISTERED = False


def _register_atexit(session):
    global _ATEXIT_REGISTERED
    if _ATEXIT_REGISTERED:
        return
    def _cleanup():
        if session.gateway_proc is not None and session.gateway_proc.poll() is None:
            session.gateway_proc.terminate()
    atexit.register(_cleanup)
    _ATEXIT_REGISTERED = True


# ----------------------------------------------------------------------------------------
# Startup / teardown / background memory polling
# ----------------------------------------------------------------------------------------

def _wait_for_gateway(timeout=25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(f"{GATEWAY}/health", timeout=1.0).status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.3)
    return False


def _memory_poller(session):
    """Runs continuously (not just during turns) so the memory panel shows real idle drift,
    a stuck load, etc. -- not just per-turn deltas."""
    while not session.stop_event.is_set():
        if session.orch is not None:
            try:
                snap = session.orch.snapshot()
                with session.lock:
                    session.memory_history.append({"t": time.time(), "snap": snap})
            except Exception as exc:
                session.log(f"[APP] memory poll failed: {exc}")
        session.stop_event.wait(1.5)


def _start_system(session):
    with session.lock:
        if session.starting or session.ready:
            return
        session.starting = True
        session.start_error = None
    try:
        session.log("[APP] launching gateway subprocess (run_all.py)...")
        session.gateway_proc = subprocess.Popen(
            [sys.executable, "run_all.py"], cwd=os.path.join(AGENTS_DIR, "api_server")
        )
        if not _wait_for_gateway():
            raise RuntimeError("gateway did not become healthy within 25s")
        session.log("[APP] gateway healthy")

        session.orch = MemoryOrchestrator(verbose=True, log_fn=session.log)
        session.agent = GramSahayakAgent()
        session.orch._snapshot_line("startup")

        session.set_stage("loading agent (session start)")
        session.orch.ensure_agent_loaded_for_session()

        if not session.poller_started:
            threading.Thread(target=_memory_poller, args=(session,), daemon=True).start()
            session.poller_started = True

        with session.lock:
            session.ready = True
            session.starting = False
        session.set_stage("idle")
        session.log("[APP] system ready")
    except Exception as exc:
        session.log(f"[APP] startup failed: {exc}")
        with session.lock:
            session.start_error = str(exc)
            session.starting = False


def _teardown_system(session):
    if session.orch is not None:
        session.set_stage("tearing down")
        try:
            session.orch.teardown()
        except Exception as exc:
            session.log(f"[APP] teardown error: {exc}")
    if session.gateway_proc is not None:
        session.gateway_proc.terminate()
        try:
            session.gateway_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            session.gateway_proc.kill()
    with session.lock:
        session.ready = False
        session.gateway_proc = None
    session.set_stage("stopped")
    session.log("[APP] system stopped")


# ----------------------------------------------------------------------------------------
# Pipeline turn -- real ASR -> NMT -> Agent -> NMT -> TTS, same shape as
# test_orchestrated_pipeline.py's run_full_pipeline(), adapted to take live browser input
# (mic/upload/typed) instead of only fixed sample files, and to log into session.logs instead
# of printing directly.
# ----------------------------------------------------------------------------------------

class _TeeToLog:
    """Mirrors agent.run_turn()'s own print()s (tool calls, per-iteration timing) into
    session.logs, on top of writing them through to the real stdout -- so the Raw Logs tab
    shows genuinely everything, not just the orchestrator's [ORCH] lines. Narrowly scoped
    (only wraps the one agent.run_turn() call below) since redirecting stdout is process-global
    and turns are only ever run one at a time (Send is disabled while busy)."""

    def __init__(self, session, real_stream):
        self.session = session
        self.real_stream = real_stream
        self._buf = ""

    def write(self, s):
        self.real_stream.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self.session.log(f"[AGENT] {line}")
        return len(s)

    def flush(self):
        self.real_stream.flush()


def _save_temp_bytes(data, suffix):
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="gramsahayak_ui_")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def _msg_get(msg, key, default=None):
    """agent.run_turn()'s own messages list mixes plain dicts (the system/user/tool messages
    it appends by hand) with ollama's Message objects (response.message, from ollama.chat() --
    a pydantic model, not a dict) -- this reads either shape the same way."""
    if isinstance(msg, dict):
        return msg.get(key, default)
    return getattr(msg, key, default)


def _extract_tool_calls(delta_messages):
    """Turns the raw message trace from one turn into the actual tool calls the agent made --
    real tool name, real arguments, real result -- by walking the same assistant-message ->
    tool-message pairing agent.run_turn() itself produces (see agent.py's run_turn(): every
    `response.message.tool_calls` entry is followed by one `{"role": "tool", ...}` message per
    call, in the same order). This is the structured counterpart to _TeeToLog's raw-text
    capture below -- the Conversation tab uses this, not scraped log lines, so what's shown is
    exactly what the agent's dispatch table actually ran, not a truncated print()."""
    calls = []
    for msg in delta_messages:
        role = _msg_get(msg, "role")
        if role == "assistant":
            for call in (_msg_get(msg, "tool_calls") or []):
                fn = call.get("function") if isinstance(call, dict) else call.function
                name = fn.get("name") if isinstance(fn, dict) else fn.name
                args = fn.get("arguments") if isinstance(fn, dict) else fn.arguments
                calls.append({"name": name, "arguments": args or {}, "result": None})
        elif role == "tool":
            tool_name = _msg_get(msg, "tool_name")
            content = _msg_get(msg, "content")
            # Real tool-calling models occasionally request the same tool twice in one turn
            # (e.g. two different pesticide lookups) -- matching the most recent same-name
            # call still missing a result keeps each result paired with the right call instead
            # of every later result silently overwriting the first.
            for c in reversed(calls):
                if c["name"] == tool_name and c["result"] is None:
                    c["result"] = content
                    break
    return calls


def _post_json(url, payload, timeout):
    """`r.raise_for_status()` alone throws away the actual reason a worker call failed --
    every worker's own /infer (worker_base.py) and the gateway's proxy both return a real
    `{"detail": "<the actual exception string>"}` body on a non-2xx response (a genuine
    server-side exception, e.g. a TTS synthesis crash on a particular answer's length/content
    -- see config.py's own notes on real mms_tts/Parler crashes this project has hit before),
    and `requests`' generic "500 Server Error: Internal Server Error for url: ..." message
    drops that detail entirely. This surfaces it instead, so a turn's error (and the Raw Logs
    line for it) shows the real underlying cause, not just the HTTP status."""
    r = requests.post(url, json=payload, timeout=timeout)
    if not r.ok:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise RuntimeError(f"{r.status_code} from {url}: {detail}")
    return r.json()


def run_pipeline_turn(session, language, audio_bytes=None, typed_english=None,
                       image_path=None, turn_label=None):
    """Meant to run in a background thread. `image_path`, if given, is a real temp file this
    function deletes itself when done (the caller is responsible for creating it -- see the
    sidebar's Send button)."""
    with session.lock:
        session.busy = True
    session.set_stage("validating input")  # so a pre-flight failure (e.g. no audio given)
    # reports "Failed during validating input" instead of the stale "idle" left over from
    # before this turn started -- current_stage wasn't touched yet at that point otherwise.
    turn = {"language": language, "turn_label": turn_label, "ts": time.time(), "timings": {},
            "input_source": None, "input_audio_bytes": None, "transcribed_text": None,
            "image_bytes": None, "tool_calls": [], "error": None}
    try:
        cfg = LANGUAGES[language]
        session.orch.reset_turn()
        t_total0 = time.perf_counter()

        if image_path:
            with open(image_path, "rb") as f:
                turn["image_bytes"] = f.read()

        if typed_english is not None:
            english_query = typed_english
            turn["input_source"] = "typed"
        else:
            if language == "en":
                raise ValueError("English has no ASR model in this pipeline -- type the query directly.")
            if not audio_bytes:
                raise ValueError("No audio given -- record, upload, or pick a sample clip for this language.")
            turn["input_source"] = "audio"
            turn["input_audio_bytes"] = audio_bytes
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

            session.set_stage(f"ASR ({language})")
            t0 = time.perf_counter()

            def _asr_call():
                return _post_json(f"{GATEWAY}/asr/infer",
                                   {"audio_base64": audio_b64, "language": language}, timeout=60)["text"]

            raw_query = session.orch.run_asr(language, _asr_call)
            turn["timings"]["asr_s"] = time.perf_counter() - t0
            turn["transcribed_text"] = raw_query

            session.set_stage(f"NMT {language}->EN")
            t0 = time.perf_counter()

            def _nmt_in_call():
                return _post_json(f"{GATEWAY}/nmt/infer",
                                   {"text": raw_query, "src_lang": language, "tgt_lang": "EN"},
                                   timeout=30)["translated_text"]

            english_query = session.orch.run_nmt(f"{language}->EN", _nmt_in_call)
            turn["timings"]["nmt_in_s"] = time.perf_counter() - t0

        turn["english_query"] = english_query

        session.set_stage("Agent (tool-calling loop)")
        t0 = time.perf_counter()
        new_messages = []

        def _agent_call():
            with session.lock:
                messages_in = session.messages
            prior_len = len(messages_in) if messages_in else 0
            tee = _TeeToLog(session, sys.__stdout__)
            with contextlib.redirect_stdout(tee):
                tm = session.agent.run_turn(english_query, image_path=image_path, messages=messages_in, verbose=True)
            new_messages.extend(tm)
            turn["tool_calls"] = _extract_tool_calls(tm[prior_len:])
            for tc in turn["tool_calls"]:
                session.log(f"[APP] tool call: {tc['name']}({tc['arguments']})")
            return tm[-1].content

        # tts_language=: cfg["tts_name"] is already known for the whole turn -- lets Rule 5
        # preload exactly this one MMS-TTS language instead of all 4 (2026-08-11 fix, see
        # orchestrator.py's run_agent() docstring). Without this the memory fix still applies
        # (nothing loads eagerly by default any more) but the golden-window latency hiding
        # would be lost -- first real TTS load would land inline at /tts/infer instead.
        english_answer = session.orch.run_agent(_agent_call, tts_language=cfg["tts_name"])
        turn["timings"]["agent_s"] = time.perf_counter() - t0
        english_answer = clean_text(english_answer)
        turn["english_answer"] = english_answer
        turn["english_answer_chars"] = len(english_answer)
        with session.lock:
            session.messages = new_messages
        # Always log the real answer (or the real absence of one) right here, before it's
        # handed to anything downstream -- agent.py's own docstring documents a real,
        # previously-hit failure mode where the model generates real tokens but they land
        # entirely in `.thinking` and `.content` comes back empty, which then silently breaks
        # whatever gets this text next (NMT or TTS) with an error that looks unrelated to the
        # agent. Logging the length + a preview here means that's diagnosable from the log
        # alone next time, instead of needing to guess after the fact which stage the blank
        # text actually broke.
        if english_answer.strip():
            session.log(f"[APP] agent answer ({len(english_answer)} chars): {english_answer[:300]}"
                        + ("..." if len(english_answer) > 300 else ""))
        else:
            turn["answer_was_empty"] = True
            session.log("[APP] WARNING: agent returned an EMPTY answer (likely all generation went into "
                        "`.thinking` and never closed into a real `.content` -- see agent.py's AGENT_THINK "
                        "note). Downstream NMT/TTS is about to run on empty text.")

        if language == "en":
            target_text = english_answer
        else:
            session.set_stage(f"NMT EN->{language}")
            t0 = time.perf_counter()

            def _nmt_out_call():
                return _post_json(f"{GATEWAY}/nmt/infer",
                                   {"text": english_answer, "src_lang": "EN", "tgt_lang": language, "long": True},
                                   timeout=30)["translated_text"]

            target_text = session.orch.run_nmt(f"EN->{language}", _nmt_out_call)
            turn["timings"]["nmt_out_s"] = time.perf_counter() - t0
        turn["target_text"] = target_text

        tts_batch_size = config.WORKERS["tts"]["default_batch_size"]
        session.set_stage(f"TTS ({cfg['tts_name']})")
        t0 = time.perf_counter()

        def _tts_call():
            return _post_json(f"{GATEWAY}/tts/infer",
                               {"text": target_text, "language": cfg["tts_name"], "batch_size": tts_batch_size},
                               timeout=180)

        tts_result = session.orch.run_tts(cfg["tts_name"], _tts_call, batch_size=tts_batch_size,
                                           text_char_count=len(target_text))
        turn["timings"]["tts_s"] = time.perf_counter() - t0
        turn["engine"] = tts_result.get("engine")
        turn["output_audio_bytes"] = base64.b64decode(tts_result["audio_base64"])
        turn["output_sample_rate"] = tts_result.get("sample_rate")
        turn["timings"]["total_s"] = time.perf_counter() - t_total0
    except Exception as exc:
        turn["error"] = str(exc)
        turn["failed_stage"] = session.current_stage  # e.g. "TTS (English)" -- so the UI can say
        # exactly where the pipeline died instead of making someone infer it from the log
        session.log(f"[APP] turn failed during {turn['failed_stage']}: {exc}")
    finally:
        if image_path:
            try:
                os.remove(image_path)
            except OSError:
                pass
        with session.lock:
            session.turns.append(turn)
            session.busy = False
        session.set_stage("idle")
    return turn


def run_weather_demo(session, language):
    """The real 5-turn crop_weather_turns() conversation (tp.crop_weather_turns), same
    fixtures test_orchestrated_pipeline.py's --weather-conversation uses, driven turn by turn
    through run_pipeline_turn() above so it shows up in the UI exactly like a manual turn
    would -- one shared background thread, so Send stays disabled for its whole duration."""
    turns = tp.crop_weather_turns(language)
    with session.lock:
        session.messages = None  # fresh conversation for the demo
    for i, text in enumerate(turns, 1):
        if i > 1:
            session.set_stage(f"waiting {FOLLOWUP_GAP_SECONDS}s before weather-demo turn {i}/{len(turns)}")
            time.sleep(FOLLOWUP_GAP_SECONDS)
        if language == "en":
            run_pipeline_turn(session, language, typed_english=text,
                               turn_label=f"weather-demo {i}/{len(turns)}")
        else:
            fpath = SAMPLE_INPUT_DIR / f"crop_turn{i}_{language}.wav"
            audio_bytes = fpath.read_bytes() if fpath.exists() else None
            run_pipeline_turn(session, language, audio_bytes=audio_bytes,
                               turn_label=f"weather-demo {i}/{len(turns)}")


def _footprint_bytes(component_dict):
    """Same preference order as orchestrator.py's own _component_bytes() -- real
    system-wide delta when available, rss+vram sum otherwise -- reimplemented here (rather
    than reaching into the orchestrator's private method) since it's a two-line computation
    over data snapshot() already returns."""
    delta = component_dict.get("system_mem_delta_bytes")
    if delta is not None:
        return delta
    return (component_dict.get("rss_bytes", 0) or 0) + (component_dict.get("vram_bytes", 0) or 0)


def _memory_history_df(session, limit=600):
    """Per-component memory (GB, CPU+GPU combined -- same _footprint_bytes() preference as the
    live snapshot, real system-wide RSS delta when the worker has one, rss+vram sum otherwise)
    across the whole session, one column per component plus a `total` column -- built from the
    same background-poller history (session.memory_history, sampled every ~1.5s regardless of
    whether a turn is running) the Memory tab's live chart already used, just broken out by
    component here instead of collapsed to a single total. Shared by the Memory tab and the
    Latency tab so both read the exact same history rather than two divergent computations."""
    with session.lock:
        hist = list(session.memory_history)[-limit:]
    if not hist:
        return None
    rows = []
    for h in hist:
        snap = h["snap"]
        row = {"time": time.strftime("%H:%M:%S", time.localtime(h["t"]))}
        for name in ALL_COMPONENTS:
            c = snap["components"][name]
            row[name] = _footprint_bytes(c) / 1e9 if c["state"] == "loaded" else 0.0
        row["total"] = snap["total_bytes"] / 1e9
        rows.append(row)
    return pd.DataFrame(rows).set_index("time")


# ----------------------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------------------

session = get_session()
_register_atexit(session)

st.title("🦜 GramSahayak — Live Pipeline Control Room")
st.caption(
    "Real gateway, real MemoryOrchestrator, real agent -- the same code path as "
    "test_orchestrated_pipeline.py, driven from a browser so memory/latency are visible live "
    "and audio in/out happens through your own mic/speakers even when the pipeline itself is "
    "running on a headless box."
)


@st.fragment(run_every=(1.0 if session.autorefresh_enabled else None))
def render_status_bar():
    s = get_session()
    cols = st.columns([1, 1, 2, 2])
    cols[0].metric("Gateway", "🟢 up" if s.ready else ("🟡 starting" if s.starting else "🔴 down"))
    cols[1].metric("Pipeline", "⏳ busy" if s.busy else "✅ idle")
    cols[2].write("**Current stage:**")
    cols[2].write(s.current_stage)
    with cols[3]:
        if s.orch is not None:
            try:
                snap = s.orch.snapshot()
                st.progress(
                    min(snap["utilization_pct"] / 100, 1.0),
                    text=f"{snap['total_bytes'] / 1e9:.2f}GB / {config.MODEL_BUDGET_BYTES / 1e9:.1f}GB "
                         f"({snap['utilization_pct']}%)",
                )
            except Exception:
                st.write("memory: n/a")
                snap = None
        else:
            snap = None
    # Live per-component breakdown (CPU+GPU combined, same numbers the Memory tab's bar chart
    # uses) right under the aggregate bar, so "what's using memory right now" is visible on
    # every tab, not just the dedicated Memory tab.
    if snap is not None:
        parts = []
        for name in ALL_COMPONENTS:
            c = snap["components"][name]
            if c["state"] == "loaded":
                parts.append(f"**{name}**: {_footprint_bytes(c) / 1e9:.2f}GB")
            else:
                parts.append(f"{name}: —")
        st.caption(" · ".join(parts))

    # One-off full-page rerun exactly on the busy->idle transition -- this is what re-enables
    # the sidebar's Send/Teardown buttons promptly after a turn finishes, now that the sidebar
    # itself no longer polls on a timer (see render_sidebar()'s docstring for why: doing it
    # there would kill an in-progress mic recording). Comparing against busy_seen_by_ui (not
    # just "if not s.busy") means this fires once per completed turn, not every second while
    # idle.
    was_busy = s.busy_seen_by_ui
    s.busy_seen_by_ui = s.busy
    if was_busy and not s.busy:
        st.rerun()


render_status_bar()

if not session.ready:
    st.warning("System not started yet.")
    if session.start_error:
        st.error(f"Last start attempt failed: {session.start_error}")
    if st.button("🚀 Start system (launch gateway + load agent)", disabled=session.starting, type="primary"):
        threading.Thread(target=_start_system, args=(session,), daemon=True).start()
        st.rerun()

    @st.fragment(run_every=1.0)
    def render_startup_log():
        s = get_session()
        st.code("\n".join(list(s.logs)[-40:]) or "(no log lines yet)", language=None)
        if s.ready:
            st.rerun()

    render_startup_log()
    st.stop()


def _list_sample_clips(language):
    if language == "en":
        return []
    return sorted(p.name for p in SAMPLE_INPUT_DIR.glob(f"*_{language}.wav"))


@st.fragment
def render_sidebar():
    """No `run_every` here -- deliberately. This fragment holds st.audio_input(), and a
    periodic auto-rerun tears down and re-instantiates the whole fragment (including any
    in-progress browser-side recording) before it ever lands in Python -- confirmed: a
    run_every=2.0 here meant clicking record and just having it disappear a couple seconds
    later, every time, permission or no permission. Widget-triggered reruns (clicking Send,
    typing, etc.) still only rerun this fragment as normal; the Send/Teardown buttons'
    disabled state instead gets refreshed by a one-off full-page rerun that render_status_bar()
    fires when a turn actually finishes (see its own comment) -- responsive without polling a
    fragment that must never auto-rerun mid-recording."""
    s = get_session()
    with st.sidebar:
        st.header("🎛 Turn composer")
        language = st.selectbox("Language", list(LANGUAGES),
                                 format_func=lambda l: f"{l} — {LANGUAGES[l]['tts_name']}")

        st.divider()
        st.subheader("Input")
        audio_bytes = None
        typed_english = None
        if "typed_en_box" not in st.session_state:
            st.session_state["typed_en_box"] = tp.Q1_TEXT_EN

        if language == "en":
            st.caption("English has no ASR model in this pipeline -- type the query directly.")
            fill_cols = st.columns(2)
            if fill_cols[0].button("Fill: Q1 pesticide"):
                st.session_state["typed_en_box"] = tp.Q1_TEXT_EN
            if fill_cols[1].button("Fill: Q2 plant disease"):
                st.session_state["typed_en_box"] = tp.Q2_TEXT_EN
            typed_english = st.text_area("English query", key="typed_en_box", height=100)
        else:
            input_mode = st.radio(
                "Source", ["🎙️ Record mic", "📁 Upload .wav", "📦 Sample clip", "⌨️ Type English (dev shortcut)"],
                label_visibility="collapsed",
            )
            # Suspend every run_every fragment on the page for exactly the window where a
            # periodic rerun could actually destroy something: "Record mic" selected, AND
            # nothing captured yet. NOT the whole time "Record mic" happens to be the selected
            # radio option -- that was the bug (staying paused through a whole turn's
            # processing, with no live status/memory/logs, just because the mode wasn't
            # switched away from afterward). The moment a clip lands in pending_recorded_audio
            # (real capture, immune to widget remounts -- see PipelineSession), or a turn is
            # actually in flight, there's nothing left to protect, so auto-refresh resumes
            # automatically -- no need to touch the mode selector at all.
            #
            # Confirmed via Streamlit's own issue tracker (#10805 and others) that a periodic
            # rerun ANYWHERE on the page, not just this fragment's own, can reset an unrelated
            # widget's in-progress browser-side state -- st.audio_input's recording only exists
            # in the browser until you stop it. A full-scope st.rerun() (not the fragment-scoped
            # default here) is required for a flip to actually take effect, since the other
            # fragments' decorators live outside this one and only re-evaluate on a full-page
            # rerun.
            want_paused = (
                input_mode == "🎙️ Record mic" and s.pending_recorded_audio is None and not s.busy
            )
            if want_paused == s.autorefresh_enabled:  # i.e. currently NOT in the state we want
                s.autorefresh_enabled = not want_paused
                st.rerun()
            if input_mode == "🎙️ Record mic":
                st.caption(
                    "⚠️ Needs a **secure context** -- the browser's mic API "
                    "(`getUserMedia`) is silently blocked on plain `http://` unless the page "
                    "is `localhost`. Browsing to GX10's IP over http from another machine "
                    "(exactly the remote-monitoring case this app is built for) means the "
                    "record button will look like it does nothing, with no error shown -- "
                    "that's the browser refusing mic access, not a pipeline bug. Fix: "
                    "`ssh -L 8501:localhost:8501 <user>@<gx10-host>`, then browse "
                    "`http://localhost:8501` on *your own* machine -- localhost is exempt "
                    "from the restriction. Or use 📁 Upload .wav below as a workaround."
                )
                st.caption("⏸️ Live auto-refresh (memory/latency/logs/status) is paused everywhere on "
                           "this page while this mode is selected, so recording won't get reset "
                           "mid-capture. It resumes automatically once you switch away from this mode.")
                rec = st.audio_input(f"Record your question in {LANGUAGES[language]['tts_name']}")
                if rec is not None:
                    audio_bytes = rec.getvalue()
                    s.pending_recorded_audio = audio_bytes  # durable copy -- see PipelineSession
                elif s.pending_recorded_audio is not None:
                    audio_bytes = s.pending_recorded_audio  # widget went back to None on this
                    # rerun (e.g. triggered by clicking Send itself) -- fall back to the last
                    # real capture instead of silently losing it
                if audio_bytes:
                    st.caption(f"Captured {len(audio_bytes) / 1024:.1f} KB "
                               f"{'✅' if len(audio_bytes) > 1000 else '⚠️ suspiciously small -- probably empty/silent'}")
                if s.pending_recorded_audio is not None and st.button("🗑️ Clear recording"):
                    s.pending_recorded_audio = None
                    st.rerun()
            elif input_mode == "📁 Upload .wav":
                up = st.file_uploader("Upload a .wav", type=["wav"])
                if up is not None:
                    audio_bytes = up.getvalue()
                    st.audio(audio_bytes)
            elif input_mode == "📦 Sample clip":
                clips = _list_sample_clips(language)
                pick = st.selectbox("Bundled fixture", clips) if clips else None
                if pick:
                    audio_bytes = (SAMPLE_INPUT_DIR / pick).read_bytes()
                    st.audio(audio_bytes)
            else:
                st.caption("Bypasses ASR + the input NMT hop entirely -- useful for testing the "
                            "agent/output side without needing a mic.")
                typed_english = st.text_area("English query", key="typed_en_box", height=100)

        st.divider()
        st.subheader("Photo (optional)")
        use_sample_image = st.checkbox("Attach bundled sample photo (pepper, diseased)")
        uploaded_image = None if use_sample_image else st.file_uploader(
            "Attach your own photo", type=["png", "jpg", "jpeg"])
        if use_sample_image:
            st.image(str(tp.SAMPLE_IMAGE_PATH), caption="pepper_diseased.png (bundled fixture)", width=180)
        elif uploaded_image is not None:
            st.image(uploaded_image, width=180)

        st.divider()
        # Catch "nothing to send yet" here, in the UI, instead of letting it become a confusing
        # downstream pipeline error (run_pipeline_turn's own ValueError) after Send is already
        # clicked -- the real bug this fixes is easy to hit: recording without pressing stop
        # first, or switching input mode after recording. `audio_bytes` here already went
        # through the pending_recorded_audio fallback above, so this reflects reality even if
        # the raw widget value itself went stale.
        missing_input = (
            language != "en" and typed_english is None and not audio_bytes
        )
        send_disabled = s.busy or (s.orch is None) or missing_input
        if missing_input:
            st.warning("⚠️ No audio yet -- record **and press stop**, upload a .wav, or pick a "
                       "sample clip before sending.")
        if st.button("▶️ Send turn", type="primary", disabled=send_disabled, width="stretch"):
            # Set busy synchronously, here, in the main script thread -- not just inside
            # run_pipeline_turn() (which only sets it after the background thread actually
            # starts running, a real race against this same function's st.rerun() a few lines
            # down). Without this, the immediately-following full-page rerun could still see
            # busy=False for a moment and re-pause auto-refresh right as the turn begins,
            # since clearing pending_recorded_audio below would otherwise satisfy
            # want_paused's other two conditions again.
            with s.lock:
                s.busy = True
            if language != "en" and input_mode == "🎙️ Record mic":
                s.pending_recorded_audio = None  # this turn is about to consume it -- clear so
                # a stale clip can't silently get resent for the next turn
            if use_sample_image:
                turn_image_path = _save_temp_bytes(Path(tp.SAMPLE_IMAGE_PATH).read_bytes(), ".png")
            elif uploaded_image is not None:
                turn_image_path = _save_temp_bytes(
                    uploaded_image.getvalue(), Path(uploaded_image.name).suffix or ".png")
            else:
                turn_image_path = None
            threading.Thread(
                target=run_pipeline_turn,
                kwargs=dict(session=s, language=language, audio_bytes=audio_bytes,
                            typed_english=typed_english, image_path=turn_image_path,
                            turn_label=f"turn {len(s.turns) + 1}"),
                daemon=True,
            ).start()
            st.rerun()

        if st.button("🧹 Clear conversation (new session)", width="stretch", disabled=send_disabled):
            with s.lock:
                s.messages = None  # next turn starts the agent with a fresh [system] list
                s.turns = []  # and the Conversation/Latency tabs stop showing the old chat
            st.success("Conversation cleared -- next turn starts a fresh session.")
            st.rerun()

        st.divider()
        st.subheader("Demo")
        st.caption("Runs the real 5-turn crop_weather_turns() conversation from "
                    "test_orchestrated_pipeline.py --weather-conversation, using its bundled "
                    "real audio fixtures for the selected language.")
        if st.button("🌾 Run 5-turn crop/weather demo", disabled=send_disabled, width="stretch"):
            threading.Thread(target=run_weather_demo, args=(s, language), daemon=True).start()
            st.rerun()

        st.divider()
        st.subheader("System")
        if st.button("🔻 Teardown (free all memory)", width="stretch"):
            threading.Thread(target=_teardown_system, args=(s,), daemon=True).start()
            st.rerun()


render_sidebar()


def _render_tool_calls(tool_calls):
    """The structured display of what agent.run_turn() actually dispatched -- real tool name,
    real arguments, real result -- built from _extract_tool_calls()'s parse of the turn's own
    message trace, not from scraped/truncated log text. Expanded by default: the whole point
    is to see what the agent did without an extra click."""
    if not tool_calls:
        st.caption("🔧 No tools called this turn -- the agent answered from the system prompt alone.")
        return
    with st.expander(f"🔧 {len(tool_calls)} tool call(s) -- what the agent actually did", expanded=True):
        for i, tc in enumerate(tool_calls, 1):
            st.markdown(f"**{i}. `{tc['name']}`**")
            args = tc.get("arguments")
            if args:
                st.code(json.dumps(args, indent=2, ensure_ascii=False), language="json")
            result = tc.get("result")
            if result is None:
                st.caption("(no result captured)")
            else:
                st.caption("→ result")
                text = result if isinstance(result, str) else json.dumps(result, indent=2, ensure_ascii=False)
                st.code(text, language=None)


tab_chat, tab_memory, tab_latency, tab_logs = st.tabs(
    ["💬 Conversation", "🧠 Memory (live)", "⏱ Latency", "📜 Raw logs"]
)

with tab_chat:
    @st.fragment(run_every=(1.0 if session.autorefresh_enabled else None))
    def render_chat():
        s = get_session()
        if s.busy:
            st.info(f"⏳ Turn in progress -- stage: **{s.current_stage}**")
        with s.lock:
            turns_snapshot = list(s.turns)
        if not turns_snapshot:
            st.caption("No turns yet -- compose one in the sidebar and hit Send.")
        # Newest first -- session.turns itself stays oldest-first (that's the order
        # run_pipeline_turn() appends in, and what messages= threading across turns relies on
        # reading), this just reverses the *display* order so the turn you just sent is the
        # one you see without scrolling.
        for turn in reversed(turns_snapshot):
            label = turn.get("turn_label") or "turn"
            cfg = LANGUAGES[turn["language"]]
            with st.chat_message("user"):
                st.markdown(f"**{label}** · {cfg['tts_name']}")
                if turn["input_source"] == "audio" and turn.get("input_audio_bytes"):
                    st.audio(turn["input_audio_bytes"])
                    st.write(f"Transcribed: {turn.get('transcribed_text')}")
                if turn.get("image_bytes"):
                    st.image(turn["image_bytes"], width=200)
                if turn.get("english_query"):
                    st.write(f"English query: {turn['english_query']}")
            with st.chat_message("assistant"):
                if turn.get("error"):
                    # Show exactly which stage died (e.g. "TTS (English)") and the real
                    # underlying detail (see _post_json()) -- but still render whatever the
                    # earlier stages actually produced below (tool calls, the agent's answer,
                    # even the translated text if it got that far) rather than discarding real,
                    # hard-won output just because a later stage failed. A 264s agent turn's
                    # answer surviving a downstream TTS crash is exactly the case this matters
                    # for -- see the turn's `failed_stage` for where things actually broke.
                    where = turn.get("failed_stage")
                    st.error(f"Failed during **{where}**: {turn['error']}" if where else turn["error"])
                _render_tool_calls(turn.get("tool_calls", []))
                if turn.get("answer_was_empty"):
                    st.warning(
                        "⚠️ The agent returned an **empty** answer -- all generation likely went into "
                        "`.thinking` and never closed into real `.content` (a known failure mode, see "
                        "agent.py's AGENT_THINK note). This is very likely why the next stage failed on "
                        "empty text, if one did."
                    )
                elif turn.get("english_answer"):
                    st.write(turn["english_answer"])
                if turn["language"] != "en" and turn.get("target_text"):
                    st.markdown(f"**{cfg['tts_name']}:** {turn['target_text']}")
                if turn.get("output_audio_bytes"):
                    st.audio(turn["output_audio_bytes"])
                timings = turn.get("timings", {})  # shown even on error -- whatever stages
                # actually completed (e.g. a real agent_s=264.12s) before a later one failed
                if timings:
                    cols = st.columns(len(timings))
                    for col, (k, v) in zip(cols, timings.items()):
                            col.metric(k.replace("_s", ""), f"{v:.1f}s")

    render_chat()

with tab_memory:
    @st.fragment(run_every=(1.5 if session.autorefresh_enabled else None))
    def render_memory():
        s = get_session()
        if s.orch is None:
            st.info("Orchestrator not ready yet.")
            return
        try:
            snap = s.orch.snapshot()
        except Exception as exc:
            st.error(f"snapshot failed: {exc}")
            return

        st.progress(
            min(snap["utilization_pct"] / 100, 1.0),
            text=f"{snap['total_bytes'] / 1e9:.2f}GB / {config.MODEL_BUDGET_BYTES / 1e9:.1f}GB budget "
                 f"({snap['utilization_pct']}%)",
        )

        comp_rows = []
        for name in ALL_COMPONENTS:
            c = snap["components"][name]
            gb = _footprint_bytes(c) / 1e9 if c["state"] == "loaded" else 0.0
            comp_rows.append({"component": name, "state": c["state"], "GB": round(gb, 3)})
        df_comp = pd.DataFrame(comp_rows).set_index("component")

        col1, col2 = st.columns([1, 1])
        col1.bar_chart(df_comp["GB"])
        col2.dataframe(df_comp, width="stretch")

        df_hist = _memory_history_df(s)
        if df_hist is not None:
            st.markdown("**Per-component memory over time (GB, CPU+GPU combined)**")
            st.line_chart(df_hist[list(ALL_COMPONENTS)])
            st.markdown("**Total memory over time (GB)**")
            st.line_chart(df_hist[["total"]])
        else:
            st.caption("Collecting memory history...")

    render_memory()

with tab_latency:
    @st.fragment(run_every=(2.0 if session.autorefresh_enabled else None))
    def render_latency():
        s = get_session()
        with s.lock:
            turns_snapshot = list(s.turns)
        rows = []
        for turn in turns_snapshot:
            if turn.get("error"):
                continue
            row = {"turn": turn.get("turn_label") or "", "language": turn["language"]}
            row.update({k: round(v, 2) for k, v in turn.get("timings", {}).items()})
            rows.append(row)
        if rows:
            df = pd.DataFrame(rows).set_index("turn")
            st.dataframe(df, width="stretch")
            if "total_s" in df.columns:
                st.bar_chart(df["total_s"])
        else:
            st.caption("No completed turns yet.")

        # Memory alongside latency -- same history the Memory tab charts, so a slow turn's
        # timings above can be read against what memory was doing at the same time (e.g. a
        # golden-window TTS preload landing, or a Rule 6 eviction) without switching tabs.
        st.divider()
        st.markdown("**Memory over time (GB, CPU+GPU combined) -- for correlating with the turns above**")
        df_hist = _memory_history_df(s)
        if df_hist is not None:
            st.line_chart(df_hist[list(ALL_COMPONENTS)])
        else:
            st.caption("Collecting memory history...")

    render_latency()

with tab_logs:
    @st.fragment(run_every=(1.0 if session.autorefresh_enabled else None))
    def render_logs():
        s = get_session()
        with s.lock:
            lines = list(s.logs)[-300:]
        with st.container(height=520):
            st.code("\n".join(lines) or "(empty)", language=None)

    render_logs()
