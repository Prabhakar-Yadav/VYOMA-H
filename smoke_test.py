import sys, time, json, os, subprocess
sys.path.insert(0, "/home/jetson/gramsahayak")
from test_orchestrated_pipeline import run_full_pipeline, wait_for_gateway
from api_server.orchestrator import MemoryOrchestrator
from agent import GramSahayakAgent

we_own = not wait_for_gateway(timeout=1.0)
gp = None
if we_own:
    gp = subprocess.Popen([sys.executable, "run_all.py"], cwd=os.path.join("/home/jetson/gramsahayak", "api_server"))
assert wait_for_gateway(), "gateway did not come up"

orch = MemoryOrchestrator()
agent = GramSahayakAgent()
orch.ensure_agent_loaded_for_session()

t0 = time.time()
result = run_full_pipeline(
    "hi", orch, agent, play=False,
    audio_path_override="/home/jetson/gramsahayak/device_test_audio/01.wav",
    turn_label="smoke-01",
)
print("TOTAL_WALL", time.time() - t0)
print("STAGE_TIMES", json.dumps(result.get("stage_times", {})))
print("ENGLISH_QUERY", result.get("english_query", ""))
print("ANSWER", result.get("target_text", "")[:300])

orch.teardown()
if gp:
    gp.terminate()
