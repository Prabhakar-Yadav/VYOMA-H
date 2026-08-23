"""MemoryOrchestrator -- a client of the gateway (dev/agents/api_server/gateway.py) that
implements suno-sutra-sw/python/pocketinfer/memory_orchestrator/load_balancer_plan.md's rules
against the real API: complementary ASR/TTS exclusion (Rule 1), proactive NMT eviction before
TTS's peak (Rule 2, REMOVED 2026-08-08, see "NMT policy" below), TTS batch defaults/floor
(Rule 3, since revised), Agent sticky-per-turn (Rule 4), golden-window async preload for TTS
(Rule 5), boundary-ordered checks (Rule 6), on-demand Embedder (Rule 7).

**Agent policy, revised (2026-08-07) -- Rules 8 and 9 removed, Agent loads once and is never
evicted mid-session.** The old design (Rule 9: fire Agent's load in a background thread
concurrently with ASR's own load, to hide Agent's ~25-30s real Jetson load time behind ASR's;
Rule 8: evict Agent before every TTS peak, unconditionally for Parler / conditionally for
mms_tts, so Agent+TTS together stay under budget) is gone. Real testing on Jetson surfaced two
hard, unrecoverable device crashes/reboots during Agent+ASR memory investigation -- the exact
mechanism was never conclusively pinned down (memory-budget arithmetic didn't clearly predict
it; a GPU-driver-level contention/hang between two concurrent CUDA-using processes is the
leading hypothesis, not confirmed), and the decision was made to stop chasing further Jetson
crashes and instead remove the concurrency/reload churn around Agent entirely: load it once, at
session start (see `ensure_agent_loaded_for_session()`), and never touch it again until
`teardown()`.

**Known, deliberately-accepted tradeoff**: Rule 8 existed because of two *already-documented*
real crashes of its own (see the old `_prepare_budget_for_tts_peak()` history preserved in git
-- Parler-TTS measured a real 7.79GB peak with Agent resident; mms_tts had its own real
length-scaling crash for a long answer). Removing Rule 8 means a sufficiently long TTS answer
with Agent resident can, in principle, reproduce either of those. This was an explicit, informed
choice (not an oversight) after real Jetson testing showed the concurrency-avoidance benefit was
worth more than keeping that particular safety net -- revisit if a long-answer TTS crash shows
up again.

**NMT policy, revised (2026-08-08) -- Rule 2 removed, NMT loads once (first use) and is never
evicted mid-session either.** Real 4-turn multi-turn testing on Jetson
(`pipeline_hi_followups_2026-08-08.log`) showed NMT paying its full ~14-17s reload cost on
*every single turn* (no preload-ahead mechanism ever existed for it, unlike ASR's Rule 10) --
purely wasted latency, since `_predict_tts_peak_bytes()`'s per-length TTS estimate combined with
the now-chunked TTS engine's real observed peak (~2.0-2.2GB, flat regardless of answer length,
see ASR_QUANTIZED_TIMING.md) means NMT's ~0.5GB was never actually the thing standing between a
turn and the budget -- Agent (fixed, already resident) and TTS (bounded by chunking) are the only
two components that matter for the peak now. NMT is simply left loaded after its first use each
session, exactly mirroring Agent's policy -- `run_nmt()`'s `keep_loaded` parameter is gone (both
call sites already always passed `keep_loaded=True`; the only place NMT was ever actually
unloaded mid-session was Rule 2 in `_prepare_budget_for_tts_peak()`, which is now removed), and
NMT is excluded from Rule 6's generic eviction pool the same way Agent already was.

Doesn't do its own memory bookkeeping -- every decision reads live `/status`/`/system/memory`
from the gateway first, exactly per API_DESIGN.md's "never a substitute for a real reading."
`config.PREDICTED_LOAD_COST_BYTES` is used only for pre-flight "would this fit" checks before
a load happens.

Usage (see test_orchestrated_pipeline.py for the full pipeline built on this):
    orch = MemoryOrchestrator()
    orch.ensure_agent_loaded_for_session()   # once, before any turn
    text = orch.run_asr("hi", lambda: call_asr_infer(...))
    english = orch.run_nmt("hi->EN", lambda: call_nmt_infer(...))
    answer = orch.run_agent(lambda: call_agent_infer(...))
    translated = orch.run_nmt("EN->hi", lambda: call_nmt_infer(...))
    audio = orch.run_tts("Hindi", lambda: call_tts_infer(...))
"""
import time
import threading
import uuid

import psutil
import requests

from api_server import config
from api_server.session_store import SessionStore, now_iso, sample_random_pincode

GATEWAY = f"http://{config.GATEWAY_HOST}:{config.GATEWAY_PORT}"
WORKER_COMPONENTS = {"asr", "nmt", "tts"}
OLLAMA_COMPONENTS = {"agent": config.OLLAMA_MODELS[0], "embedder": config.OLLAMA_MODELS[1]}
ALL_COMPONENTS = ("agent", "embedder", "asr", "nmt", "tts")


