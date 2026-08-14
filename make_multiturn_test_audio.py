#!/usr/bin/env python3
"""Creates the real test-fixture audio for the 5-turn multi-language stress test
(test_multiturn_stress.py) -- run once on GX10, output gets scp'd to Jetson.

5-turn farmer conversation (one continuous conversation, real follow-ups, real topic
switches), written in English then translated via the real NMT engine (in-process, not
the gateway -- same pattern as rag/test_chunked_vs_unchunked.py) and synthesized via the
real production MMS-TTS engine (GPU/PyTorch -- the actual pipeline path, NOT the ONNX one)
for all 4 languages: en (direct), hi/ta/ml (via NMT).

Turn 1 carries the image context (late blight potato leaves) -- the image itself is
attached separately by the test script, not encoded in the audio.
Turn 2: real follow-up on turn 1 (dose/frequency) -- tests conversation memory + G1 RAG.
Turn 3: weather forecast (new topic) -- tests weather tools + a Rule 1 topic-switch.
Turn 4: spraying follow-up on turn 3 -- designed to plausibly need BOTH a weather tool
        (query_spray_window) and a G1 RAG tool (pesticide/disease) in the same turn.
Turn 5: government scheme question (new topic) -- tests G2 RAG tools.

Run: source venv/bin/activate && cd gramsahayak && python3 make_multiturn_test_audio.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import soundfile as sf

from api_server import config
from models.nmt.model_loader import NMTEngine
from models.mms_tts import MultiLangMmsTtsEngine, MmsTtsInferencer

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_audio", "multiturn_stress")

TURNS_EN = [
    "I'm a farmer in Nashik district. My potato plants have these dark spots on the "
    "leaves that seem to be spreading fast. What is this, and what should I do?",

    "How much of that should I use per acre, and how many times do I need to spray it?",

    "What's the weather going to be like in Nashik over the next two weeks?",

    "Given that forecast, is this a good time to spray the potato crop, or should I wait?",

    "Are there any government schemes that could help me get compensation if my crop "
    "gets badly damaged?",
]

LANGUAGES = {
    "en": None,       # no translation needed
    "hi": "hi",
    "ta": "ta",
    "ml": "ml",
}


def main():
    print("Loading NMT engine...")
    nmt = NMTEngine(checkpoint_root=config.WORKERS["nmt"]["checkpoint_root"])
    nmt.load()

    print("Loading TTS engine (mms_tts, GPU/PyTorch -- real production path)...")
    tts_cfg = config.WORKERS["tts"]["engines"]["mms_tts"]
    tts_engine = MultiLangMmsTtsEngine(checkpoint_root=tts_cfg["checkpoint_root"],
                                        languages=tts_cfg["preload_languages"])
    tts_engine.load()  # lazy -- loads nothing yet

    texts_by_lang = {}
    for lang, nmt_code in LANGUAGES.items():
        texts_by_lang[lang] = []
        for i, text_en in enumerate(TURNS_EN):
            if nmt_code is None:
                text = text_en
            else:
                text = nmt.infer(text_en, "EN", nmt_code)["translated_text"]
            texts_by_lang[lang].append(text)
            print(f"  [{lang}] turn{i+1}: {text}")

    nmt.unload()

    tts_lang_names = {"en": "English", "hi": "Hindi", "ta": "Tamil", "ml": "Malayalam"}
    for lang, texts in texts_by_lang.items():
        lang_dir = os.path.join(OUT_DIR, lang)
        os.makedirs(lang_dir, exist_ok=True)
        tts_engine.load(language=lang)
        inferencer = MmsTtsInferencer(tts_engine.get(lang))
        for i, text in enumerate(texts):
            audio, sr = inferencer.synthesize(text)
            out_path = os.path.join(lang_dir, f"turn{i+1}.wav")
            sf.write(out_path, audio, sr)
            print(f"[{lang}] turn{i+1} -> {out_path} ({len(audio)/sr:.2f}s)")

    print(f"\nAll audio written under {OUT_DIR}/<lang>/turn<N>.wav")
    print("Spot-check at least one file per language by ear before transferring to Jetson.")


if __name__ == "__main__":
    main()
