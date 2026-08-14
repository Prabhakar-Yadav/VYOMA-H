"""Generic FastAPI worker: wraps ONE engine object (anything with `.is_loaded`, `.load()`,
`.unload()`, and optionally `.vram_allocated_gb()` -- exactly the interface every engine in
dev/agents/models/*/model_loader.py already has) behind a load/unload/status/infer state
machine, meant to run as its own OS process. See API_DESIGN.md for why "own process" matters:
this is what makes `?full=true` unload (a gateway-triggered kill+respawn) a *guaranteed*
memory reclaim instead of a hopeful one.

Every concrete worker module (workers/asr_worker.py etc.) supplies:
  - `name`: used in logs/status only
  - `engine_factory`: a zero-arg callable that *constructs* (but does not load) the engine
  - `infer_fn`: `(engine, payload: dict) -> dict`, the actual ASR/NMT/TTS call
  - `stream_infer_fn` (optional): `(engine, payload: dict) -> Iterator[dict]`, for a worker
    that can produce results incrementally (currently just TTS -- see tts_worker.py's
    `_stream_infer`). Only registers `/infer_stream` if a worker actually passes this; ASR
    and NMT have nothing to stream (one request -> one short answer, no benefit to chunking
    it), so they don't get the extra route at all rather than a not-implemented stub.

This file has no ASR/NMT/TTS-specific knowledge at all.
"""
import gc
import json
import threading
import time
from enum import Enum
from typing import Callable, Optional

import psutil
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

try:
    import torch
except ImportError:
    torch = None

_process = psutil.Process()


