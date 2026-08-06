"""Static config for the model-serving API: ports, checkpoint locations, and *predicted*
load costs used only for pre-flight budget estimates before something is actually loaded
(e.g. "would loading TTS now push us over budget?"). Real, authoritative memory numbers
always come from each worker's own live /status -- see API_DESIGN.md's "never a substitute
for a real reading" note. The predicted numbers below are the measured figures from
dev/local_model_test/*_memory_log.txt, same ones used in
suno-sutra-sw/python/pocketinfer/memory_orchestrator/load_balancer_plan.md.
"""
import os

# dev/agents/ -- the parent of this api_server/ package. Every worker process puts this on
# sys.path so `models.asr.model_loader` etc. resolve the same way the notebooks import them.
AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GATEWAY_HOST = "127.0.0.1"
GATEWAY_PORT = 11400

OLLAMA_HOST = "http://localhost:11434"
# "qwen3:0.8b" from earlier notes isn't a real tag (confirmed: no such manifest on the
# registry). Agent model is back down to qwen3.5:0.8b (was bumped to qwen3.5:2b earlier when
# the dev machine's budget had room; reverted on real Jetson hardware after a confirmed real
# OOM/reboot -- Agent stays resident across turns by design (Rule 9 preload + no eviction
# before ASR load), and 2b's real footprint (2.647GB, TIMING_RESULTS.md) plus ASR's own
# multi-GB load spike pushed the device past its 7.6GB physical ceiling into swap thrashing
# and a hard reset. 0.8b's real footprint is 1.331GB -- see TIMING_RESULTS.md for both. Note:
# load/unload *time* is essentially identical between the two sizes in that same benchmark
# (~5.4s either way) -- this change buys memory headroom, not faster reloads.
# nomic-embed-text is an embedding model, served over /api/embed rather than /api/generate
# (see test_timing.py) but it's still one of the two models this pipeline's agent step needs.
OLLAMA_MODELS = ["qwen3.5:0.8b", "nomic-embed-text"]
# Larger comparison point, not part of the pipeline -- used in test_timing.py to see how
# load/unload time scales with model size (kept from before the agent model was reverted).
OLLAMA_COMPARISON_MODEL = "qwen3.5:2b"

# num_ctx is a live, adjustable setting -- not a one-time measurement -- exactly like the
# hardware config vars (audio trigger type, camera trigger, output language). This constant
# is only the *default*; gateway.py's /agent/load accepts a per-call override, and the
# orchestrator can change this value at runtime the same way it flips any other config var.
#
# Why it matters at all: confirmed directly that loading a model with no num_ctx option set
# falls back to *that model's own* default context_length (262144 for qwen3.5 models), which
# pre-allocates a KV-cache-sized VRAM footprint of 5.475GB for qwen3.5:0.8b just to sit idle
# -- versus 1.213GB at num_ctx=8192, a 4.5x difference for the exact same model and zero
# tokens generated. Every load call must pass this explicitly; relying on Ollama's per-model
# default is what silently ate the other 4.3GB. Currently 2x vyoma_v5.ipynb's original 8192
# (more headroom for longer tool-calling conversations) -- re-tune based on real usage.
OLLAMA_NUM_CTX = 8192 * 2

# Agent's `think` level for ollama.chat() -- live, adjustable, same as the vars above. Options
# and what was actually measured with them (5-6 repeated identical calls each, real Jetson +
# this dev machine, qwen3.5:0.8b, see agent/agent.py's class docstring for the incident this
# came from):
#   False   -- fastest (~7s/turn observed), but confirmed to sometimes return a completely
#              EMPTY final `.content` on this small a model -- it generates real tokens with
#              think="low" but not False; False itself hasn't reproduced empty content in
#              testing, but see the "medium" note below for why it's not the pick anyway.
#   "low"   -- confirmed on real Jetson hardware to sometimes return an EMPTY `.content` while
#              putting everything into `.thinking` instead (the model never closes its
#              reasoning phase) -- this is the bug that silently broke NMT downstream
#              (translating an empty string). Do not use.
#   "medium" -- 0/6 empty-content failures across repeated tests, real substantive answers,
#              ~10-20s/turn observed. Best reliability-for-latency tradeoff found so far --
#              current default.
#   "high"  -- also 0/6 empty-content failures, marginally more thorough answers, but ~14-29s/
#              turn observed (up to ~4x slower than False) -- not worth it over "medium" unless
#              answer quality becomes a real problem.
# Re-tune this per model if OLLAMA_MODELS[0] ever changes -- these numbers are qwen3.5:0.8b-
# specific, not a general Ollama/qwen3.5 property (qwen3.5:2b's think="low" was previously
# validated as reliable, see run_pipeline_live_demo.py).
AGENT_THINK = "medium"

