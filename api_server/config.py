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
# registry). Agent model was reverted to qwen3.5:0.8b from qwen3.5:2b on real Jetson hardware
# after a confirmed real OOM/reboot: 2b's real footprint (2.647GB, TIMING_RESULTS.md) plus the
# *old* multilingual ASR model's own multi-GB load spike pushed the device past its 7.6GB
# physical ceiling into swap thrashing and a hard reset. 0.8b's real footprint is 1.331GB --
# see TIMING_RESULTS.md for both. Note: load/unload *time* is essentially identical between
# the two sizes in that same benchmark (~5.4s either way) -- this change buys memory headroom,
# not faster reloads.
#
# TEMPORARILY back on qwen3.5:2b (2026-08-08) for a real multi-turn re-test of the *current*
# system -- the OOM above predates the quantized per-language ASR migration (ASR footprint is
# now ~0.4-0.8GB, not multi-GB) and predates Agent/NMT both being made sticky-resident. The
# original crash's specific cause (2b + old heavy ASR together) is no longer the same shape,
# but Agent(2.647GB)+NMT(0.54GB) sitting permanently resident is new territory this combination
# hasn't been tested against -- watch memory closely, revert to 0.8b if anything looks tight.
# granite-embedding:30m (2026-08-11, replaces nomic-embed-text) -- this is now what the real
# G1/G2 RAG system actually uses (rag/embed.py, int8-quantized index build/query embeddings,
# see RAG-BUILD-LOG.md), so it's the model that belongs here, not the older nomic-embed-text
# this pipeline's "embedder" component name predates. Confirmed no current agent tool actually
# calls Ollama's own /api/embed through this "embedder" component at all -- rag/embed.py talks
# to granite-embedding directly, bypassing this component concept entirely -- so this slot is
# currently unused dead weight regardless of which model name sits here; kept configured (not
# removed) since a real embedder-calling tool is a plausible near-future addition, and at
# ~30MB, granite-embedding:30m is cheap enough to just leave loaded once at session start
# (like Agent/NMT) rather than the on-demand Rule 7 machinery this used to justify -- see
# orchestrator.py's `ensure_agent_loaded_for_session()` for where that's wired in.
#
# Agent model swapped back qwen3.5:2b -> qwen3.5:0.8b on 2026-08-11, after a real, controlled
# decode-TPS bench on Jetson (same system_prompt+tools prefix, same question, num_ctx=16384,
# think="medium", full eviction between models so no cross-model GPU contention):
#   qwen3.5:2b         : 15.2 tok/s gen, 2.4GB VRAM, correct tool call
#   gemma4:e2b-it-qat   : 14.7 tok/s gen, 1.8GB VRAM, WRONG tool call (analyze_photo on a
#                         photo-less question -- ruled out, not faster and less reliable)
#   qwen3.5:0.8b        : 23.6 tok/s gen, 1.16GB VRAM (real size_vram, see PREDICTED_LOAD_COST_
#                         BYTES["agent"] below), correct tool call -- ~1.55x qwen3.5:2b's TPS
# This is also a return to a previously-validated config (see OLLAMA_NUM_CTX/AGENT_THINK
# comments below, both already qwen3.5:0.8b-tuned from before the earlier revert to 2b) -- that
# revert was to work around an old ASR multi-GB load spike which the ASR lazy-per-language-load
# fix (2026-08-10/11 Jetson stress test) already solved, so the original reason for avoiding
# 0.8b no longer applies.
#
# FINAL (2026-08-12): standardized on qwen3.5:2b, not qwen3.5:0.8b. The 0.8b TPS win (23.6 vs
# 15.2 tok/s at 15W) stopped being the deciding factor once nvpmodel MAXN power mode (device-
# wide, independent of model choice) closed most of that gap for 2b -- confirmed both in an
# isolated bench (2b gen: 15.2 -> 25.0-25.1 tok/s, +64%) and in a real 5-turn live pipeline run
# (hindi_v9: every non-first turn ~40-55% faster than the matched 15W run, e.g. turn 3 129.59s ->
# 75.07s, turn 5 118.72s -> 68.42s). With MAXN, 2b's real generation speed (~25 tok/s) is now
# ABOVE 0.8b's own 15W number -- the whole reason to trade down to 0.8b is gone. What's left is
# a real, observed accuracy gap in the other direction: 0.8b's image-based diagnosis of the same
# sample photo got the disease wrong ("Potato Black Scurf"), while 2b's plain-text diagnosis of
# the identical symptom description correctly said "Potato late blight" (the photo's actual real
# condition) -- one data point, not exhaustively tested, but real and in 2b's favor, and there
# was no offsetting reason left to prefer 0.8b once MAXN was in the picture. Turn 1's own
# remaining slowness is NOT a model-choice problem either way -- traced (2026-08-12, real
# journalctl per-call prompt_eval/eval data) to turn 1 routinely making 4-5 separate tool-calling
# LLM round-trips where a normal turn makes 1-2 (each one a real ~15-25s generation cost even at
# MAXN speed), not to decode TPS, prefix-cache warmup (confirmed working correctly call-to-call),
# or the image. See prompts.py's SYSTEM_PROMPT "AT MOST ONCE per turn" rule -- strengthened the
# same day after finding a real instance of it being violated (pesticide_usage_and_dose called
# twice in one turn, second time with a hallucinated, self-contradicting disease name).
#
# Also tried and found NOT to work: an mlock Modelfile variant (`PARAMETER use_mlock true`) --
# Ollama 0.32.6 prints "parameter use_mlock is deprecated" and, confirmed directly via the loaded
# process's real /proc/<pid>/status (VmLck: 0 kB) and its actual llama-server command line (no
# --mlock flag present at all), it's a genuine no-op on this version, not just a soft warning.
# Deleted the resulting model tag rather than keep a variant that provides nothing.
#
# 2026-08-15/16: promoted from two separate globals (OLLAMA_MODELS[0] + AGENT_THINK, picked
# independently) to a registry + one selector below. Real reason: `think` is NOT a model-
# independent setting -- qwen3.5:2b needs "medium" (think=False real-crashed with an EMPTY
# final answer on turn 1 of a real 5-turn Jetson run, see THINKING_MODE_RESULTS.md), while
# gemma4-e2b-mtp needs think=False (its own real bench win depends on it -- think="medium"
# reintroduces the thinking-token overhead that's the whole reason it's faster, and is also
# what produced the earlier, now-superseded "ruled out" verdict on a related gemma4 tag, see
# GEMMA4_E2B_ROBUSTNESS_RESULTS.md). Picking a model without its paired `think` value is a
# real, easy-to-hit footgun (a mismatched pairing either silently gives up gemma4's whole real
# advantage or reproduces qwen2b's real empty-answer failure) -- this registry makes the two
# travel together so that can't happen by accident.
AVAILABLE_AGENT_MODELS = {
    "qwen3.5:2b": {
        "model": "qwen3.5:2b",
        "think": "medium",
        "system_prompt": "default",
        "notes": (
            "Current production default (since 2026-08-12, MAXN power mode closed 0.8b's "
            "speed advantage). Real 5-turn Jetson bench (THINKING_MODE_RESULTS.md, "
            "2026-08-15/16): think=\"medium\" 0/5 empty-content failures; think=\"low\" also "
            "0/5 failures but no clear total-generation-time win over medium in that "
            "comparison (turn-to-turn tool-iteration-count variance dominated); think=False "
            "produced a real EMPTY final answer on turn 1 of a full run -- confirmed unsafe "
            "for this model, do not use."
        ),
    },
    "qwen3.5:0.8b": {
        "model": "qwen3.5:0.8b",
        "think": "medium",  # think="low" confirmed to sometimes return empty .content on this model specifically (the original incident this whole per-model registry is built
        "system_prompt": "default",
        "notes": (
            "Lower-memory backup: 1.33GB vs 2b's 2.66GB real VRAM. Real, observed accuracy "
            "gap vs 2b on image-based photo diagnosis (one data point, not exhaustively "
            "tested: 0.8b said \"Potato Black Scurf\" on a sample where 2b's plain-text "
            "diagnosis of the same symptoms correctly said \"Potato late blight\")."
        ),
    },
    "4skl/gemma4-e2b-mtp:latest": {
        "model": "4skl/gemma4-e2b-mtp:latest",
        "think": False,
        "system_prompt": "default",
        "notes": (
            "NOT SAFE TO SELECT (2026-08-16) -- real, root-caused memory problem, not just "
            "an orchestrator-contention issue. This tag's OWN command line (confirmed via "
            "real Jetson `ps aux`) shows it loads THREE things simultaneously: the base "
            "gemma4-e2b model, a SEPARATE draft model for speculative decoding (`--spec-type "
            "draft-mtp --spec-draft-model ...` -- \"mtp\" in the tag name -- almost certainly "
            "the real reason it benched fast, genuine speculative decoding, not just "
            "think=False), and a vision projector (`--mmproj ...`). Real measured RSS for "
            "that combination, confirmed via `ps aux --sort=-rss` with NOTHING else loaded "
            "(no ASR/NMT/TTS/embedder -- isolates this from orchestrator contention "
            "entirely): 5.18GB -- while Ollama's own `/api/ps` reports only `size_vram` "
            "~304MB for the same load, a real, large accounting gap. 5.18GB resident before "
            "a single image is processed, out of Jetson's real ~7.4GB physical, leaves "
            "essentially no margin for the vision call's own compute buffers regardless of "
            "what else is or isn't loaded -- confirmed directly: the SAME real CUDA OOM on "
            "analyze_photo reproduces even in this fully-isolated, nothing-else-loaded case, "
            "not just in the full orchestrated 5-turn/10-turn runs (3/3 turn-1 photo calls, "
            "2/2 attempts in the 10-turn run before it crashed outright at turn 4 -- "
            "journalctl: 'runtime OOM detected; expiring loaded models to clear memory' / "
            "'CUDA error: out of memory'). A farmer photographing a diseased plant -- the "
            "single most common real use case -- is exactly the case this breaks. Zero "
            "empty-content (non-vision) failures across all 15 successful orchestrated turns "
            "(a real positive, unlike qwen3.5:2b's think=False). Also "
            "unresolved: the one real photo-diagnosis case tested (ground truth = late blight) "
            "-- this model said a viral disease, qwen3.5:2b said a different wrong blight type; "
            "neither got it right. No parallel tool-calling observed. Before this candidate can "
            "be selected here for real, someone would need a variant WITHOUT the draft-model+"
            "vision bundle eating ~5GB at rest (e.g. the plain, non-MTP gemma4:e2b-it-qat tag, "
            "not yet re-benched at think=False -- see this project's own earlier notebook "
            "finding that think=False was gemma4's biggest lever, tested there on a DIFFERENT, "
            "non-MTP tag) -- this specific bundle's resting footprint is the real blocker, not "
            "something the orchestrator's eviction logic could route around. Full data: "
            "GEMMA4_E2B_ROBUSTNESS_RESULTS.md. NOTE: this is a working community tag of the "
            "Gemma-4 E2B family, NOT the exact originally-requested "
            "hf.co/unsloth/gemma-4-E2B-it-qat-mobile-GGUF:UD-Q2_K_XL file -- that specific "
            "GGUF fails to load on Ollama 0.32.1 (\"tensor 'token_embd.weight' size "
            "overflow\", confirmed via both `ollama show` and a real chat call)."
        ),
    },
    "hf.co/LiquidAI/LFM2.5-VL-1.6B-GGUF": {
        "model": "hf.co/LiquidAI/LFM2.5-VL-1.6B-GGUF",
        "think": None,  # not a qwen3.5-style thinking model -- None means "don't pass think="
                         # at all (see agent.py's own None-vs-False distinction), same as every
                         # non-qwen candidate tested in LFM2_LIQUIDAI_BENCH_RESULTS.md.
        "system_prompt": "vl_1_6b_tool_emphasis",  # see prompts.py's own docstring for why
                         # this model gets a distinct prompt, not qwen3.5:2b's "default" one.
        "notes": (
            "Real candidate, added 2026-08-17 after a real 15-question Jetson bench "
            "(LFM2_LIQUIDAI_BENCH_RESULTS.md) comparing it against qwen3.5:2b directly on the "
            "actual target device: 11/15 tool accuracy (vs qwen's 10/15), 3221MB real peak "
            "memory (vs qwen's 5772MB, 44% less), 105s total wall-clock for all 15 questions "
            "(vs qwen's 644s, ~6x faster). This is the ONLY one of three LiquidAI LFM2.5 "
            "configs tested that beat qwen3.5:2b on every measured axis (the other two traded "
            "real accuracy for a smaller memory/speed win). Real caveats, not fully resolved: "
            "(1) skipped analyze_photo on the one real photo question tested, inferring a "
            "diagnosis from the farmer's words alone instead -- prompted the "
            "vl_1_6b_tool_emphasis system prompt variant above as a real, direct attempt at a "
            "fix, itself not yet re-verified; (2) one wrong-tool call (pesticide_lookup "
            "instead of get_treatment_details on a real Mancozeb dosage question) produced a "
            "factually WRONG answer ('may not be registered' for a real, registered "
            "treatment) -- a wrong tool call here isn't just a scoring miss, it can mislead a "
            "farmer. Vision genuinely works (confirmed via real photo input, real specific "
            "descriptions, not generic non-answers) and tool-calling works via Ollama's "
            "DEFAULT Modelfile template on Ollama 0.32.1/0.32.9 -- no custom Modelfile needed, "
            "contrary to an older, stale secondhand report found during research. Uses this "
            "same model for BOTH agent reasoning and analyze_photo's own vision call (no "
            "separate vision_model= needed) -- same single-resident-model shape as qwen3.5:2b "
            "today, just a smaller model in that one slot."
        ),
    },
}

