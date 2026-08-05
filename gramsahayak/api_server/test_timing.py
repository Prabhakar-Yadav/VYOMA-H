#!/usr/bin/env python3
"""Measures cold load time and full-unload time for every pipeline component -- ASR, NMT,
TTS (via the gateway's own subprocess kill+respawn) -- and the Ollama-served models
(qwen3.5:2b as the agent, nomic-embed-text as the embedder, plus qwen3.5:0.8b as a
smaller-model comparison point) -- and writes the results to TIMING_RESULTS.md +
timing_results.json.

These numbers calibrate the orchestrator's preload-window math -- load_balancer_plan.md's
"golden window" rules depend on knowing things like "does TTS's load time fit inside NMT's
translation time." Measured on this dev machine (NVIDIA GB10, ~130GB unified CPU/GPU memory,
no Jetson-style 8GB ceiling) -- real numbers from the real checkpoints and the real Ollama
server, but not Jetson Orin numbers. Re-run this same script on-device before trusting these
for the orchestrator's timing assumptions.

Run from dev/agents/: `python -m api_server.test_timing [--repeats N]`
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests

AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AGENTS_DIR)

from api_server import config  # noqa: E402

GATEWAY = f"http://{config.GATEWAY_HOST}:{config.GATEWAY_PORT}"
OLLAMA = config.OLLAMA_HOST


def gb(n):
    return round((n or 0) / 1e9, 3)


def stats(values):
    return {
        "n": len(values),
        "mean": round(statistics.mean(values), 3) if values else None,
        "min": round(min(values), 3) if values else None,
        "max": round(max(values), 3) if values else None,
        "values": [round(v, 3) for v in values],
    }


# ---------------------------------------------------------------------------
# Gateway-managed workers (ASR / NMT / TTS)
# ---------------------------------------------------------------------------

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


def worker_status(name):
    return requests.get(f"{GATEWAY}/{name}/status", timeout=10).json()


def worker_full_unload(name):
    """Kill + respawn, timed client-side -- the wall-clock an orchestrator actually pays for
    a guaranteed-clean unload: process kill, respawn, interpreter+import startup, and the
    gateway's own health-check poll before it responds."""
    t0 = time.perf_counter()
    r = requests.post(f"{GATEWAY}/{name}/unload", params={"full": "true"}, timeout=60)
    elapsed = time.perf_counter() - t0
    r.raise_for_status()
    return elapsed, r.json()


def worker_soft_unload(name):
    t0 = time.perf_counter()
    r = requests.post(f"{GATEWAY}/{name}/unload", params={"full": "false"}, timeout=60)
    elapsed = time.perf_counter() - t0
    r.raise_for_status()
    return elapsed, r.json()


def worker_load(name):
    """Sync load. `load_time_sec` (server-reported) isolates engine.load() itself from
    HTTP/proxy overhead; `wall` is what a caller actually waits end to end."""
    t0 = time.perf_counter()
    r = requests.post(f"{GATEWAY}/{name}/load", timeout=120)
    wall = time.perf_counter() - t0
    r.raise_for_status()
    body = r.json()
    return body.get("load_time_sec"), wall, body


def time_worker(name, repeats):
    load_times, load_walls, soft_unload_times, full_unload_times = [], [], [], []
    peak_rss, peak_vram = 0, 0.0

    worker_full_unload(name)  # normalize to a known-clean starting state

    for _ in range(repeats):
        load_time_sec, load_wall, _ = worker_load(name)
        load_times.append(load_time_sec)
        load_walls.append(load_wall)

        st = worker_status(name)
        peak_rss = max(peak_rss, st.get("rss_bytes", 0) or 0)
        peak_vram = max(peak_vram, st.get("vram_bytes", 0) or 0)

        soft_elapsed, _ = worker_soft_unload(name)
        soft_unload_times.append(soft_elapsed)

        # Soft-unload leaves the process UNLOADED but alive with some RSS never returned
        # (see API_DESIGN.md). Reload once more so the full-unload measurement below starts
        # from a genuinely LOADED state -- matching what the orchestrator actually does
        # (evict something in active use, not something already idle).
        worker_load(name)
        full_elapsed, _ = worker_full_unload(name)
        full_unload_times.append(full_elapsed)

    return {
        "load_time_sec_serverside": stats(load_times),
        "load_time_sec_wallclock": stats(load_walls),
        "soft_unload_time_sec_wallclock": stats(soft_unload_times),
        "full_unload_time_sec_wallclock": stats(full_unload_times),
        "peak_rss_gb": gb(peak_rss),
        "peak_vram_gb": gb(peak_vram),
    }


