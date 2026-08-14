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
OLLAMA_MODELS = ["qwen3.5:2b", "granite-embedding:30m"]
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
OLLAMA_NUM_CTX = 8192 * 4

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
MODEL_BUDGET_BYTES = 7_000_000_000
COMPLEMENTARY_PAIRS = [("asr", "tts")]
