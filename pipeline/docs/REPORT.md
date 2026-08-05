# Bhashini stack testing — NMT, TTS, and an ASR defect found along the way

Prabhakar | 1 August 2026

Covers the three items assigned: NMT accuracy against a commercial model, TTS
voice quality, and ASR alternatives.

NMT and TTS were measured on a laptop CPU, which is the honest place to test
them — both have to run on a Jetson eventually. The GPU server came online part
way through and was used for Veena, which cannot run on CPU.

Everything is reproducible. Scripts and data are in `bhashini-eval/`.

---

## The short version

| | Finding | What to do |
|---|---|---|
| **NMT** | Good enough. It loses technical terms, but the RAG's gates absorb the damage and it never produced wrong advice. | Keep it. Do not add a cloud dependency. |
| **TTS** | Flite is the weak link. Piper is nearly as good as a 3B model at 1/100th the cost, and is already in our codebase. | Switch the Indic path to Piper. Veena was tested and does not fit the device. |
| **ASR** | **Found a bug.** The decoder is throwing away a third of the model's vocabulary. | Fix before evaluating any replacement. |

The ASR item was not on the list. It surfaced while testing TTS and it is the
most consequential thing in this report.

---

## 1. NMT accuracy

### How it was tested

Bhashini's NMT is IndicTrans2 quantised to int8 and served through CTranslate2.
On the device it runs behind an HTTP service on CUDA; here the same checkpoints
are loaded straight off disk on CPU. Same weights, same tokeniser, same
preprocessing, so translation quality is identical — only speed is not
comparable.

50 Hindi sentences, written specifically for this device rather than taken from
a generic benchmark. That choice matters. A translator can score well on news
text and still drop "Mancozeb", and a corpus-level BLEU score will not show it.

So the headline metric is **term retention**: of the 162 terms that must survive
into English for the RAG to work — crop names, product names, numbers,
negations — how many actually did. BLEU and chrF are reported alongside as
context, not as the verdict.

Categories: symptom descriptions, crop plus disease, pesticide products, doses
and waiting periods, safety and poisoning, government schemes, negations, and
five ordinary non-farm sentences as a control.

### Results

**A caveat first.** Gemini's free tier ran out of daily quota after 19 of the 50
sentences, on both API keys. I have not forced past it. So Bhashini is measured
on all 50, and the head-to-head is measured on the 19 both translated — which
covers symptom, crop and product sentences, but **not** the number, negation,
safety or scheme categories. Treat the head-to-head as indicative, not final.

**Bhashini across all 50 sentences — 149 of 162 terms kept, 92.0%**

| Category | Terms kept | |
|---|---|---|
| scheme | 13/13 | 100% |
| control (non-farm) | 17/17 | 100% |
| number | 20/21 | 95% |
| safety | 15/16 | 94% |
| crop | 22/24 | 92% |
| symptom | 33/37 | 89% |
| product | 20/23 | 87% |
| **negation** | **9/11** | **82%** |

13 of the 50 sentences lost at least one critical term.

The shape is informative. Ordinary language is perfect — all five control
sentences, every scheme name, almost every number. **What degrades is exactly
the specialist vocabulary**, and the worst category is negation, which is also
the one the RAG can least afford to lose.

**Head-to-head on the 19 sentences both translated**

| | Term retention | chrF | BLEU | sec/sentence |
|---|---|---|---|---|
| Bhashini | 57/63 — 90.5% | 65.6 | 42.4 | **0.13 s** |
| Gemini 3.6 Flash | 62/63 — 98.4% | 78.6 | 54.2 | 3.30 s |

Gemini is better. It is also 25× slower on this measurement and requires a
network connection the device does not have.

### What Bhashini gets wrong

The errors are consistent and they are all of one type: **technical vocabulary
gets translated into everyday vocabulary, or into the wrong technical term.**

| Hindi | Should be | Bhashini said |
|---|---|---|
| उकठा रोग (wilt) | wilt disease | **Urticaria** — a human skin condition |
| झुलसा रोग (blight) | blight | **scabies** |
| सफेद फफूंद | white fungus | white mildew |
| अंगूर की बेल | grape vine | "the vine" — crop name dropped |
| डाइफेनथाइयूरॉन | diafenthiuron | diphenthyuron |
| एमामेक्टिन | emamectin | Amamectin |

Fluency is fine. Grammar is fine. Numbers survive. What degrades is precisely
the vocabulary the RAG matches on.

