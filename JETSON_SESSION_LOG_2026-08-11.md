# Jetson multi-turn stress test + performance session — 2026-08-11/12

Real findings and decisions from the overnight Jetson (`vaultstackai`, tailscale IP
100.118.21.46, tegra R36.4.2, Orin Nano devkit — 7W/15W/MAXN power modes, no MAXN_SUPER)
session. Written so GX10 and Jetson never drift apart on what was actually decided and why.
GX10's `gramsahayak/` tree is the source of truth for all code in this doc — every change below
was made locally first, then `scp`'d to Jetson and diff-verified, confirmed via a real `rsync
-avzc --dry-run` pass at the end (no code drift, only model-checkpoint binaries and directory
mtimes differ, which is expected and fine).

## 1. RAG + lazy-loading fixes moved to Jetson and stress-tested

- Real RAG tools (`g1_rag_tools.py`, `g2_rag_tools.py`, `datasets/rag/{g1,g2}.sqlite`) synced
  and confirmed working standalone on Jetson.
- ASR (`models/asr/quantized_multilang_loader.py`) and TTS (`models/mms_tts/model_loader.py`)
  lazy per-language loading confirmed via real RSS measurements on Jetson, not just GX10.
- `granite-embedding:30m` forced CPU-only (`rag/embed.py`'s `CPU_ONLY_OPTIONS`) — was silently
  paying a multi-GB CUDA-context tax for a ~30MB model.
- `api_server/orchestrator.py`: added `real_available_bytes`/`real_used_bytes` (from
  `psutil.virtual_memory()`) to every budget decision (Rule 5/6/10), not just the synthetic
  tracked total — the tracked total alone was blind to real system pressure.
- `run_tts(evict_nmt_first=True)` — now the default, after a real confirmed crash (Malayalam
  turn 1) traced to NMT/embedder sitting resident through TTS's own peak memory window.
- Real, confirmed GPU contention between Ollama (llama.cpp/CUDA) and PyTorch/TTS on Jetson's
  single shared GPU — TTS load stalled 60s+ concurrent with real agent generation. Fixed by
  moving the TTS golden-window preload trigger from Agent-generation-time to NMT-out-time
  (`orchestrator.preload_tts()`), plus fixing a bug where ASR being still-resident blocked that
  preload from ever firing.

## 2. Real agent prefix-cache warmup (`agent/warmup.py`)

`warmup_agent()` runs one throwaway `ollama.chat()` call with the real `SYSTEM_PROMPT`+`TOOLS`
prefix at session start (`keep_alive=-1`), landing that ~5700-5900 token prefix in llama.cpp's
prompt cache before the farmer's first real turn. **Confirmed working correctly, not assumed** —
traced real `journalctl` per-call `prompt_eval` numbers on 2026-08-12: the warmup call itself
pays the full cold prefill (~4.6-4.8s for ~5800 tokens), and every real call afterward — across
the whole session, not just the first — shows a fast, small, LCP-similarity-matched incremental
prefill (474-1137ms for only the new tail tokens). This holds up call-to-call throughout a whole
turn's internal tool-calling loop, not just turn 1's first call.

## 3. Turn 1's real slowness — root-caused, not fixed by any infra lever

Ruled out, with real evidence, in order tried:
- **Decode TPS**: not the cause — turn 1's tokens generate at the same steady per-token rate as
  every other turn.
- **`GGML_CUDA_ENABLE_UNIFIED_MEMORY=1`**: tested directly, no measurable difference. Left set
  (harmless) but not the fix.
- **Prefix-cache warmup not working**: checked directly via real `journalctl` timing (section 2
  above) — it works correctly. Ruled out.
- **llama.cpp checkpoint/context-reprocessing bug** (real, documented issue for Qwen 3.5's
  hybrid architecture, ggml-org/llama.cpp#20225): checked our own logs for the exact smoking-gun
  message (`"forcing full prompt re-processing due to lack of cache data"`) — zero occurrences
  in any of tonight's real pipeline runs. The `"erasing context checkpoint too close to an
  earlier one"` messages we DO see are benign slot-table housekeeping after a successful cache
  hit, confirmed by cross-referencing one directly against its own fast prefill time. Ruled out
  for our actual workload.
- **The image**: tested directly by moving the image to turn 2 (`--image-turn` flag on
  `test_orchestrated_pipeline.py`). Turn 1 without an image was faster than turn-1-with-image
  (199.24s vs 272.08s) but still much slower than steady-state turns (~70-130s) — so the image
  adds real cost on top, but isn't the root cause on its own.