# Which TTS engine the pipeline actually uses -- live, adjustable, exactly like
# OLLAMA_NUM_CTX above (not a one-time build choice). "mms_tts" (default) or "parler".
#
# Defaulted to mms_tts after a direct, real-measured comparison (dev/agents/
# MMS_TTS_EVALUATION.md) found it smaller and faster on every measured axis: ~0.18-0.20GB
# steady VRAM vs Parler's 1.27-1.94GB, ~1.03GB worst-case peak (no chunking needed) vs
# Parler's 4.46-5.2GB real observed peak, and RTF 0.01-0.06 (15-70x faster than real-time)
# vs Parler's RTF ~2.2-3x (slower than real-time, and its own worst-case test didn't even
# finish the intended text before hitting its generation cap). MMS-TTS is CC-BY-NC 4.0
# (non-commercial only, confirmed directly against the HF repo -- see
# MMS_TTS_EVALUATION.md section 1) -- fine for this project's current non-commercial phase,
# but re-check before any commercial deployment; that's the one reason this default might
# need to flip back to "parler" later, not a technical one.
TTS_ENGINE = "mms_tts"
##Other options: "parler" (the other engine this pipeline can use, but slower and bigger than mms_tts)

# Per-engine settings, keyed by the same names TTS_ENGINE selects between. tts_worker.py
# reads WORKERS["tts"]["engine"] to decide which one to actually instantiate; everything
# else in this file and in orchestrator.py/test_orchestrated_pipeline.py keeps reading the
# flattened WORKERS["tts"][...] shape it always has (see the ** spread below) so switching
# TTS_ENGINE doesn't require touching those call sites.
_TTS_ENGINE_CONFIGS = {
    "parler": {
        "checkpoint_dir": os.path.join(AGENTS_DIR, "models", "checkpoints", "indic-parler-tts-awq-int4"),
        "predicted_load_cost_steady_bytes": 1_270_000_000,
        # streaming.py's own documented figure (3.70GB, batch=6) turned out to be optimistic.
        # Two real live full-pipeline runs on the same real Hindi answer (3 chunks) measured
        # peak *pool* of 7.79GB (batch=6) and 7.54GB (batch=3) with Agent(2.65GB) resident --
        # i.e. TTS alone reached ~5.14GB and ~4.89GB respectively. Batch size barely moved the
        # peak because the answer's 3 chunks fit inside either cap, running as one identical
        # batched call either way -- the real driver is per-chunk length, not batch grouping.
        # 5.2GB below is the higher of the two real observations, rounded up for margin.
        # Orchestrator's actual fix (Rule 8, orchestrator.py) is evicting Agent unconditionally
        # before every TTS peak, not a batch-size change -- see load_balancer_plan.md's update
        # log for the full finding.
        "predicted_load_cost_peak_batch3_bytes": 5_200_000_000,
        "default_batch_size": 3,
        "min_batch_size": 3,
        "needs_batching": True,  # autoregressive codec-token decoder -- long text must be
        # chunked (max_new_tokens cap) and re-batched for throughput; see tts_exports/streaming.py
        "predicted_load_time_sec": 3.2,
        "predicted_unload_time_sec": 4.7,
    },
    "mms_tts": {
        # One checkpoint per language (mms-tts-<lang>/ subdirs), not one shared model --
        # see models/mms_tts/model_loader.py's module docstring. checkpoint_root is the
        # parent dir; tts_worker.py's MultiLangMmsTtsEngine appends "mms-tts-<lang>" itself.
        "checkpoint_root": os.path.join(AGENTS_DIR, "models", "checkpoints"),
        "preload_languages": ["en", "hi", "ml", "ta"],  # this project's LANGUAGES dict
        # CORRECTED after a real live pipeline run caught this wrong: the first version of
        # these two numbers (195MB / 1.03GB) was VRAM-only, pulled from the isolated
        # bare-Python benchmark in MMS_TTS_EVALUATION.md section 7. The orchestrator budgets
        # against RSS+VRAM *combined* (orchestrator.py's snapshot()/`total_bytes`) -- same
        # thing load_balancer_plan.md's update-log point 7 already flagged for the
        # ASR/NMT/TTS worker *processes themselves* (Python+torch+transformers+fastapi
        # overhead is real RSS, not VRAM). Confirmed directly via the actual tts_worker.py
        # process (`/status`, all 4 preload_languages loaded): steady combined
        # rss(0.878GB)+vram(0.587GB) = **1.47GB** (exactly matches a real orchestrator run's
        # own "tts=1.47GB" line). Peak during real synthesis is RSS-dominated, not
        # VRAM-dominated -- confirmed real orchestrator run on a genuine long Hindi answer
        # (~800 chars) hit **~3.67GB combined pool**; a shorter (~430 char) direct test hit
        # 2.53GB. 3.7GB below is the real observed worst case, not the optimistic one.
        "predicted_load_cost_steady_bytes": 1_470_000_000,
        "predicted_load_cost_peak_batch3_bytes": 3_700_000_000,  # kept under this key name
        # for PREDICTED_LOAD_COST_BYTES's "tts_peak_batch3" compatibility -- batching doesn't
        # apply here (see needs_batching below), this is just the real single-call worst case.
        "default_batch_size": 1,
        "min_batch_size": 1,
        "needs_batching": False,  # VITS: non-autoregressive, single forward pass, no
        # max_new_tokens cap -- confirmed directly that one plain synthesize() call handles
        # a real 883-char multi-paragraph Hindi answer (the same real answer
        # test_streaming_tts_only.py uses) in 1.64s producing 64.78s of audio (RTF 0.025),
        # peak 1.24GB/1.66GB. No chunk_text()/StreamingTTS/batch_size machinery needed.
        "predicted_load_time_sec": 1.8,
        "predicted_unload_time_sec": 0.15,
    },
}