class MemoryOrchestrator:
    def __init__(self, verbose=True, log_fn=print):
        self.verbose = verbose
        self._log_fn = log_fn
        # Turn-scoped state the rules need but can't observe from a memory snapshot alone --
        # set by real tool-calling code, not exercised in this demo -- see Rule 7.
        # (NMT used to have its own `_nmt_output_cached` flag here, gating Rule 2's eviction --
        # removed 2026-08-08 along with Rule 2 itself, see module docstring's "NMT policy".)
        self._tool_needs_embedder = False
        # Real load/unload event log (2026-08-11, added alongside the real-availability fix
        # after a real confirmed Jetson crash) -- every _load()/_unload()/successful async-wait
        # appends one entry here: {time, component, action, duration_sec, turn_label, language}.
        # turn_label/language come from set_turn_context() (called by the test script before
        # each turn) rather than being threaded through every load/unload call site -- this
        # class's own methods stay turn-agnostic, the caller just tags what's "current" and
        # every event records it. Purely additive/observational -- reading this list never
        # affects any Rule's actual decision.
        self.events = []
        self._turn_label = None
        self._turn_language = None
        # Real system-wide before/after memory delta for agent/embedder loads (2026-08-13),
        # mirroring the fix `worker_base.py` already has for asr/nmt/tts's own `system_mem_
        # delta_bytes` -- see that fix's own comment in snapshot() for why rss+vram (the old
        # fallback, still used for agent/embedder before this) undercounts/overcounts CUDA-
        # loaded components on Jetson's unified memory (GPU allocations already show up inside
        # the process's own RSS there, unlike a discrete GPU where they're genuinely separate
        # pools -- so summing them double-counts). Confirmed the double-counting directly: a
        # real crash during --multiturn-stress reported agent=7.31GB via the old rss+vram sum,
        # while the real llama-server process's own RSS was 4.34GB and Ollama's own self-
        # reported size_vram was 2.82GB (4.34+2.82=7.16GB, matching the inflated figure almost
        # exactly) -- and real system-wide `free`-equivalent usage at that same moment was only
        # 5.0GB, making "one component alone uses 7.3GB" mathematically impossible. Keyed by
        # component name ("agent"/"embedder"), populated by _load(), consumed by snapshot().
        self._ollama_mem_delta = {}

        # 2026-08-16: handle to _reload_asr_then_nmt()'s own fire-and-forget daemon thread, so
        # teardown() can wait for it -- see that method's own docstring and teardown()'s own
        # comment for the real race this closes (confirmed live: a real 5-turn Jetson run
        # printed "after teardown: ... nmt=loading ..." followed by "nmt ready in 10.05s"
        # AFTER teardown() had already returned, because this thread's own is_loaded() check
        # hadn't caught up yet when teardown()'s unload loop ran its one-time check).
        self._background_reload_thread = None

        # 2026-08-23: transient permission flag for the record-window ASR preload's
        # eviction ladder (see preload_asr()'s evict_nmt_first). The pocketinfer app pins
        # TTS resident between turns by wrapping this class's _unload (keep_resident=true,
        # gramsahayak_ux.py); the wrapper consults THIS flag so a sanctioned record-window
        # TTS eviction passes through while every ordinary one stays swallowed. False the
        # rest of the time -- set True only inside the ladder's try/finally window.
        self._allow_tts_eviction = False

        # Real session-transcript logging (2026-08-14, api_server/session_store.py) -- see
        # that module's own docstring for the full design/history (a same-day earlier attempt
        # built this at the wrong layer, inside pocketinfer; this supersedes it). Persisted on
        # three real triggers: teardown() (app/process shutting down), reset_conversation()
        # ("Reset" -- cheap, no reload), start_new_session() ("New Session" -- persist + a real
        # full reload/re-warm). A session with zero turns is never written (see
        # _persist_current_session()) -- constructing the orchestrator and immediately tearing
        # it down (every test script that doesn't drive a real turn) shouldn't leave a junk row.
        self._session_store = SessionStore(log_fn=self._log)
        self._current_session = self._new_session_dict()

    def set_turn_context(self, turn_label=None, language=None):
        """Call at the start of each pipeline turn so subsequent load/unload events in
        self.events get tagged with which turn/language they happened during -- purely for
        the post-run loading/unloading times table, no effect on any Rule's behavior."""
        self._turn_label = turn_label
        self._turn_language = language

    def _record_event(self, component, action, duration_sec):
        self.events.append({
            "time": time.time(),
            "component": component,
            "action": action,
            "duration_sec": round(duration_sec, 3),
            "turn_label": self._turn_label,
            "language": self._turn_language,
        })

    def reset_turn(self):
        """Call between pipeline turns -- clears the per-turn flags above."""
        self._tool_needs_embedder = False

    # ------------------------------------------------------------------
    # Session-transcript logging (api_server/session_store.py) -- a SESSION is coarser than a
    # turn: it's everything from device start (or the last reset) through the next hardware
    # trigger or app shutdown. See session_store.py's own module docstring for the full design.
    # ------------------------------------------------------------------

    def _new_session_dict(self):
        """Fresh `self._current_session` accumulator -- a new uuid4, a real (placeholder)
        pincode/state/district sampled from this project's own weather DB, and an empty
        `turns` list that `record_turn()` appends to."""
        try:
            pincode, state, district = sample_random_pincode()
        except Exception as exc:
            # A missing/unbuilt weather DB shouldn't block a real session from starting --
            # location here is only ever a placeholder (no real GPS exists to fall back on
            # either), so logging with no location is strictly better than not logging at all.
            self._log(f"        could not sample a placeholder pincode ({exc}) -- this "
                       f"session will log with no location")
            pincode, state, district = None, None, None
        return {
            "session_id": uuid.uuid4().hex,
            "started_at": now_iso(),
            "pincode": pincode, "state": state, "district": district,
            "turns": [],
        }

    def record_turn(self, **fields):
        """Call once per real completed turn (after TTS/playback, not on a turn that raised
        partway through) with whatever the caller has: `input_language`, `output_language`,
        `had_image`, `raw_query` (original spoken-language ASR text), `english_query`,
        `english_answer`, `target_text` (post-NMT-out), `tool_calls` (e.g.
        `list(agent.last_tool_calls)`, see agent.py's own docstring). `turn_index` and
        `timestamp` are added automatically -- don't pass those. Purely additive/observational,
        same spirit as `_record_event()` above -- never affects any Rule's own behavior, and a
        caller that never calls this just ends up persisting a zero-turn (skipped, see
        `_persist_current_session()`) or shorter session, nothing breaks.

        2026-08-21: also persists immediately, after every turn -- not just at
        teardown()/start_new_session() like before. Real, confirmed gap this closes: a crash or
        power loss mid-session (a real risk on field hardware -- unclean kill, no chance to
        reach teardown()'s own persist call) used to lose the WHOLE session's transcript, even
        if several turns had already completed successfully; a 7-day sweep of the real session
        DB on Jetson (2026-08-21) turned up zero evidence of an actual problem field session,
        consistent with it never having been persisted at all. Safe to do unconditionally:
        `session_store.save()` is `INSERT OR REPLACE` keyed by session_id (see its own
        docstring), so re-saving the same session after each new turn just overwrites the row
        with the latest turns-so-far, not a duplicate. Done SYNCHRONOUSLY here on purpose, not
        on a background thread -- a background write could itself still be lost if the crash
        lands in the small window before that thread runs; a single small sqlite INSERT is
        already documented as fast enough to run synchronously (session_store.py's own
        docstring), and is negligible next to a turn's own real ASR/NMT/Agent/TTS wall-clock
        time (tens of seconds) -- there's no real latency reason to make this async instead."""
        fields["turn_index"] = len(self._current_session["turns"])
        fields["timestamp"] = now_iso()
        self._current_session["turns"].append(fields)
        self._persist_current_session()

    def _persist_current_session(self):
        """Writes `self._current_session` to the sessions DB if it has any turns -- shared by
        every real trigger (`start_new_session()`, `teardown()`), so none of them can silently
        lose a real conversation. No-op for a session with zero turns (e.g. the app just
        started, or a test script that constructs an orchestrator and tears it down without
        ever calling record_turn()). Never raises -- a logging failure shouldn't block a real
        session reset or the app's own shutdown."""
        session = self._current_session
        if not session["turns"]:
            self._log("        no turns recorded this session -- nothing to persist")
            return
        try:
            self._session_store.save(session, ended_at=now_iso())
        except Exception as exc:
            self._log(f"        *** failed to persist session {session['session_id']} "
                       f"({exc!r}) -- continuing anyway ***")

    def start_new_session(self):
        """The ONE real hardware-triggered "reset"/"new session" action (per direct
        instruction: both the device's "Reset" and "New Session" controls call this exact same
        method, not two different-weight variants) -- persists the just-finished session, frees
        real memory, and re-warms the agent so the next farmer's first turn is fast, not cold:

          1. `teardown()` -- persists `self._current_session` to the sessions DB FIRST (see
             `teardown()`'s own docstring), then releases every resident component for real
             (not just Python state) -- one persist call, not a duplicate here.
          2. `ensure_agent_loaded_for_session()` / `ensure_embedder_loaded_for_session()` --
             the exact same two calls a fresh process makes at real startup, re-run here on
             demand instead of only once.
          3. Real prefix-cache warmup (`agent.warmup.warmup_agent`) -- same real fix already
             applied at startup (~4.6x faster first-turn prefill, see warmup.py's own
             docstring) -- imported locally here, not at module level, so a caller that never
             triggers a reset doesn't pay for importing agent.py's own (heavier) dependencies
             just to construct an orchestrator.
          4. Fresh `self._current_session` for the session that's about to start.

        The CALLER is still responsible for its own local turn-state (e.g.
        gramsahayak_app.py's `self.messages = None`) -- this method only owns what it actually
        tracks (memory + the session transcript), not a caller's own conversation-history
        variable."""
        self._log("--- start_new_session: persisting + freeing memory + re-warming " + "-" * 20)
        self.teardown()
        self.ensure_agent_loaded_for_session()
        self.ensure_embedder_loaded_for_session()
        try:
            from agent.warmup import warmup_agent
            warmup_agent(model=config.OLLAMA_MODELS[0], num_ctx=config.OLLAMA_NUM_CTX)
        except Exception as exc:
            # Same resilience as the real startup path -- a slow/failed warmup shouldn't block
            # the new session from starting; the first real turn just pays whatever
            # cold-prefill cost this would have hidden.
            self._log(f"        *** warmup failed ({exc!r}) -- continuing anyway ***")
        self._current_session = self._new_session_dict()
        self._log(f"        new session started: {self._current_session['session_id']} "
                   f"(pincode={self._current_session['pincode']})")

    # ------------------------------------------------------------------
    # Low-level component I/O -- the only place that talks HTTP
    # ------------------------------------------------------------------

    def _worker_status(self, name):
        try:
            return requests.get(f"{GATEWAY}/{name}/status", timeout=10).json()
        except requests.exceptions.RequestException as exc:
            return {"state": "unreachable", "error": str(exc), "rss_bytes": 0, "vram_bytes": 0.0}

    def _ollama_status_all(self):
        try:
            return requests.get(f"{GATEWAY}/agent/status", timeout=10).json()
        except requests.exceptions.RequestException as exc:
            return {"models": [], "vram_bytes": 0.0, "error": str(exc)}

    def _ollama_process_rss_bytes(self, context_length, is_embedding):
        """Real per-process RSS for the specific llama-server subprocess backing this Ollama
        model. `/api/ps` doesn't expose a PID, and its own `digest` field turned out NOT to be
        a usable match key either -- confirmed directly (2026-08-12 live Jetson test) that it's
        a manifest digest, not the same sha256 as the GGUF blob the process's own `--model`
        flag points at, so a naive digest-in-cmdline match silently found nothing (real bug hit
        while building this, not a hypothetical). What DOES match, confirmed directly against a
        real `ps aux`: each spawned llama-server's own `-c <N>` flag is that model's exact
        `context_length` from `/api/ps` (agent: `-c 32768` / embedder: `-c 512`, matching
        32768/512 there) -- `is_embedding` (does `/api/ps` show a `context_length` this class
        knows is the embedder's, i.e. `comp == "embedder"`) is passed through as a second signal
        (embedder's process carries `--embedding`, agent's doesn't) since two simultaneously-
        loaded models sharing an identical context_length would otherwise be ambiguous; not a
        concern for this project's actual 2-model set today, but cheap to guard against anyway.

        Added after a real isolated-load test found agent/embedder's tracked cost was
        undercounting the true system-wide delta: loading qwen3.5:2b alone cost 3.56GB real
        (`free -m` before/after), while `size_vram` alone only self-reports 2.6GB -- the missing
        ~960MB was exactly this process's own RSS (HTTP server, CPU-side buffers, the
        `--mmproj` vision-tower's host-side allocation), previously discarded by `snapshot()`
        hardcoding `rss_bytes: 0` for agent/embedder on the (unverified) assumption that
        Ollama's self-report already covered everything. Embedder showed the same gap even more
        starkly: real delta ~507MB vs a self-reported `size_vram` of just 26MB -- explains why
        every session log all night showed `embedder=0.00GB` despite it being loaded and
        sticky-resident the whole time (see `ensure_embedder_loaded_for_session()`)."""
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                if proc.info["name"] != "llama-server":
                    continue
                cmdline = proc.info["cmdline"] or []
                if "-c" not in cmdline:
                    continue
                c_value = cmdline[cmdline.index("-c") + 1]
                if c_value != str(context_length):
                    continue
                if is_embedding != ("--embedding" in cmdline):
                    continue
                return proc.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, IndexError):
                continue
        return 0

    def _ollama_entry(self, component, ollama_status=None):
        """`ollama_status=` lets a caller doing multiple lookups (see snapshot() below) pass
        one already-fetched /agent/status result in, instead of each lookup hitting the
        network separately -- snapshot() used to fire two full /agent/status round-trips
        (one for "agent", one for "embedder") for what's actually one underlying Ollama
        /api/ps call either way."""
        tag = config.normalize_ollama_tag(OLLAMA_COMPONENTS[component])
        status = ollama_status if ollama_status is not None else self._ollama_status_all()
        for m in status.get("models", []):
            if config.normalize_ollama_tag(m.get("model", "")) == tag:
                return m
        return None

    def _is_loaded(self, name):
        if name in WORKER_COMPONENTS:
            return self._worker_status(name).get("state") == "loaded"
        return self._ollama_entry(name) is not None

    def snapshot(self):
        """Live memory view across all five components -- the same shape as the gateway's
        own /system/memory, but with Agent and Embedder broken out separately (the gateway
        reports them combined, since Ollama itself doesn't distinguish "why" a model is
        loaded).

        `footprint_bytes` (each component) and `total_bytes`/`available_bytes`/
        `utilization_pct` are computed via `_component_bytes()`, which prefers each worker's
        real `system_mem_delta_bytes` over the old rss+vram sum -- see that method and
        `worker_base.py`'s `_system_used_bytes()` docstring for why the old sum undercounted
        CUDA-loaded workers on Jetson by 5x+ (confirmed directly,
        TIMING_RESULTS_CROSS_DEVICE.md Sec. 6). `rss_bytes`/`vram_bytes` are kept in each
        component's dict for diagnostic/backward-compat purposes but are no longer what the
        totals below are built from."""
        components = {}
        for name in ("asr", "nmt", "tts"):
            st = self._worker_status(name)
            components[name] = {
                "state": st.get("state", "unknown"),
                "rss_bytes": st.get("rss_bytes", 0) or 0,
                "vram_bytes": st.get("vram_bytes", 0) or 0,
                "system_mem_delta_bytes": st.get("system_mem_delta_bytes"),
            }
        ollama_status = self._ollama_status_all()  # one round-trip, shared by both lookups below
        for comp in ("agent", "embedder"):
            entry = self._ollama_entry(comp, ollama_status=ollama_status)
            components[comp] = {
                "state": "loaded" if entry else "unloaded",
                # Real per-process RSS, matched by context_length (+ --embedding as a
                # tiebreaker) -- see _ollama_process_rss_bytes()'s own docstring for the real
                # test (2026-08-12) that found this was being silently dropped (hardcoded 0
                # here before), a real ~960MB (agent) / ~480MB (embedder) undercount, not a
                # rounding error.
                "rss_bytes": (
                    self._ollama_process_rss_bytes(entry["context_length"], comp == "embedder")
                    if entry else 0
                ),
                "vram_bytes": float(entry.get("size_vram", 0)) if entry else 0.0,
                # Real system-wide before/after delta from _load() (2026-08-13), same fix
                # workers already had -- see __init__'s `_ollama_mem_delta` comment for the
                # real crash this replaces the old rss+vram-sum fallback because of. None only
                # if this component hasn't gone through THIS orchestrator instance's own
                # _load() yet (e.g. it was already loaded by something else before this
                # process started) -- falls back to the old rss+vram sum in that case, same as
                # workers do when they've never loaded this session either.
                "system_mem_delta_bytes": self._ollama_mem_delta.get(comp),
            }
        _snap_so_far = {"components": components}
        total = sum(self._component_bytes(n, snap=_snap_so_far) for n in components)
        total_rss = sum(c["rss_bytes"] for c in components.values())
        total_vram = sum(c["vram_bytes"] for c in components.values())
        # Real system-wide reading (2026-08-11, added after a real confirmed Jetson crash that
        # this class's own tracking never saw coming -- the pre-crash snapshot showed a
        # comfortable 3.14GB/7.0GB, 44.8%, right before the device went down). `available_bytes`
        # below is a SYNTHETIC number (MODEL_BUDGET_BYTES minus this class's own tracked total)
        # -- it has no connection to what the OS actually has free. If something this class
        # doesn't track erodes real headroom across a long session (OS page cache/buff growth
        # that doesn't reclaim cleanly, a leftover process, fragmentation), the synthetic number
        # stays blind to it right up until a real OOM. `real_available_bytes`/`real_used_bytes`
        # are `psutil.virtual_memory()`'s own ground truth -- ONLY valid when this orchestrator
        # process runs on the same machine as the workers (true for every real deployment and
        # for this repo's own test scripts, which all spawn/reuse a local gateway -- not true if
        # someone ever pointed GATEWAY at a genuinely remote host, a case this doesn't handle).
        vm = psutil.virtual_memory()
        # `misc_bytes` (2026-08-12): whatever's left over once every tracked component's real
        # cost (now fixed up above, not vram-only) is subtracted from real system-wide used --
        # by construction, components + misc always equals real_used_bytes, so this is a
        # reconciliation bucket, not a rounding fudge. Expected to be dominated by a genuine
        # fixed OS/kernel/GPU-driver floor confirmed directly at true idle (~1.1-1.3GB on this
        # Jetson, nothing of ours running at all) plus whatever untracked client/test-harness
        # process happens to be alive (e.g. test_orchestrated_pipeline.py's own ~50-100MB) --
        # logged every snapshot specifically so it can be watched *over time* within one
        # session: roughly flat turn-to-turn is the fixed floor doing its thing as expected, a
        # steady climb turn-over-turn would be a real leak this class still isn't attributing
        # to anything, worth chasing further if it ever shows up.
        misc = max(vm.used - total, 0)
        return {
            "components": components,
            "total_rss_bytes": total_rss,
            "total_vram_bytes": total_vram,
            "total_bytes": total,
            "misc_bytes": misc,
            "available_bytes": config.MODEL_BUDGET_BYTES - total,
            "utilization_pct": round(100 * total / config.MODEL_BUDGET_BYTES, 1),
            "real_available_bytes": vm.available,
            "real_used_bytes": vm.used,
            "real_total_bytes": vm.total,
        }

    def _component_bytes(self, name, snap=None):
        """Real per-component memory footprint. Prefers `system_mem_delta_bytes` (the real
        system-wide before/after delta measured at load time, see `worker_base.py`'s
        `_system_used_bytes()`) when a worker has one -- falls back to `rss_bytes` ALONE for
        components that never get one (a worker never loaded this session, or Ollama's
        agent/embedder, which don't go through a `/load` round-trip this class controls the
        timing of -- for those, `rss_bytes` is now a real per-process reading too, see
        `_ollama_process_rss_bytes()`, not the old hardcoded-0 + vram-only figure).

        2026-08-13: dropped `+ vram_bytes` from this fallback (was `rss_bytes + vram_bytes`).
        Both this dev machine (GB10/Grace-Blackwell, see MODEL_BUDGET_BYTES's own comment)
        and the real Jetson deployment target are UNIFIED memory -- CUDA/GPU allocations are
        already mapped into the process's own address space and counted in `rss_bytes`, not a
        physically separate pool the way a discrete GPU's VRAM is. Summing them double-counts
        the overlap. Confirmed directly on a real crash: this fallback fires whenever
        agent/embedder are found already resident from a PRIOR session (Ollama's own
        `keep_alive=-1` keeps qwen3.5:2b warm across separate script/process runs, so a fresh
        orchestrator instance often never gets to run its own `_load()` and populate a real
        delta for it -- this is the common case, not an edge case) -- real per-process RSS was
        4.34GB, Ollama's own self-reported `size_vram` was 2.82GB, and the old sum (7.16GB)
        matched the inflated `agent=7.31GB`/`7.26GB` this bug produced almost exactly, while
        real total system usage at the same moment was only ~5-6GB, making that reported
        figure mathematically impossible. `vram_bytes` is still recorded on each component
        (see `snapshot()`) for diagnostic/backward-compat purposes, just no longer summed in."""
        snap = snap or self.snapshot()
        c = snap["components"].get(name, {})
        delta = c.get("system_mem_delta_bytes")
        if delta is not None:
            return delta
        return c.get("rss_bytes", 0) or 0

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, msg):
        if self.verbose:
            self._log_fn(f"[ORCH] {msg}")

    def _snapshot_line(self, label):
        snap = self.snapshot()
        parts = []
        for name in ALL_COMPONENTS:
            c = snap["components"][name]
            if c["state"] == "loaded":
                parts.append(f"{name}={self._component_bytes(name, snap) / 1e9:.2f}GB")
            else:
                parts.append(f"{name}={c['state']}")
        self._log(
            f"{label}: {' '.join(parts)} | total={snap['total_bytes'] / 1e9:.2f}GB "
            f"({snap['utilization_pct']}%), budget={config.MODEL_BUDGET_BYTES / 1e9:.1f}GB "
            f"| real_used={snap['real_used_bytes'] / 1e9:.2f}GB real_avail={snap['real_available_bytes'] / 1e9:.2f}GB "
            # misc = real_used - tracked total (see snapshot()'s own docstring on this field) --
            # printed every line on purpose so it's watchable turn-to-turn in a real session log,
            # not just inspectable after the fact from a raw snapshot() dict.
            f"misc={snap['misc_bytes'] / 1e9:.2f}GB"
        )
        return snap

    # ------------------------------------------------------------------
    # Load / unload primitives (with logging + timing)
    # ------------------------------------------------------------------

    def _load(self, name, reason, language=None):
        t0 = time.perf_counter()
        self._log(f"LOAD    {name:9s} <- {reason}")
        if name in WORKER_COMPONENTS:
            params = {"language": language} if language else None
            r = requests.post(f"{GATEWAY}/{name}/load", params=params, timeout=180)
            r.raise_for_status()
        else:
            # Real system-wide before/after delta, same measurement this orchestrator process
            # already trusts for real_used_bytes elsewhere (psutil.virtual_memory(), valid
            # since orchestrator and Ollama run on the same machine) -- see __init__'s
            # `_ollama_mem_delta` comment for why this replaces the old rss+vram sum instead of
            # supplementing it.
            mem_before = psutil.virtual_memory().used
            r = requests.post(f"{GATEWAY}/agent/load", json={"model": OLLAMA_COMPONENTS[name]}, timeout=120)
            r.raise_for_status()
            mem_after = psutil.virtual_memory().used
            self._ollama_mem_delta[name] = max(mem_after - mem_before, 0)
        duration = time.perf_counter() - t0
        self._log(f"        {name} ready in {duration:.2f}s")
        self._record_event(name, "load", duration)

    def _load_async(self, name, reason, language=None):
        """Fire-and-forget -- only meaningful for worker components (Ollama's own load call
        is already fast enough, ~0.5-5s, that a fire-and-forget path isn't worth the extra
        state to track; TTS's ~3.2s load is the one that actually benefits, see Rule 5).

        `language=` (2026-08-11) -- TTS-specific, ignored by ASR/NMT's own `/load`. Without
        it, TTS's `/load` is now a fast no-op (see MultiLangMmsTtsEngine.load()'s own
        docstring for why that changed) -- passing the turn's real target language here is
        what keeps Rule 5's whole point (real load cost hidden in the agent's own downtime,
        not paid inline at first synthesis) intact after that fix, instead of trading the
        memory waste for latency regression."""
        self._log(f"LOAD    {name:9s} <- {reason} (async, fire-and-forget)")
        params = {"mode": "async"}
        if language:
            params["language"] = language
        requests.post(f"{GATEWAY}/{name}/load", params=params, timeout=10)

    def _await_async_load(self, name, timeout=30):
        """Blocks until `name` finishes an in-flight async load. If it's already LOADED by
        the time this is called, returns instantly -- the golden window paid off in full.

        Treats a transient "unreachable" status read (see _worker_status -- that's what a
        failed /status HTTP call itself maps to, not a state the worker ever reports) as
        noise to retry through, not an immediate failure. Confirmed real: ASR's load is
        CPU-heavy (CUDA/onnxruntime graph compilation) and can hold the GIL long enough that
        the worker's own async event loop can't service a concurrent /status request in time
        -- even though the load itself is proceeding fine in the background. Only gives up
        early on a genuine WorkerState.ERROR (a real failure the worker itself reported) or
        once `timeout` is truly exhausted."""
        t0 = time.perf_counter()
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self._worker_status(name)
            state = st.get("state")
            if state == "loaded":
                waited = time.perf_counter() - t0
                if waited > 0.05:
                    self._log(f"        waited {waited:.2f}s for {name}'s async preload to finish")
                else:
                    self._log(f"        {name} was already fully loaded -- zero additional wait (golden window paid off)")
                # Record the worker's own real load_time_sec (measured worker-side, covers the
                # full async load, not just however much of it this call happened to wait
                # through) -- falls back to `waited` if the worker didn't report one.
                real_duration = st.get("load_time_sec")
                self._record_event(name, "load", real_duration if real_duration is not None else waited)
                return True
            if state == "error":
                self._log(f"        {name}'s async preload failed: {st.get('error')}")
                return False
            if state not in ("loading", "unreachable"):
                return False  # not in flight -- caller should do a normal load instead
            time.sleep(0.1)
        self._log(f"        WARNING: {name} still not loaded after {timeout}s wait")
        return False

    def _unload(self, name, reason, full=True):
        t0 = time.perf_counter()
        tag = " (process-kill, no standing pool)" if name in WORKER_COMPONENTS else " (process-kill)"
        self._log(f"EVICT   {name:9s} -> {reason}{tag}")
        if name in WORKER_COMPONENTS:
            r = requests.post(f"{GATEWAY}/{name}/unload", params={"full": str(full).lower()}, timeout=60)
            r.raise_for_status()
        else:
            requests.post(f"{GATEWAY}/agent/unload", json={"model": OLLAMA_COMPONENTS[name]}, timeout=30)
            # The gateway's /agent/unload doesn't poll to confirm -- Ollama's own unload HTTP
            # call returns before the model is actually gone (confirmed directly, see
            # TIMING_RESULTS.md's notes), so poll here to make the budget math trustworthy.
            deadline = time.time() + 15
            while time.time() < deadline and self._is_loaded(name):
                time.sleep(0.1)
            # 2026-08-16 real fix: clear this component's tracked load-time delta now that it's
            # actually confirmed gone. `_component_bytes()` prefers `system_mem_delta_bytes`
            # over `rss_bytes` whenever it's not None (see that method's own docstring), and
            # `_load()` above is the ONLY place that ever SETS `self._ollama_mem_delta[name]` --
            # nothing cleared it on unload before this fix, so a component that had been loaded
            # even once kept "costing" its peak load-time delta in every snapshot()'s
            # total_bytes/available_bytes/utilization_pct for the rest of this orchestrator
            # process's life, even after a real, confirmed unload -- while rss_bytes correctly
            # fell back to 0. Confirmed directly against a real teardown log: `total=4.26GB`
            # printed with `agent=unloaded embedder=unloaded` (i.e. everything genuinely gone)
            # -- that 4.26GB was exactly agent+embedder's stale deltas from when they were last
            # loaded, still being summed. Real `real_used_bytes`/`real_available_bytes`
            # (psutil.virtual_memory(), ground truth) were never affected by this -- only the
            # synthetic tracked total was wrong.
            self._ollama_mem_delta.pop(name, None)
        duration = time.perf_counter() - t0
        self._log(f"        {name} freed in {duration:.2f}s")
        self._record_event(name, "unload", duration)

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------

    def _enforce_complementary(self, target):
        """Rule 1."""
        for a, b in config.COMPLEMENTARY_PAIRS:
            other = b if target == a else (a if target == b else None)
            if other and self._is_loaded(other):
                self._unload(other, reason=f"Rule 1: complementary to {target}, must be unloaded first")

    def _find_eviction_candidate(self, exclude):
        """Rule 6's eviction scoring, adapted: biggest loaded, evictable component wins.

        NMT is deliberately not in this pool (2026-08-08) -- it's sticky-resident now, same as
        Agent, never an eviction candidate for anyone else's room -- see the module docstring's
        "NMT policy"."""
        snap = self.snapshot()
        candidates = []
        for name in ("embedder", "asr", "tts"):
            if name in exclude or snap["components"][name]["state"] != "loaded":
                continue
            if name == "embedder" and self._tool_needs_embedder:
                continue  # actively in use right now
            candidates.append((name, self._component_bytes(name, snap)))
        if not candidates:
            return None
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]

    def _make_room_for(self, name):
        """Rule 6: pre-flight budget check before any load. `name` is one of asr/nmt/tts (the
        components with predicted-cost keys matching their own name) -- Agent/Embedder are
        small enough and infrequent enough as eviction *targets* that this isn't called for
        them; they're still eviction *candidates* via _find_eviction_candidate when something
        else needs the room."""
        predicted = config.PREDICTED_LOAD_COST_BYTES.get(name, 0)
        snap = self.snapshot()
        already_loaded = snap["components"][name]["state"] == "loaded"
        projected = snap["total_bytes"] + (0 if already_loaded else predicted)
        # Real-memory check (2026-08-11) alongside the tracked/synthetic one -- this used to be
        # blind to real system memory entirely, same class of gap already fixed in
        # preload_asr()/Rule 5's TTS preload (see snapshot()'s own docstring). A real crash
        # happened with the tracked check alone reporting "comfortable" right before the
        # device went down -- this is the actual gate before every ASR/NMT/TTS load, so it's
        # the most important of the three to have this right.
        real_headroom_ok = predicted <= snap["real_available_bytes"] or already_loaded
        if projected <= config.MODEL_BUDGET_BYTES and real_headroom_ok:
            return
        self._log(
            f"        budget check: {name} (+{predicted / 1e9:.2f}GB) would reach "
            f"{projected / 1e9:.2f}GB > {config.MODEL_BUDGET_BYTES / 1e9:.1f}GB OR real_avail="
            f"{snap['real_available_bytes'] / 1e9:.2f}GB is too tight -- evicting to make room"
        )
        while projected > config.MODEL_BUDGET_BYTES or not real_headroom_ok:
            candidate = self._find_eviction_candidate(exclude={name, "agent"})
            if not candidate:
                self._log("        WARNING: no safe eviction candidate found -- proceeding anyway")
                break
            freed = self._component_bytes(candidate)
            self._unload(candidate, reason=f"Rule 6: freeing room for {name}")
            projected -= freed
            snap = self.snapshot()
            real_headroom_ok = predicted <= snap["real_available_bytes"]

    def _predict_tts_peak_bytes(self, text_char_count=None):
        """Real, chunk-count-independent plateau estimate for mms_tts (2026-08-13 rewrite --
        see git history for the linear-in-length formula this replaces, which predates and
        directly contradicted this project's own later, more rigorous finding below; kept
        broken in production long enough to produce a real, confirmed-false "projected-at-
        peak=14.39GB vs budget=7.0GB" alarm on a genuine 2042-char answer, whose REAL observed
        total system peak the same run was well under 5GB).

        chunk_text() + tts_worker.py's per-chunk `_release_chunk_memory()` together mean real
        peak memory for one language's synthesis SATURATES almost immediately (already
        near-peak by chunk 0-1) and stays flat regardless of how many more chunks/how long the
        rest of the answer is -- confirmed independently twice, on two different real devices:
        GX10 (2026-08-11, real 2397-char/8-chunk Hindi answer: plateaus by chunk 4, flat
        through chunk 8, ~1.22GB RSS + 0.18GB VRAM growth from steady) and THIS Jetson
        (2026-08-13, real 2042-char/8-chunk Hindi answer, current 360-char/hi chunk config,
        direct isolated measurement matching tts_worker.py's real call pattern exactly: growth
        already at 634MB by chunk 0, 633-653MB range through chunk 7 -- ~20MB of noise, not
        growth). The old formula's two calibration points (430/800 chars) were both well
        inside this same pre-saturation growth window, so extrapolating a straight line from
        them out to a real ~2000-char answer wildly overshot where actual behavior plateaus.

        1.0GB flat (real ~650MB Jetson measurement + margin for one-data-point uncertainty and
        real per-language/content variance) once text is long enough to plateau; scaled down
        for a genuinely short input that may not even reach chunk 0's full growth. Falls back
        to the flat config constant if text_char_count isn't known (defensive default matching
        the old behavior, e.g. if a caller doesn't pass it through)."""
        if text_char_count is None:
            return config.PREDICTED_LOAD_COST_BYTES["tts_peak_batch3"]
        real_plateau_bytes = 1_000_000_000
        if text_char_count < 400:
            return int(real_plateau_bytes * max(0.3, text_char_count / 400))
        return real_plateau_bytes

    def _prepare_budget_for_tts_peak(self, text_char_count=None):
        """Proactive visibility check before TTS ramps from steady to peak (was "Rule 7").

        **Rule 2 (NMT eviction before every TTS peak) removed 2026-08-08**, **Rule 8 (Agent
        eviction before every TTS peak) removed 2026-08-07**, **Rule 7 (embedder on-demand
        eviction before every TTS peak) removed 2026-08-11** -- see the module docstring's "NMT
        policy"/"Agent policy" sections and config.py's OLLAMA_MODELS comment for the full
        history. Embedder is now granite-embedding:30m, loaded once at session start
        (`ensure_embedder_loaded_for_session()`) and never evicted, same policy as Agent/NMT --
        ~30MB isn't worth an eviction cycle for. Rule 8's removal carries a known, deliberately
        accepted tradeoff (this used to be the load-bearing fix for two separate real crashes,
        one on Parler-TTS at a measured 7.79GB peak, one on mms_tts for a sufficiently long
        answer -- both are possible again with Agent resident and no eviction). Nothing gets
        touched here anymore; only `teardown()` unloads any of these three now.
        """
        tts_engine = config.WORKERS["tts"]["engine"]
        tts_peak = (
            self._predict_tts_peak_bytes(text_char_count) if tts_engine == "mms_tts"
            else config.PREDICTED_LOAD_COST_BYTES["tts_peak_batch3"]
        )

        # Diagnostic only now -- Rule 8 used to act on this projection (evicting Agent when it
        # crossed budget); it no longer does, so this is purely a visibility log, not a
        # decision point. See the removed-Rule-8 note above for why. NMT is also always
        # resident now, so it's already folded into snap["total_bytes"] below like Agent is --
        # this projection isn't hiding anything by not separately calling it out anymore.
        snap = self.snapshot()
        tts_steady_now = self._component_bytes("tts", snap) if snap["components"]["tts"]["state"] == "loaded" else 0
        projected = snap["total_bytes"] - tts_steady_now + tts_peak
        self._log(
            f"        TTS-peak check after Rule 7 (Rules 2/8 removed, NMT/Agent never evicted): "
            f"projected-at-peak={projected / 1e9:.2f}GB vs budget={config.MODEL_BUDGET_BYTES / 1e9:.1f}GB"
        )

    # ------------------------------------------------------------------
    # Pipeline-stage API -- what the demo script actually calls
    # ------------------------------------------------------------------

    def preload_asr(self, reason="Rule 10: golden-window preload after TTS eviction",
                     session_language=None, blocking=False, evict_nmt_first=False):
        """Fires ASR's load in a background thread the moment TTS is freed at the end of a
        turn, instead of waiting cold for the next turn's run_asr() call -- overlaps ASR's
        real ~35-55s load time (dominated by CUDA/onnxruntime graph compilation on Jetson,
        not I/O -- confirmed real, see the direct-load timings this was measured from) with
        whatever gap exists before the next turn actually starts: on real hardware, the pause
        while waiting for the next spoken question; in --all test runs, the explicit
        inter-language buffer (see test_orchestrated_pipeline.py). Mirrors Rule 5's pattern
        for TTS (same `_load_async` + worker-status-polling mechanism -- Rule 9's own
        thread+Event pattern, which existed only for this same purpose applied to Agent, is
        gone along with Rule 9 itself, see the module docstring's "Agent policy" section).
        No-op if ASR is already loaded or preloading.

        Budget check uses whatever's resident right now -- Agent is always resident from
        session start onward (never evicted mid-session anymore), so this naturally accounts
        for Agent(~1.31GB) + ASR's own load footprint via the live snapshot, not a hardcoded
        assumption -- see `ASR_CTC_ONLY_TIMING.md`/`TIMING_RESULTS_CROSS_DEVICE.md` for real
        measured numbers on this pairing (and the real crashes encountered probing it further,
        module docstring).

        `session_language=` (2026-08-11): a real production session's language is fixed for
        its whole duration (pocketinfer's own `self.settings["input_language"]`, see
        gramsahayak_app.py) -- pass it so this preload can warm exactly that language's ONNX
        session (`QuantizedMultiLangASR.load(language=...)`, see its own module docstring for
        the real regression this fixes: without a language hint, the lazy-by-default load()
        just marks the engine ready and loads nothing, so the "hide ASR's real load time in
        the gap before the next turn" benefit this whole method exists for had silently become
        a no-op). If `session_language` has no ASR checkpoint at all (English -- see
        config.WORKERS["asr"]["languages"], hi/ta/ml only), skip preloading entirely: there is
        no next turn on an English session that could ever use it, so even the "wasted
        load/evict cycle, not a correctness problem" cost below isn't worth paying for one.

        Leave `session_language=None` (the old behavior, still the default) for a caller that
        genuinely doesn't know the next turn's language ahead of time -- e.g. a mixed-language
        test harness. In that case, or if the next turn turns out not to need ASR at all
        despite a hint being given wrong, the preload goes unused -- Rule 1's complementary-pair
        eviction (asr/tts) cleans it up automatically the moment that turn's TTS stage loads.

        `blocking=` (2026-08-14): False (default, unchanged) fires ASR's load in its own
        background thread and returns immediately, same as always. True runs the exact same
        checks but loads ASR SYNCHRONOUSLY on the caller's own thread instead -- used by
        `_reload_asr_then_nmt()` below so NMT's own reload only starts once ASR's is genuinely
        done, not racing it for GPU memory at the same instant. See that method's docstring
        for the real production crash this sequencing fixes.

        `evict_nmt_first=` (2026-08-23, default False -- record-window pass): when headroom
        is too tight for ASR's predicted load, unload to MAKE room instead of skipping, in a
        fixed ladder -- NMT first (idle mid-recording anyway; it pays a reload at that same
        turn's NMT stage either way under today's memory ceiling, so this only moves WHEN the
        cost happens), then TTS only if still tight after NMT (~0.11GB, but the sanctioned
        sacrifice per the user's explicit instruction; it re-warms via Rule 5's golden-window
        preload at the next answer stage). Used by pocketinfer's GramSahayakUX, which fires
        this from the record-button handler (`_start_recorder`) so ASR's ~12s inline load
        hides inside the farmer speaking instead of sitting in the critical path. Peak
        residency set is unchanged -- this moves today's sanctioned NMT->ASR swap earlier
        into the GPU-idle recording window, it doesn't hold more models resident than before.
        Two coordination notes: (1) TTS eviction only passes through while
        `self._allow_tts_eviction` is set -- the app wraps _unload to keep TTS resident and
        consults that flag; (2) mid-recording nothing GPU-heavy runs (mic capture is
        `arecord`), so unlike an NMT/answer-stage overlap this load has the GPU to itself --
        no Ollama contention window (run_agent()'s measured finding). Default False keeps the
        existing callers (`_reload_asr_then_nmt`, golden-window Rule 10) byte-identical.
        """
        if session_language is not None and session_language not in config.WORKERS["asr"]["languages"]:
            self._log(f"        skipping asr preload -- session_language={session_language!r} has no ASR checkpoint")
            return
        state = self._worker_status("asr").get("state")
        if state in ("loaded", "loading"):
            if blocking and state == "loading":
                self._await_async_load("asr", timeout=90)
            return
        snap = self.snapshot()
        predicted = config.PREDICTED_LOAD_COST_BYTES["asr"]
        # min() of the synthetic tracked figure and the real OS reading -- either one being
        # tight is a real reason to act/skip (see snapshot()'s own docstring for why the
        # synthetic number alone isn't trustworthy).
        headroom = min(snap["available_bytes"], snap["real_available_bytes"])
        if headroom < predicted and evict_nmt_first:
            # Record-window ladder: free sanctioned components until ASR fits or nothing
            # sanctioned remains -- then fall through to the plain skip below, exactly as
            # every pre-ladder caller did when truly out of room.
            headroom = self._evict_for_record_window_preload(predicted)
            snap = self.snapshot()  # re-read so a post-ladder skip log reports post-eviction truth
        if headroom < predicted:
            self._log(f"        skipping asr preload -- only {headroom / 1e9:.2f}GB available "
                       f"(tracked={snap['available_bytes']/1e9:.2f}GB, real={snap['real_available_bytes']/1e9:.2f}GB)")
            return
        if blocking:
            self._load("asr", reason=reason, language=session_language)
        else:
            self._load_async("asr", reason=reason, language=session_language)

    def _evict_for_record_window_preload(self, predicted):
        """The record-window eviction ladder behind preload_asr(evict_nmt_first=True):
        unload NMT, then (only if still short) TTS, re-checking headroom after each.
        Returns the post-eviction min(tracked, real) headroom (always a real number, even
        when nothing was loaded to free) so the caller can still skip honestly if even the
        emptied ladder isn't enough. TTS's unload runs inside the `_allow_tts_eviction`
        window because the app's keep-TTS-resident _unload wrapper otherwise swallows it;
        try/finally so a failed unload can't leave the flag stuck open. Agent is
        deliberately NOT in this ladder -- always-resident policy."""
        snap = self.snapshot()
        headroom = min(snap["available_bytes"], snap["real_available_bytes"])
        for name in ("nmt", "tts"):
            if headroom >= predicted:
                break  # already enough room without touching the next component
            if not self._is_loaded(name):
                continue
            if name == "tts":
                self._allow_tts_eviction = True
            try:
                self._log(f"        record-window preload: freeing {name} first -- "
                           f"real headroom too tight for ASR's ~{predicted / 1e9:.2f}GB load")
                self._unload(name, reason="record-window preload: freeing room for ASR")
            finally:
                if name == "tts":
                    self._allow_tts_eviction = False
            snap = self.snapshot()
            headroom = min(snap["available_bytes"], snap["real_available_bytes"])
        return headroom

    def run_asr(self, language, infer_fn, evict_nmt_first=True):
        """`evict_nmt_first=` (2026-08-16, default True -- REAL confirmed production crash
        fix, found and fixed live on real Jetson hardware). `_find_eviction_candidate()`'s
        pool deliberately excludes NMT (sticky-resident policy, see its own docstring) and
        always excludes Agent -- so when only Agent+NMT are resident (the normal mid-session
        state) and ASR needs real room, `_make_room_for("asr")` has NOTHING it can evict.
        Confirmed via a real Jetson production log: "WARNING: no safe eviction candidate
        found -- proceeding anyway", immediately followed by a genuine CUDA/NvMap allocation
        failure inside ASR's onnxruntime session creation (`cudaErrorMemoryAllocation: out of
        memory`) -- not a fluke, a structurally guaranteed outcome any time real headroom is
        tight in exactly this common resident state (also confirmed separately: real
        `tegrastats`/`/proc/meminfo` measurement shows a genuine ~1.5GB fixed OS/kernel floor
        on this device that MODEL_BUDGET_BYTES's own "8GB-1GB" assumption doesn't fully
        capture -- Agent(~4.2-4.3GB)+NMT(~0.6-0.9GB)+that floor alone leaves well under 1GB of
        real slack for ASR's own loading transient).

        Conditional, not unconditional (unlike run_tts()'s own evict_nmt_first, which always
        evicts NMT if it's loaded): only evicts here if the SAME real-headroom check
        _make_room_for() itself already uses says this specific load is genuinely tight --
        most turns have comfortable real headroom and pay zero extra cost; only the turns that
        would otherwise hit the crash pay a real, controlled ~9-11s NMT reload instead.

        Reloaded SYNCHRONOUSLY right after ASR's own load+infer complete, before this call
        returns -- deliberately NOT the fire-and-forget async pattern run_tts()'s
        `_reload_asr_then_nmt` uses. That pattern is safe there because a farmer has to
        trigger a whole new turn before NMT is needed again, a real multi-second-plus gap.
        Here, `run_nmt()` gets called moments after this returns (ASR's own real infer is
        ~1s) -- nowhere near enough of a gap to hide an async reload safely, and `run_nmt()`
        itself only checks `_is_loaded()` (no wait-for-in-flight-load handling), so an async
        version here would risk `run_nmt()` racing a still-loading NMT -- a new bug in place
        of the crash this fixes. Pass evict_nmt_first=False for the old sticky-through-ASR
        behavior, e.g. an A/B comparison."""
        self._log(f"--- stage: ASR ({language}) " + "-" * 40)
        _evicted_nmt_for_asr = False
        if evict_nmt_first and self._is_loaded("nmt"):
            predicted = config.PREDICTED_LOAD_COST_BYTES.get("asr", 0)
            real_headroom_ok = predicted <= self.snapshot()["real_available_bytes"]
            if not real_headroom_ok:
                self._log("        evict_nmt_first: real headroom too tight for ASR's own "
                           "load -- freeing NMT first (real crash fix, see run_asr()'s own "
                           "docstring)")
                self._unload("nmt", reason="evict_nmt_first: freeing real headroom before ASR load")
                _evicted_nmt_for_asr = True
        self._enforce_complementary("asr")
        self._make_room_for("asr")
        asr_state = self._worker_status("asr").get("state")
        if asr_state == "loading":
            self._log("        ASR was preloading during the previous turn's downtime -- waiting on it now")
            # 90s, not the 30s default -- ASR's real load is ~35-56s (CUDA/onnxruntime graph
            # compile, confirmed on real Jetson hardware), longer than TTS's ~3.2s that the
            # 30s default was tuned for.
            if not self._await_async_load("asr", timeout=90):
                # Genuine failure (error or true timeout, not just "still loading" -- see
                # _await_async_load's docstring) -- fall back to a fresh synchronous load
                # rather than silently proceeding to infer against a not-ready worker (the
                # real bug this fallback fixes: 409 Conflict from /asr/infer).
                self._log("        ASR preload didn't complete -- falling back to a fresh synchronous load")
                # language=language (2026-08-13, was missing) -- real, confirmed root cause of
                # the ASR pipeline being consistently slow: without it, _load()'s own
                # `language` parameter defaults to None, so QuantizedMultiLangASR.load(None)
                # only marks the engine "ready" (a fast no-op, see its own docstring) and the
                # real per-language CUDA session build + warmup (confirmed ~6s directly on this
                # Jetson) gets silently deferred to the first real transcribe() call instead --
                # landing inside THIS call's own "asr infer" timing, disguised as transcription
                # cost. Confirmed via extensive isolated testing tonight: every manual
                # reproduction that explicitly passed language= to /asr/load stayed fast
                # (0.2-0.7s infer); the real orchestrator flow, which never did, was consistently
                # 8-33s. Same fix as preload_asr()'s own already-correct `language=session_language`
                # call a few lines above this method -- this fallback path just never got it.
                self._load("asr", reason=f"transcribing {language} input (preload fallback)", language=language)
        elif asr_state != "loaded":
            self._load("asr", reason=f"transcribing {language} input", language=language)
        else:
            # 2026-08-23: "record-window" added to this line -- since the GramSahayakUX
            # record-button preload (preload_asr(evict_nmt_first=True)) this state is
            # usually reached via THAT window, not the end-of-turn golden window; the
            # distinction matters when reading device logs to attribute latency wins.
            self._log("        ASR already fully loaded "
                      "(record/golden-window preload paid off, zero wait)")
            # 2026-08-23 logging-fix: this branch used to re-record the worker's
            # self-reported load_time_sec here ("so the per-turn table doesn't silently
            # miss it"). Real device log showed why that's a misrepresentation: after
            # session warm start, turn 1's summary printed "asr load 7.7s" -- the
            # BOOT-time load -- under a section literally labeled "loads/unloads since
            # turn start". The worker's load_time_sec describes its LAST load whenever
            # that happened; re-recording it misattributes old work to this turn AND
            # double-counts when the load genuinely was in-window (sync _load() and
            # _await_async_load() already record their own events -- run_nmt()'s
            # identical re-record produced the bogus second "nmt load" entry the same
            # day). Log-only now; the per-turn table stays literal.
            lt = self._worker_status("asr").get("load_time_sec")
            if lt is not None:
                self._log(f"        (asr's underlying load was {lt:.2f}s -- paid outside "
                          f"this turn's window: warm start or earlier downtime)")
        self._snapshot_line("ready")
        t0 = time.perf_counter()
        result = infer_fn()
        infer_elapsed = time.perf_counter() - t0
        self._log(f"        asr infer: {infer_elapsed:.2f}s")
        self._record_event("asr", "infer", infer_elapsed)
        # Rule 6 removed 2026-08-08: used to evict ASR immediately after its own inference,
        # back when its footprint (~2.7-3.7GB, the old multilingual model) was too big to sit
        # through the NMT/Agent stages alongside everything else. The new per-language
        # quantized model's footprint (~0.6-0.8GB for all three languages combined) is small
        # enough to just stay resident -- see ASR_QUANTIZED_TIMING.md. Rule 1 (complementary
        # with TTS) still evicts it when TTS actually needs to load, and Rule 10 still
        # preloads it back afterward -- only the *per-transcription* eviction is gone.
        if _evicted_nmt_for_asr:
            # Synchronous, on purpose -- see evict_nmt_first's own docstring above for why an
            # async reload here would be unsafe (run_nmt() gets called moments after this
            # returns, with no wait-for-in-flight-load handling of its own).
            #
            # 2026-08-16 real fix -- headroom check added before this reload, after a REAL
            # crash: a genuine HTTP 500 from the gateway's /nmt/load (an out-of-memory-class
            # failure, same family as the original crash evict_nmt_first exists to fix) hit
            # when this fired unconditionally with real_avail down to 0.45GB right after ASR's
            # own load, on a real Jetson run. `_reload_asr_then_nmt()`'s own async NMT-reload
            # step already has this exact guard (see its own code) -- this call site never got
            # it because it's the SYNCHRONOUS sibling, not the async one. If headroom is too
            # tight, skip the eager reload here (same graceful-degrade philosophy already
            # documented at that async call site) -- run_nmt() runs moments after this returns
            # and already safely handles "NMT not loaded" via its own _make_room_for() (real
            # eviction + real-memory check), so nothing breaks; this turn's NMT stage just pays
            # a real (small) synchronous load cost there instead of finding it pre-warmed.
            snap = self.snapshot()
            predicted = config.PREDICTED_LOAD_COST_BYTES.get("nmt", 0)
            headroom = min(snap["available_bytes"], snap["real_available_bytes"])
            if headroom < predicted:
                self._log(f"        skipping eager nmt reload -- only {headroom / 1e9:.2f}GB "
                           f"available (tracked={snap['available_bytes']/1e9:.2f}GB, "
                           f"real={snap['real_available_bytes']/1e9:.2f}GB) -- run_nmt() will "
                           f"load it safely when actually needed")
            else:
                self._load("nmt", reason="evict_nmt_first: reloading NMT after ASR load (synchronous)")
        return result

    def run_nmt(self, direction_label, infer_fn):
        """NMT loads on first use and stays resident for the rest of the session (2026-08-08
        policy, mirroring Agent -- see module docstring's "NMT policy"). The old `keep_loaded`
        parameter is gone -- both call sites always passed `keep_loaded=True` anyway, and the
        only path that ever unloaded NMT mid-session (Rule 2) has been removed."""
        self._log(f"--- stage: NMT ({direction_label}) " + "-" * 40)
        if not self._is_loaded("nmt"):
            self._make_room_for("nmt")
            self._load("nmt", reason=f"translating ({direction_label})")
        else:
            self._log("        nmt already resident")
            # 2026-08-23 logging-fix: used to re-record the worker's load_time_sec here
            # ("same real gap already fixed for ASR") -- the reasoning was stale on two
            # counts. (1) Both evict_nmt_first reload paths are SYNCHRONOUS _load() calls
            # today and record their own events; no async NMT load path exists anymore
            # (the old _reload_asr_then_nmt _load_async("nmt") is gone too). (2) When NMT
            # is resident for any other reason -- session warm start, a previous turn's
            # downtime, app restart against the live gateway -- the re-record pulled a
            # minutes-old duration into THIS turn's window. Real device log: one turn
            # showed BOTH "nmt load 10.3s" (the genuine in-window sync load) AND
            # "nmt load 2.4s" (this re-record of the same physical load, worker-side
            # measure) in one summary. Log-only now, mirroring run_asr()'s fix above.
            lt = self._worker_status("nmt").get("load_time_sec")
            if lt is not None:
                self._log(f"        (nmt's underlying load was {lt:.2f}s -- paid outside "
                          f"this turn's window)")
        self._snapshot_line("ready")
        t0 = time.perf_counter()
        result = infer_fn()
        infer_elapsed = time.perf_counter() - t0
        self._log(f"        nmt infer: {infer_elapsed:.2f}s")
        self._record_event("nmt", "infer", infer_elapsed)
        return result

    def ensure_agent_loaded_for_session(self):
        """Loads Agent once, synchronously -- call this exactly once, before any pipeline turn
        runs (see test_orchestrated_pipeline.py's main()). Replaces the old Rule 9 (async
        per-turn preload racing ASR's own load) -- see the module docstring's "Agent policy"
        section for why. No-op if Agent is already loaded (e.g. a second call is harmless).

        Deliberately synchronous, not backgrounded: there's nothing to overlap it with at
        session start (no ASR/NMT stage running yet), so the old async-thread+Event machinery
        would add complexity for zero benefit here.
        """
        if self._is_loaded("agent"):
            self._log("        agent already resident")
            return
        self._load("agent", reason="session start -- loaded once, stays resident all session")

    def ensure_embedder_loaded_for_session(self):
        """Loads Embedder (granite-embedding:30m) once, synchronously -- same policy as
        ensure_agent_loaded_for_session() above, added 2026-08-11 alongside the config.py
        nomic-embed-text -> granite-embedding:30m swap. At ~30MB this is cheap enough that the
        old on-demand Rule 7 (load only when a tool needs it, evict before every TTS peak) buys
        nothing worth the eviction-cycle overhead -- see _prepare_budget_for_tts_peak()'s own
        docstring. No-op if already loaded."""
        if self._is_loaded("embedder"):
            self._log("        embedder already resident")
            return
        self._load("embedder", reason="session start -- loaded once, stays resident all session")

    def ensure_nmt_loaded_for_session(self):
        """Warm-starts NMT at session start IF real headroom allows (2026-08-23 turn-latency
        pass 2, user-requested): saves the first turn's ~9s inline NMT reload at the NMT
        stage. Conditional, unlike its two ensure_* siblings above -- this device is
        memory-bottomed (agent+embedder+ASR alone leave well under 1GB real free on a bad
        day, and OLLAMA_NUM_CTX went 8192 -> 16384 on 2026-08-23, ~137MB more KV cache), so
        when the same min(tracked, real) check every other preload uses says NMT's predicted
        load doesn't fit, skip and leave NMT to run_nmt()'s own proven during-run load path
        (its _make_room_for + evict ladder) instead of forcing an OOM here. Also no-ops when
        NMT is already resident (app restart against a still-running gateway). Call order
        from the app: agent -> ASR -> this -- NMT last so it's the one that yields."""
        if self._is_loaded("nmt"):
            self._log("        nmt already resident")
            return
        snap = self.snapshot()
        predicted = config.PREDICTED_LOAD_COST_BYTES.get("nmt", 0)
        headroom = min(snap["available_bytes"], snap["real_available_bytes"])
        if headroom < predicted:
            self._log(f"        skipping nmt warm start -- only {headroom / 1e9:.2f}GB available "
                       f"(tracked={snap['available_bytes']/1e9:.2f}GB, "
                       f"real={snap['real_available_bytes']/1e9:.2f}GB, "
                       f"need ~{predicted / 1e9:.2f}GB) -- it will load during the first turn "
                       f"as before")
            return
        self._load("nmt", reason="session warm start -- headroom allows")

    def run_agent(self, infer_fn, preload_tts=False, tts_language=None):
        """`preload_tts=` default flipped to False (2026-08-12) -- Rule 5 used to preload TTS
        here, concurrent with the agent's own generation, on the theory that GPU time during
        agent's "thinking" was otherwise idle and free to use. REAL, directly tested finding:
        it isn't. Ollama (llama.cpp/CUDA) and PyTorch (MMS-TTS/CUDA) genuinely contend for
        this Jetson's one shared GPU -- a controlled concurrent test found TTS's own /load
        call (normally 5-16s alone) still hadn't finished after 60s+ running alongside a real
        generation call, and the generation itself was still running past 120s (should have
        taken ~35-40s alone). This wasn't a minor overlap tax, it was severe mutual stalling.
        Real per-language TTS load cost is small either way (~0.11-0.17GB RSS, confirmed
        directly) -- this was never a memory problem, purely a GPU-scheduling one.

        The actual fix: `preload_tts()` (a new standalone method, mirrors `preload_asr()`)
        gets called by the caller right after this method returns, overlapping with the
        NMT-out stage instead -- confirmed clean via the same kind of direct concurrent test
        (NMT's CTranslate2 backend runs CPU-only, `models/nmt/model_loader.py`'s own
        `device="cpu"` -- a real translate call and a TTS load running truly concurrently
        landed at completely normal, uncontended durations for both). Same "hide the load
        cost in downtime" idea Rule 5 always had, just moved to a downtime window that's
        actually free instead of one that only looked free.

        `preload_tts=True` here is kept only for a caller that genuinely wants the old
        during-agent behavior back (e.g. to reproduce/compare against the contention finding
        above) -- not recommended for real use on this hardware.

        `tts_language=` still applies to whichever preload call actually fires -- see that
        docstring for the real per-language-vs-blind-preload-all cost story."""
        self._log("--- stage: Agent " + "-" * 40)
        if not self._is_loaded("agent"):
            # Shouldn't happen in the normal flow (ensure_agent_loaded_for_session() already
            # loaded it, and nothing evicts it mid-session anymore) -- defensive fallback only,
            # e.g. if Ollama itself was restarted externally, outside this orchestrator's view.
            self._log("        WARNING: agent not resident despite never being evicted -- loading now "
                      "(unexpected -- check whether Ollama was restarted externally)")
            self._load("agent", reason="agent turn starting (unexpected cold state)")
        else:
            self._log("        agent already resident")
        if preload_tts and not self._is_loaded("tts"):
            self._log("        WARNING: preload_tts=True on run_agent() -- this reproduces a real "
                       "confirmed GPU-contention slowdown with Ollama, see this method's own docstring")
            snap = self.snapshot()
            tts_steady = config.PREDICTED_LOAD_COST_BYTES["tts_steady"]
            headroom = min(snap["available_bytes"], snap["real_available_bytes"])
            if headroom >= tts_steady:
                self._load_async("tts", reason="Rule 5 (legacy during-agent mode): golden-window preload",
                                  language=tts_language)
            else:
                self._log(f"        skipping TTS preload -- only {headroom / 1e9:.2f}GB available "
                           f"(tracked={snap['available_bytes']/1e9:.2f}GB, real={snap['real_available_bytes']/1e9:.2f}GB)")
        self._snapshot_line("ready")
        t0 = time.perf_counter()
        result = infer_fn()
        self._log(f"        agent turn: {time.perf_counter() - t0:.2f}s")
        return result

    def preload_tts(self, language=None, reason="Rule 5: golden-window preload during NMT-out downtime"):
        """The real fix (2026-08-12) for Rule 5's GPU-contention problem -- see run_agent()'s
        own docstring for the full story and the real concurrent-load numbers behind this.
        Call this right after run_agent() returns (whether or not an NMT-out stage follows) --
        for a non-English turn it overlaps with NMT-out (confirmed directly, 2026-08-14, after
        NMT itself moved to CUDA: some real contention exists, ~0.5s solo -> ~3.5s concurrent,
        but nowhere near the severe Agent+TTS mutual-stalling this method was built to avoid --
        total wall-clock for both running together stayed bounded by TTS's own load time, a net
        win either way); for English (no NMT-out stage at all) it's still safe to call here, it
        just won't have anything to hide behind, no worse than loading synchronously at the TTS
        stage itself. No-op if TTS is already loaded or loading.

        2026-08-23 note: warm-starting TTS at session start was evaluated and DECLINED --
        it would trade turn 1's ~7s wait-for-preload for the same ~5-7s paid on every
        service start, and the boot budget is already +~21s from ASR/NMT. Turn 1 keeps
        the golden-window wait.

        2026-08-14: found (via a direct user question) that this method was never actually
        being called by the real production app (gramsahayak_app.py) at all -- only
        test_orchestrated_pipeline.py called it. So this preload had never fired in real
        production use; every real turn paid TTS's full ~8-12s cold load inline at the TTS
        stage instead. Fixed by adding the missing call to gramsahayak_app.py."""
        if self._is_loaded("tts") or self._worker_status("tts").get("state") == "loading":
            return
        # Real bug found and fixed (2026-08-12): called right after run_agent(), ASR is still
        # resident here from the turn's own input transcription -- Rule 1 doesn't evict it
        # until run_tts() itself starts, much later. Confirmed directly: every turn in a real
        # test run hit "skipping tts preload -- only ~1GB available" at this exact point, real
        # availability recovering to ~1.8-2GB moments later once run_tts() evicted ASR anyway.
        # ASR is genuinely idle here (nothing left to transcribe this turn) -- freeing it now
        # rather than waiting gives this preload the same real headroom run_tts() would see.
        self._enforce_complementary("tts")
        snap = self.snapshot()
        # tts_single_language (2026-08-14, was "tts_steady") -- real, confirmed-in-production
        # bug: "tts_steady" is the OLDER eager-all-4-languages figure (1.47GB), while a real
        # preload here only ever loads ONE language (matching MultiLangMmsTtsEngine's own lazy
        # design). Confirmed directly: once the missing call to this method was added to the
        # real app, every single real preload attempt was rejected by this check anyway --
        # observed real available memory at this point (0.59/1.25/1.34GB) was comfortably
        # enough for the real ~0.11-0.15GB single-language cost, but nowhere near the stale
        # 1.47GB threshold, so the fix that was supposed to start hiding TTS's load cost was
        # itself silently defeated by this second bug in the same real code path.
        tts_single_lang = config.PREDICTED_LOAD_COST_BYTES["tts_single_language"]
        headroom = min(snap["available_bytes"], snap["real_available_bytes"])
        if headroom < tts_single_lang:
            self._log(f"        skipping tts preload -- only {headroom / 1e9:.2f}GB available "
                       f"(tracked={snap['available_bytes']/1e9:.2f}GB, real={snap['real_available_bytes']/1e9:.2f}GB)")
            return
        self._load_async("tts", reason=reason, language=language)

    def run_tts(self, language, infer_fn, batch_size=None, text_char_count=None,
                evict_nmt_first=True, session_language=None):
        """`evict_nmt_first=` (2026-08-11, default True as of a REAL confirmed crash -- was
        opt-in/False until a live 4-language Jetson multi-turn stress test genuinely crashed
        the device mid-TTS-synthesis on Malayalam turn 1: the /tts/infer call hung past its
        180s timeout, the whole device stopped responding to SSH for ~5.5 minutes, then came
        back up on a fresh boot (`last -x reboot` confirmed a real reboot at the time of the
        hang, not just a stall). The pre-hang orchestrator snapshot showed only 3.14GB/7.0GB
        (44.8%) resident -- nowhere near the tracked budget -- so whatever actually spiked
        stayed invisible to this class's own accounting; the real trajectory during the hang
        was lost too (see _poll_peak()'s own note below on why). Root cause not fully
        isolated, but NMT sitting resident through TTS's own memory-heavy synthesis window is
        the one clearly avoidable contributor identified so far, and freeing it is cheap
        (reloads async, hidden in the same post-turn downtime ASR's Rule 10 preload already
        uses) -- so it defaults on now rather than waiting for a second crash to confirm the
        theory. Evicts NMT (if loaded) BEFORE the peak-check below runs, then reloads it async
        alongside Rule 10's ASR preload once TTS is freed. `session_language` gets threaded to
        `preload_asr()` (see its own docstring for why) and also skips the NMT reload entirely
        for an English session (NMT is never called there either -- see run_full_pipeline()'s
        own `language == "en"` branch, no translation step exists to reload for). Pass
        `evict_nmt_first=False` explicitly to get the old sticky-resident-through-TTS behavior
        back, e.g. for an A/B comparison."""
        batch_size = batch_size or config.WORKERS["tts"]["default_batch_size"]
        self._log(f"--- stage: TTS ({language}, batch_size={batch_size}) " + "-" * 40)
        if evict_nmt_first and self._is_loaded("nmt"):
            self._unload("nmt", reason="evict_nmt_first: freeing headroom before TTS synthesis")
        self._prepare_budget_for_tts_peak(text_char_count)
        self._enforce_complementary("tts")

        tts_state = self._worker_status("tts").get("state")
        if tts_state == "loading":
            self._log("        TTS was preloading during the Agent/NMT downtime -- waiting on it now")
            if not self._await_async_load("tts"):
                # Same fallback as run_asr() -- genuine failure (not just "still loading",
                # see _await_async_load's docstring), so retry with a fresh synchronous load
                # rather than silently proceeding to infer against a not-ready worker.
                self._log("        TTS preload didn't complete -- falling back to a fresh synchronous load")
                self._load("tts", reason="tts stage starting (preload fallback)")
        elif tts_state != "loaded":
            self._load("tts", reason="tts stage starting (no successful preload)")
        else:
            self._log("        TTS already fully loaded (golden-window preload paid off, zero wait)")
            lt = self._worker_status("tts").get("load_time_sec")
            if lt is not None:
                self._record_event("tts", "load", lt)

        self._snapshot_line("steady-state ready, starting synthesis (peak incoming)")

        # Real baseline for isolating TTS's OWN contribution (2026-08-13, see below) -- taken
        # right at the steady-state point just logged above, before synthesis starts growing
        # anything.
        baseline_bytes = self.snapshot()["total_bytes"]
        peak_delta_bytes = [0]
        stop_flag = threading.Event()

        def _poll_peak():
            # Real gap found and fixed (2026-08-11): this used to only report peak_bytes[0]
            # AFTER infer_fn() returns -- so a call that hangs/crashes (a real TTS /infer call
            # once hung past its 180s timeout and the whole device stopped responding, see
            # run_tts()'s own docstring) leaves zero trace of what memory was actually doing
            # during the hang, even though this thread was sampling the whole time. Now logs
            # every time it sees a meaningfully higher peak (>=50MB over the last logged one,
            # to avoid spamming every 0.15s) -- real, incremental, on-disk evidence that
            # survives the process even if infer_fn() never returns.
            #
            # Tracks growth ABOVE baseline_bytes, not the raw whole-system total (2026-08-13
            # fix -- this used to sample `self.snapshot()["total_bytes"]` directly, i.e.
            # Agent+embedder+(NMT if resident)+TTS combined, then get logged/compared as if it
            # were "tts alone": a real, confirmed apples-to-oranges bug -- e.g. a run with
            # Agent(4.53GB)+embedder(0.10GB) already steady would report a "~4.76GB tts peak"
            # for a TTS call that only actually grew memory by ~0.65GB. Subtracting the real
            # steady-state baseline isolates what THIS synthesis call actually added, which is
            # the only number `_predict_tts_peak_bytes()`'s real measurements (themselves
            # measured as delta-from-steady, see its own docstring) are comparable against.
            last_logged = [0]
            while not stop_flag.is_set():
                current = self.snapshot()["total_bytes"] - baseline_bytes
                peak_delta_bytes[0] = max(peak_delta_bytes[0], current)
                if peak_delta_bytes[0] - last_logged[0] >= 50_000_000:
                    self._log(f"        [live] tts synthesis pool growth above steady: "
                              f"{peak_delta_bytes[0] / 1e9:.3f}GB (t+{time.perf_counter() - t0_poll:.1f}s)")
                    last_logged[0] = peak_delta_bytes[0]
                time.sleep(0.15)

        t0_poll = time.perf_counter()
        poll_thread = threading.Thread(target=_poll_peak, daemon=True)
        poll_thread.start()
        t0 = time.perf_counter()
        try:
            result = infer_fn()
        finally:
            stop_flag.set()
            poll_thread.join(timeout=2)
        elapsed = time.perf_counter() - t0
        # Same real prediction _prepare_budget_for_tts_peak() already used before this call
        # started (2026-08-13 fix -- this used to always read the flat Parler-only
        # "tts_peak_batch3" constant here regardless of engine, disagreeing with the real
        # char-count-aware mms_tts prediction computed just above, a real confirmed
        # inconsistency: the same run logged a 9.74GB mms_tts prediction in one place and a
        # 3.70GB Parler-constant prediction in this one, for the same synthesis call).
        tts_engine = config.WORKERS["tts"]["engine"]
        predicted_growth = (
            self._predict_tts_peak_bytes(text_char_count) if tts_engine == "mms_tts"
            else config.PREDICTED_LOAD_COST_BYTES["tts_peak_batch3"]
        )
        self._log(
            f"        tts infer: {elapsed:.2f}s, observed growth above steady "
            f"~{peak_delta_bytes[0] / 1e9:.2f}GB (predicted ~{predicted_growth / 1e9:.2f}GB for tts alone at batch={batch_size})"
        )
        self._record_event("tts", "infer", elapsed)
        if getattr(config, "TTS_STAY_RESIDENT", False):
            self._log("        [policy] TTS stays resident between turns")
        else:
            self._unload("tts", reason="turn complete, freeing TTS")
        if evict_nmt_first and session_language != "en" and not self._is_loaded("nmt"):
            # 2026-08-14: SEQUENCED (ASR then NMT), not concurrent -- see
            # _reload_asr_then_nmt()'s own docstring for the real production crash this fixes.
            # Used to be self.preload_asr(...) + a separate self._load_async("nmt", ...) fired
            # back-to-back here, each spinning up its own independent background thread at the
            # same instant.
            self._reload_asr_then_nmt(session_language)
        else:
            self.preload_asr(session_language=session_language)
        return result

    def _reload_asr_then_nmt(self, session_language):
        """2026-08-14: real fix for a confirmed production crash, not a theoretical worry --
        ASR's Rule 10 preload and NMT's post-TTS reload used to fire as two INDEPENDENT
        concurrent background threads the instant TTS was evicted, both touching GPU/NvMap
        memory allocation at the same real moment. Under real tight memory (confirmed: a real
        full 10-case Hindi pipeline run had real_avail down to ~1GB right when this fired),
        that race triggered a genuine CUDA/NvMap allocation failure inside ASR's onnxruntime
        session (`NvMapMemAllocInternalTagged failed: error 12` ->
        `cudaErrorMemoryAllocation:out of memory`) -- not a slowdown, a hard crash that left
        the ASR worker broken; the next real turn's `/asr/infer` call then hit an HTTP 500.

        Fix: one background thread, ASR loads first (confirmed ~6-9s warm on real Jetson
        hardware -- much faster in practice than this file's older "~35-55s cold load"
        estimate), THEN NMT loads, using `preload_asr(..., blocking=True)` so this thread
        itself waits rather than firing a second concurrent one. Real budget for this: a
        farmer's TTS answer plays for ~15s+ before they'd plausibly start speaking again, and
        this whole sequence runs hidden in that window plus the gap before the next turn even
        starts -- sequencing costs a few real seconds of background time (NMT ready slightly
        later than the old, riskier concurrent version) but that cost is invisible to the
        farmer, unlike a crash. Still fire-and-forget from the caller's perspective (run_tts()
        doesn't block on this thread) -- only the ASR/NMT ordering inside it changed."""
        def _sequence():
            # 2026-08-14: wrapped in try/except after a real (non-fatal) incident -- the
            # gateway was itself momentarily unreachable (ConnectionRefusedError on
            # `/nmt/load`, same real memory-pressure family as the crash this method fixes,
            # just a transient hiccup rather than a hard failure this time) during a live
            # 10-case run. Without this, an uncaught exception in a background thread just
            # dumps a raw traceback to stderr and vanishes -- confusing, and easy to mistake
            # for something worse than it is. Degrades safely either way: if this background
            # reload fails or is skipped, the next real run_nmt() call just does a normal
            # synchronous load instead of finding NMT already warm -- a real but minor latency
            # cost for that one turn, not a correctness problem (confirmed directly: this
            # exact incident's very next turn loaded NMT fine in the foreground when needed).
            try:
                self.preload_asr(session_language=session_language, blocking=True)
                if self._is_loaded("nmt"):
                    return
                snap = self.snapshot()
                predicted = config.PREDICTED_LOAD_COST_BYTES["nmt"]
                headroom = min(snap["available_bytes"], snap["real_available_bytes"])
                if headroom < predicted:
                    self._log(f"        skipping nmt reload -- only {headroom / 1e9:.2f}GB available "
                               f"(tracked={snap['available_bytes']/1e9:.2f}GB, real={snap['real_available_bytes']/1e9:.2f}GB)")
                    return
                self._load("nmt", reason="evict_nmt_first: reloading NMT after ASR's sequenced preload")
            except Exception as exc:
                self._log(f"        *** background ASR-then-NMT sequence failed ({exc!r}) -- "
                           f"non-fatal, next real use just loads synchronously instead ***")
        t = threading.Thread(target=_sequence, daemon=True)
        self._background_reload_thread = t  # so teardown() can wait for it -- see its own comment
        t.start()

    def teardown(self):
        """Unload everything still resident -- call at the very end of a session to
        demonstrate/confirm the pool genuinely returns to empty, not just between turns.

        2026-08-14: persists `self._current_session` FIRST (see `_persist_current_session()`)
        -- this is the real "app/process shutting down" trigger from session_store.py's own
        docstring, so a farmer's conversation is captured even if only `teardown()` gets
        called directly (a test script's own cleanup, a crash-handler path) rather than
        through `start_new_session()`. `start_new_session()` relies on THIS persist rather
        than doing its own separate one -- one persist call per real teardown, not two."""
        self._persist_current_session()

        # 2026-08-16 real fix -- wait for any in-flight _reload_asr_then_nmt() background
        # thread BEFORE the unload loop below runs its one-time is_loaded() checks. Confirmed
        # live on a real 5-turn Jetson run: that thread was still mid-flight (hadn't loaded NMT
        # yet) at the exact instant teardown() was called, so the loop below's own is_loaded()
        # check missed it (read not-loaded-yet) -- the thread then went on to actually LOAD NMT
        # after teardown()'s own "after teardown" line had already printed and returned,
        # leaving it genuinely resident with nothing left to unload it. Bounded wait (not
        # indefinite): the sequence's own real worst case is ASR (~6-9s warm) + NMT (~10s), so
        # 20s covers it with real margin -- if it's somehow still running past that, the loop
        # below still runs as before and simply won't catch a load that finishes even later.
        t = self._background_reload_thread
        if t is not None and t.is_alive():
            self._log("        waiting for in-flight background ASR/NMT reload before teardown...")
            t.join(timeout=20.0)

        self._log("--- teardown: releasing everything still resident " + "-" * 20)
        for name in ALL_COMPONENTS:
            if self._is_loaded(name):
                self._unload(name, reason="session teardown")

        # 2026-08-16 real fix -- settle before the final snapshot. A real caller's OWN process
        # (an interactive test script, gramsahayak_app.py itself) is very often dying from the
        # SAME signal that triggered this teardown (Ctrl+C/SIGTERM hits the whole process
        # group, including the gateway subprocess if the caller hasn't detached it) -- if that
        # sibling process's own CUDA/torch state is still mid-exit at the instant the unload
        # loop above finishes, `psutil.virtual_memory()` can briefly report real_used still
        # elevated even though everything THIS orchestrator tracks already reads unloaded/
        # unreachable. Confirmed directly: a real teardown log showed real_used=7.34GB/
        # real_avail=0.57GB printed immediately after "everything unloaded", but the SAME
        # machine measured genuinely idle (~1.5GB, matching the independently-established OS
        # floor, zero llama-server/gateway processes) well after -- a transient race in when
        # the snapshot got taken, not a standing leak. Briefly poll for real_available_bytes to
        # stop climbing (cheap -- shutdown isn't latency-sensitive) so the number actually
        # printed reflects settled state instead of a mid-death instant that reads like a leak.
        settle_deadline = time.time() + 3.0
        prev_avail = None
        while time.time() < settle_deadline:
            avail = psutil.virtual_memory().available
            if prev_avail is not None and avail <= prev_avail:
                break  # stopped climbing -- whatever was going to free up already has
            prev_avail = avail
            time.sleep(0.5)
        self._snapshot_line("after teardown")

    def print_events_table(self):
        """Real load/unload times, one row per event, grouped by turn/language -- answers
        "how long did loading/unloading actually take, per turn, per language" directly from
        self.events (see set_turn_context()'s docstring) instead of having to reconstruct it
        by hand from scattered [ORCH] log lines. Call any time -- safe to call mid-session
        (e.g. from a per-turn hook) as well as at the end, so a crash leaves a real partial
        table on disk instead of nothing."""
        if not self.events:
            self._log_fn("(no load/unload events recorded yet)")
            return
        self._log_fn("\n" + "=" * 100)
        self._log_fn("LOAD/UNLOAD TIMES")
        self._log_fn("=" * 100)
        header = f"{'turn':30s} {'language':10s} {'component':10s} {'action':8s} {'duration_sec':>12s}"
        self._log_fn(header)
        self._log_fn("-" * len(header))
        for e in self.events:
            self._log_fn(
                f"{str(e['turn_label'] or '-'):30s} {str(e['language'] or '-'):10s} "
                f"{e['component']:10s} {e['action']:8s} {e['duration_sec']:>12.3f}"
            )