**Real root cause, found via real per-call `journalctl` tracing (2026-08-12)**: turn 1 routinely
makes 4-5 separate LLM round-trips (tool call → result → next call) where a normal follow-up
turn makes only 1-2. Each round-trip pays its own real ~13-25s generation cost even at MAXN
speed — that's the actual multiplier, not any one call being unusually slow. Caught a concrete
instance: `pesticide_usage_and_dose` called twice in the same real turn, second time with a
hallucinated disease label ("Potato early blight") contradicting the turn's own first-call
diagnosis ("Potato late blight") — a real violation of `SYSTEM_PROMPT`'s existing "AT MOST ONCE
per turn" rule.

**Fix applied**: strengthened `agent/prompts.py`'s wording (not a code-level block — deliberately
rejected a hardcoded "block any repeat call to this tool name" guard as too brittle, since a
tool can legitimately need calling again with genuinely different, valid arguments; this was
about trusting the model to actually follow its own stated rule, not about mechanically
preventing all repeats). New wording explicitly calls out the actual failure mode: seeing
another condition/disease name mentioned inside a tool's own result text is not a reason to
re-query with that name.

## 4. Model choice: settled on `qwen3.5:2b`, not `qwen3.5:0.8b`

Real controlled decode-TPS bench (same system_prompt+tools prefix, same question, num_ctx=16384,
think="medium", full eviction between models):

| Model | Gen TPS (15W) | VRAM | Tool call |
|---|---|---|---|
| qwen3.5:2b | 15.2 tok/s | 2.4GB | correct |
| gemma4:e2b-it-qat | 14.7 tok/s | 1.8GB | **wrong** (called `analyze_photo` on a photo-less question) — ruled out |
| qwen3.5:0.8b | 23.6 tok/s | 1.16GB | correct |

0.8b looked like the win on raw TPS alone, and a real 5-turn Hindi run (`hindi_v8`) confirmed a
real ~25% steady-state speedup over 2b (turns 2-5) — but two things changed the decision:

1. **MAXN power mode closed the gap.** `nvpmodel -m 2` + `jetson_clocks` took 2b's own decode
   speed from 15.2 → 25.0-25.1 tok/s (+64%, confirmed both in an isolated bench and in a real
   live pipeline run `hindi_v9` — every non-first turn 40-55% faster than the matched 15W run).
   Once MAXN is in the picture, 2b's real generation speed is *above* 0.8b's own 15W number, so
   the entire reason to trade down to 0.8b evaporated.
