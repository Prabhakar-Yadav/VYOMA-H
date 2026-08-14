"""v3 -- fixes what v2's own run found: v2's gateway (run_all.py subprocess) died
during case 1 (Ollama returned "unexpected EOF" while real_avail was already
down to 0.34GB) and NEVER CAME BACK -- every one of the other 39 cases failed
instantly with "Connection refused", not a fresh failure each time. v2's retry
logic retried the HTTP CALL but never checked whether the SERVER was still
alive, so it retried into a dead gateway 39 times in a row.

v3 adds: before every case, confirm the gateway is actually reachable; if not,
respawn run_all.py and wait for /health before proceeding. This is the one
piece both v1 and v2 lacked. Keeps v2's 10s inter-turn gap (reasonable, low-risk)
but drops v2's explicit per-case ASR/NMT unload -- the log shows real_avail was
already critical BEFORE any unload call ran, so that wasn't the cause and
added complexity without addressing the actual failure. Rule 10 (async ASR
preload)/evict_nmt_first (NMT evicted before every TTS) already unload ASR/NMT
around every turn by default -- confirmed in v1's own successful 31 turns.
"""
import json
import os
import subprocess
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
RESULTS_PATH = AUDIO_DIR / "results_v3.jsonl"
DONE_PATH = AUDIO_DIR / "DONE_v3"
DEADLINE_SECONDS = 60 * 60
INTER_TURN_GAP_SECONDS = 10
RETRY_COOLDOWN_SECONDS = 20

# v4: honor a shared absolute deadline across supervisor-driven restarts (a crash
# mid-hour shouldn't reset the clock -- the supervisor passes the SAME deadline
# to every relaunch via this env var, so total wall-clock across restarts still
# caps at exactly one hour, not one hour PER restart).
_deadline_ts_override = os.environ.get("DEVICE_TEST_DEADLINE_TS")

singles = json.load(open(AUDIO_DIR / "manifest_single_batch2.json", encoding="utf-8"))

results_f = open(RESULTS_PATH, "a", encoding="utf-8")

gateway_proc = None  # module-level so ensure_gateway_alive() can respawn+replace it


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


MIN_SAFE_AVAIL_GB = 1.0  # below this, v2's whole run died on turn 1 -- don't even attempt a case here


def wait_for_safe_memory(orch, max_wait_s=90, poll_s=5):
    """Real gap v2 had: nothing checked memory BEFORE starting a case, so a run
    could (and did) begin already critical. Poll real_available and refuse to
    proceed until there's real headroom, or give up after max_wait_s (caller
    decides what to do with a False return -- currently: skip the case rather
    than attempt a call already known to be in the failure zone)."""
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        try:
            snap = orch.snapshot()
            avail_gb = snap["real_available_bytes"] / 1e9
        except Exception as exc:
            print(f"[RUNNER] *** memory check itself failed: {exc} ***")
            return False
        if avail_gb >= MIN_SAFE_AVAIL_GB:
            return True
        print(f"[RUNNER] real_avail={avail_gb:.2f}GB < {MIN_SAFE_AVAIL_GB}GB safe floor -- waiting {poll_s}s before checking again")
        time.sleep(poll_s)
    print(f"[RUNNER] *** memory still below {MIN_SAFE_AVAIL_GB}GB safe floor after {max_wait_s}s -- not attempting this case ***")
    return False


def ensure_gateway_alive(orch, agent):
    """Real fix for what v2 hit: if the gateway is unreachable, respawn it and
    reload agent+embedder (a fresh run_all.py starts with nothing resident).
    Returns True if the gateway is confirmed healthy by the end of this call."""
    global gateway_proc
    if wait_for_gateway(timeout=2.0):
        return True

    print("[RUNNER] *** gateway unreachable -- respawning run_all.py ***")
    record({"event": "gateway_respawn"})
    if gateway_proc is not None:
        gateway_proc.terminate()
        try:
            gateway_proc.wait(timeout=10)
        except Exception:
            gateway_proc.kill()
    # Safety net for any orphaned worker subprocess the dead gateway left behind.
    subprocess.run(["pkill", "-f", "workers/asr_worker\\|workers/nmt_worker\\|workers/tts_worker"],
                    check=False)
    time.sleep(2)
    gateway_proc = subprocess.Popen([sys.executable, "run_all.py"],
                                     cwd=os.path.join(AGENTS_DIR, "api_server"))
    if not wait_for_gateway(timeout=30):
        print("[RUNNER] *** gateway respawn FAILED to come up in 30s ***")
        return False
    try:
        orch.ensure_agent_loaded_for_session()
        orch.ensure_embedder_loaded_for_session()
    except Exception as exc:
        print(f"[RUNNER] *** reload after respawn failed: {exc} ***")
        return False
    print("[RUNNER] gateway respawned and healthy again")
    return True