# ---------------------------------------------------------------------------
# Ollama-served models -- separate server, separate load/unload primitive (keep_alive)
# ---------------------------------------------------------------------------

def ollama_ps():
    """Keyed by normalized tag -- Ollama reports an untagged request back as '<name>:latest'
    in every /api/ps entry (confirmed directly), so callers that look up by the short name
    they requested with (e.g. "nomic-embed-text") would otherwise never find themselves
    resident. See config.normalize_ollama_tag."""
    try:
        r = requests.get(f"{OLLAMA}/api/ps", timeout=5)
        r.raise_for_status()
        return {config.normalize_ollama_tag(m["name"]): m for m in r.json().get("models", [])}
    except requests.exceptions.RequestException:
        return {}


def ollama_is_resident(model):
    return config.normalize_ollama_tag(model) in ollama_ps()


def ollama_load(model, endpoint, num_ctx=None):
    """Both /api/generate (no prompt) and /api/embed (empty input) block until the model is
    actually resident -- confirmed directly: `ollama ps` shows it loaded immediately after
    the HTTP call returns, unlike unload (see ollama_unload below).

    `num_ctx` must be passed explicitly on every call: confirmed directly that omitting it
    makes Ollama fall back to the *model's own* default context_length (262144 for
    qwen3.5:0.8b), which pre-allocates a KV-cache-sized VRAM footprint of 5.475GB at idle --
    versus 1.213GB at num_ctx=8192 (this pipeline's actual agent config, see
    dev/agents/vyoma_v5.ipynb) for the exact same model with zero tokens generated. See
    config.OLLAMA_NUM_CTX."""
    t0 = time.perf_counter()
    payload = {"model": model, "keep_alive": -1}
    if num_ctx is not None:
        payload["options"] = {"num_ctx": num_ctx}
    if endpoint == "embed":
        payload["input"] = ""
        r = requests.post(f"{OLLAMA}/api/embed", json=payload, timeout=120)
    else:
        r = requests.post(f"{OLLAMA}/api/generate", json=payload, timeout=120)
    elapsed = time.perf_counter() - t0
    r.raise_for_status()
    return elapsed


def ollama_unload(model, endpoint, poll_timeout=30.0):
    """The unload HTTP call itself returns almost immediately (`done_reason: "unload"`), but
    `ollama ps` keeps showing the model as `Stopping...` for a further stretch before it
    actually disappears -- confirmed directly (~1-1.5s for a 5.5GB model in this test). The
    number that matters for the orchestrator's budget math is when the memory is actually
    gone, not when the HTTP call returned, so this polls /api/ps to the real end."""
    t0 = time.perf_counter()
    if endpoint == "embed":
        requests.post(f"{OLLAMA}/api/embed", json={"model": model, "input": "", "keep_alive": 0}, timeout=30)
    else:
        requests.post(f"{OLLAMA}/api/generate", json={"model": model, "keep_alive": 0}, timeout=30)
    deadline = time.time() + poll_timeout
    while time.time() < deadline and ollama_is_resident(model):
        time.sleep(0.1)
    return time.perf_counter() - t0


def time_ollama_model(model, endpoint, repeats, num_ctx):
    load_times, unload_times = [], []
    size_bytes = None

    if ollama_is_resident(model):
        ollama_unload(model, endpoint)

    for _ in range(repeats):
        load_times.append(ollama_load(model, endpoint, num_ctx=num_ctx))
        info = ollama_ps().get(config.normalize_ollama_tag(model), {})
        size_bytes = info.get("size_vram") or info.get("size") or size_bytes
        unload_times.append(ollama_unload(model, endpoint))

    return {
        "load_time_sec": stats(load_times),
        "unload_time_sec": stats(unload_times),
        "size_gb": gb(size_bytes),
        "num_ctx": num_ctx,
    }


