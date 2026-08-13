"""One pipeline stage, as its own short-lived process.

In-process unloading does not work: `del` plus `empty_cache()` returns pages to
the allocator, not to the OS. Measured, it made things worse - swapping the ASR
saved 588 MB of GPU but cost 2.7 GB of RAM and slowed the ASR 13x.

A process that exits returns everything, unconditionally. So each stage runs
here, writes its output to disk, and dies. Peak memory becomes the largest
single stage rather than the sum of everything ever loaded.

    python stage.py asr      <wav>  <out.txt>   <lang>
    python stage.py nmt_in   <in>   <out.txt>   <lang>
    python stage.py rag      <in>   <out.json>
    python stage.py nmt_out  <in>   <out.txt>   <lang>
    python stage.py tts      <in>   <out.wav>   <lang>
"""
import json
import os
import re
import sys
from pathlib import Path

# Must happen before onnxruntime is imported anywhere. The RAG's embedder
# (fastembed) grabs the CUDA provider by default and then fails with
# NOT_IMPLEMENTED on this build; it is a 384-dim MiniLM and has no business on
# the GPU anyway. Hiding the device also removes ~350 MB of CUDA context from
# the stage, which is most of what the RAG was costing in GPU terms.
if len(sys.argv) > 1 and sys.argv[1] in ("rag", "nmt_in", "nmt_out", "tts"):
    os.environ["CUDA_VISIBLE_DEVICES"] = ""

HERE = Path.home() / "vyoma_pipeline"
D = HERE / "pipeline/models/ai4bharat-int8/indic-conformer-600m-multilingual"
NMT = HERE / "pipeline/models/nmt/indicTrans2"


def peak_kb():
    """This process's own high-water anonymous memory, reported on exit."""
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def load_asr_cpu():
    """ASR on CPU with only the Hindi head: 3045 MB -> 457 MB, same accuracy."""
    import importlib.util
    src = (D / "model_onnx.py").read_text(encoding="utf-8")
    src = re.sub(r"\+ \[f'joint_post_net_\{z\}' for z in \[[^\]]*\]\]",
                 "+ ['joint_post_net_hi']", src)
    src = src.replace(
        "providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] "
        "if torch.cuda.is_available() else ['CPUExecutionProvider']",
        "providers = ['CPUExecutionProvider']")
    p = Path("/tmp/_stage_asr.py")
    p.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("stage_asr", str(p))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.IndicASRModel(m.IndicASRConfig(ts_folder=str(D)))