def run_one_case(case, orch, agent):
    audio_path = AUDIO_DIR / case["audio"]
    t0 = time.time()
    result = run_full_pipeline(
        case["lang"], orch, agent, play=False,
        audio_path_override=str(audio_path),
        turn_label=f"batch2v3-{case['id']:02d}",
    )
    snap = snapshot_components(orch)
    return {
        "event": "turn_complete", "phase": "single_batch2_v3", "case_id": case["id"],
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
    global gateway_proc
    t_start = time.time()
    deadline = float(_deadline_ts_override) if _deadline_ts_override else t_start + DEADLINE_SECONDS
    print(f"[RUNNER] deadline set to {time.strftime('%H:%M:%S', time.localtime(deadline))} "
          f"({'shared/supervisor' if _deadline_ts_override else 'own'} deadline)")

    we_own_the_gateway = not wait_for_gateway(timeout=1.0)
    if we_own_the_gateway:
        gateway_proc = subprocess.Popen(
            [sys.executable, "run_all.py"], cwd=os.path.join(AGENTS_DIR, "api_server")
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

    # Real gap v2 hit: it started case 1 with real_avail already at 0.34GB and
    # never had a chance. Refuse to even begin Phase 1 in that state.
    if not wait_for_safe_memory(orch, max_wait_s=120):
        print("[RUNNER] *** aborting run: memory was never safe enough to start Phase 1 ***")
        record({"event": "session_end", "stopped_early": True, "n_done": 0, "n_retried": 0,
                "n_failed": 0, "n_gateway_respawns": 0, "total_wall_s": time.time() - t_start,
                "abort_reason": "memory never reached safe floor before Phase 1"})
        results_f.close()
        DONE_PATH.write_text(json.dumps({"stopped_early": True, "n_done": 0,
                                          "abort_reason": "memory never reached safe floor"}))
        return 1

    n_done = n_retried = n_failed = n_respawns = 0
    stopped_early = False
    pass_num = 0

    banner("PHASE 1 (v4) -- 40 real-audio cases, repeating until deadline, gateway auto-respawn, 10s gap")
    while time.time() < deadline:
        pass_num += 1
        print(f"[RUNNER] === starting pass {pass_num} over all 40 cases "
              f"({(deadline - time.time())/60:.1f} min remaining) ===")
        for i, case in enumerate(singles):
            if time.time() > deadline:
                stopped_early = True
                record({"event": "deadline_hit_before_case", "phase": "single_batch2_v3",
                         "case_id": case["id"], "pass": pass_num})
                break

            if not (pass_num == 1 and i == 0):
                print(f"[RUNNER] waiting {INTER_TURN_GAP_SECONDS}s before next case...")
                time.sleep(INTER_TURN_GAP_SECONDS)

            if not ensure_gateway_alive(orch, agent):
                n_respawns += 1
                record({"event": "turn_error", "phase": "single_batch2_v3", "case_id": case["id"],
                         "pass": pass_num, "error": "gateway respawn failed, skipping case"})
                n_failed += 1
                continue

            if not wait_for_safe_memory(orch):
                record({"event": "turn_error", "phase": "single_batch2_v3", "case_id": case["id"],
                         "pass": pass_num, "error": f"real_avail stayed below {MIN_SAFE_AVAIL_GB}GB, skipping case"})
                n_failed += 1
                continue

            try:
                entry = run_one_case(case, orch, agent)
                entry["pass"] = pass_num
                record(entry)
                print_stage_times(entry["stage_times"], f"batch2v3-p{pass_num}-{case['id']:02d}")
                print_full_snapshot(orch, f"batch2v3-p{pass_num}-{case['id']:02d}")
                n_done += 1
            except Exception as exc:
                print(f"[RUNNER] *** case {case['id']} raised: {exc} -- cooling down {RETRY_COOLDOWN_SECONDS}s then retrying once ***")
                record({"event": "turn_error", "phase": "single_batch2_v3", "case_id": case["id"],
                         "pass": pass_num, "error": str(exc), "retry": "pending"})
                time.sleep(RETRY_COOLDOWN_SECONDS)
                n_retried += 1
                if not ensure_gateway_alive(orch, agent):
                    n_respawns += 1
                    record({"event": "turn_error", "phase": "single_batch2_v3", "case_id": case["id"],
                             "pass": pass_num, "error": "gateway respawn failed on retry path", "retry": "failed"})
                    n_failed += 1
                    continue
                if not wait_for_safe_memory(orch):
                    record({"event": "turn_error", "phase": "single_batch2_v3", "case_id": case["id"],
                             "pass": pass_num, "error": f"real_avail stayed below {MIN_SAFE_AVAIL_GB}GB on retry",
                             "retry": "failed"})
                    n_failed += 1
                    continue
                try:
                    entry = run_one_case(case, orch, agent)
                    entry["retried"] = True
                    entry["pass"] = pass_num
                    record(entry)
                    print_stage_times(entry["stage_times"], f"batch2v3-p{pass_num}-{case['id']:02d} (retry)")
                    print_full_snapshot(orch, f"batch2v3-p{pass_num}-{case['id']:02d} (retry)")
                    n_done += 1
                except Exception as exc2:
                    print(f"[RUNNER] *** case {case['id']} retry ALSO failed: {exc2} -- giving up on this case ***")
                    record({"event": "turn_error", "phase": "single_batch2_v3", "case_id": case["id"],
                             "pass": pass_num, "error": str(exc2), "retry": "failed"})
                    n_failed += 1

    record({
        "event": "session_end", "stopped_early": stopped_early, "passes_completed_or_started": pass_num,
        "n_done": n_done, "n_retried": n_retried, "n_failed": n_failed,
        "n_gateway_respawns": n_respawns, "total_wall_s": time.time() - t_start,
    })

    if we_own_the_gateway and gateway_proc is not None:
        try:
            orch.teardown()
        except Exception:
            pass
        gateway_proc.terminate()
        try:
            gateway_proc.wait(timeout=10)
        except Exception:
            gateway_proc.kill()

    results_f.close()
    DONE_PATH.write_text(json.dumps({
        "stopped_early": stopped_early, "n_done": n_done, "n_retried": n_retried,
        "n_failed": n_failed, "n_gateway_respawns": n_respawns,
        "total_wall_s": time.time() - t_start,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