# Change this ONE line to switch the agent's model -- pulls in its correctly-paired `think`
# value automatically (see AVAILABLE_AGENT_MODELS' own comment for why the two must travel
# together). test_orchestrated_pipeline.py's --agent-model/--agent-think flags remain the way
# to try something ad hoc for a single test run without touching this file at all.
AGENT_MODEL_CHOICE = "qwen3.5:2b"

OLLAMA_MODELS = [AVAILABLE_AGENT_MODELS[AGENT_MODEL_CHOICE]["model"], "granite-embedding:30m"]
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
#
# Bumped 16384 -> 32768 (2026-08-12), motivated by the real turn-1 investigation: system_prompt+
# tools alone is ~5800-5900 tokens (~35% of a 16384 budget) before any conversation content, and
# a real redundant-tool-call turn (see prompts.py's "AT MOST ONCE per turn" section) can push a
# single turn's own message history well past what's comfortable, risking --context-shift
# truncation mid-conversation. The real memory cost of doubling is small, not assumed: measured
# directly (same method as PREDICTED_LOAD_COST_BYTES below) at 2.5619GB real size_vram for
# qwen3.5:2b at 32768, only ~124MB more than 16384's 2.4383GB -- KV cache scales far more gently
# than the num_ctx=262144-default case above (that one wasn't quantized/GQA-tuned the same way).
OLLAMA_NUM_CTX = 8192   # 2026-08-22: 32768 KV-cache did not fit with all models resident (OOM/reboot at real_avail=0.10GB during turn-4 ASR load); 8192 keeps the full multi-turn conversation within budget so nothing evicts