class WorkerState(str, Enum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    UNLOADING = "unloading"
    ERROR = "error"


class StatusResponse(BaseModel):
    name: str
    state: WorkerState
    pid: int
    rss_bytes: int
    vram_bytes: float = 0.0
    system_mem_delta_bytes: Optional[float] = None
    loaded_at: Optional[float] = None
    last_used_at: Optional[float] = None
    load_time_sec: Optional[float] = None
    error: Optional[str] = None


def make_worker_app(name: str, engine_factory: Callable, infer_fn: Callable,
                     stream_infer_fn: Optional[Callable] = None) -> FastAPI:
    app = FastAPI(title=f"{name}-worker")

    state = {
        "engine": None,
        "status": WorkerState.UNLOADED,
        "loaded_at": None,
        "last_used_at": None,
        "load_time_sec": None,
        "system_mem_delta_bytes": None,
        "error": None,
    }
    lock = threading.Lock()

    def _rss_bytes() -> int:
        return _process.memory_info().rss

    def _vram_bytes() -> float:
        engine = state["engine"]
        if engine is not None and hasattr(engine, "vram_allocated_gb"):
            gb = engine.vram_allocated_gb()
            if gb is not None:
                return gb * 1e9
        if torch is not None and torch.cuda.is_available():
            return float(torch.cuda.memory_allocated())
        return 0.0

    def _system_used_bytes() -> int:
        """Real, ground-truth system-wide memory in use (`psutil.virtual_memory().used`,
        the same figure `free`'s "used" column reports) -- NOT this process's own RSS.

        Why: on Jetson's unified CPU/GPU memory, CUDA/onnxruntime allocations are managed by
        NVIDIA's own driver-level pool (Tegra's unified-memory allocator), not through this
        process's normal page tables -- confirmed directly (TIMING_RESULTS_CROSS_DEVICE.md
        Sec. 6): `_rss_bytes()`/`torch.cuda.memory_allocated()` reported ASR's peak footprint
        as 0.777-0.844GB in GPU mode, while the real system-wide `free -m` delta for the same
        load+transcribe was 4.42GB -- over 5x higher. Neither `psutil`'s per-process RSS nor
        `torch.cuda.memory_allocated()` (which only tracks memory PyTorch's own allocator
        manages, missing onnxruntime's separate CUDA arena entirely) can see that driver-owned
        memory from inside the process; only a system-wide before/after comparison can.

        Caveat, documented rather than solved here: this only isolates one worker's own
        footprint cleanly when nothing else is loading *concurrently* in the same window. The
        orchestrator's own Rule 5/Rule 9 (golden-window async preloads -- e.g. Agent loading
        in a background thread while ASR loads synchronously, see
        TIMING_RESULTS_CROSS_DEVICE.md Sec. 7) means two components' memory can grow at the
        same real time; a delta measured here during that overlap will include some of the
        *other* component's growth too, not just this worker's. Still strictly more accurate
        than the old rss+vram sum (which undercounted even in the uncontended case), but not a
        perfect per-component attribution during genuine concurrency -- flagged as follow-up,
        not fixed here."""
        return psutil.virtual_memory().used

    def _do_load(language=None):
        state["status"] = WorkerState.LOADING
        t0 = time.perf_counter()
        sys_before = _system_used_bytes()
        try:
            engine = engine_factory()
            # `language=` (2026-08-11): both MultiLangMmsTtsEngine.load() and
            # QuantizedMultiLangASR.load() now accept an optional `language=` to eagerly warm
            # exactly one session instead of the lazy-by-default no-op -- same underlying fix
            # for the same mistake in both places (a "load nothing eagerly" change that forgot
            # preloading still needs a way to ask for one specific thing). NMT's own load()
            # still takes no arguments (it's one combined load of all 3 translation-direction
            # models, not per-language) and ignores this entirely -- `**kwargs`-style optional
            # forwarding, not a signature every worker has to support.
            if language is not None:
                engine.load(language=language)
            else:
                engine.load()
            state["engine"] = engine
            state["status"] = WorkerState.LOADED
            state["loaded_at"] = time.time()
            state["load_time_sec"] = time.perf_counter() - t0
            state["system_mem_delta_bytes"] = max(_system_used_bytes() - sys_before, 0)
            state["error"] = None
        except Exception as exc:
            state["status"] = WorkerState.ERROR
            state["error"] = str(exc)
            raise

    def _do_unload():
        engine = state["engine"]
        try:
            if engine is not None:
                engine.unload()
        finally:
            state["engine"] = None
            gc.collect()
            if torch is not None and torch.cuda.is_available():
                torch.cuda.empty_cache()
            state["status"] = WorkerState.UNLOADED
            state["loaded_at"] = None
            state["load_time_sec"] = None
            state["system_mem_delta_bytes"] = None
            state["error"] = None

    @app.get("/health")
    def health():
        return {"ok": True, "name": name, "pid": _process.pid}

    @app.get("/status", response_model=StatusResponse)
    def status():
        return StatusResponse(
            name=name,
            state=state["status"],
            pid=_process.pid,
            rss_bytes=_rss_bytes(),
            vram_bytes=_vram_bytes(),
            system_mem_delta_bytes=state["system_mem_delta_bytes"],
            loaded_at=state["loaded_at"],
            last_used_at=state["last_used_at"],
            load_time_sec=state["load_time_sec"],
            error=state["error"],
        )

    @app.post("/load")
    def load(mode: str = "sync", language: str | None = None):
        with lock:
            if state["status"] in (WorkerState.LOADED, WorkerState.LOADING):
                return {"state": state["status"]}
            if mode == "async":
                threading.Thread(target=_do_load, args=(language,), daemon=True).start()
                return {"state": WorkerState.LOADING}
            try:
                _do_load(language)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))
            return {"state": state["status"], "load_time_sec": state["load_time_sec"]}

    @app.post("/unload")
    def unload(full: bool = False):
        # `full=true` is a no-op *at this layer* -- it's a signal the gateway reads to decide
        # whether to kill+respawn this whole process after this call returns (see
        # API_DESIGN.md: only process exit guarantees RSS/VRAM actually return to the OS).
        # This endpoint always performs the best-effort soft unload either way, and reports
        # the honest before/after byte counts rather than assuming they hit zero.
        before_rss = _rss_bytes()
        before_sys = _system_used_bytes()
        with lock:
            state["status"] = WorkerState.UNLOADING
            _do_unload()
        after_rss = _rss_bytes()
        after_sys = _system_used_bytes()
        return {
            "state": state["status"],
            "rss_before_bytes": before_rss,
            "rss_after_bytes": after_rss,
            "rss_freed_bytes": before_rss - after_rss,
            # Real system-wide freed amount -- see _system_used_bytes()'s docstring for why
            # this, not rss_freed_bytes above, is the trustworthy number on Jetson.
            "system_mem_freed_bytes": before_sys - after_sys,
            "full_unload_requested": full,
        }

    @app.post("/infer")
    def infer(payload: dict, auto_load: bool = False):
        if state["status"] != WorkerState.LOADED:
            if auto_load and state["status"] == WorkerState.UNLOADED:
                with lock:
                    try:
                        _do_load()
                    except Exception as exc:
                        raise HTTPException(status_code=500, detail=str(exc))
            else:
                raise HTTPException(
                    status_code=409,
                    detail=f"{name} is not loaded (state={state['status']}) -- call /load first",
                )
        state["last_used_at"] = time.time()
        try:
            return infer_fn(state["engine"], payload)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    if stream_infer_fn is not None:
        @app.post("/infer_stream")
        def infer_stream(payload: dict):
            if state["status"] != WorkerState.LOADED:
                raise HTTPException(
                    status_code=409,
                    detail=f"{name} is not loaded (state={state['status']}) -- call /load first",
                )
            state["last_used_at"] = time.time()
            engine = state["engine"]

            def _ndjson():
                # A StreamingResponse's headers (200 OK) are sent the moment the FIRST byte
                # of the body is written -- so a failure partway through generation can no
                # longer become an HTTPException/non-200 status the way /infer's failures
                # can; the client has already committed to reading a 200 stream. The only
                # way to signal it is in-band: one final NDJSON line carrying {"error": ...}
                # instead of a real chunk. streaming.py's play_http_stream() checks for this
                # key explicitly and raises on it -- never silently treats it as audio.
                try:
                    for item in stream_infer_fn(engine, payload):
                        yield json.dumps(item) + "\n"
                except Exception as exc:
                    yield json.dumps({"error": str(exc)}) + "\n"

            return StreamingResponse(_ndjson(), media_type="application/x-ndjson")

    return app
