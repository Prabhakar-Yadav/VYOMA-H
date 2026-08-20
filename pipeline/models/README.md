# pipeline-models — the exact models for the full-pipeline test

Everything needed to run **voice/image → ASR → NMT → RAG → voice** offline, in
one folder, so the same weights are used in the test as on the device. Kept
separate from `bhashini-eval/` (which is benchmarking scratch) and gitignored.

```
pipeline-models/
  ai4bharat/indic-conformer-600m-multilingual/   ASR, 22 languages  (~2.5 GB)
  nmt/indicTrans2/checkpoints/
      indic-en/       farmer's language -> English   (the RAG only sees English)
      en-indic/       English -> farmer's language   (for the spoken reply)
      indic-indic/    not used in this pipeline
  tts/                <- awaiting your model choice
```

## Why these two are fixed already

**ASR — IndicConformer 600M.** Measured against every viable alternative on 400
FLEURS utterances: it wins or ties everywhere, covers all 22 languages, and runs
CPU-side ONNX so it takes no GPU. RNNT decoding, which measured better than CTC
on every language we tested.

**NMT — IndicTrans2.** This is what Bhashini already ships, unchanged. It kept
0.86 semantic similarity against Gemini's 0.89 on 50 farmer turns at 0.09 s per
turn with no network, so there was no case for replacing it.

## TTS is deliberately empty

Two candidates are measured and ready; the choice is yours:

| | Size | Speed | Round-trip WER (named speakers) |
|---|---|---|---|
| **indic-parler-tts int4** (David's) | 0.88 GB load, 1.78 GB peak | rtf 0.70 on a 5090 | or 6.2, kn 8.3, ml 9.1, hi 11.1 |
| **FastSpeech2_HS** | ~0.4 GB, per language | rtf 0.06–0.12 | pa 0.0, kn 16.7, gu 25.0, hi 27.8 |

Tell me which and it lands in `tts/` with a loader wired into the pipeline
script.

## The one thing worth knowing before running the pipeline

**The RAG only ever sees English.** Speech is transcribed in the farmer's
language, translated to English, and only then does retrieval happen; the answer
is translated back for TTS. Every RAG test we have — 54 core, 99 cluster, 16
deficiency — is written in English for exactly this reason.

That means a pipeline failure can come from four different places, and the
per-stage output is what tells them apart:

```
ASR wrong   -> transcript is wrong Hindi
NMT wrong   -> transcript fine, English wrong (measured: ~8% of turns lose a term)
RAG wrong   -> English fine, wrong condition or wrong dose
TTS wrong   -> answer correct, audio unintelligible
```

`run_pipeline.py` prints all four so a failure can be attributed rather than
guessed at.
