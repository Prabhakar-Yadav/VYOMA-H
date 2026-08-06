"""MemoryOrchestrator -- a client of the gateway (dev/agents/api_server/gateway.py) that
implements suno-sutra-sw/python/pocketinfer/memory_orchestrator/load_balancer_plan.md's rules
against the real API: complementary ASR/TTS exclusion (Rule 1), proactive NMT eviction before
TTS's peak (Rule 2), TTS batch defaults/floor (Rule 3, since revised), Agent sticky-per-turn
(Rule 4), golden-window async preload for TTS (Rule 5), boundary-ordered checks (Rule 6),
on-demand Embedder (Rule 7), Agent eviction before every TTS peak (Rule 8 -- unconditional for
Parler, the load-bearing real fix there; conditional/budget-checked for mms_tts, since its real
peak is small and predictable enough that evicting Agent isn't automatically necessary -- see
`_prepare_budget_for_tts_peak()`'s own docstring), and golden-window async preload for Agent
itself during ASR/NMT downtime (Rule 9, `preload_agent()`).

Doesn't do its own memory bookkeeping -- every decision reads live `/status`/`/system/memory`
from the gateway first, exactly per API_DESIGN.md's "never a substitute for a real reading."
`config.PREDICTED_LOAD_COST_BYTES` is used only for pre-flight "would this fit" checks before
a load happens.

Usage (see test_orchestrated_pipeline.py for the full pipeline built on this):
    orch = MemoryOrchestrator()
    text = orch.run_asr("hi", lambda: call_asr_infer(...))
    english = orch.run_nmt("hi->EN", lambda: call_nmt_infer(...))
    answer = orch.run_agent(lambda: call_agent_infer(...))
    translated = orch.run_nmt("EN->hi", lambda: call_nmt_infer(...), keep_loaded=False)
    audio = orch.run_tts("Hindi", lambda: call_tts_infer(...))
"""
import time
import threading

import requests

from api_server import config

GATEWAY = f"http://{config.GATEWAY_HOST}:{config.GATEWAY_PORT}"
WORKER_COMPONENTS = {"asr", "nmt", "tts"}
OLLAMA_COMPONENTS = {"agent": config.OLLAMA_MODELS[0], "embedder": config.OLLAMA_MODELS[1]}
ALL_COMPONENTS = ("agent", "embedder", "asr", "nmt", "tts")