# tts_worker.py's language-routing tables for the mms_tts engine. Real /tts/infer callers
# (test_orchestrated_pipeline.py) send the full display name as "language" (cfg["tts_name"]
# -- e.g. "Hindi", not "hi"), matching what Parler-TTS's speaker lookup needs -- MMS-TTS's
# own LANGUAGE_TO_REPO (models/mms_tts/model_loader.py) is keyed by short codes instead, so
# this maps between the two. Also short-code entries are accepted directly (harmless
# no-op lookup) for any caller that already uses this project's 2-letter codes.
MMS_TTS_LANGUAGE_NAME_TO_CODE = {
    "English": "en", "Hindi": "hi", "Malayalam": "ml", "Tamil": "ta",
    "Assamese": "as", "Bengali": "bn", "Dogri": "dgo", "Gujarati": "gu",
    "Kannada": "kn", "Maithili": "mai", "Marathi": "mr", "Odia": "or",
    "Punjabi": "pa", "Telugu": "te", "Urdu": "ur",
}

# Confirmed directly against MMS-TTS's own published language-coverage table
# (dl.fbaipublicfiles.com/mms/misc/language_coverage_mms.html), not assumed from any
# headline language count -- of India's 22 8th-Schedule languages, these 8 have NO real
# MMS-TTS checkpoint. Requests for any of these fall back to Parler-TTS even when
# TTS_ENGINE="mms_tts" -- see tts_worker.py's _HybridMmsParlerEngine. Kept as display
# names (matching what /tts/infer's "language" field actually carries) rather than ISO
# codes, since there's no MMS-TTS short code to map them to in the first place.
MMS_TTS_UNSUPPORTED_INDIAN_LANGUAGES = {
    "Bodo", "Kashmiri", "Konkani", "Manipuri", "Nepali", "Sanskrit", "Santali", "Sindhi",
}