### Does it actually matter? The end-to-end test

Term retention says which words were lost. It does not say whether losing them
changed the farmer's answer. So each translation was fed through the actual
Krishi RAG and compared against what a perfect translation produces.

36 diagnosable cases. Graded on whether a dose was actually given, and whether
it was the same one.

| | Bhashini (36) | Gemini (19) |
|---|---|---|
| Same answer as a perfect translation | **28/36 — 78%** | 17/19 — 89% |
| SAME — identical condition and chemical | 11 | 7 |
| SAFE_DIFF — neither gave advice | 17 | 10 |
| LOST — refused where it should have answered | 5 | 1 |
| GAINED — answered where it should have refused | 3 | 1 |
| **WRONG — different disease or different chemical** | **0** | **0** |

**The important column is WRONG, and for Bhashini it is zero.**

Bhashini's translation errors never caused the device to name a different
disease or a different chemical. When a term degrades, the query gets vaguer,
the relevance score drops, and a gate abstains. The failure mode is the device
saying "I am not sure, ask your Krishi Vigyan Kendra" — which is the correct
behaviour, just less useful.

That is not luck. It is the abstention gates doing what they were built for. A
translator that degrades into vagueness is exactly the input that design
handles well.

### Recommendation

**Keep Bhashini NMT.** Gemini is measurably better at technical vocabulary, but:

1. Gemini needs the internet. The device is offline by design. It could never
   ship as the translator, so this comparison measures a ceiling, not a
   candidate.
2. The measured gap does not turn into wrong advice. It turns into extra
   refusals.

If we want to close the gap without giving up offline operation, the cheap fix
is a **glossary layer**, not a bigger model: a lookup table applied after
translation that maps the ~60 agricultural terms we care about onto their
correct forms. "Urticaria" is a deterministic, repeatable error on a closed
vocabulary. That is a dictionary problem, not a model problem, and it is a day
of work against a corpus we already have.

---

## 2. TTS quality

### Veena was tested, and it is the best-sounding and the wrong choice

Veena was run properly on the GPU server (RTX 5090, 24 GB) in bfloat16 — that
is Veena at its best, so the "is it worth it" question is answered against the
good version, not a degraded one. All 12 sentences generated.

| | Veena 3B | Flite (current) | Piper |
|---|---|---|---|
| Languages | **Hindi + English only** | 8 Indian | 7 Indian |
| Size on disk | ~6 GB bf16 (~1.7 GB at 4-bit) | ~250 MB all voices | **64 MB per voice** |
| Memory in use | **7.65 GB VRAM** | tens of MB | tens of MB |
| Hardware | **GPU required** | CPU | **CPU** |
| Speed | **1.21× real time on an RTX 5090** | fast | **0.06× real time on a laptop CPU** |
| Licence | Apache 2.0 | permissive | MIT |

**Read the speed row twice.** On one of the fastest laptop GPUs available,
Veena takes 4.9 seconds to produce 4.0 seconds of audio. It is slower than real
time on an RTX 5090. Piper produces the same length of audio in 0.23 seconds on
a **CPU**.

The Jetson Orin Nano is a small fraction of a 5090, and its 8 GB is shared
across the whole pipeline — the VLM, the LLM, ASR and NMT all need a share.
Veena alone wants 7.65 GB. It does not fit, and even if it did, a farmer would
wait a very long time for one sentence. I have not benchmarked it on the Jetson,
so treat the exact factor as an estimate; the direction is not in doubt.

And it speaks two languages. For a device whose whole premise is reaching
farmers in their own language, replacing an 8-language engine with a
2-language one is a step backwards regardless of how good it sounds.

### Piper is already in our codebase

While reading the device code I found `pocketinfer/models/piper.py`. It exists,
it is wired up, and `hear_the_world.py` already loads it — with an **English**
voice. The Indic path calls Flite instead. Line 166 is literally:

```python
# self.piper.start_playback(result)
```

Commented out. So there is already a neural TTS engine on the device, already
integrated, that runs on CPU in 64 MB and has three Hindi voices. That is worth
measuring before anyone ports a 3B model.

### How "robotic" was measured

"Robotic" is a judgement and a written report cannot settle it. So I measured
something objective instead: **intelligibility by round trip.**

```
Hindi text -> TTS -> audio -> Bhashini ASR -> Hindi text
```

