# TTS Engine Timing Comparison — Parler vs mms_tts

Generated: 2026-08-05T13:58:21+00:00
Repeats per language: 1

Measured directly against each engine in-process (bypassing the `/tts/infer` HTTP path, which never exposes partial-chunk timing) — same real text per language for both engines, same settings `tts_worker.py` uses in production (`batch_size=3, solo_first_chunk=False` for parler). Not the load-balancer's own orchestrated pipeline numbers — see `ARCHITECTURE.md` §3 for the full-pipeline wall-clock and per-step breakdown tables — this isolates TTS's own generation timing specifically.

## Time-to-first-audio vs. total generation time

mms_tts's `time_to_first_audio_s` always equals `total_tts_time_s` — VITS's single forward pass has no partial output, so there is no "first chunk" to measure separately. This is a real architectural difference from parler's chunked generation, not a measurement gap.

| Engine | Language | Time to first audio (s) | Total TTS time (s) | Audio duration (s) | RTF to first audio | RTF total |
|---|---|---|---|---|---|---|
| parler | English | 28.369 | 104.015 | 78.41 | 0.3618 | 1.3266 |
| parler | Hindi | 26.934 | 61.783 | 57.26 | 0.4704 | 1.0790 |
| parler | Malayalam | 23.611 | 58.024 | 61.55 | 0.3836 | 0.9427 |
| parler | Tamil | 43.030 | 98.525 | 83.59 | 0.5148 | 1.1787 |
| mms_tts | English | 1.425 | 1.425 | 75.31 | 0.0189 | 0.0189 |
| mms_tts | Hindi | 0.736 | 0.736 | 54.85 | 0.0134 | 0.0134 |
| mms_tts | Malayalam | 0.926 | 0.926 | 57.47 | 0.0161 | 0.0161 |
| mms_tts | Tamil | 1.090 | 1.090 | 87.41 | 0.0125 | 0.0125 |

## Engine load time (once, before any language)

| Engine | Load time (s) | Batch size used |
|---|---|---|
| parler | 2.402 | 3 |
| mms_tts | 7.560 | n/a (no chunking) |

## Raw per-repeat samples

- **parler / English**: rep1: ttfa=28.369s total=104.015s dur=78.41s
- **parler / Hindi**: rep1: ttfa=26.934s total=61.783s dur=57.26s
- **parler / Malayalam**: rep1: ttfa=23.611s total=58.024s dur=61.55s
- **parler / Tamil**: rep1: ttfa=43.030s total=98.525s dur=83.59s
- **mms_tts / English**: rep1: ttfa=1.425s total=1.425s dur=75.31s
- **mms_tts / Hindi**: rep1: ttfa=0.736s total=0.736s dur=54.85s
- **mms_tts / Malayalam**: rep1: ttfa=0.926s total=0.926s dur=57.47s
- **mms_tts / Tamil**: rep1: ttfa=1.090s total=1.090s dur=87.41s