2. **A real accuracy data point favored 2b.** 0.8b's image-based diagnosis of the sample potato
   photo got the disease wrong ("Potato Black Scurf"); 2b's plain-text diagnosis of the identical
   symptom description correctly said "Potato late blight" (the photo's actual real condition).
   One data point, not exhaustively tested — but real, and with no offsetting TPS reason left to
   prefer 0.8b, it tipped the decision.

**Final: `config.py`'s `OLLAMA_MODELS = ["qwen3.5:2b", "granite-embedding:30m"]`, MAXN power mode
left on permanently** (real GPU clock 612MHz → 1020MHz; one real cost observed: `real_avail`
memory dipped to ~1.1-1.35GB mid-turn with 2b's bigger 2.44GB footprint under MAXN — still
positive headroom throughout every test, but worth a longer soak-test at some point for thermal
throttling, not done tonight).

## 5. Tried and found NOT to help

- **`--mlock` via a Modelfile variant** (`PARAMETER use_mlock true`): Ollama 0.32.6 prints
  `"parameter use_mlock is deprecated"`, and confirmed directly — via the loaded process's real
  `/proc/<pid>/status` (`VmLck: 0 kB`) and its actual `llama-server` command line (no `--mlock`
  flag present at all) — that it's a genuine no-op on this version, not just a soft warning.
  Deleted the resulting model tag rather than keep a variant that provides nothing.
- **`keep_alive` tuning**: already correct everywhere before this session touched it — every real
  load call already used `keep_alive=-1` (`agent.py`, `warmup.py`, `gateway.py`'s `/agent/load`,
  `photo_analysis.py`), and the orchestrator's own deliberate unloads already use `keep_alive=0`
  explicitly. Ollama's own idle-timeout auto-eviction was never in play. No code changed for this.
- **Explicit `OLLAMA_FLASH_ATTENTION=1`**: not needed — confirmed via real logs that leaving it
  unset already resolves to enabled (`--flash-attn auto` → `flash_attn = enabled` in practice,
  and separately forced-on anyway by the existing q4_0 KV-cache quantization).
- **Disabling KV-cache quantization to isolate flash-attention's own effect**: considered, not
  done — would cost real VRAM headroom on this memory-constrained board for an unclear payoff,
  since FA is already confirmed enabled either way.

## 6. Diagnostic tooling added (`test_orchestrated_pipeline.py`)

- `--image-turn N`: moves the sample image to turn N instead of the default turn 1, AND swaps
  which turn's pre-recorded text+audio plays at position 1 vs position N — added after finding
  the agent silently skips `analyze_photo` if the image's turn doesn't have matching spoken
  content (a real bug: turn 2's original dosage-follow-up audio says nothing about a photo, so
  the model never called the tool even with an image attached).

## 7. Final validation runs, all 3 languages, full fix set (2b + MAXN + strengthened prompt)

Re-ran `hindi_v10` (crashed from my own concurrent `rsync` dry-run against the same Jetson
device mid-test — self-inflicted contention, not a real pipeline bug; don't run parallel heavy
Jetson SSH/rsync operations during an active stress test) as `hindi_v11`, clean this time, plus
fresh Tamil (`ta_v1`) and Malayalam (`ml_v1`) runs. All three completed all 5 turns with no
crash, no OOM, memory returning to the same ~1.3GB idle baseline after every run. Output audio +
full run logs copied to `gramsahayak/audio-results/{hi,ta,ml}/` on GX10.

**Real, important finding from `hindi_v11`'s audio-swap turn 2 (the properly-isolated
image-cost test)**: the strengthened once-per-turn prompt wording did NOT reliably hold. That
turn made 5 tool calls total (`analyze_photo`, `plant_disease_lookup` x2, `pesticide_usage_and_
dose` x2), retrying both RAG lookups with reworded arguments after the first `plant_disease_
lookup` call returned a wrong "healthy plant" match — exactly the anti-pattern the strengthened
wording was meant to prevent. This pushed the turn to `agent.py`'s `max_tool_iterations=5` cap,
which triggered a genuinely serious NEW bug: the turn's final fallback call returned **completely
empty content** (`*** WARNING: agent returned EMPTY content this turn`), the same empty-content
failure class `config.py` had only previously documented for `think="low"`, now confirmed
happening under `"medium"` too in this specific redundant-call-cascade scenario. Real downstream
consequence: `real_avail` memory dropped to 0.54GB (the lowest seen all night) because the
empty-content path skipped the normal turn-complete TTS eviction, leaving TTS resident an extra
turn — recovered cleanly on the next turn's completion, but this is a real, not-yet-fixed
mechanism for turning "the model retried a tool call" into "a farmer gets silence AND memory
pressure climbs." **This needs a real fix, not just the prompt wording** — worth revisiting the
rejected code-level dedup approaches (the "soft reminder in tool result" option specifically) or
addressing the `max_tool_iterations` fallback path directly so it can't return empty.

Per-turn totals, all three languages (turn 1 = image turn for ta/ml; hi's turn 1 was the
audio-swapped no-image case, turn 2 carried the image instead — see section 6):

| Turn | Hindi (`hindi_v11`) | Tamil (`ta_v1`) | Malayalam (`ml_v1`) |
|---|---|---|---|
| 1 | 76.26s (no image) | 254.00s (+image) | 221.03s (+image) |
| 2 | 173.67s (+image, empty-content bug above) | 89.21s | 107.71s |
| 3 | 72.91s | 75.37s | 75.68s |
| 4 | 72.70s | 108.52s | 79.27s |
| 5 | 76.47s | 84.02s | 71.19s |