class MemoryOrchestrator:
    def __init__(self, verbose=True, log_fn=print):
        self.verbose = verbose
        self._log_fn = log_fn
        # Turn-scoped state the rules need but can't observe from a memory snapshot alone --
        # set by the pipeline caller (run_nmt marks this automatically; tool_needs_embedder
        # would be set by real tool-calling code, not exercised in this demo -- see Rule 7).
        self._nmt_output_cached = False
        self._tool_needs_embedder = False
        # name -> threading.Event, set once a background preload_* call's load finishes.
        # Ollama's own API has no async-load primitive (unlike the workers' ?mode=async),
        # so "async" for agent/embedder means running the normal blocking call in a
        # background thread from this process -- see preload_agent().
        self._pending_preloads = {}

    def reset_turn(self):
        """Call between pipeline turns -- clears the per-turn flags above."""
        self._nmt_output_cached = False
        self._tool_needs_embedder = False

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
        loaded)."""
        components = {}
        for name in ("asr", "nmt", "tts"):
            st = self._worker_status(name)
            components[name] = {
                "state": st.get("state", "unknown"),
                "rss_bytes": st.get("rss_bytes", 0) or 0,
                "vram_bytes": st.get("vram_bytes", 0) or 0,
            }
        ollama_status = self._ollama_status_all()  # one round-trip, shared by both lookups below
        for comp in ("agent", "embedder"):
            entry = self._ollama_entry(comp, ollama_status=ollama_status)
            components[comp] = {
                "state": "loaded" if entry else "unloaded",
                "rss_bytes": 0,
                "vram_bytes": float(entry.get("size_vram", 0)) if entry else 0.0,
            }
        total_rss = sum(c["rss_bytes"] for c in components.values())
        total_vram = sum(c["vram_bytes"] for c in components.values())
        total = total_rss + total_vram
        return {
            "components": components,
            "total_rss_bytes": total_rss,
            "total_vram_bytes": total_vram,
            "total_bytes": total,
            "available_bytes": config.MODEL_BUDGET_BYTES - total,
            "utilization_pct": round(100 * total / config.MODEL_BUDGET_BYTES, 1),
        }

    def _component_bytes(self, name, snap=None):
        snap = snap or self.snapshot()
        c = snap["components"].get(name, {})
        return (c.get("rss_bytes", 0) or 0) + (c.get("vram_bytes", 0) or 0)

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
            f"({snap['utilization_pct']}%), budget={config.MODEL_BUDGET_BYTES / 1e9:.1f}GB"
        )
        return snap

    # ------------------------------------------------------------------
    # Load / unload primitives (with logging + timing)
    # ------------------------------------------------------------------

    def _load(self, name, reason):
        t0 = time.perf_counter()
        self._log(f"LOAD    {name:9s} <- {reason}")
        if name in WORKER_COMPONENTS:
            r = requests.post(f"{GATEWAY}/{name}/load", timeout=180)
            r.raise_for_status()
        else:
            r = requests.post(f"{GATEWAY}/agent/load", json={"model": OLLAMA_COMPONENTS[name]}, timeout=120)
            r.raise_for_status()
        self._log(f"        {name} ready in {time.perf_counter() - t0:.2f}s")

    def _load_async(self, name, reason):
        """Fire-and-forget -- only meaningful for worker components (Ollama's own load call
        is already fast enough, ~0.5-5s, that a fire-and-forget path isn't worth the extra
        state to track; TTS's ~3.2s load is the one that actually benefits, see Rule 5)."""
        self._log(f"LOAD    {name:9s} <- {reason} (async, fire-and-forget)")
        requests.post(f"{GATEWAY}/{name}/load", params={"mode": "async"}, timeout=10)

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
        self._log(f"        {name} freed in {time.perf_counter() - t0:.2f}s")

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
        """Rule 6's eviction scoring, adapted: biggest loaded, evictable component wins."""
        snap = self.snapshot()
        candidates = []
        for name in ("embedder", "nmt", "asr", "tts"):
            if name in exclude or snap["components"][name]["state"] != "loaded":
                continue
            if name == "nmt" and not self._nmt_output_cached:
                continue  # not safe -- still needed this turn
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
        if projected <= config.MODEL_BUDGET_BYTES:
            return
        self._log(
            f"        budget check: {name} (+{predicted / 1e9:.2f}GB) would reach "
            f"{projected / 1e9:.2f}GB > {config.MODEL_BUDGET_BYTES / 1e9:.1f}GB -- evicting to make room"
        )
        while projected > config.MODEL_BUDGET_BYTES:
            candidate = self._find_eviction_candidate(exclude={name, "agent"})
            if not candidate:
                self._log("        WARNING: no safe eviction candidate found -- proceeding anyway")
                break
            freed = self._component_bytes(candidate)
            self._unload(candidate, reason=f"Rule 6: freeing room for {name}")
            projected -= freed

    def _predict_tts_peak_bytes(self, text_char_count=None):
        """Length-scaled mms_tts peak estimate, replacing a flat constant that turned out to
        be measured at exactly one specific length. config.py's mms_tts block documents two
        real data points, both real live/direct runs: 430 chars -> 2.53GB combined RSS+VRAM,
        800 chars -> 3.67GB. That's a 45% peak increase for an 86% length increase -- real,
        meaningful content-dependence, not "far less content-dependent" as this method's
        caller originally assumed (that assumption is what let a genuinely long Hindi answer
        -- multi-section, numbered dosages, comfortably 1200+ chars -- get waved through as
        "projected 5.01GB fits budget" by the flat 3.7GB constant, immediately followed by a
        real device crash/reboot; the flat-constant version of this function never saw the
        text at all, only config.py's one fixed number).

        Linear fit from those two points: ~1.2GB baseline + ~3.08MB/char. +30% safety margin
        on top -- only two real data points is not enough to trust a tight fit, and separately
        observed peaks have varied 3.47-4.74GB against the *same* flat 3.7GB estimate on
        answers of similar length (see TTS_ENGINE_TIMING_RESULTS.md), so real variance beyond
        pure char-count exists too (phoneme complexity, language, etc.) -- err conservative.

        Falls back to the flat config constant if text_char_count isn't known (defensive
        default matching the old behavior, e.g. if a caller doesn't pass it through)."""
        if text_char_count is None:
            return config.PREDICTED_LOAD_COST_BYTES["tts_peak_batch3"]
        predicted_gb = 1.2 + 0.00308 * text_char_count
        return int(predicted_gb * 1e9 * 1.3)

    def _prepare_budget_for_tts_peak(self, text_char_count=None):
        """Rules 2, 7, and 8: proactive eviction before TTS ramps from steady to peak.

        Rule 8 was originally unconditional for every TTS engine, added after real evidence
        overturned the original conditional-only design: two live full-pipeline runs on the
        same real Hindi answer measured peak pool at 7.79GB (batch=6) and 7.54GB (batch=3)
        with **Parler-TTS** -- batch size barely mattered because the answer's 3 chunks fit
        inside either cap, so both ran as one identical batched call. Parler's own real
        chunk-dependent need (~4.9-5.1GB observed, both runs) can exceed its 3.70GB estimate,
        so a projected-budget check built on that estimate was never trustworthy enough to
        decide *whether* to evict for Parler -- Agent is evicted unconditionally every time
        for that engine, the one mitigation that doesn't depend on chunk count or content
        length.

        **Revised for mms_tts (config.TTS_ENGINE)**: originally treated as "far less
        content-dependent" than Parler based on MMS_TTS_EVALUATION.md's isolated benchmarks,
        which is why this used to check the flat 3.7GB constant regardless of actual answer
        length. That assumption didn't survive a real long answer -- see
        _predict_tts_peak_bytes's docstring for the real crash this caused and the real two-
        point data (430/800 chars) showing genuine, non-trivial length scaling. Agent is only
        evicted if the *length-scaled* projected total (with Agent still resident) would
        exceed budget -- if there's room, Agent stays loaded straight through TTS and into
        the next turn (zero reload cost); if not, this falls back to evicting it, same as
        Parler always does.
        """
        if self._nmt_output_cached and self._is_loaded("nmt"):
            self._unload("nmt", reason="Rule 2: evict before TTS peak (output already cached)")
        if self._is_loaded("embedder") and not self._tool_needs_embedder:
            self._unload("embedder", reason="Rule 7: embedder is on-demand only, freeing before TTS peak")

        tts_engine = config.WORKERS["tts"]["engine"]
        tts_peak = (
            self._predict_tts_peak_bytes(text_char_count) if tts_engine == "mms_tts"
            else config.PREDICTED_LOAD_COST_BYTES["tts_peak_batch3"]
        )

        if self._is_loaded("agent"):
            if tts_engine != "mms_tts":
                # Original unconditional Rule 8 -- still the load-bearing fix for Parler,
                # not revisited here (that finding stands; see docstring above).
                self._unload(
                    "agent",
                    reason=f"Rule 8: unconditional ({tts_engine} engine) -- real TTS peak isn't "
                           "reliably predictable per-turn, freeing Agent's fixed 2.65GB is the "
                           "mitigation that doesn't depend on content",
                )
            else:
                snap = self.snapshot()
                tts_steady_now = (
                    self._component_bytes("tts", snap) if snap["components"]["tts"]["state"] == "loaded" else 0
                )
                projected_with_agent = snap["total_bytes"] - tts_steady_now + tts_peak
                if projected_with_agent > config.MODEL_BUDGET_BYTES:
                    self._log(
                        f"        Rule 8 (mms_tts, conditional): projected {projected_with_agent / 1e9:.2f}GB "
                        f"> {config.MODEL_BUDGET_BYTES / 1e9:.1f}GB budget with Agent resident -- evicting"
                    )
                    self._unload(
                        "agent",
                        reason="Rule 8 (mms_tts, conditional): projected TTS peak would exceed "
                               "budget with Agent resident",
                    )
                else:
                    self._log(
                        f"        Rule 8 (mms_tts, conditional): projected {projected_with_agent / 1e9:.2f}GB "
                        f"fits {config.MODEL_BUDGET_BYTES / 1e9:.1f}GB budget -- keeping Agent resident "
                        "(mms_tts's peak is small/predictable enough not to need the unconditional evict)"
                    )

        snap = self.snapshot()
        tts_steady_now = self._component_bytes("tts", snap) if snap["components"]["tts"]["state"] == "loaded" else 0
        projected = snap["total_bytes"] - tts_steady_now + tts_peak
        self._log(
            f"        TTS-peak check after Rule 2/7/8: projected-at-peak={projected / 1e9:.2f}GB "
            f"vs budget={config.MODEL_BUDGET_BYTES / 1e9:.1f}GB"
        )

    # ------------------------------------------------------------------
    # Pipeline-stage API -- what the demo script actually calls
    # ------------------------------------------------------------------

    def preload_asr(self, reason="Rule 10: golden-window preload after TTS eviction"):
        """Fires ASR's load in a background thread the moment TTS is freed at the end of a
        turn, instead of waiting cold for the next turn's run_asr() call -- overlaps ASR's
        real ~35-55s load time (dominated by CUDA/onnxruntime graph compilation on Jetson,
        not I/O -- confirmed real, see the direct-load timings this was measured from) with
        whatever gap exists before the next turn actually starts: on real hardware, the pause
        while waiting for the next spoken question; in --all test runs, the explicit
        inter-language buffer (see test_orchestrated_pipeline.py). Mirrors Rule 5's pattern
        for TTS (same `_load_async` + worker-status-polling mechanism, not Rule 9's
        thread+Event pattern -- that one exists only because Agent isn't a WORKER_COMPONENT
        with its own /status endpoint to poll). No-op if ASR is already loaded or preloading.

        Budget check uses whatever's resident right now -- typically just Agent, since TTS
        was just evicted and NMT/embedder are already evicted earlier in the turn by Rules
        2/7. Agent(0.8b, ~1.3GB) + ASR's own load peak (~4.2GB observed climbing during CUDA
        graph compile) comfortably fits the 7.0GB budget -- this is the same pairing Rule 9's
        preload_agent already treats as safe, just triggered from the other end of a turn.

        If the next turn turns out not to need ASR at all (e.g. English input, which skips
        ASR/NMT entirely), this preload goes unused -- Rule 1's complementary-pair eviction
        (asr/tts) cleans it up automatically the moment that turn's TTS stage loads. Costs one
        wasted load/evict cycle in that case, not a correctness or memory problem.
        """
        state = self._worker_status("asr").get("state")
        if state in ("loaded", "loading"):
            return
        snap = self.snapshot()
        predicted = config.PREDICTED_LOAD_COST_BYTES["asr"]
        if snap["available_bytes"] < predicted:
            self._log(f"        skipping asr preload -- only {snap['available_bytes'] / 1e9:.2f}GB available")
            return
        self._load_async("asr", reason=reason)

    def run_asr(self, language, infer_fn):
        self._log(f"--- stage: ASR ({language}) " + "-" * 40)
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
                self._load("asr", reason=f"transcribing {language} input (preload fallback)")
        elif asr_state != "loaded":
            self._load("asr", reason=f"transcribing {language} input")
        else:
            self._log("        ASR already fully loaded (golden-window preload paid off, zero wait)")
        self._snapshot_line("ready")
        t0 = time.perf_counter()
        result = infer_fn()
        self._log(f"        asr infer: {time.perf_counter() - t0:.2f}s")
        # Rule 6: ASR's output is fully consumed the instant transcription returns, and
        # NMT/Agent need the room next -- free it immediately rather than waiting.
        self._unload("asr", reason="Rule 6: output consumed, freeing before NMT/Agent")
        return result

    def run_nmt(self, direction_label, infer_fn, keep_loaded=False):
        self._log(f"--- stage: NMT ({direction_label}) " + "-" * 40)
        self._make_room_for("nmt")
        if not self._is_loaded("nmt"):
            self._load("nmt", reason=f"translating ({direction_label})")
        self._snapshot_line("ready")
        t0 = time.perf_counter()
        result = infer_fn()
        self._log(f"        nmt infer: {time.perf_counter() - t0:.2f}s")
        self._nmt_output_cached = True
        if not keep_loaded:
            self._unload("nmt", reason="output cached, not needed again this turn")
        return result

    def preload_agent(self, reason="Rule 9: preload during ASR/NMT downtime"):
        """Fires Agent's load in a background thread as early in the turn as possible --
        call this right when ASR starts (or immediately, for an English turn with no ASR at
        all) so Agent's real ~5-7.5s load time overlaps with ASR+NMT's own work instead of
        sitting serially in front of the Agent stage.

        Budget-safe unconditionally: Agent(2.65GB) + ASR(3.20GB) = 5.85GB, well under the
        7.0GB budget (load_balancer_plan.md section 4-C already lists this combination as
        safe) -- and no complementary-pair conflict either, since Rule 1 only concerns
        ASR/TTS, not Agent. No-op if Agent is already loaded or already preloading.
        """
        if self._is_loaded("agent") or "agent" in self._pending_preloads:
            return
        snap = self.snapshot()
        predicted = config.PREDICTED_LOAD_COST_BYTES["agent"]
        if snap["available_bytes"] < predicted:
            self._log(f"        skipping agent preload -- only {snap['available_bytes'] / 1e9:.2f}GB available")
            return

        self._log(f"LOAD    agent     <- {reason} (async, background thread)")
        t0 = time.perf_counter()
        event = threading.Event()

        def _bg():
            try:
                r = requests.post(f"{GATEWAY}/agent/load", json={"model": OLLAMA_COMPONENTS["agent"]}, timeout=120)
                r.raise_for_status()
                self._log(f"        agent preload finished in background, {time.perf_counter() - t0:.2f}s")
            except requests.exceptions.RequestException as exc:
                self._log(f"        WARNING: agent preload failed in background: {exc}")
            finally:
                event.set()

        threading.Thread(target=_bg, daemon=True).start()
        self._pending_preloads["agent"] = event

    def run_agent(self, infer_fn, preload_tts=True):
        self._log("--- stage: Agent " + "-" * 40)
        if "agent" in self._pending_preloads:
            event = self._pending_preloads.pop("agent")
            t0 = time.perf_counter()
            finished = event.wait(timeout=30)
            waited = time.perf_counter() - t0
            if not finished:
                self._log("        WARNING: agent preload still not done after 30s wait")
            elif waited > 0.05:
                self._log(f"        waited {waited:.2f}s for agent's Rule-9 preload (fired during ASR/NMT) to finish")
            else:
                self._log("        agent already fully loaded from Rule-9 preload -- zero additional wait")
        elif not self._is_loaded("agent"):
            self._load("agent", reason="agent turn starting")
        else:
            self._log("        agent already resident")
        if preload_tts and not self._is_loaded("tts"):
            snap = self.snapshot()
            tts_steady = config.PREDICTED_LOAD_COST_BYTES["tts_steady"]
            if snap["available_bytes"] >= tts_steady:
                self._load_async("tts", reason="Rule 5: golden-window preload during Agent turn")
            else:
                self._log(f"        skipping TTS preload -- only {snap['available_bytes'] / 1e9:.2f}GB available")
        self._snapshot_line("ready")
        t0 = time.perf_counter()
        result = infer_fn()
        self._log(f"        agent turn: {time.perf_counter() - t0:.2f}s")
        return result

    def run_tts(self, language, infer_fn, batch_size=None, text_char_count=None):
        batch_size = batch_size or config.WORKERS["tts"]["default_batch_size"]
        self._log(f"--- stage: TTS ({language}, batch_size={batch_size}) " + "-" * 40)
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

        self._snapshot_line("steady-state ready, starting synthesis (peak incoming)")

        peak_bytes = [0]
        stop_flag = threading.Event()

        def _poll_peak():
            while not stop_flag.is_set():
                peak_bytes[0] = max(peak_bytes[0], self.snapshot()["total_bytes"])
                time.sleep(0.15)

        poll_thread = threading.Thread(target=_poll_peak, daemon=True)
        poll_thread.start()
        t0 = time.perf_counter()
        try:
            result = infer_fn()
        finally:
            stop_flag.set()
            poll_thread.join(timeout=2)
        elapsed = time.perf_counter() - t0
        predicted_peak = config.PREDICTED_LOAD_COST_BYTES["tts_peak_batch3"]
        self._log(
            f"        tts infer: {elapsed:.2f}s, observed peak pool "
            f"~{peak_bytes[0] / 1e9:.2f}GB (predicted ~{predicted_peak / 1e9:.2f}GB for tts alone at batch={batch_size})"
        )
        self._unload("tts", reason="turn complete, freeing TTS")
        self.preload_asr()
        return result

    def teardown(self):
        """Unload everything still resident -- call at the very end of a session to
        demonstrate/confirm the pool genuinely returns to empty, not just between turns."""
        self._log("--- teardown: releasing everything still resident " + "-" * 20)
        for name in ALL_COMPONENTS:
            if self._is_loaded(name):
                self._unload(name, reason="session teardown")
        self._snapshot_line("after teardown")