def measure_context_window_blowup(model):
    """One-off comparison, not part of the repeated-timing loop: what does *not* passing
    num_ctx actually cost, in real VRAM, versus this pipeline's configured value? Confirmed
    directly during development (see config.OLLAMA_NUM_CTX's comment) -- captured here so
    it's in the generated report, not just a one-time terminal observation."""
    if ollama_is_resident(model):
        ollama_unload(model, "generate")

    tag = config.normalize_ollama_tag(model)
    ollama_load(model, "generate")  # no options -- Ollama's own default context_length
    default_info = ollama_ps().get(tag, {})
    default_vram = default_info.get("size_vram", 0)
    default_ctx = default_info.get("context_length")
    ollama_unload(model, "generate")

    ollama_load(model, "generate", num_ctx=config.OLLAMA_NUM_CTX)
    configured_info = ollama_ps().get(tag, {})
    configured_vram = configured_info.get("size_vram", 0)
    ollama_unload(model, "generate")

    return {
        "model": model,
        "default_context_length": default_ctx,
        "default_vram_gb": gb(default_vram),
        "configured_num_ctx": config.OLLAMA_NUM_CTX,
        "configured_vram_gb": gb(configured_vram),
        "multiplier": round(default_vram / configured_vram, 1) if configured_vram else None,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def render_markdown(results, repeats):
    lines = [
        "# Component Load/Unload Timing Results",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Repeats per component: {repeats}",
        "",
        "Measured on this dev machine (NVIDIA GB10, ~130GB unified CPU/GPU memory, no "
        "Jetson-style 8GB ceiling) -- real numbers from the real checkpoints and the real "
        "Ollama server, but **not** Jetson Orin numbers. Re-run this same script on-device "
        "before trusting these for the orchestrator's preload-window math "
        "(`load_balancer_plan.md`'s \"golden window\" rules).",
        "",
    ]

    blowup = results.get("context_window_blowup")
    if blowup:
        lines += [
            "## ⚠️ Context window controls VRAM more than model size does",
            "",
            f"`{blowup['model']}` at its own Ollama default context "
            f"(`num_ctx={blowup['default_context_length']}`) allocates "
            f"**{blowup['default_vram_gb']}GB** of VRAM at idle, zero tokens generated -- "
            f"purely pre-allocated KV cache. At this pipeline's configured context "
            f"(`num_ctx={blowup['configured_num_ctx']}`, `config.OLLAMA_NUM_CTX`), the same "
            f"model loads at **{blowup['configured_vram_gb']}GB** -- a "
            f"**{blowup['multiplier']}x** difference for identical weights.",
            "",
            "This means every Ollama load call in the orchestrator/API **must** pass "
            "`options: {\"num_ctx\": ...}` explicitly -- never rely on Ollama's per-model "
            "default. Omitting it on a real device is enough on its own to blow the entire "
            "8GB budget before ASR, NMT, or TTS even get a chance to load.",
            "",
        ]

    lines += [
        "## ASR / NMT / TTS (gateway-managed worker processes -- lazy spawn)",
        "",
        "Workers are no longer a standing pool (see `gateway.py`'s module docstring) -- "
        "\"unloaded\" now means zero processes running, zero cost, but every cold `/load` "
        "pays real process-spawn + heavy-import time on top of the model's own load() call. "
        "`spawn overhead` below is exactly that gap (`wall-clock − server-reported`), broken "
        "out explicitly rather than left hidden inside the wall-clock number.",
        "",
        "| Component | Load, server-reported (s) | Load, wall-clock (s) | Spawn overhead (s) "
        "| Unload -- process-kill, no respawn (s) | Peak RSS | Peak VRAM |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in ("asr", "nmt", "tts"):
        r = results["workers"][name]
        ls, lw = r["load_time_sec_serverside"], r["load_time_sec_wallclock"]
        fu = r["full_unload_time_sec_wallclock"]
        spawn_overhead = round(lw["mean"] - ls["mean"], 3)
        lines.append(
            f"| {name.upper()} | {ls['mean']} (min {ls['min']}, max {ls['max']}) "
            f"| {lw['mean']} | {spawn_overhead} "
            f"| {fu['mean']} (min {fu['min']}, max {fu['max']}) "
            f"| {r['peak_rss_gb']}GB | {r['peak_vram_gb']}GB |"
        )
    lines += ["", "Raw samples per component:", ""]
    for name in ("asr", "nmt", "tts"):
        r = results["workers"][name]
        lines.append(
            f"- **{name.upper()}** load(server)={r['load_time_sec_serverside']['values']}s, "
            f"load(wall-clock)={r['load_time_sec_wallclock']['values']}s, "
            f"unload={r['full_unload_time_sec_wallclock']['values']}s"
        )

    lines += [
        "",
        "## Ollama-served models (agent + embedder)",
        "",
        f"All generate-capable models loaded with `num_ctx={config.OLLAMA_NUM_CTX}` (see the "
        "warning above) -- this is *not* Ollama's per-model default, it's this pipeline's "
        "configured value, set via `config.OLLAMA_NUM_CTX` and overridable per-call through "
        "the gateway's `/agent/load`.",
        "",
        "| Model | Role | num_ctx | Size (VRAM) | Load (s) | Unload -- until gone from `/api/ps` (s) |",
        "|---|---|---|---|---|---|",
    ]
    role_map = {
        config.OLLAMA_MODELS[0]: "agent (`/api/generate`)",
        config.OLLAMA_MODELS[1]: "embedder (`/api/embed`)",
        config.OLLAMA_COMPARISON_MODEL: "smaller-model comparison (`/api/generate`)",
    }
    for model, r in results["ollama"].items():
        lo, un = r["load_time_sec"], r["unload_time_sec"]
        lines.append(
            f"| {model} | {role_map.get(model, '')} | {r['num_ctx'] or '(embed default)'} "
            f"| {r['size_gb']}GB "
            f"| {lo['mean']} (min {lo['min']}, max {lo['max']}) "
            f"| {un['mean']} (min {un['min']}, max {un['max']}) |"
        )
    lines += ["", "Raw samples per model:", ""]
    for model, r in results["ollama"].items():
        lines.append(f"- **{model}** load={r['load_time_sec']['values']}s, unload={r['unload_time_sec']['values']}s")

    lines += [
        "",
        "## Notes",
        "",
        "- Ollama's unload HTTP call (`keep_alive: 0`) returns almost immediately, but the "
        "model stays visible in `/api/ps` as `Stopping...` for a further stretch before it "
        "actually disappears -- confirmed directly. The unload numbers above are timed until "
        "the model is genuinely gone from `/api/ps`, not until the HTTP call returned, since "
        "the HTTP-return number alone would understate real unload time.",
        "- `nomic-embed-text` doesn't support `/api/generate` at all (confirmed: "
        '`"nomic-embed-text" does not support generate`) -- it\'s loaded/unloaded via '
        "`/api/embed` with an empty `input`, same `keep_alive` semantics.",
        "- Workers are lazily spawned, not a standing pool (see `gateway.py`) -- every unload "
        "is now a full process kill, no respawn, and the next `/load` pays real process-spawn "
        "+ heavy-import time on top of the model's own load() call (see the `spawn overhead` "
        "column above). This replaced an earlier always-on-pool design after a live "
        "orchestrator run caught its ~2.06GB combined idle-process baseline (ASR+NMT+TTS, "
        "never zero even fully \"unloaded\") pushing a supposedly-safe combination over the "
        "7GB Jetson budget for real -- see `load_balancer_plan.md`'s update log.",
        "- `qwen3:0.8b` (from the original notes) is not a real Ollama tag -- confirmed via "
        "`ollama pull` (`Error: pull model manifest: file does not exist`). The real tag is "
        "`qwen3.5:0.8b`, kept here only as the smaller comparison point now that the agent "
        "model has moved to `qwen3.5:2b`. Likewise there is no `qwen3.5:2.5b` tag.",
        "- Verified directly (process list, not just `/api/ps`'s self-report) that Ollama "
        "runs each *loaded* model as its own `llama-server` subprocess (command line includes "
        "`-c <num_ctx>`, confirming the configured context size actually took effect), and "
        "that subprocess is fully gone -- not just flagged idle -- once the model is "
        "unloaded. Unloading a model this way is a genuine process-kill, the same guarantee "
        "as `?full=true` on the ASR/NMT/TTS workers, not a soft in-process release.",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    gateway_proc = subprocess.Popen(
        [sys.executable, "run_all.py"], cwd=os.path.dirname(os.path.abspath(__file__))
    )
    results = {"workers": {}, "ollama": {}}
    try:
        if not wait_for_gateway():
            print("gateway did not become healthy in time", file=sys.stderr)
            return 1

        for name in ("asr", "nmt", "tts"):
            print(f"timing {name} ...")
            results["workers"][name] = time_worker(name, args.repeats)

        ollama_targets = [
            (config.OLLAMA_MODELS[0], "generate"),
            (config.OLLAMA_MODELS[1], "embed"),
            (config.OLLAMA_COMPARISON_MODEL, "generate"),
        ]
        for model, endpoint in ollama_targets:
            print(f"timing ollama model {model} ({endpoint}) ...")
            # num_ctx only applies to generate-capable models -- nomic-embed-text's own
            # default context (2048) is already small and isn't part of this pipeline's
            # num_ctx concern, so it's left unset (embed endpoint ignores it regardless).
            num_ctx = config.OLLAMA_NUM_CTX if endpoint == "generate" else None
            results["ollama"][model] = time_ollama_model(model, endpoint, args.repeats, num_ctx)

        print(f"measuring default-vs-configured num_ctx VRAM difference on {config.OLLAMA_MODELS[0]} ...")
        results["context_window_blowup"] = measure_context_window_blowup(config.OLLAMA_MODELS[0])

    finally:
        gateway_proc.terminate()
        try:
            gateway_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gateway_proc.kill()

    here = os.path.dirname(os.path.abspath(__file__))
    md_path = os.path.join(here, "TIMING_RESULTS.md")
    with open(md_path, "w") as f:
        f.write(render_markdown(results, args.repeats))
    print(f"\nWrote {md_path}")

    json_path = os.path.join(here, "timing_results.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Wrote {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