Steady-state turns (excluding both image-bearing turns and the empty-content anomaly) land
consistently in the ~70-110s band across all three languages — the MAXN + model-choice work
generalizes across languages, not just Hindi. Real ASR/NMT transcription-accuracy misses also
showed up independently in Tamil and Malayalam this run (e.g. Malayalam's "spray" mistranslated
as "crack", Tamil's "potato" as "peanut") — not related to tonight's fixes, flagged as a
separate, real accuracy gap worth investigating later.
## 8. num_ctx bumped 16384 -> 32768, re-validated (`hindi_v12`)

Real measured cost of doubling context: qwen3.5:2b's size_vram went from 2.4383GB to 2.5619GB —
only ~124MB more, far gentler than the num_ctx=262144-default case (5.475GB) documented above.
Safe to make the change. Ran a full 5-turn Hindi validation (`hindi_v12`, image-turn-2, same
fixes as `hindi_v11`) to confirm nothing broke: all 5 turns completed, no crash, memory returned
to the same ~1.3GB idle baseline afterward.

**The redundant-tool-call/empty-content bug from section 8 reproduced again, with new detail**:
turn 2 (the image turn) made the same 5-tool-call pattern -- `analyze_photo`, `plant_disease_
lookup` x2, `pesticide_usage_and_dose` x2 -- but this time one of the `plant_disease_lookup`
repeats used the SAME exact arguments as an earlier call (not just reworded), and the two
`plant_disease_lookup` calls landed on two DIFFERENT, contradictory diagnoses ("Potato early
blight" then "Potato late blight") within the same turn. Turn cost 269.19s, the longest of the
whole night. Real silver lining: this time the turn did NOT hit the empty-content failure --
it produced a real, correct final answer. Also a good real confirmation of the orchestrator's
own protective behavior under pressure: with `real_avail` down to 1.47GB, it explicitly skipped
the speculative TTS preload (`"skipping tts preload -- only 1.47GB available"`) rather than risk
overcommitting, and TTS still loaded and ran successfully once actually needed.

Per-turn totals, `hindi_v12` (32768 ctx) vs `hindi_v11` (16384 ctx), both audio-swapped so turn 1
has no image and turn 2 does:

| Turn | `hindi_v11` (16K) | `hindi_v12` (32K) |
|---|---|---|
| 1 (no image) | 76.26s | 87.31s |
| 2 (+image, redundant-call turn) | 173.67s (empty-content bug) | 269.19s (real answer, no bug) |
| 3 | 72.91s | 90.74s |
| 4 | 72.70s | 76.03s |
| 5 | 76.47s | 78.43s |

Non-image turns are consistently a bit slower at 32K (roughly +5-18s) -- plausible real cost of
the larger KV cache/attention computation over more context, not free even though the *memory*
cost is small. Worth keeping in mind: 32K isn't a strictly-better free upgrade on speed, it's a
real headroom-vs-latency tradeoff, traded specifically to reduce context-overflow risk from the
still-unfixed redundant-tool-call bug. The bug itself needs a real fix regardless of context size.

## 9. RAG tool coverage gap closed: `get_guidelines_and_safety` added, `get_treatment_details` renamed + boost bug fixed

Real cross-tab of `datasets/rag/g1.sqlite`'s `concept_type`/`source_type` columns found 60
chunks (12 concepts: 53 "Practice Guidance"/govt_guideline + 7 "Safety Guidance"/safety, incl.
the real "spray-safety" concept) that no tool reached on purpose -- `plant_disease_lookup`/
`plant_entomology_lookup` could stumble onto it unboosted at best, and the old
`pesticide_usage_and_dose`'s `concept_types={"Treatment"}` filter excluded it outright. New
tool `get_guidelines_and_safety(query, crop=None)` added with that exact concept_type filter,
real-tested against the actual DB (returns "Safe Pesticide Handling -- official Do's and
Don'ts" etc. for a real safety query).

Also found and fixed a real, separate bug while investigating: `pesticide_usage_and_dose`
(renamed `get_treatment_details`, same tool) boosted the smaller 42-chunk generic-chemical
`source_type="treatments"` slice over the larger, more relevant 129-chunk crop+disease-specific
`source_type="pesticide_label"` slice -- backwards from the tool's own stated purpose ("how
much do I use and when can I harvest"). Boost removed entirely, both slices now compete at
equal weight. Real-tested: a potato-late-blight query now correctly ranks the crop-specific
"Cymoxanil 8% + Mancozeb 64% WP for potato late blight" record appropriately instead of being
suppressed relative to the generic slice.

Renamed/added across `agent/tools/g1_rag_tools.py`, `agent/agent.py` (import, TOOLS schema,
dispatch table), `agent/prompts.py` (SYSTEM_PROMPT tool references + new usage guidance for
the safety tool) -- confirmed importing cleanly and registering all 15 tools (was 14) on
Jetson, not just GX10.

**Deliberately NOT done**: splitting `get_treatment_details` further into separate
disease→treatment-class→dose tool calls, as originally considered -- the underlying data
doesn't cleanly support that split (both slices are pesticide/product-level, just different
granularity, not "general recommendation" vs "specific dose"), and every extra tool call is a
real ~15-25s cost given section 7-9's confirmed, unresolved tool-call-reliability problem.
Also found, while fixing this: an earlier (pre-tonight) session already discovered and
partially addressed the same redundancy problem (see RAG-BUILD-LOG.md Β§5's own "AT MOST ONCE
per turn" prompt-fix attempt, dated before this session) -- confirms this is a longstanding,
still-open issue, not something newly introduced tonight.

## 10. Known open items, not yet actioned

- Longer MAXN soak test for thermal throttling not done.
- **The redundant-tool-call / empty-content bug (section 8) is the most important open item.**
  Reproduced twice now (`hindi_v11`, `hindi_v12`), confirmed NOT fixed by: the strengthened
  prompt wording, larger context, MAXN power mode, or model choice. A real code-level fix was
  discussed and deliberately deferred (see section 8's own text) -- rejected a blunt "block any
  repeat call to this tool name" guard as too brittle (legitimate different-argument re-calls
  exist); options considered but not yet built: a soft in-tool-result reminder on repeat calls,
  or exact-duplicate-only detection (which WOULD have caught `hindi_v12`'s literal repeat call).