def main():
    what, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    lang = sys.argv[4] if len(sys.argv) > 4 else "hi"

    if what == "asr":
        import soundfile as sf
        import torch
        import torchaudio
        asr = load_asr_cpu()
        data, sr = sf.read(src, dtype="float32", always_2d=True)
        w = torch.from_numpy(data.T).mean(0, keepdim=True)
        if sr != 16000:
            w = torchaudio.functional.resample(w, sr, 16000)
        with torch.no_grad():
            out = asr(w, lang, "rnnt")
        text = out[0] if isinstance(out, (list, tuple)) else out
        Path(dst).write_text(str(text), encoding="utf-8")

    elif what in ("nmt_in", "nmt_out"):
        sys.path.insert(0, str(NMT))
        from inference.engine import Model
        ck = "indic-en" if what == "nmt_in" else "en-indic"
        m = Model(str(NMT / "checkpoints" / ck / "ct2_int8_model"),
                  device="cpu", input_lang_code_format="iso",
                  model_type="ctranslate2")
        text = Path(src).read_text(encoding="utf-8").strip()
        a, b = ("hi", "en") if what == "nmt_in" else ("en", lang)
        # Sentence-split rather than the Moses splitter, which shells out to a
        # Perl subprocess and died with a MemoryError on the first real case.
        sents = [s.strip() for s in re.split(r"(?<=[।.!?])\s+", text) if s.strip()] or [text]
        out = m.batch_translate(sents, a, b)
        Path(dst).write_text(" ".join(out), encoding="utf-8")

    elif what == "rag":
        sys.path.insert(0, str(HERE / "pipeline" / "models"))
        if not (HERE / "pipeline").exists():
            sys.path.insert(0, str(Path(__file__).resolve().parent / "models"))
        
        from module_router import route_module, Module
        
        q = Path(src).read_text(encoding="utf-8").strip()
        decision = route_module(q)
        
        if decision.module == Module.SCHEMES:
            schemes_dir = HERE / "schemes-rag"
            if not schemes_dir.exists():
                schemes_dir = Path(__file__).resolve().parent.parent / "schemes-rag"
            
            sys.path.insert(0, str(schemes_dir))
            from government_schemes_rag import GovernmentSchemesRAGEngine
            
            engine = GovernmentSchemesRAGEngine(jsonl_file=str(schemes_dir / "enriched_schemes_dataset.jsonl"))
            res = engine.query_schemes(q)
            
            outcome = res.get("status", "success")
            condition = res.get("scheme_id")
            label_ids = []
            text = res.get("bhashini_voice_text", "")
            
            Path(dst).write_text(json.dumps(
                {"outcome": outcome, "condition": condition,
                 "label_ids": label_ids, "text": text},
                ensure_ascii=False), encoding="utf-8")
        else:
            krishi_dir = HERE / "krishi-rag"
            if not krishi_dir.exists():
                krishi_dir = Path(__file__).resolve().parent.parent / "krishi-rag"
            
            sys.path.insert(0, str(krishi_dir / "src"))
            from grounding import CoverageGate, build_response, lookup_treatment
            from okf import load_bundle
            from phonetic import PhoneticIndex
            from retrieval import HybridRetriever
            from router import Route, build_product_index, route
            concepts = load_bundle(krishi_dir / "bundle")
            by_id = {c.concept_id: c for c in concepts}
            retr = HybridRetriever.load(krishi_dir / "index" / "krishi.pkl")
            gate = CoverageGate(by_id)
            prods = build_product_index(concepts)
            d = route(q, has_image=False, crop=None, coverage_gate=gate,
                      product_names=prods, product_index=PhoneticIndex(prods),
                      crop_index=PhoneticIndex(gate.canonical))
            if d.route == Route.PESTICIDE and d.product:
                r = lookup_treatment(d.product, by_id)
            elif not d.needs_retrieval:
                from grounding import Outcome, Response
                r = Response(outcome=Outcome.OUT_OF_SCOPE,
                             spoken_text="(model may answer this directly)")
            else:
                r = build_response(q, retr, by_id, crop=d.crop,
                                   require_crop=d.route in (Route.DIAGNOSE,),
                                   boost_source=d.boost_source)
            Path(dst).write_text(json.dumps(
                {"outcome": r.outcome.value, "condition": r.condition_id,
                 "label_ids": r.label_ids, "text": r.spoken_text},
                ensure_ascii=False), encoding="utf-8")

    elif what == "tts":
        import soundfile as sf
        import torch
        from transformers import AutoTokenizer, VitsModel
        code = {"hi": "hin", "bn": "ben", "mr": "mar", "te": "tel", "ta": "tam",
                "gu": "guj", "kn": "kan", "ml": "mal", "pa": "pan",
                "or": "ory"}.get(lang, "hin")
        repo = "facebook/mms-tts-" + code
        tok = AutoTokenizer.from_pretrained(repo)
        m = VitsModel.from_pretrained(repo).eval()          # CPU
        text = Path(src).read_text(encoding="utf-8").strip()
        ins = tok(text, return_tensors="pt")
        with torch.no_grad():
            w = m(**ins).waveform[0].numpy()
        sf.write(dst, w, m.config.sampling_rate)

    else:
        raise SystemExit("unknown stage " + what)

    # Last line of stdout is the contract with the orchestrator.
    print("PEAK_KB {}".format(peak_kb()))


if __name__ == "__main__":
    main()
