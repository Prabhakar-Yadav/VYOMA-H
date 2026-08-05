"""Gateway: one address (:11400) for pipeline apps, hardware/UI, and the orchestrator to talk
to. Proxies `/​<name>/...` calls to ASR/NMT/TTS worker subprocesses and aggregates
`/system/memory` and `/system/status` from each component's own live self-report. `/agent/...`
talks straight to Ollama's own REST API instead of a new worker, since Ollama already is one
-- see API_DESIGN.md.

**Workers are spawned lazily, not at gateway startup.** Confirmed directly (see
load_balancer_plan.md's update log): keeping all three worker processes running as an
always-on standing pool costs a permanent, hidden tax -- each one holds real baseline RSS
even fully "unloaded" (Python + FastAPI/uvicorn + heavy imports: ~0.54GB/0.66GB/0.86GB for
ASR/NMT/TTS, ~2.06GB combined), which a live orchestrator run caught blowing a supposedly-safe
"Agent+ASR" combination (5.85GB assumed, 7.38GB real) straight over the 7.0GB Jetson budget.
Lazy spawn makes "unloaded" mean what it should: zero cost, no process even running. The
trade-off: a cold `/load` on a never-spawned (or previously-killed) worker now pays real
process-spawn + heavy-import time on top of the model's own load time -- there is no longer a
distinct "soft unload, fast reload" path for workers; every unload is a full process kill (the
`?full=` query param is kept for API compatibility but no longer changes behavior -- there's
nothing left for it to distinguish once idle processes aren't kept around at all).

Run: `python run_all.py` from this directory (or `uvicorn api_server.gateway:app --port 11400`
from dev/agents/, which is what run_all.py does under the hood).
"""
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from api_server import config

_procs: dict[str, subprocess.Popen] = {}
# Names currently being spawned in a background thread (see the "load" branch below) --
# checked by /status so a poll during the spawn window reports "loading" instead of either
# a misleading "unloaded" (it's not, a spawn is in flight) or "unreachable" (an HTTP attempt
# against a port nothing is listening on yet). This is what lets the orchestrator's
# _await_async_load() correctly keep waiting through the whole spawn+load window, not just
# the load half of it.
_spawning: set[str] = set()


def _is_spawned(name: str) -> bool:
    proc = _procs.get(name)
    return proc is not None and proc.poll() is None


def _unspawned_status(name: str) -> dict:
    """Synthetic /status shape for a worker with no process running at all -- genuinely zero
    cost, not a guess or an unreachable-error placeholder."""
    return {
        "name": name, "state": "unloaded", "pid": None,
        "rss_bytes": 0, "vram_bytes": 0.0,
        "loaded_at": None, "last_used_at": None, "load_time_sec": None, "error": None,
    }


def _spawning_status(name: str) -> dict:
    """Synthetic /status shape while a background async load's spawn step is still in
    flight -- see _spawning above."""
    return {
        "name": name, "state": "loading", "pid": None,
        "rss_bytes": 0, "vram_bytes": 0.0,
        "loaded_at": None, "last_used_at": None, "load_time_sec": None, "error": None,
    }


def _spawn(name: str) -> subprocess.Popen:
    cfg = config.WORKERS[name]
    cmd = [
        sys.executable, "-m", "uvicorn", f"api_server.{cfg['module']}:app",
        "--host", "127.0.0.1", "--port", str(cfg["port"]), "--log-level", "warning",
    ]
    return subprocess.Popen(cmd, cwd=config.AGENTS_DIR)


