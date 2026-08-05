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

    def _do_load():
        state["status"] = WorkerState.LOADING
        t0 = time.perf_counter()
        try:
            engine = engine_factory()
            engine.load()
            state["engine"] = engine
            state["status"] = WorkerState.LOADED
            state["loaded_at"] = time.time()
            state["load_time_sec"] = time.perf_counter() - t0
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
            loaded_at=state["loaded_at"],
            last_used_at=state["last_used_at"],
            load_time_sec=state["load_time_sec"],
            error=state["error"],
        )

    @app.post("/load")
    def load(mode: str = "sync"):
        with lock:
            if state["status"] in (WorkerState.LOADED, WorkerState.LOADING):
                return {"state": state["status"]}
            if mode == "async":
                threading.Thread(target=_do_load, daemon=True).start()
                return {"state": WorkerState.LOADING}
            try:
                _do_load()
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
        with lock:
            state["status"] = WorkerState.UNLOADING
            _do_unload()
        after_rss = _rss_bytes()
        return {
            "state": state["status"],
            "rss_before_bytes": before_rss,
            "rss_after_bytes": after_rss,
            "rss_freed_bytes": before_rss - after_rss,
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
