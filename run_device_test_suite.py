"""60-minute continuous device test run: 40 real farmer-audio single-turn cases,
then (if time remains) 20 constructed multi-turn conversations built from the same
real clips. Reuses test_orchestrated_pipeline.py's own proven run_full_pipeline(),
MemoryOrchestrator and GramSahayakAgent -- does not reimplement the pipeline.

Per turn, records: ASR/NMT-in/Agent/NMT-out/TTS stage latency (from
result["stage_times"], real numbers already computed by orchestrator.py's own
run_asr/run_nmt/run_agent/run_tts), and a full orch.snapshot() per-component RSS
memory breakdown taken right after the turn (same granularity --multiturn-stress
already uses for real memory-budget stress testing).

Writes results incrementally to device_test_audio/results.jsonl (one JSON line per
turn) so a crash or the 60-minute cutoff still leaves everything done so far on
disk, plus device_test_audio/DONE marker file when the whole run (single cases,
then conversations if time allowed) is over.
"""
import json
import sys
import time
from pathlib import Path

AGENTS_DIR = "/home/jetson/gramsahayak"
sys.path.insert(0, AGENTS_DIR)

from test_orchestrated_pipeline import (  # noqa: E402
    run_full_pipeline, wait_for_gateway, banner, print_full_snapshot,
    print_stage_times, LANGUAGES,
)
from api_server.orchestrator import MemoryOrchestrator  # noqa: E402
from agent import GramSahayakAgent  # noqa: E402
from api_server import config  # noqa: E402

AUDIO_DIR = Path(AGENTS_DIR) / "device_test_audio"
RESULTS_PATH = AUDIO_DIR / "results.jsonl"
DONE_PATH = AUDIO_DIR / "DONE"
DEADLINE_SECONDS = 60 * 60

singles = json.load(open(AUDIO_DIR / "manifest_single.json", encoding="utf-8"))
conversations = json.load(open(AUDIO_DIR / "manifest_conversations.json", encoding="utf-8"))

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

    n_done_single = n_done_convo = 0
    stopped_early = False

    banner("PHASE 1 -- 40 single-turn real-audio cases")
    for case in singles:
        if time.time() > deadline:
            stopped_early = True
            record({"event": "deadline_hit_before_case", "phase": "single", "case_id": case["id"]})
            break
        audio_path = AUDIO_DIR / f"{case['id']:02d}.wav"
        t0 = time.time()
        try:
            result = run_full_pipeline(
                case["lang"], orch, agent, play=False,
                audio_path_override=str(audio_path),
                turn_label=f"single-{case['id']:02d}",
            )
            snap = snapshot_components(orch)
            record({
                "event": "turn_complete", "phase": "single", "case_id": case["id"],
                "category": case["category"], "reference_hindi": case["reference_hindi"],
                "expect": case["expect"], "must_not": case["must_not"],
                "stage_times": result.get("stage_times", {}),
                "english_query": result.get("english_query"),
                "english_answer": result.get("english_answer"),
                "target_text": result.get("target_text"),
                "empty_response": result.get("empty_response", False),
                "snapshot_after": snap,
                "wall_s": time.time() - t0,
            })
            print_stage_times(result.get("stage_times", {}), f"single-{case['id']:02d}")
            print_full_snapshot(orch, f"single-{case['id']:02d}")
        except Exception as exc:
            record({"event": "turn_error", "phase": "single", "case_id": case["id"], "error": str(exc)})
            print(f"[RUNNER] *** case {case['id']} raised: {exc} -- continuing ***")
        n_done_single += 1

    if not stopped_early:
        banner("PHASE 2 -- 20 multi-turn conversations (time remaining)")
        for conv in conversations:
            if time.time() > deadline:
                stopped_early = True
                record({"event": "deadline_hit_before_case", "phase": "conversation", "case_id": conv["id"]})
                break
            running_messages = None
            for turn in conv["turns"]:
                if time.time() > deadline:
                    stopped_early = True
                    record({"event": "deadline_hit_mid_conversation", "conv_id": conv["id"],
                             "turn": turn["turn"]})
                    break
                audio_path = AUDIO_DIR / f"{turn['source_clip_id']:02d}.wav"
                t0 = time.time()
                try:
                    result = run_full_pipeline(
                        turn["lang"], orch, agent, play=False,
                        audio_path_override=str(audio_path),
                        messages=running_messages,
                        turn_label=f"{conv['id']}-turn{turn['turn']}",
                    )
                    running_messages = result["messages"]
                    snap = snapshot_components(orch)
                    record({
                        "event": "turn_complete", "phase": "conversation", "conv_id": conv["id"],
                        "topic": conv["topic"], "turn": turn["turn"],
                        "source_clip_id": turn["source_clip_id"], "category": turn["category"],
                        "reference_hindi": turn["reference_hindi"], "expect": turn["expect"],
                        "must_not": turn["must_not"],
                        "stage_times": result.get("stage_times", {}),
                        "english_query": result.get("english_query"),
                        "english_answer": result.get("english_answer"),
                        "target_text": result.get("target_text"),
                        "empty_response": result.get("empty_response", False),
                        "snapshot_after": snap,
                        "wall_s": time.time() - t0,
                    })
                    print_stage_times(result.get("stage_times", {}), f"{conv['id']}-turn{turn['turn']}")
                    print_full_snapshot(orch, f"{conv['id']}-turn{turn['turn']}")
                except Exception as exc:
                    record({"event": "turn_error", "phase": "conversation", "conv_id": conv["id"],
                            "turn": turn["turn"], "error": str(exc)})
                    print(f"[RUNNER] *** conv {conv['id']} turn {turn['turn']} raised: {exc} -- continuing ***")
            n_done_convo += 1

    record({
        "event": "session_end", "stopped_early": stopped_early,
        "n_single_done": n_done_single, "n_conversations_done": n_done_convo,
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
        "stopped_early": stopped_early, "n_single_done": n_done_single,
        "n_conversations_done": n_done_convo, "total_wall_s": time.time() - t_start,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