# Agent's `think` level for ollama.chat() -- derived from AGENT_MODEL_CHOICE above, NOT an
# independent setting anymore (see AVAILABLE_AGENT_MODELS' own comment for why: think is a
# real, model-specific tuning, not a global preference). Re-tune by editing that model's own
# "think" entry above, not this line -- kept as its own name (not inlined at every call site)
# since a lot of code still reads `config.AGENT_THINK` directly.
AGENT_THINK = AVAILABLE_AGENT_MODELS[AGENT_MODEL_CHOICE]["think"]

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
##Other options: "parler" (the other engine this pipeline can use, but slower and bigger than
# mms_tts), "fastspeech2_hs" (Bhashini/IIT Madras FastSpeech2+HiFi-GAN -- added 2026-08-14,
# real GX10 evaluation in fastspeech2_bhashini_eval/COMPARISON.md on the dev machine. Real,
# live comparison: MMS-TTS is currently faster and smaller on every measured axis -- this
# option exists as a config-selectable fallback specifically for MMS-TTS's CC-BY-NC-4.0
# license (non-commercial only, see this file's own comment above), since fastspeech2_hs is
# CC BY 4.0 (commercial-friendly with attribution). NOT a drop-in yet: needs `espnet`+
# `espnet2` importable in whatever interpreter runs the "tts" worker -- real, unresolved
# dependency conflict (espnet's install downgraded torch 2.13.0->2.12.1 in GX10 testing, not
# yet attempted against this project's own shared venv) -- see models/fastspeech2_hs/
# model_loader.py's own docstring point 5. Only "hindi"/"male" has a real checkpoint vendored
# so far (models/checkpoints/fastspeech2-hs/).

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
        "preload_languages": ["en", "hi", "ml", "ta"],  # this project's LANGUAGES dict --
        # 2026-08-11: this is now a REFERENCE/validity list only, not an eager-load
        # instruction. Before this date, MultiLangMmsTtsEngine.load() eagerly loaded ALL
        # FOUR of these on every /tts/load call, regardless of which single language a
        # session actually needed -- confirmed a real, avoidable waste (a single-language
        # session never touches 3 of the 4), mirroring the same eager-vs-lazy question
        # already fixed for ASR (models/asr/quantized_multilang_loader.py, 2026-08-09). Real
        # fix: load() is now lazy by default (loads nothing, just marks ready); pass
        # `language=<code>` to eagerly load exactly one -- which is what
        # orchestrator.py's Rule 5 golden-window preload now does once a turn's real target
        # output language is known (see run_agent()'s own docstring), so the real
        # per-language load cost still gets hidden in the agent's downtime instead of
        # landing in the critical path, without paying for the other 3 languages nobody
        # asked for. See RAG-BUILD-LOG.md's TTS section for the fix + real verification.
        #
        # CORRECTED, real GX10 numbers (2026-08-11, isolated in-process test --
        # rag/test_tts_lazy_load.py, no gateway/HTTP layer, no other components concurrently
        # loaded -- NOT yet re-verified on the actual Jetson):
        #   - Loading ONE language: **0.108GB** real RSS delta (confirmed by inspecting the
        #     engine's own resident-language set directly, not just a memory number) --
        #     roughly 13x smaller than the old eager-all-4 cost below, since a real session
        #     only ever needs one.
        #   - Real peak during synthesis of a genuinely long (2397-char) Hindi answer,
        #     chunked (8 pieces) with `_release_chunk_memory()` firing after each: **2.089GB
        #     RSS + 0.180GB VRAM = 2.269GB combined**, confirmed to plateau by chunk 4 and
        #     stay flat through chunk 8 (2.086->2.088->2.089->2.087->2.087->2.088GB) --
        #     bounded growth, not the earlier unbounded-with-answer-length behavior the
        #     chunking fix was originally built to stop.
        #   - **Peak is real-content-length-dependent, confirmed directly, not just assumed
        #     from the old 430-vs-800-char pattern**: a real full-pipeline run through the
        #     actual orchestrator (rag/test_full_turn_memory.py) on a genuine, typical
        #     ~1028-char Hindi answer showed the total pool NEVER exceed its own
        #     steady-loaded value (tts=0.10GB contribution, 3.72GB total pool, before AND
        #     during synthesis -- `_poll_peak()`'s own 0.15s sampling caught zero growth for
        #     this length). So: **2.269GB is a real, genuine worst-case for a long
        #     (2400-char-class) answer; a typical ~1000-char answer shows next to no peak
        #     growth above steady at all.** Neither number is "the" peak on its own --
        #     budgeting for the worst case (2.269GB) is the safe choice, but reporting only
        #     that figure without this context overstates what a typical turn actually costs.
        #   - Growth from steady-loaded to peak-during-synthesis, long-answer case
        #     specifically: ~0.87GB -> 2.089GB RSS, i.e. **~1.22GB real growth**, plus VRAM --
        #     this is the number that actually reflects what the chunking +
        #     `_release_chunk_memory()` effort bought on a genuinely long answer; it's real
        #     and it's bounded, just not quite the ~1.6GB some earlier internal recollection
        #     suggested (that figure wasn't found in any doc when checked directly against
        #     this real measurement -- possibly a different metric or a mid-length answer
        #     between the two real data points above; flagged rather than silently reconciled).
        #
        # The two numbers directly below (steady/peak) are the OLDER, all-4-languages-eager
        # figures -- kept for now since PREDICTED_LOAD_COST_BYTES's pre-flight budget math
        # still reads "tts_steady" as one flat number regardless of language count, and a
        # single-language-aware version of that budget check hasn't been built yet (real gap,
        # not yet closed -- the pre-flight check is currently more conservative than reality
        # post-fix, which is safe direction to be wrong in, just not tight).
        "predicted_load_cost_steady_bytes": 1_470_000_000,
        # 2026-08-14: the gap above just got closed for orchestrator.py's preload_tts() headroom
        # check specifically -- real, confirmed-in-production bug: preload_tts() (Rule 5, meant
        # to hide TTS's ~8-12s cold load by overlapping with the NMT-out downtime) was comparing
        # real available memory against the stale all-4-languages figure above (1.47GB) instead
        # of the real single-language lazy-load cost, so it was skipping every single real
        # preload attempt even when there was genuinely enough room (observed skips at
        # 0.59/1.25/1.34GB real available -- all comfortably enough for the real per-language
        # cost, all rejected anyway). Real measured single-language load: 0.108GB RSS (GX10,
        # rag/test_tts_lazy_load.py) / 0.122GB RSS (this Jetson, direct isolated measurement,
        # 2026-08-13). 250MB keeps real margin over both real measurements while still being
        # ~6x tighter than the stale figure -- used by preload_tts() only, not the two
        # eager-all-4 figures above (still real, still what a genuinely cold multi-language
        # spawn costs, kept for that use).
        "predicted_load_cost_single_language_bytes": 250_000_000,
        "predicted_load_cost_peak_batch3_bytes": 3_700_000_000,  # STALE, see the real 2.269GB
        # GX10 number above -- kept under this key name for PREDICTED_LOAD_COST_BYTES's
        # "tts_peak_batch3" compatibility, batching doesn't apply here (see needs_batching
        # below); scheduled for replacement once a full pipeline run re-confirms 2.269GB
        # (or a different number) end-to-end, not just in the isolated test that found it.
        "default_batch_size": 1,
        "min_batch_size": 1,
        "needs_batching": False,  # VITS: non-autoregressive, single forward pass, no
        # max_new_tokens cap -- confirmed directly that one plain synthesize() call handles
        # a real 883-char multi-paragraph Hindi answer (the same real answer
        # test_streaming_tts_only.py uses) in 1.64s producing 64.78s of audio (RTF 0.025),
        # peak 1.24GB/1.66GB. No chunk_text()/StreamingTTS/batch_size machinery needed.
        "predicted_load_time_sec": 1.8,
        "predicted_unload_time_sec": 0.15,
        # Duration-aware chunk sizing, added 2026-08-08 -- chunk_text()'s own default
        # (max_chunk_chars=180) was tuned as a memory-bounding heuristic (see tts_worker.py's
        # docstring on why mms_tts chunks at all), not for any particular playback duration --
        # confirmed directly it produces ~14s chunks for Hindi (969 chars -> ~75s audio over 6
        # chunks), not the ~30s a streaming caller actually wants for smooth
        # generate-ahead-of-playback pacing. Real measured chars/sec per language (real
        # ASR-transcribed sentences, MmsTtsInferencer.synthesize() on Jetson): hi=12.01,
        # ta=12.47, ml=12.23 -- remarkably close across scripts (~4% spread), but kept
        # per-language rather than one shared constant since they were actually measured
        # separately, not assumed equal. tts_worker.py's mms_tts call sites use this instead
        # of chunk_text()'s bare default; Parler's own chunk_text() usage is untouched (still
        # gets the 180-char default -- this table is mms_tts-specific, doesn't apply there).
        #
        # RETUNED 2026-08-08 (30s -> 15s), then REVERTED 2026-08-09 back to 30s. The 15s
        # detour was a reasonable hypothesis at the time (halving chunk length should halve
        # peak memory) but real isolated testing (isolate_tts_memory_test.py) disproved the
        # mechanism it assumed: TTS's real memory growth comes from the CUDA caching
        # allocator accumulating reserved memory across *distinct chunk shapes* seen in one
        # call, not from any single chunk's own size -- and that growth saturates within the
        # first ~7-9 chunks of a real answer regardless of how long the answer is (confirmed:
        # a 9-chunk realistic answer and a 27-chunk stress-test answer grew almost identically,
        # +1025MB vs +1136MB). Since 15s chunking roughly *doubles* chunk count for the same
        # answer (more distinct shapes to hit that same saturation point, not fewer), it
        # bought nothing on memory -- the qwen3.5:2b retest at 15s hit the same wall as before
        # -- while making a real, audible tradeoff worse: more chunk boundaries means more
        # independent VITS forward passes per answer, each with no prosody continuity across
        # the cut, which is the more likely explanation for reported "flow lost, struggling"
        # audio quality at 15s than the model itself being at fault. The real memory fix that
        # stuck is `_release_chunk_memory()` (tts_worker.py, per-chunk `empty_cache()`), which
        # is independent of chunk duration -- so 30s can be restored for audio quality without
        # giving back the real memory improvement. Real measured chars/sec per language (real
        # ASR-transcribed sentences, MmsTtsInferencer.synthesize() on Jetson): hi=12.01,
        # ta=12.47, ml=12.23 -- remarkably close across scripts (~4% spread), but kept
        # per-language rather than one shared constant since they were actually measured
        # separately, not assumed equal. tts_worker.py's mms_tts call sites use this instead
        # of chunk_text()'s bare default; Parler's own chunk_text() usage is untouched (still
        # gets the 180-char default -- this table is mms_tts-specific, doesn't apply there).
        "chunk_max_chars_by_language": {"hi": 360, "ta": 373, "ml": 366},
        "chunk_target_duration_sec": 30,  # what the numbers above were calibrated against
        "chunk_max_chars_default": 360,  # fallback for any mms_tts-supported language not
        # in the table above (e.g. if preload_languages grows past hi/ta/ml/en) -- close to
        # the three real measurements rather than reverting to chunk_text()'s untuned 180
        # (coincidentally almost identical to Hindi's own 15s-target value).

        # ---- STREAMING (/tts/infer_stream) chunk sizes -- separate from the 30s values
        # above ON PURPOSE. The blocking /infer path keeps 30s chunks: fewer VITS forward
        # passes = better cross-sentence prosody (the real "flow lost, struggling" finding
        # from the 2026-08-09 revert documented above). The streaming path deliberately pays
        # that same prosody tradeoff in exchange for latency: time-to-first-audio is
        # proportional to chunk 0's size alone, so a small first chunk (~80 chars ~= 6-7s of
        # Hindi speech at the measured 12.01 chars/sec) turns ~26s of silence into sound
        # within ~7s. Later chunks use stream_target_chunk_chars (~140 chars ~= 12s audio):
        # big enough that per-chunk overhead and prosody loss stay bounded, small enough
        # that generation keeps reasonably ahead of playback. These are starting values to
        # be TUNED FROM THE [tts-stream] LOG BLOCK's real stall stats, not from theory --
        # see GRAMSAHAYAK_UX.md's streaming section for the TTFA-vs-stall trade each knob
        # controls.
        "stream_first_chunk_chars": 80,
        "stream_target_chunk_chars": 140,
        # Oversize guard: one NMT run-on sentence longer than this gets force-split at
        # secondary punctuation (then word boundaries), because an unbounded sentence would
        # reintroduce exactly the whole-answer-latency problem streaming exists to fix.
        "stream_hard_max_chars": 280,
        # Floor for forced splits: below this a fragment sounds clipped (VITS needs some
        # utterance length for natural prosody).
        "stream_min_piece_chars": 45,

        # ---- Voice consistency across chunks (added 2026-08-23) ----
        # Real incident this block exists for: a streamed Hindi answer measured 122-155 Hz
        # median F0 on chunks 0-2 and 195 Hz on chunk 3 -- audibly a different person.
        # Root cause is architectural, not a bug: VITS samples a fresh latent z and fresh
        # duration noise on EVERY forward pass, unseeded, with no speaker embedding to
        # anchor "the voice" (these checkpoints are mono-speaker, speaker_embedding_size: 0),
        # so every chunk of an answer is an independent draw. Streaming's ~12s chunks make
        # MORE draws per answer than blocking /infer's 30s chunks -- the tradeoff the
        # stream_*_chars block above already documents as "no prosody continuity across the
        # cut", heard here at full strength. Two levers, both in tts_worker.py:
        #
        # 1. noise_scale / noise_scale_s -- applied to the loaded VitsModel around its
        #    forward pass. NOT forward() kwargs: this transformers build's VitsModel.forward()
        #    rejects them outright (real 500s on every TTS call, 2026-08-23) -- they are model
        #    ATTRIBUTES (model.noise_scale / model.noise_scale_duration / model.speaking_rate)
        #    that inference.py's synthesize() sets before forward() and restores after.
        #    Note the attribute for noise_scale_s is named noise_scale_duration on the model --
        #    the config key keeps the HF-forward-style name on purpose. Defaults are
        #    0.667 / 1.0; the values below HALVE both, clustering draws around the model's
        #    mean voice so consecutive chunks agree more. Cost: somewhat flatter prosody.
        #    Initial values chosen by reasoning, not by ear -- tune from real device A/B
        #    before treating them as settled (set either to null to restore the HF default).
        # 2. voice_match_* -- the hard guarantee: each chunk's median F0 (cheap numpy
        #    autocorrelation, tts_worker.py::_chunk_f0_median) must land within tolerance of
        #    the running median of the chunks before it, or it is redrawn up to
        #    voice_match_max_retries times, keeping the closest draw. Chunk 0 is always
        #    accepted as-is -- it IS the reference. At RTF ~0.1 even a fully-retried chunk
        #    (~0.5s/draw) stays far inside its own playback time, so retries don't stall
        #    the stream. voice_match_tolerance=0 disables the matcher entirely.
        "noise_scale": 0.333,
        "noise_scale_s": 0.667,
        "speaking_rate": 1.0,
        # Deterministic seed, applied via torch.manual_seed() before EVERY chunk's forward
        # pass -- the same seed on every chunk makes all chunks share one random sequence
        # (strongest consistency lever), at the cost of identical text -> identical audio.
        # null = unseeded (current behavior, diversity across turns). Never set this while
        # also expecting the voice matcher to have anything to do: same-seed chunks of the
        # same length are near-identical by construction.
        "seed": None,
        "voice_match_tolerance": 0.15,
        "voice_match_max_retries": 2,
    },
    "fastspeech2_hs": {
        # 2026-08-14: added via a real, hands-on GX10 evaluation -- see models/fastspeech2_hs/
        # model_loader.py's own module docstring for the full derivation and every caveat
        # (female voices vendored for 12 languages, Hindi/male as an extra, Maithili has no
        # real checkpoint at all, espnet dependency conflict unresolved, Dravidian vocoder
        # routing untested beyond confirming it loads). Real numbers below are all from
        # that evaluation's live, same-methodology comparison against mms_tts
        # (fastspeech2_bhashini_eval/COMPARISON.md on the dev machine) -- NOT re-measured on
        # Jetson.
        "checkpoint_dir": os.path.join(AGENTS_DIR, "models", "checkpoints", "fastspeech2-hs"),
        # Real, current path on GX10 (the dev machine) -- see gateway.py's _spawn() for what
        # reads this. NOT valid on Jetson or any other machine; this whole engine hasn't been
        # deployed there yet (see model_loader.py's own module docstring). Update this path
        # (or give that machine its own dedicated espnet venv at a different path) before
        # selecting "fastspeech2_hs" anywhere other than GX10.
        "python_executable": "/home/davidacad10/Documents/github/blue-parrot/fastspeech2_bhashini_eval/venv/bin/python3",
        "default_gender": "female",  # 2026-08-14: real bug fix, see models/fastspeech2_hs/
        # model_loader.py's own DEFAULT_GENDER comment -- female is the primary vendored
        # voice across languages of interest now, Hindi/male is the only extra.
        # Real measured RSS after a real /load?language=hindi call through the actual
        # gateway spawn mechanism (fresh process): 1352MB. This is a SINGLE language+gender
        # resident (this engine loads voices lazily per-(language,gender), not eagerly like
        # mms_tts's old all-4 design) -- there's no "all languages eager" figure to report
        # since that was never this engine's design in the first place.
        "predicted_load_cost_steady_bytes": 1_400_000_000,
        # Real bug found and fixed testing this block for the first time (2026-08-14):
        # PREDICTED_LOAD_COST_BYTES["tts_single_language"] unconditionally reads this exact
        # key regardless of which engine is active, so config.py failed to IMPORT AT ALL
        # (KeyError) the moment TTS_ENGINE was switched to "fastspeech2_hs" without it. This
        # engine only ever loads one voice lazily to begin with (no eager-all-languages
        # design the way mms_tts originally had), so there's no smaller "just one more
        # language on top of an already-warm worker" number to report the way mms_tts's own
        # 250MB figure represents -- reusing the steady figure here is the conservative,
        # safe-direction choice (may make preload_tts() skip a preload it could have
        # safely done; better than the reverse).
        "predicted_load_cost_single_language_bytes": 1_400_000_000,
        # Real measured peak RSS after a long (~1300-char/270-word, ~90s audio) real answer,
        # CHUNKED at the real 360-char Hindi budget below (chunking is a hard requirement for
        # this engine, not optional -- see model_loader.py's own docstring point 3: the SAME
        # answer unchunked peaked at 1985MB VRAM alone, ~2.3GB+ combined, a real, measured
        # ~32x-worse number this key deliberately does NOT reflect, since production always
        # chunks). 2.35GB keeps real margin over the measured ~2.3-2.33GB.
        "predicted_load_cost_peak_batch3_bytes": 2_350_000_000,
        "default_batch_size": 1,
        "min_batch_size": 1,
        "needs_batching": False,  # non-autoregressive (FastSpeech2 duration predictor +
        # HiFi-GAN parallel vocoder) -- confirmed directly, same as mms_tts's own VITS.
        # Real measured cold /load (through the actual gateway spawn mechanism, WITH a real
        # language= param -- this engine's load() is lazy-no-op without one, same as
        # mms_tts's): 4.41s. Real measured process-kill unload: 0.72s.
        "predicted_load_time_sec": 4.41,
        "predicted_unload_time_sec": 0.72,
        # Chunking is NOT optional for this engine (unlike mms_tts, where it's more of a
        # memory-bounding hygiene measure) -- see model_loader.py's own docstring point 3.
        # Only Hindi is real-measured/tuned so far; other languages fall back to the same
        # conservative default until individually calibrated the way mms_tts's three were.
        "chunk_max_chars_by_language": {"hi": 360},
        "chunk_target_duration_sec": 30,
        "chunk_max_chars_default": 300,
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
        # 2026-08-07: switched from the multilingual model (indic-conformer-600m-fp32, kept
        # on disk for reference/rollback) to per-language INT8 quantized exports -- see
        # models/asr/indic_quantized_asr.py's module docstring.
        #
        # 2026-08-14: expanded from the original ("hi", "ta", "ml") -- that was a deliberate
        # scope limit, not a technical one ("the only three languages with real audio test
        # fixtures"), and the loader itself was always config-driven (models/asr/
        # quantized_multilang_loader.py takes `languages=` as a plain constructor arg, no
        # hardcoded 3-language assumption anywhere else in the codebase -- confirmed via a
        # real grep sweep). All 12 quantized checkpoints (188MB each, same
        # config.json+<lang>_ctc.int8.onnx+tokens.txt shape as hi/ta/ml) already exist on
        # disk here; this just activates the other 9. Matches MMS-TTS's own Indic language
        # coverage (MMS_TTS_LANGUAGE_NAME_TO_CODE below) exactly for these 12, so English +
        # these 12 = the real, complete set of languages with BOTH real ASR and real TTS --
        # a genuine two-way voice conversation is now possible in all 13, not just 4.
        "checkpoint_dir": os.path.join(AGENTS_DIR, "models", "checkpoints", "indic-conformer-quantized"),
        "languages": ("hi", "ta", "ml", "as", "bn", "gu", "kn", "mai", "mr", "pa", "te", "ur"),
        # 2026-08-14: replaced the old 787MB/2.4s figures -- those were GX10's CPU-only
        # numbers (three languages loaded together, hi/ta/ml) and had already gone stale on
        # Jetson specifically once 2026-08-13's device-conditional provider selection
        # (indic_quantized_asr.py) switched Jetson to CUDA. Confirmed directly (real Jetson
        # hardware, test_asr_12lang_expansion.py, all 12 languages): first language load
        # (cold CUDA context + session build) costs +2.04GB RSS, matching
        # indic_quantized_asr.py's own already-documented "+1.9GB RSS for the CUDA path"
        # measurement almost exactly. Each subsequent language loaded in the SAME session
        # only adds ~350-450MB (context is already built) -- but a real production session
        # only ever loads one language for its whole duration (module docstring, "session's
        # language is fixed"), so the number that matters for Rule 10's preflight "would this
        # fit" check is the cold FIRST-load cost, not the cheaper marginal one. 2.2GB keeps a
        # real margin over the measured 2.04GB. Load time also real-measured cold: 7.09s
        # (vs the old 2.4s estimate) -- subsequent languages in the same session load in
        # ~2.0-2.2s once the CUDA context already exists.
        "predicted_load_cost_bytes": 2_200_000_000,
        "predicted_load_time_sec": 7.1,
        "predicted_unload_time_sec": 0.5,
    },
    "nmt": {
        "port": 11412,
        "module": "workers.nmt_worker",
        "checkpoint_root": os.path.join(AGENTS_DIR, "models", "checkpoints", "indic-trans2-nmt"),
        # 900MB / 2.0s (2026-08-13, was 1.616GB / 0.7s) -- NMTEngine now auto-detects real
        # CUDA support (model_loader.py's _default_device()) instead of hardcoding "cpu", so
        # these need to reflect the CUDA footprint, not the old CPU one. Real, isolated
        # measurement (both en-indic + indic-en loaded, one real inference call to force any
        # lazy CUDA workspace allocation, on the actual Jetson checkpoint): 858MB delta --
        # 900MB keeps a small real margin. CUDA is not just faster than the old CPU-mode
        # figure, it's genuinely SMALLER too (old 1.616GB was real CPU-mode RSS for both
        # directions) -- not a speed/memory tradeoff, a real win on both axes for this
        # component specifically. Load time: measured 0.58s-4.12s across several real cold
        # loads (cache-state dependent) -- 2.0s is a conservative real estimate, not the old
        # 0.7s CPU-load figure (kept from before this fix, since this hadn't been
        # re-measured for CUDA yet -- unload time below is likewise still the old CPU-mode
        # figure and needs the same re-verification once CUDA unload is observed live).
        "predicted_load_cost_bytes": 900_000_000,
        "predicted_load_time_sec": 2.0,
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
    # Real single-language lazy-load cost (2026-08-14) -- see WORKERS["tts"]'s own comment on
    # this key for the real bug this fixes (preload_tts()'s headroom check was using the much
    # larger eager-all-4-languages "tts_steady" above, rejecting real, genuinely-safe preloads).
    "tts_single_language": WORKERS["tts"]["predicted_load_cost_single_language_bytes"],
    # Real size_vram for qwen3.5:2b at num_ctx=32768, read directly off Ollama's /api/ps on
    # Jetson (2026-08-14, with OLLAMA_FLASH_ATTENTION=1 + OLLAMA_KV_CACHE_TYPE=q8_0 now set in
    # ollama.service, real GPU-resident measurement, not estimated): 2,662,565,148 bytes.
    # (Prior figure, same num_ctx, BEFORE explicit KV-cache quantization: 2,561,901,852 bytes --
    # confirmed directly this real model+context combo does NOT get a meaningful VRAM win from
    # q8_0 KV-cache quantization; model weights dominate this small 2.3B model's footprint far
    # more than KV-cache does, unlike larger models/longer contexts where q8_0 KV-cache
    # quantization's usual "~halves KV-cache memory" claim actually moves the total. Kept
    # anyway -- no real downside, and flash-attention is now explicitly forced on rather than
    # relying on Ollama's own "auto" default.) Prior num_ctx=16384 figure, kept for reference:
    # 2,438,316,685 bytes -- doubling context only cost ~124MB real, see OLLAMA_NUM_CTX's own
    # comment above for why. qwen3.5:0.8b's own figure at 16384, for reference if
    # OLLAMA_MODELS[0] changes again: 1,164,758,219 bytes, measured 2026-08-11. Keep this in
    # sync with whichever model+num_ctx combo is actually active -- this number is specific to
    # both (see the qwen3.5:0.8b num_ctx comment above showing the 5.475GB idle-KV-cache case
    # at default context_length, i.e. what happens if num_ctx isn't passed explicitly).
    "agent": 2_662_565_148,
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

# TTS stay-resident policy (2026-08-21): keep the TTS worker loaded between turns
# instead of unloading at every 'turn complete'. Unloading cost a real ~15s reload per
# turn on Jetson. With agent+ASR+NMT all resident there is still real headroom for TTS.
TTS_STAY_RESIDENT = True

MODEL_BUDGET_BYTES = 7_000_000_000
COMPLEMENTARY_PAIRS = [("asr", "tts")]