def _wait_healthy(name: str, timeout: float = 30.0) -> bool:
    port = config.WORKERS[name]["port"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        proc = _procs.get(name)
        if proc is not None and proc.poll() is not None:
            return False  # process already died -- no point polling further
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
            if r.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    return False


def ensure_spawned(name: str):
    """Spawns `name`'s worker process if it isn't already running, and waits for it to
    become healthy. This is the only place a worker process gets created -- called from
    the `/load` path, never from `/status` (a status check must never itself cause a spawn)."""
    if _is_spawned(name):
        return
    _procs[name] = _spawn(name)
    if not _wait_healthy(name):
        raise RuntimeError(f"worker '{name}' did not become healthy within timeout")


def kill_worker(name: str, timeout: float = 5.0):
    """The only unload primitive now -- no respawn. Process gone entirely; next /load call
    spawns a fresh one via ensure_spawned()."""
    proc = _procs.pop(name, None)
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No eager spawning -- see module docstring. Every worker starts genuinely unloaded,
    # zero processes running, zero baseline cost.
    yield
    for name in list(_procs):
        kill_worker(name)


app = FastAPI(title="pocketinfer model-serving gateway", lifespan=lifespan)


@app.get("/health")
async def gateway_health():
    return {"ok": True, "workers": {n: _is_spawned(n) for n in config.WORKERS}}


# ---- Agent (Ollama) -- proxies straight to Ollama's own REST API, no new worker process ----

async def _agent_status_dict() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{config.OLLAMA_HOST}/api/ps")
            resp.raise_for_status()
            models = resp.json().get("models", [])
        except httpx.HTTPError as exc:
            return {"state": "unknown", "error": str(exc), "vram_bytes": 0.0, "models": []}
    configured = {config.normalize_ollama_tag(m) for m in config.OLLAMA_MODELS}
    resident = [m for m in models if config.normalize_ollama_tag(m.get("model", "")) in configured]
    total_vram = sum(m.get("size_vram", 0) for m in resident)
    return {
        "state": "loaded" if resident else "unloaded",
        "vram_bytes": float(total_vram),
        # context_length as Ollama actually applied it -- lets a caller confirm num_ctx took
        # effect rather than silently falling back to the model's own default (see
        # config.OLLAMA_NUM_CTX).
        "num_ctx": {m["model"]: m.get("context_length") for m in resident},
        "models": resident,
    }


@app.get("/agent/status")
async def agent_status():
    return await _agent_status_dict()


@app.post("/agent/load")
async def agent_load(payload: dict = None):
    # num_ctx defaults to config.OLLAMA_NUM_CTX but can be overridden per call -- same
    # runtime-adjustable pattern as any other config var (see config.py's comment on this).
    # Omitting it entirely is the one thing never allowed here: that silently falls back to
    # Ollama's own per-model default context_length, confirmed to cost 4-5x the VRAM for
    # zero benefit (see config.OLLAMA_NUM_CTX's docstring).
    payload = payload or {}
    model = payload.get("model", config.OLLAMA_MODELS[0])
    num_ctx = payload.get("num_ctx", config.OLLAMA_NUM_CTX)
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{config.OLLAMA_HOST}/api/generate",
            json={"model": model, "keep_alive": -1, "options": {"num_ctx": num_ctx}},
        )
    return {
        "state": "loaded" if resp.status_code == 200 else "error",
        "status_code": resp.status_code,
        "model": model,
        "num_ctx": num_ctx,
    }


@app.post("/agent/unload")
async def agent_unload(payload: dict = None):
    payload = payload or {}
    model = payload.get("model", config.OLLAMA_MODELS[0])
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{config.OLLAMA_HOST}/api/generate", json={"model": model, "keep_alive": 0})
    return {"state": "unloaded" if resp.status_code == 200 else "error", "status_code": resp.status_code, "model": model}


# ---- System-wide views, built from each component's own live self-report ----

async def _gather_worker_status() -> dict:
    """Never spawns a worker just to check on it -- an unspawned worker's status is the
    synthetic zero-cost dict, not a network call."""
    results = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        for name, cfg in config.WORKERS.items():
            if name in _spawning:
                results[name] = _spawning_status(name)
                continue
            if not _is_spawned(name):
                results[name] = _unspawned_status(name)
                continue
            try:
                resp = await client.get(f"http://127.0.0.1:{cfg['port']}/status")
                resp.raise_for_status()
                results[name] = resp.json()
            except httpx.HTTPError as exc:
                results[name] = {"state": "unreachable", "error": str(exc), "rss_bytes": 0, "vram_bytes": 0.0}
    return results


@app.get("/system/status")
async def system_status():
    workers = await _gather_worker_status()
    agent = await _agent_status_dict()
    return {"components": {**workers, "agent": agent}}


@app.get("/system/memory")
async def system_memory():
    workers = await _gather_worker_status()
    agent = await _agent_status_dict()

    total_rss = sum(w.get("rss_bytes", 0) or 0 for w in workers.values())
    total_vram = sum(w.get("vram_bytes", 0) or 0 for w in workers.values())
    total_vram += agent.get("vram_bytes", 0) or 0
    total = total_rss + total_vram

    return {
        "budget_max_bytes": config.MODEL_BUDGET_BYTES,
        "total_rss_bytes": total_rss,
        "total_vram_bytes": total_vram,
        "total_bytes": total,
        "available_bytes": config.MODEL_BUDGET_BYTES - total,
        "utilization_pct": round(100 * total / config.MODEL_BUDGET_BYTES, 1),
        "components": {**workers, "agent": agent},
    }


@app.post("/system/workers/{name}/restart")
async def workers_restart(name: str):
    if name not in config.WORKERS:
        raise HTTPException(status_code=404, detail=f"unknown worker '{name}'")
    kill_worker(name)
    ensure_spawned(name)
    return {"worker": name, "restarted": True}


# ---- Generic proxy: /{worker}/load, /unload, /status, /infer, /health ----
# Registered last so the specific routes above always win the match first.

