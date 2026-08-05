"""Full pipeline: voice -> ASR -> NMT -> RAG -> NMT -> (TTS) -> voice.

Prints every intermediate so a failure can be ATTRIBUTED rather than guessed at.
Four stages can each break it, and the symptoms are indistinguishable from the
final audio alone:

    ASR wrong  -> transcript is wrong in the farmer's own language
    NMT wrong  -> transcript fine, English wrong
    RAG wrong  -> English fine, wrong condition or wrong dose
    TTS wrong  -> answer correct, audio unintelligible

Usage:
    python run_pipeline.py --audio clip.wav --lang hi
    python run_pipeline.py --text "मेरे टमाटर के पत्तों पर भूरे धब्बे हैं" --lang hi

TTS is skipped until a model is chosen; every earlier stage runs regardless, so
the pipeline is testable end-to-end minus the final audio today.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
ASR_DIR = ROOT / "ai4bharat" / "indic-conformer-600m-multilingual"
NMT_DIR = ROOT / "nmt" / "indicTrans2"
RAG = REPO / "krishi-rag"

sys.path.insert(0, str(RAG / "src"))
sys.path.insert(0, str(NMT_DIR))


def stage(n: int, name: str) -> None:
    print(f"\n{'='*72}\n{n}. {name}\n{'='*72}")


# ----------------------------------------------------------------- 1. ASR
def transcribe(wav: Path, lang: str) -> str:
    import torch
    from transformers import AutoModel
    model = AutoModel.from_pretrained(str(ASR_DIR), trust_remote_code=True)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        model = model.to(dev)
    except Exception:
        dev = "cpu"
    import soundfile as sf
    import torchaudio
    data, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    w = torch.from_numpy(data.T).mean(0, keepdim=True)
    if sr != 16000:
        w = torchaudio.functional.resample(w, sr, 16000)
    with torch.no_grad():
        # RNNT: measured better than CTC on every language we tested.
        out = model(w.to(dev), lang, "rnnt")
    return str(out[0] if isinstance(out, (list, tuple)) else out)


# ----------------------------------------------------------------- 2. NMT
_nmt_cache: dict[str, object] = {}


def translate(text: str, src: str, tgt: str) -> str:
    from inference.engine import Model
    key = "indic-en" if tgt == "en" else "en-indic"
    if key not in _nmt_cache:
        _nmt_cache[key] = Model(
            str(NMT_DIR / "checkpoints" / key / "ct2_int8_model"),
            device="cpu", input_lang_code_format="iso",
            model_type="ctranslate2")
    return _nmt_cache[key].paragraphs_batch_translate__multilingual(
        [[text, src, tgt]])[0]


# ----------------------------------------------------------------- 3. RAG
def diagnose(english: str, has_image: bool = False):
    from grounding import CoverageGate, build_response, lookup_treatment
    from okf import load_bundle
    from phonetic import PhoneticIndex
    from retrieval import HybridRetriever
    from router import Route, build_product_index, route

    concepts = load_bundle(RAG / "bundle")
    by_id = {c.concept_id: c for c in concepts}
    retriever = HybridRetriever.load(RAG / "index" / "krishi.pkl")
    gate = CoverageGate(by_id)
    products = build_product_index(concepts)

    d = route(english, has_image=has_image, crop=None, coverage_gate=gate,
              product_names=products, product_index=PhoneticIndex(products),
              crop_index=PhoneticIndex(gate.canonical))
    print(f"   route      : {d.route.value}  ({d.reason})")
    if d.route == Route.PESTICIDE and d.product:
        return lookup_treatment(d.product, by_id)
    if not d.needs_retrieval:
        from grounding import Outcome, Response
        return Response(outcome=Outcome.OUT_OF_SCOPE,
                        spoken_text="The model may answer this directly.")
    return build_response(english, retriever, by_id, crop=d.crop,
                          require_crop=d.route in (Route.DIAGNOSE,),
                          boost_source=d.boost_source)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", type=Path)
    ap.add_argument("--text", type=str, help="skip ASR, start from text")
    ap.add_argument("--lang", default="hi")
    ap.add_argument("--image", action="store_true")
    a = ap.parse_args()
    if not a.audio and not a.text:
        ap.error("give --audio or --text")

    t0 = time.time()

    stage(1, "ASR — speech to text, in the farmer's language")
    if a.audio:
        t = time.time()
        native = transcribe(a.audio, a.lang)
        print(f"   heard      : {native}\n   took       : {time.time()-t:.2f}s")
    else:
        native = a.text
        print(f"   given      : {native}   (ASR skipped)")

    stage(2, f"NMT — {a.lang} to English (the RAG only ever sees English)")
    t = time.time()
    english = translate(native, a.lang, "en") if a.lang != "en" else native
    print(f"   English    : {english}\n   took       : {time.time()-t:.2f}s")

    stage(3, "RAG — diagnosis and grounded dose")
    t = time.time()
    r = diagnose(english, has_image=a.image)
    print(f"   outcome    : {str(r.outcome).replace('Outcome.','')}")
    print(f"   condition  : {r.condition_id}")
    print(f"   label_ids  : {list(r.label_ids or []) or '(none — no prescription)'}")
    print(f"   answer     : {r.spoken_text}")
    print(f"   took       : {time.time()-t:.2f}s")

    stage(4, f"NMT — English back to {a.lang}")
    t = time.time()
    reply = (translate(r.spoken_text, "en", a.lang)
             if a.lang != "en" and r.spoken_text else r.spoken_text)
    print(f"   reply      : {reply}\n   took       : {time.time()-t:.2f}s")

    stage(5, "TTS — text to speech")
    tts_dir = ROOT / "tts"
    if not tts_dir.exists() or not any(tts_dir.iterdir()):
        print("   SKIPPED — no TTS model chosen yet. Put one in pipeline-models/tts/")
        print("   Candidates measured and ready: indic-parler-tts int4, or FastSpeech2_HS")
    else:
        print("   (loader wires in once the model is chosen)")

    print(f"\n{'='*72}\ntotal: {time.time()-t0:.2f}s\n{'='*72}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
