"""End-to-end pipeline test on REAL farmer audio. Prepared; run when flagged.

    audio -> ASR -> NMT (hi->en) -> Krishi RAG -> NMT (en->hi) -> [TTS]

WHY REAL AUDIO AND NOT SENTENCES WE WROTE

Every RAG number we have so far came from queries I authored, and every ASR
number came from FLEURS, which is news prose read in a studio. Neither is a
farmer. These 40 clips are smallholder farmers speaking real questions to
Digital Green's Farmer.Chat advisory line, with transcripts produced by human
annotators — nothing scripted, nothing studio-recorded. Expect the numbers to
be worse than our FLEURS figures, and expect that to be the honest ones.

ATTRIBUTING FAILURE

Four stages can break the answer and they look identical from the far end, so
every stage is printed and scored separately:

    ASR   transcript vs the human reference   -> WER/CER, the in-between check
    NMT   English out of the Hindi
    RAG   condition, label_id, spoken answer
    TTS   (only once a voice is wired in)

A case can pass ASR and fail RAG, or fail ASR and still reach the right answer
because retrieval is robust to a mangled word. Both facts are worth knowing and
neither is visible from the final audio alone.

WHAT COUNTS AS PASSING

Not "did it answer" — the manifest states, per case, what a correct answer must
do AND what would make it dangerous. The deficiency cases are the sharp ones:
a nutrient problem answered with a pesticide is a failure even if every other
stage was perfect.

Usage:
    python run_audio_tests.py                # all 40
    python run_audio_tests.py --only 1 5 12  # specific cases
    python run_audio_tests.py --limit 5      # quick smoke
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PIPE = REPO / "pipeline-models"
RAG = REPO / "krishi-rag"

sys.path.insert(0, str(RAG / "src"))
sys.path.insert(0, str(PIPE / "nmt" / "indicTrans2"))
sys.path.insert(0, str(PIPE))

ASR_FP32 = PIPE / "ai4bharat" / "indic-conformer-600m-multilingual"
ASR_INT8 = PIPE / "ai4bharat-int8" / "indic-conformer-600m-multilingual"
NMT_DIR = PIPE / "nmt" / "indicTrans2"


# --------------------------------------------------------------- components
class Pipeline:
    def __init__(self, asr_variant: str = "fp32") -> None:
        import torch
        from transformers import AutoModel

        asr_dir = ASR_INT8 if asr_variant == "int8" else ASR_FP32
        if not asr_dir.exists():
            raise SystemExit(f"ASR variant '{asr_variant}' not built: {asr_dir}")
        print(f"loading ASR (IndicConformer 600M, {asr_variant}) ...", flush=True)
        self.asr_variant = asr_variant
        self.torch = torch
        self.asr = AutoModel.from_pretrained(str(asr_dir), trust_remote_code=True)
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            self.asr = self.asr.to(self.dev)
        except Exception:
            self.dev = "cpu"
        print(f"  ASR on {self.dev}", flush=True)

        print("loading NMT (IndicTrans2 indic-en, CPU) ...", flush=True)
        from inference.engine import Model
        self.nmt_in = Model(str(NMT_DIR / "checkpoints" / "indic-en" / "ct2_int8_model"),
                            device="cpu", input_lang_code_format="iso",
                            model_type="ctranslate2")
        self.nmt_out = None       # loaded lazily; only needed for the reply

        print("loading Krishi RAG ...", flush=True)
        from grounding import CoverageGate, build_response, lookup_treatment
        from okf import load_bundle
        from phonetic import PhoneticIndex
        from retrieval import HybridRetriever
        from router import Route, build_product_index, route

        self._build_response = build_response
        self._lookup = lookup_treatment
        self._route = route
        self._Route = Route
        self._PhoneticIndex = PhoneticIndex
        concepts = load_bundle(RAG / "bundle")
        self.by_id = {c.concept_id: c for c in concepts}
        self.retriever = HybridRetriever.load(RAG / "index" / "krishi.pkl")
        self.gate = CoverageGate(self.by_id)
        self.products = build_product_index(concepts)
        print("  ready\n", flush=True)

    def transcribe(self, wav: Path, lang: str) -> str:
        import soundfile as sf
        import torchaudio
        data, sr = sf.read(str(wav), dtype="float32", always_2d=True)
        w = self.torch.from_numpy(data.T).mean(0, keepdim=True)
        if sr != 16000:
            w = torchaudio.functional.resample(w, sr, 16000)
        with self.torch.no_grad():
            out = self.asr(w.to(self.dev), lang, "rnnt")
        return str(out[0] if isinstance(out, (list, tuple)) else out)

    def to_english(self, text: str, src: str) -> str:
        return self.nmt_in.paragraphs_batch_translate__multilingual(
            [[text, src, "en"]])[0]

    def to_native(self, text: str, tgt: str) -> str:
        if self.nmt_out is None:
            from inference.engine import Model
            self.nmt_out = Model(
                str(NMT_DIR / "checkpoints" / "en-indic" / "ct2_int8_model"),
                device="cpu", input_lang_code_format="iso",
                model_type="ctranslate2")
        return self.nmt_out.paragraphs_batch_translate__multilingual(
            [[text, "en", tgt]])[0]

    def diagnose(self, english: str):
        d = self._route(english, has_image=False, crop=None,
                        coverage_gate=self.gate, product_names=self.products,
                        product_index=self._PhoneticIndex(self.products),
                        crop_index=self._PhoneticIndex(self.gate.canonical))
        if d.route == self._Route.PESTICIDE and d.product:
            return self._lookup(d.product, self.by_id), d
        if not d.needs_retrieval:
            from grounding import Outcome, Response
            return Response(outcome=Outcome.OUT_OF_SCOPE,
                            spoken_text="(model may answer directly)"), d
        return self._build_response(
            english, self.retriever, self.by_id, crop=d.crop,
            require_crop=d.route in (self._Route.DIAGNOSE,),
            boost_source=d.boost_source), d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--reply", action="store_true",
                    help="also translate the answer back to Hindi (slower)")
    ap.add_argument("--asr", choices=["fp32", "int8"], default="fp32",
                    help="which ASR build to run; int8 is the quantised twin")
    ap.add_argument("--out", default=None,
                    help="results filename (defaults to results_<asr>.json)")
    a = ap.parse_args()

    cases = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    if a.only:
        cases = [c for c in cases if c["id"] in a.only]
    if a.limit:
        cases = cases[:a.limit]

    import jiwer
    sys.path.insert(0, str(REPO / "bhashini-eval"))
    import asr_scoring as scoring

    p = Pipeline(asr_variant=a.asr)
    results = []
    t_all = time.time()

    for c in cases:
        print("=" * 78)
        print(f"CASE {c['id']:02d}  [{c['category']}]")
        print("=" * 78)
        ref = c["reference_hindi"]
        print(f"  human transcript : {ref}")

        t = time.time()
        heard = p.transcribe(HERE / c["audio"], c["lang"])
        t_asr = time.time() - t
        nr, nh = scoring.normalise(ref), scoring.normalise(heard)
        wer = 100 * jiwer.wer(nr, nh) if nr else float("nan")
        cer = 100 * jiwer.cer(nr, nh) if nr else float("nan")
        print(f"  ASR heard        : {heard}")
        print(f"  ASR error        : WER {wer:.1f}%  CER {cer:.1f}%   ({t_asr:.2f}s)")

        t = time.time()
        eng = p.to_english(heard, c["lang"])
        t_nmt = time.time() - t
        print(f"  English          : {eng}   ({t_nmt:.2f}s)")

        t = time.time()
        r, d = p.diagnose(eng)
        t_rag = time.time() - t
        labels = list(r.label_ids or [])
        print(f"  route            : {d.route.value}")
        print(f"  RAG outcome      : {str(r.outcome).replace('Outcome.','')}")
        print(f"  condition        : {r.condition_id}")
        print(f"  prescribed       : {labels or '(nothing)'}")
        print(f"  answer           : {(r.spoken_text or '')[:150]}   ({t_rag:.2f}s)")

        if a.reply and r.spoken_text:
            back = p.to_native(r.spoken_text, c["lang"])
            print(f"  reply in Hindi   : {back[:150]}")

        print(f"  EXPECT           : {c['expect']}")
        print(f"  MUST NOT         : {c['must_not']}")
        # The one machine-checkable safety property: a nutrient problem must
        # never come back with a chemical. Everything else needs a human read.
        auto = None
        if c["category"] in ("deficiency_like", "deficiency_khaira",
                             "nutrient_question", "out_of_scope",
                             "uncovered_crop"):
            auto = "SAFE" if not labels else "UNSAFE — prescribed for a non-disease"
            print(f"  auto-check       : {auto}")
        print()

        results.append({**c, "heard": heard, "wer": round(wer, 1),
                        "cer": round(cer, 1), "english": eng,
                        "outcome": str(r.outcome).replace("Outcome.", ""),
                        "condition": r.condition_id, "labels": labels,
                        "answer": r.spoken_text, "auto_check": auto,
                        "secs": {"asr": round(t_asr, 2), "nmt": round(t_nmt, 2),
                                 "rag": round(t_rag, 2)}})

    out_name = a.out or f"results_{a.asr}.json"
    (HERE / out_name).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = [r for r in results if r["wer"] == r["wer"]]
    print("=" * 78)
    print(f"SUMMARY  (ASR: {a.asr})")
    print("=" * 78)
    if ok:
        print(f"  ASR mean WER : {sum(r['wer'] for r in ok)/len(ok):.1f}%"
              f"   mean CER: {sum(r['cer'] for r in ok)/len(ok):.1f}%")
    unsafe = [r for r in results if r["auto_check"] and "UNSAFE" in r["auto_check"]]
    print(f"  prescribed on a non-disease : {len(unsafe)}"
          f"{' — ' + ', '.join(str(r['id']) for r in unsafe) if unsafe else ''}")
    print(f"  total wall clock : {time.time()-t_all:.1f}s for {len(results)} cases")
    print(f"  written to {out_name}")
    return 1 if unsafe else 0


if __name__ == "__main__":
    raise SystemExit(main())
