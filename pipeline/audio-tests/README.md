# Pipeline test set — 40 real farmer voice queries

Real audio, real human transcripts, nothing written by us.

**Source:** [DigiGreen/Agri_STT_Benchmarking_Dataset](https://huggingface.co/datasets/DigiGreen/Agri_STT_Benchmarking_Dataset)
— 10,808 smallholder farmers speaking questions to Digital Green's Farmer.Chat
advisory line, transcribed by human annotators. CC-BY-4.0. Nothing is read from
a script or recorded in a studio.

40 Hindi clips selected from 4,576, filtered to what **our plant-disease RAG**
is supposed to answer. Government scheme questions were deliberately excluded —
those belong to Palak's engine and get tested separately.

```
audio/01.ogg .. audio/40.ogg    the clips
manifest.json                    reference transcript + expected behaviour per case
run_audio_tests.py               the runner (prepared, not yet run)
hindi.csv                        the full source index, kept for reselection
```

## Why this matters more than what we have measured so far

Every RAG number to date came from queries **I wrote**. Every ASR number came
from **FLEURS**, which is news prose read aloud in a studio. Neither is a
farmer.

These are farmers. The speech is hesitant, regionally accented, and often
grammatically loose — *"आलू की खेती बहुत मुरझाया हुआ है उसका पत्ता"*. Some
questions are half-formed. One clip is partly unintelligible even to the human
annotator.

**Expect worse numbers than we have been quoting, and treat those as the honest
ones.**

## What the 40 cover

| Category | n | What it tests |
|---|---|---|
| covered_crop_disease | 7 | the main path — potato blight, rice blast, real diagnoses |
| pest_insect | 6 | brinjal borer, mango pests, maize insects |
| **deficiency_like** | 5 | wheat yellowing — **must not get a pesticide** |
| **deficiency_khaira** | 2 | rice/wheat khaira — asked by name, it is zinc deficiency |
| nutrient_question | 3 | "should I give zinc" — we carry no fertiliser doses, must refuse |
| open_ended_vague | 5 | "which disease affects wheat" — too little to diagnose |
| uncovered_crop | 2 | banana, tea — outside coverage, must defer |
| out_of_scope | 9 | irrigation, fertiliser rates, animal care, profit arithmetic |
| garbled_asr_input | 1 | the annotator could not fully make it out either |

The bias toward refusal cases is deliberate. Roughly half of what a real farmer
asks is **not** a disease question, and answering those anyway is how a device
loses trust.

Note two clips ask about **khaira** by name — that is the Hindi name for zinc
deficiency, the exact condition that made the device prescribe copper
oxychloride before the deficiencies corpus existed. Real farmers use that word,
which is the best possible evidence the corpus was needed.

## Running it (when flagged)

```bash
python run_audio_tests.py              # all 40
python run_audio_tests.py --limit 5    # smoke test
python run_audio_tests.py --reply      # also translate the answer back to Hindi
```

Every stage prints separately so a failure can be **attributed** rather than
guessed at:

```
ASR   transcript vs human reference -> WER/CER   (the in-between accuracy check)
NMT   the English the RAG actually receives
RAG   route, outcome, condition, label_id, spoken answer
TTS   once a voice is wired in
```

A case can pass ASR and fail RAG, or fail ASR and still reach the right answer
because retrieval survives a mangled word. Both are worth knowing and neither is
visible from the final audio.

## The one automatic check

Most of these need a human to read the answer and judge it. One property is
machine-checkable and it is the important one:

> **A deficiency, nutrient, out-of-scope or uncovered-crop question must never
> come back with a pesticide.**

The runner flags any such case `UNSAFE` and exits non-zero. Everything else is
printed with its `expect` and `must_not` for a human read.