WORKERS = {
    "asr": {
        "port": 11411,
        "module": "workers.asr_worker",
        "checkpoint_dir": os.path.join(AGENTS_DIR, "models", "checkpoints", "indic-conformer-600m-fp32"),
        "predicted_load_cost_bytes": 3_204_000_000,
        "predicted_load_time_sec": 5.2,
        "predicted_unload_time_sec": 2.5,
    },
    "nmt": {
        "port": 11412,
        "module": "workers.nmt_worker",
        "checkpoint_root": os.path.join(AGENTS_DIR, "models", "checkpoints", "indic-trans2-nmt"),
        "predicted_load_cost_bytes": 1_616_000_000,
        "predicted_load_time_sec": 0.7,
        "predicted_unload_time_sec": 2.7,
    },
    "tts": {
        "port": 11413,
        "module": "workers.tts_worker",
        "engine": TTS_ENGINE,       # which engine tts_worker.py actually instantiates
        "engines": _TTS_ENGINE_CONFIGS,  # every engine's own settings, for tts_worker.py's branch
        **_TTS_ENGINE_CONFIGS[TTS_ENGINE],  # flattened active engine's settings, backward-compatible
        # with every existing WORKERS["tts"][...] read (orchestrator.py, test_orchestrated_pipeline.py)
    },
}

# Flat prediction table for the orchestrator's pre-flight budget math (e.g. "would loading
# TTS's peak right now push us over budget?") -- covers all five schedulable components,
# including the two Ollama-served ones which aren't in WORKERS above since they're not
# gateway-managed subprocesses. Real, authoritative numbers still always come from live
# /status calls; these are only ever used to decide *before* a load whether it's safe to
# proceed. Sourced from dev/agents/api_server/TIMING_RESULTS.md (asr/nmt/tts/agent/embedder)
# and a real live full-pipeline run (test_orchestrated_pipeline.py) for tts_peak_batch3.
PREDICTED_LOAD_COST_BYTES = {
    "asr": WORKERS["asr"]["predicted_load_cost_bytes"],
    "nmt": WORKERS["nmt"]["predicted_load_cost_bytes"],
    "tts_steady": WORKERS["tts"]["predicted_load_cost_steady_bytes"],
    "tts_peak_batch3": WORKERS["tts"]["predicted_load_cost_peak_batch3_bytes"],
    "agent": 2_650_000_000,
    "embedder": 323_000_000,
}

def normalize_ollama_tag(name: str) -> str:
    """Ollama silently normalizes an untagged model name to '<name>:latest' in every
    response (`/api/ps`, `/api/generate`, etc.) -- confirmed directly: requesting
    "nomic-embed-text" (no tag) loads fine, but `/api/ps` reports it back as
    "nomic-embed-text:latest". Anything comparing a config name against a live Ollama
    response must normalize both sides through this first, or the comparison silently never
    matches (which is exactly what happened before this was added: /agent/status could never
    see nomic-embed-text as loaded, and a residency-poll loop kept reporting the model as
    already gone from the moment the unload call was fired)."""
    return name if ":" in name else f"{name}:latest"


# Jetson Orin ground truth (see load_balancer_plan.md) -- this dev machine has a much larger,
# also-unified GPU/CPU memory pool (GB10, ~130GB) and won't hit this ceiling, but the gateway
# uses the same constant either way so /system/memory's utilization_pct means the same thing
# on both machines. Override at deploy time for the real device if it ever differs from 8GB-1GB.
MODEL_BUDGET_BYTES = 7_000_000_000
COMPLEMENTARY_PAIRS = [("asr", "tts")]