@app.api_route("/{worker_name}/{sub_path:path}", methods=["GET", "POST"])
async def proxy(worker_name: str, sub_path: str, request: Request):
    if worker_name not in config.WORKERS:
        raise HTTPException(status_code=404, detail=f"unknown worker '{worker_name}'")

    # /status and /health never trigger a spawn -- checking on a worker must not itself cost
    # anything. An unspawned worker's status is the synthetic zero-cost dict; one whose
    # background async load is still spawning reports "loading", not "unloaded"/"unreachable".
    if sub_path == "status":
        if worker_name in _spawning:
            return _spawning_status(worker_name)
        if not _is_spawned(worker_name):
            return _unspawned_status(worker_name)
        return (await _gather_worker_status())[worker_name]

    if sub_path == "health":
        if not _is_spawned(worker_name):
            return {"ok": False, "spawned": False, "name": worker_name}
        port = config.WORKERS[worker_name]["port"]
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://127.0.0.1:{port}/health")
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

    if sub_path == "load":
        mode = request.query_params.get("mode", "sync")
        if mode == "async" and not _is_spawned(worker_name):
            # True fire-and-forget: with a standing pool, "async" only had to cover the
            # model's own load time. With lazy spawn, the process-spawn step itself can now
            # take longer than the model load (see TIMING_RESULTS.md) -- ensure_spawned() is
            # blocking, so it has to move into the background thread too, or Rule 5/Rule 9's
            # whole point (the caller never blocks) breaks silently the first time a preload
            # targets a cold/never-spawned worker.
            def _bg():
                _spawning.add(worker_name)
                try:
                    ensure_spawned(worker_name)
                    httpx.post(
                        f"http://127.0.0.1:{config.WORKERS[worker_name]['port']}/load",
                        params={"mode": "async"}, timeout=180.0,
                    )
                except Exception:
                    pass  # surfaced via /status's state staying "loading"/error on next check
                finally:
                    _spawning.discard(worker_name)

            threading.Thread(target=_bg, daemon=True).start()
            return {"state": "loading"}

        ensure_spawned(worker_name)  # spawns fresh if this is a cold load -- see module docstring
        port = config.WORKERS[worker_name]["port"]
        body = await request.body()
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"http://127.0.0.1:{port}/load", params=request.query_params, content=body,
                headers={"content-type": request.headers.get("content-type", "application/json")},
            )
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

    if sub_path == "unload":
        # Every unload is a full process kill now -- see module docstring for why the
        # soft/full distinction from the standing-pool design no longer applies. `full=` is
        # still accepted so existing callers (orchestrator.py) don't need to change, but it
        # no longer selects between two different behaviors.
        before = _unspawned_status(worker_name) if not _is_spawned(worker_name) else (await _gather_worker_status())[worker_name]
        kill_worker(worker_name)
        return {
            "state": "unloaded",
            "full_unload": True,
            "rss_before_bytes": before.get("rss_bytes"),
            "rss_after_bytes": 0,
        }

    # Everything else (currently /infer and /infer_stream): never spawn on demand -- matches
    # the existing contract that a caller must /load explicitly first (see worker_base.py's
    # own 409).
    if not _is_spawned(worker_name):
        raise HTTPException(
            status_code=409,
            detail=f"{worker_name} is not loaded (no process running) -- call /load first",
        )

    port = config.WORKERS[worker_name]["port"]
    url = f"http://127.0.0.1:{port}/{sub_path}"
    body = await request.body()

    if sub_path == "infer_stream":
        # A REAL streaming passthrough, not the buffered `resp.content` pattern below --
        # that pattern would silently defeat the entire point of /infer_stream even if the
        # worker itself streams correctly: `httpx.AsyncClient.request()` (used everywhere
        # else in this proxy) waits for the complete response body before returning, and
        # wrapping that in a plain `Response(content=resp.content, ...)` sends it to the
        # real caller as one blob regardless of how progressively the worker produced it.
        # Confirmed directly this was the original bug here -- caught before it shipped, not
        # after. `client.stream()` + `resp.aiter_bytes()` + `StreamingResponse` is the actual
        # fix: bytes are forwarded to the real caller as they arrive from the worker, not
        # once the worker's own response is fully done.
        async def _passthrough():
            async with httpx.AsyncClient(timeout=300.0) as client:
                try:
                    async with client.stream(
                        "POST", url, content=body,
                        headers={"content-type": request.headers.get("content-type", "application/json")},
                    ) as resp:
                        async for chunk in resp.aiter_bytes():
                            yield chunk
                except httpx.HTTPError as exc:
                    # Same in-band-error constraint as worker_base.py's own /infer_stream --
                    # once streaming has started, a real HTTP error status can no longer be
                    # sent, only an in-band sentinel line the client already knows to check for.
                    yield (json.dumps({"error": f"worker '{worker_name}' unreachable: {exc}"}) + "\n").encode()

        return StreamingResponse(_passthrough(), media_type="application/x-ndjson")

    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.request(
                request.method, url, params=request.query_params, content=body,
                headers={"content-type": request.headers.get("content-type", "application/json")},
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"worker '{worker_name}' unreachable: {exc}")
    return Response(content=resp.content, status_code=resp.status_code,
                     media_type=resp.headers.get("content-type"))