If a speech recogniser trained on human Hindi cannot recover the words, the
audio is far from human speech. Twelve sentences the device would actually say —
doses, waiting periods, the refusal message, poisoning first aid — each carrying
terms that must survive.

| Engine | CER | WER | Critical terms kept | Cost |
|---|---|---|---|---|
| Flite (current) | 12.6% | 29.8% | 9/21 — 43% | free |
| **Piper** | 9.3% | 21.8% | 10/21 — 48% | 64 MB, CPU |
| Veena 3B | **7.3%** | **19.4%** | **11/21 — 52%** | 7.65 GB, GPU |

Veena scores best, and it should — it is a 3B model. But it buys **2 points of
CER over Piper** for roughly a hundred times the memory and a GPU the device
does not have. Piper captures most of the available gain at a fraction of the
cost, which is the whole argument.

Piper wins on every measure. But read the next section before treating that gap
as the real difference between the two engines, because most of the errors
turned out not to be the TTS's fault at all.

### Speed

Piper synthesised 3.59 s of audio in 0.23 s on laptop CPU — about **16× faster
than real time**. Comfortably fast enough for the device. Veena, on an RTX 5090,
was 1.21× real time — that is 20× slower than Piper while using a GPU instead of
a CPU.

The Flite timing in my data (12.7 s) is not real. Flite is Linux-only so it runs
through WSL here, and almost all of that is process startup. Flite on the device
is very fast. **I am not claiming Piper is faster than Flite** — only that Piper
is fast enough, which is the decision-relevant fact.

### Recommendation

**Switch the Indic path to Piper and uncomment line 166.** It is already
integrated, it is 64 MB, it runs on CPU, and it scores better on every measure I
could take.

Two things to check first:

- **Coverage is not identical.** Piper has Hindi, Bengali, Marathi, Telugu,
  Malayalam, Urdu, Nepali. Flite has Hindi, Bengali, Gujarati, Kannada, Marathi,
  Punjabi, Tamil, Telugu. Piper adds Malayalam and Urdu but **loses Tamil,
  Gujarati, Punjabi and Kannada**. Tamil matters because it is one of only two
  languages our ASR supports. So the right answer is probably **Piper where a
  voice exists, Flite as fallback**, not a wholesale swap.
- **Someone has to listen.** My metric is a proxy. The wav files are in
  `bhashini-eval/audio/`, one pair per sentence, and the numbers say where to
  listen first.

### A small bug in the TTS language map

`bhashini_models/tts/infer.py` maps Kannada to `"ka"`. Kannada is `"kn"`;
`"ka"` is Georgian. The NMT side uses `"kn"` — I checked the IndicTrans2
language table. So a Kannada request passed straight through from NMT will be
rejected by TTS with "Language 'kn' not supported". One-character fix.

---

## 3. ASR — a defect worth fixing before anything else

This was not on my list. It surfaced because the TTS round-trip kept producing
the same strange errors for **both** engines, which pointed at the recogniser
rather than the voices.

### What I saw

```
said    छिड़काव के पैंतीस दिन बाद ही फसल काटें
flite   िका    के पैंतीस दिन बाद ही फसल काटें
piper   िकाव   के पैंतीस दिन बाद ही फसल काटें
```

Both engines lose छ and ड़ in exactly the same place. Two independent synthesis
methods do not fail identically by chance.

### What is actually wrong

The Hindi ASR model outputs **129 classes**. I checked the ONNX graph directly:

```
logprobs  [1, T, 129]
```

The vocabulary table hard-coded in `bhashini_models/asr/infer.py` has **88
entries**, and the decoder assumes blank is index 88:

```python
blank = len(vocab)                      # 88
token_ids = np.argmax(logits, axis=-1)[0]
if t != blank and t != prev and t < len(vocab):   # drops everything >= 88
```

Two separate errors:

1. **The blank index is wrong.** I ran the model and looked at the predictions:
   index **128** is the dominant class, which is the CTC blank. Index 88 is a
   real token being silently treated as blank.
2. **40 of 128 tokens can never be emitted.** The `t < len(vocab)` check
   discards every id from 88 upward. In three test clips, ids 88 and 94 were
   predicted and thrown away.

### The consequence

These characters are absent from the truncated table and therefore **cannot ever
be transcribed**:

```
consonants   घ  ङ  छ  झ  ञ  ठ  ढ  ण  ष
nukta forms  ड़  ढ़  क़  ख़  ग़  ज़  फ़
vowels       ऊ  ऐ  ओ  ऋ
```

