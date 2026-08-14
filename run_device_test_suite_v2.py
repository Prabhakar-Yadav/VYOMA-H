"""v2 -- fresh 60-minute continuous run, 40 NEW real farmer-audio single-turn
cases only (batch2, no reused clips, no conversations this time).

Two real fixes over v1, based on what v1's own run found:
1. v1 had ZERO gap between turns -- every other proven script in this repo
   (--all/--followups/--multiturn-stress) uses a 10s inter-turn gap for a real,
   documented reason (lets Rule 10's async ASR preload actually land, mimics a
   farmer needing a moment before the next question). v1 skipped it and the run
   showed real_avail dropping to 0.18GB with Ollama silently restarting under
   pressure (case 37/38's "agent not resident despite never being evicted --
   unexpected" warning) -- not a code bug, a missing pause under this script's
   own back-to-back load.
2. Explicit orch._unload('asr', ...) / orch._unload('nmt', ...) after every turn
   -- matches the explicit ask (do not rely on Rule 10's async preload keeping
   ASR/NMT warm between cases; force them cold each time, trading speed for
   headroom on a stress run that's about the temperature/memory ceiling, not
   turn-to-turn latency).

Also added: one retry after a 20s cool-down on a transient error (the exact
failure mode v1 hit -- worker 500/EOF under pressure) before giving up on a
case, instead of just logging and moving on.
"""
import json
import sys
import time
from pathlib import Path

AGENTS_DIR = "/home/jetson/gramsahayak"
sys.path.insert(0, AGENTS_DIR)

from test_orchestrated_pipeline import (  # noqa: E402
    run_full_pipeline, wait_for_gateway, banner, print_full_snapshot, print_stage_times,
)
from api_server.orchestrator import MemoryOrchestrator  # noqa: E402
from agent import GramSahayakAgent  # noqa: E402
from api_server import config  # noqa: E402

AUDIO_DIR = Path(AGENTS_DIR) / "device_test_audio_batch2"
RESULTS_PATH = AUDIO_DIR / "results.jsonl"
DONE_PATH = AUDIO_DIR / "DONE"
DEADLINE_SECONDS = 60 * 60
INTER_TURN_GAP_SECONDS = 10
RETRY_COOLDOWN_SECONDS = 20

singles = json.load(open(AUDIO_DIR / "manifest_single_batch2.json", encoding="utf-8"))

results_f = open(RESULTS_PATH, "a", encoding="utf-8")


def record(entry):
    entry["wall_clock_ts"] = time.time()
    results_f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    results_f.flush()


def snapshot_components(orch):
    snap = orch.snapshot()
    out = {}
    for name, c in snap["components"].items():
        if c["state"] == "loaded":
            out[name] = round(orch._component_bytes(name, snap) / 1e9, 4)
        else:
            out[name] = c["state"]
    out["_total_gb"] = round(snap["total_bytes"] / 1e9, 4)
    out["_real_used_gb"] = round(snap["real_used_bytes"] / 1e9, 4)
    out["_real_available_gb"] = round(snap["real_available_bytes"] / 1e9, 4)
    return out


def run_one_case(case, orch, agent):
    audio_path = AUDIO_DIR / case["audio"]
    t0 = time.time()
    result = run_full_pipeline(
        case["lang"], orch, agent, play=False,
        audio_path_override=str(audio_path),
        turn_label=f"batch2-{case['id']:02d}",
    )
    snap = snapshot_components(orch)
    return {
        "event": "turn_complete", "phase": "single_batch2", "case_id": case["id"],
        "category": case["category"], "reference_hindi": case["reference_hindi"],
        "expect": case["expect"], "must_not": case["must_not"],
        "stage_times": result.get("stage_times", {}),
        "english_query": result.get("english_query"),
        "english_answer": result.get("english_answer"),
        "target_text": result.get("target_text"),
        "empty_response": result.get("empty_response", False),
        "snapshot_after": snap,
        "wall_s": time.time() - t0,
    }


def main():
    t_start = time.time()
    deadline = t_start + DEADLINE_SECONDS

    we_own_the_gateway = not wait_for_gateway(timeout=1.0)
    gateway_proc = None
    if we_own_the_gateway:
        import subprocess, os as _os
        gateway_proc = subprocess.Popen(
            [sys.executable, "run_all.py"], cwd=_os.path.join(AGENTS_DIR, "api_server")
        )
    if not wait_for_gateway():
        print("gateway did not become healthy in time", file=sys.stderr)
        return 1

    orch = MemoryOrchestrator()
    agent = GramSahayakAgent()
    orch.ensure_agent_loaded_for_session()
    orch.ensure_embedder_loaded_for_session()

    t_load0 = time.time()
    try:
        from agent.warmup import warmup_agent
        warmup_agent(model=config.OLLAMA_MODELS[0], num_ctx=config.OLLAMA_NUM_CTX)
    except Exception as exc:
        print(f"[RUNNER] warmup failed ({exc}), continuing")
    warmup_s = time.time() - t_load0

    record({"event": "session_start", "warmup_s": warmup_s,
            "snapshot_after_warmup": snapshot_components(orch)})

    n_done = n_retried = n_failed = 0
    stopped_early = False

    banner("PHASE 1 (v2) -- 40 NEW single-turn real-audio cases, 10s gap + explicit ASR/NMT unload each turn")
    for i, case in enumerate(singles):
        if time.time() > deadline:
            stopped_early = True
            record({"event": "deadline_hit_before_case", "phase": "single_batch2", "case_id": case["id"]})
            break

        if i > 0:
            print(f"[RUNNER] waiting {INTER_TURN_GAP_SECONDS}s before next case (memory settle + realistic pacing)...")
            time.sleep(INTER_TURN_GAP_SECONDS)

        try:
            entry = run_one_case(case, orch, agent)
            record(entry)
            print_stage_times(entry["stage_times"], f"batch2-{case['id']:02d}")
            print_full_snapshot(orch, f"batch2-{case['id']:02d}")
            n_done += 1
        except Exception as exc:
            print(f"[RUNNER] *** case {case['id']} raised: {exc} -- cooling down {RETRY_COOLDOWN_SECONDS}s then retrying once ***")
            record({"event": "turn_error", "phase": "single_batch2", "case_id": case["id"],
                     "error": str(exc), "retry": "pending"})
            time.sleep(RETRY_COOLDOWN_SECONDS)
            n_retried += 1
            try:
                entry = run_one_case(case, orch, agent)
                entry["retried"] = True
                record(entry)
                print_stage_times(entry["stage_times"], f"batch2-{case['id']:02d} (retry)")
                print_full_snapshot(orch, f"batch2-{case['id']:02d} (retry)")
                n_done += 1
            except Exception as exc2:
                print(f"[RUNNER] *** case {case['id']} retry ALSO failed: {exc2} -- giving up on this case ***")
                record({"event": "turn_error", "phase": "single_batch2", "case_id": case["id"],
                         "error": str(exc2), "retry": "failed"})
                n_failed += 1

        # Explicit per-case unload -- do not rely on Rule 10's async preload keeping
        # ASR/NMT warm between cases. Best-effort: a failed unload shouldn't kill the run.
        for component in ("asr", "nmt"):
            try:
                orch._unload(component, reason=f"explicit per-case unload after batch2-{case['id']:02d}")
            except Exception as exc:
                print(f"[RUNNER] *** explicit unload of {component} failed: {exc} -- continuing ***")

    record({
        "event": "session_end", "stopped_early": stopped_early,
        "n_done": n_done, "n_retried": n_retried, "n_failed": n_failed,
        "total_wall_s": time.time() - t_start,
    })

    if we_own_the_gateway:
        orch.teardown()
        if gateway_proc is not None:
            gateway_proc.terminate()
            try:
                gateway_proc.wait(timeout=10)
            except Exception:
                gateway_proc.kill()

    results_f.close()
    DONE_PATH.write_text(json.dumps({
        "stopped_early": stopped_early, "n_done": n_done, "n_retried": n_retried,
        "n_failed": n_failed, "total_wall_s": time.time() - t_start,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