छ and ड़ are not rare. छिड़काव (spraying), छह (six), बड़ा, पेड़, दवाई का डिब्बा —
these are ordinary farming words. The recogniser is being prevented from
producing them by a table in our own code.

### Why this matters for the "replace with AI4Bharat" question

The task was to research replacing Bhashini's ASR with AI4Bharat's models
because Bhashini only covers Hindi and Tamil.

Two things to say about that:

1. **Our checkpoints are almost certainly AI4Bharat IndicConformer already.**
   The evidence:

   | | AI4Bharat IndicConformer Large | `hi-conformer.onnx` |
   |---|---|---|
   | Parameters | 120 M | 506 MB fp32 weights ≈ **126 M** |
   | Architecture | Conformer, hybrid CTC-RNNT | Conformer, CTC output (`logprobs`) |
   | Decoding | CTC mode selectable | CTC greedy, as used here |
   | Languages in family | **22 scheduled languages** | we ship 2 |

   The ONNX file carries no provenance metadata — it just says "exported from
   pytorch 2.9" — so this is inference from size and architecture, not proof.
   But if it holds, the task is not "replace Bhashini with AI4Bharat", it is
   **"download the other 20 checkpoints of the model we already run"**. Same
   inference code, same decoder, dramatically less risk than a swap.
2. **Whatever we decide, fix the vocabulary first.** Right now any comparison
   between Bhashini's ASR and an alternative is unfair by roughly a third of the
   output vocabulary. We would be measuring our own decoder bug and attributing
   it to the model.

**What is needed:** the tokenizer/vocabulary file the model was actually trained
with, all 128 entries, and blank set to 128. This is Deep's area — flagging it,
not taking it.

---

## Confirmed while doing this

The ASR discards its own confidence scores:

```python
token_ids = np.argmax(logits, axis=-1)[0]
```

The probabilities exist in `logits` and are dropped before anything downstream
can read them. This is the blocker behind the "feed ASR confidence into
retrieval" idea from the RAG discussion. Fixing the vocabulary and exposing an
utterance-level confidence score are the same edit to the same function.

---

## Coverage across the pipeline

Worth having in one place, because the bottleneck is not where the task list
assumes:

| Stage | Languages |
|---|---|
| ASR | **2** — Hindi, Tamil (+ English via Vosk) |
| NMT | 38 codes, ~22 languages |
| TTS | 8 via Flite, 7 via Piper |

The device can translate into 22 languages and speak 8, but it can only **hear**
2. ASR is the constraint, and no amount of TTS or NMT work moves it.

---

## What I could not do

- **Finish the Gemini comparison.** The free tier ran out of daily quota at 19
  of 50 sentences, across both API keys. There is no billing plan on either, so
  I stopped rather than force it. The missing categories are number, negation,
  safety and scheme. Bhashini's own numbers are complete.
- **Judge the voices by ear.** The numbers say Piper is better; a person still
  has to confirm it. Files are in `bhashini-eval/audio/`.
- **Separate ASR error from TTS error.** The round-trip number contains both. I
  have no human recordings of these sentences to establish the ASR's floor, so
  the absolute values overstate how bad both engines are. The comparison between
  them is still fair — same ASR, same sentences.
- **Confirm the IndicConformer identity claim** beyond parameter count and
  architecture. The ONNX file carries no provenance metadata.
- **Benchmark anything on the actual Jetson.** All timings here are laptop CPU
  or a desktop-class GPU.

---

## Reproducing

```bash
cd bhashini-eval
python testset.py          # 50 NMT cases
python run_nmt_eval.py     # Bhashini vs Gemini        -> results_nmt.json
python run_e2e.py          # through the Krishi RAG    -> results_e2e.json
python run_tts_eval.py     # Flite vs Piper vs Veena   -> results_tts.json

# Veena only runs on the GPU server (bf16 needs ~8 GB VRAM):
#   scp veena_gen.py veena_input.json prabhakar@100.105.243.101:~/veena_eval/
#   ssh ... 'cd veena_eval && .venv/bin/python veena_gen.py'
#   scp back into bhashini-eval/veena_audio/
```

Model weights are extracted from the zips in
`suno-sutra-sw/rootfs/roles/indic/files/` and are gitignored. The Gemini key
lives in `.env`, also gitignored.
