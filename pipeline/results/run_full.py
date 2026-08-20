"""Full-pipeline run that ARCHIVES every artefact, per case, per configuration.

    audio -> ASR -> NMT(hi->en) -> RAG -> NMT(en->hi) -> TTS -> audio

Layout produced:

    pipeline-results/<config>/<case>/
        01_input.ogg          the farmer's actual recording
        02_asr.txt            what our ASR heard, next to the human reference
        03_nmt_en.txt         the English the RAG actually receives
        04_rag.json           route, outcome, condition, label_ids, full response
        05_answer_en.txt      the answer the RAG produced, in English
        06_nmt_back.txt       that answer translated back to the farmer's language
        07_output.wav         the spoken reply
        case.json             everything above as one record, plus timings

One folder per case, numbered files in pipeline order, so a failure can be read
top to bottom without running anything. <config> is e.g. "fp32-fastspeech2" or
"int8-fastspeech2", which keeps configurations side by side for comparison
rather than overwriting each other.

Usage:
    python run_full.py --config fp32-fastspeech2
    python run_full.py --config int8-fastspeech2 --asr int8
    python run_full.py --config fp32-fastspeech2 --limit 3     # smoke first
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import traceback
from pathlib import Path

# Layout, after the three pipeline-* folders were grouped under pipeline/:
#   <repo>/pipeline/results     <- HERE, and where run output is written
#   <repo>/pipeline/models      <- ASR, NMT, TTS weights
#   <repo>/pipeline/audio-tests <- the 40 real farmer clips
#   <repo>/krishi-rag           <- bundle, index and the RAG source
#
# Resolved by walking up from this file rather than hardcoding, so the tree can
# be copied to the GPU box (~/vyoma_pipeline) and run unchanged.
HERE = Path(__file__).resolve().parent
PIPE_ROOT = HERE.parent
REPO = PIPE_ROOT.parent
PIPE = PIPE_ROOT / "models"
TESTS = PIPE_ROOT / "audio-tests"

# On the GPU box the code is copied without the surrounding repo, so krishi-rag
# may sit beside pipeline/ instead of above it. Take whichever exists.
RAG = REPO / "krishi-rag"
if not (RAG / "bundle").is_dir() and (PIPE_ROOT / "krishi-rag" / "bundle").is_dir():
    RAG = PIPE_ROOT / "krishi-rag"

sys.path.insert(0, str(RAG / "src"))
sys.path.insert(0, str(PIPE / "nmt" / "indicTrans2"))
sys.path.insert(0, str(REPO / "bhashini-eval"))

def _hf_snapshot(repo: str):
    """Path to a model inside the HuggingFace cache, if it is already there.

    The GPU box already had the ASR and FastSpeech2 pulled down for earlier
    work, 2.4 GB and 1.6 GB respectively. Re-uploading them from the laptop
    over a relayed Tailscale link would have taken far longer than reusing what
    is on disk, so the runner looks in the cache before giving up.
    """
    import os
    root = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    hub = root / "hub" / ("models--" + repo.replace("/", "--")) / "snapshots"
    if not hub.is_dir():
        return None
    snaps = sorted((d for d in hub.iterdir() if d.is_dir()),
                   key=lambda d: d.stat().st_mtime, reverse=True)
    return snaps[0] if snaps else None


def _pick(local: Path, repo: str, marker: str = ""):
    """Prefer a local copy; fall back to the HuggingFace cache."""
    if (local / marker).exists() if marker else local.is_dir():
        return local
    cached = _hf_snapshot(repo)
    if cached is not None and ((cached / marker).exists() if marker else True):
        return cached
    return local          # let the caller report the missing path


ASR_DIRS = {
    "fp32": _pick(PIPE / "ai4bharat" / "indic-conformer-600m-multilingual",
                  "ai4bharat/indic-conformer-600m-multilingual", "model_onnx.py"),
    "int8": PIPE / "ai4bharat-int8" / "indic-conformer-600m-multilingual",
}
# Hard ceiling for the ASR session's CUDA arena, in bytes.
# 1.5 GB leaves the encoder plenty of room while keeping the
# whole-process peak inside an 8 GB unified-memory budget.
ASR_GPU_MEM_LIMIT = 1536 * 1024 * 1024

NMT_DIR = PIPE / "nmt" / "indicTrans2"
FS2_DIR = _pick(PIPE / "smtiitm" / "Fastspeech2_HS",
                "smtiitm/Fastspeech2_HS", "inference.py")

FS2_LANG = {"hi": "hindi", "bn": "bengali", "mr": "marathi", "ta": "tamil",
            "te": "telugu", "kn": "kannada", "gu": "gujarati", "pa": "punjabi",
            "ml": "malayalam", "or": "odia"}



# ---------------------------------------------------------------- resources
#
# What each stage costs, measured rather than estimated, because the whole
# point of the exercise is deciding what fits on an 8 GB Jetson.
#
# VRAM is read from torch's own allocator AND from nvidia-smi. They answer
# different questions and both matter: torch.max_memory_allocated is the
# tensor high-water mark, while nvidia-smi shows what the process actually
# holds from the driver, which includes the CUDA context and the ONNX
# Runtime arena. ORT does not allocate through torch at all, so on the ASR
# stage the torch number alone would read as nearly zero and be nonsense.

def _nvidia_smi_mb():
    """MiB in use on GPU 0, or None when there is no GPU."""
    try:
        import subprocess
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return None


def _dir_mb(p: Path) -> float:
    try:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1048576
    except Exception:
        return 0.0


class Resources:
    """Peak GPU and host memory around a block of work."""

    def __init__(self, torch_mod=None):
        self.torch = torch_mod
        self.rows = {}

    def snapshot(self, label: str):
        gpu = _nvidia_smi_mb()
        t_alloc = t_peak = None
        if self.torch is not None and self.torch.cuda.is_available():
            t_alloc = self.torch.cuda.memory_allocated() / 1048576
            t_peak = self.torch.cuda.max_memory_allocated() / 1048576
        rss = None
        try:
            import resource
            # ru_maxrss is KB on Linux, bytes on macOS. The box is Linux.
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        except Exception:
            try:
                import psutil
                rss = psutil.Process().memory_info().rss / 1048576
            except Exception:
                pass
        self.rows[label] = {
            "gpu_used_mb": gpu,
            "torch_alloc_mb": None if t_alloc is None else round(t_alloc, 1),
            "torch_peak_mb": None if t_peak is None else round(t_peak, 1),
            "host_rss_mb": None if rss is None else round(rss, 1),
        }
        return self.rows[label]

    def reset_peak(self):
        if self.torch is not None and self.torch.cuda.is_available():
            self.torch.cuda.reset_peak_memory_stats()


class Pipeline:
    def __init__(self, asr_variant: str = "fp32", tts: str = "fastspeech2",
                 asr_device: str = "cuda") -> None:
        self.asr_device = asr_device
        import torch
        from transformers import AutoModel

        self.torch = torch
        self.asr_variant = asr_variant
        self.tts_kind = tts

        d = ASR_DIRS[asr_variant]
        if not d.exists():
            raise SystemExit(f"ASR '{asr_variant}' not built at {d}")
        self._asr_dir = d
        self._build_asr()

    def _build_asr(self):
        # torch was a local in __init__ before this method was split out of it.
        import torch
        self.torch = torch
        d = self._asr_dir
        asr_variant = self.asr_variant
        print(f"[load] ASR IndicConformer 600M ({asr_variant})", flush=True)
        # Its own from_pretrained() calls snapshot_download() unconditionally,
        # so a local directory is rejected as a malformed repo id and the whole
        # 2.7 GB would be fetched again. The class itself takes a ts_folder, so
        # load the module the repo ships and construct against our own copy -
        # which is also what makes the int8 twin loadable at all, since it
        # exists only on disk.
        # Cap ONNX Runtime's CUDA arena before the session is built.
        #
        # Measured: the ASR session sits at +158 MB after its first call and
        # climbs to +3114 MB by the fortieth. That is not the model - it is the
        # arena allocator caching every block it has ever needed and never
        # returning it. It set the whole run's peak at 4.6 GB, and swapping
        # FastSpeech2 for VITS moved that peak by only 200 MB because TTS was
        # never what caused it.
        #
        # kSameAsRequested stops the default kNextPowerOfTwo over-allocation,
        # and gpu_mem_limit is a hard ceiling. On an 8 GB Jetson an unbounded
        # arena is the difference between running and being OOM-killed.
        import onnxruntime as _ort
        _orig_session = _ort.InferenceSession

        def _capped_session(*sa, **kw):
            provs = kw.get("providers") or (sa[1] if len(sa) > 1 else None)
            if provs and "CUDAExecutionProvider" in provs:
                # The ASR is not one session, it is 28: the encoder, a CTC and
                # an RNNT decoder, three joint nets, and one joint_post_net per
                # language for 22 languages. Each opens its own CUDA arena, so
                # a per-session cap bounds nothing in aggregate - capping at
                # 1.5 GB each actually pushed the peak UP, to 4963 MB.
                #
                # Only the encoder is worth putting on the GPU. It holds
                # essentially all 600M parameters; everything else is a few MB
                # and runs fine on CPU, where it costs no VRAM and no arena.
                model_path = str(sa[0] if sa else kw.get("path_or_bytes", ""))
                # --asr-device cpu puts every ASR session on CPU. On a Jetson
                # the memory is unified, so CPU-side ORT draws from the same
                # 8 GB pool but opens no CUDA arena at all - which is the thing
                # that was setting the peak.
                on_gpu = (self.asr_device == "cuda"
                          and model_path.endswith("encoder.onnx"))
                kw["providers"] = ([
                    ("CUDAExecutionProvider", {
                        "arena_extend_strategy": "kSameAsRequested",
                        "gpu_mem_limit": ASR_GPU_MEM_LIMIT,
                    }),
                    "CPUExecutionProvider",
                ] if on_gpu else ["CPUExecutionProvider"])
                if len(sa) > 1:
                    sa = (sa[0],) + sa[2:]
            return _orig_session(*sa, **kw)

        _ort.InferenceSession = _capped_session

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            f"iasr_{asr_variant}", str(d / "model_onnx.py"))
        iasr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(iasr)
        try:
            self.asr = iasr.IndicASRModel(iasr.IndicASRConfig(ts_folder=str(d)))
        finally:
            _ort.InferenceSession = _orig_session
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            self.asr = self.asr.to(self.dev)
        except Exception:
            self.dev = "cpu"
        print(f"       running on {self.dev}", flush=True)

        print("[load] NMT IndicTrans2 indic-en", flush=True)
        from inference.engine import Model
        self.nmt_in = Model(str(NMT_DIR / "checkpoints" / "indic-en" / "ct2_int8_model"),
                            device="cpu", input_lang_code_format="iso",
                            model_type="ctranslate2")
        self.nmt_out = None

        print("[load] Krishi RAG", flush=True)
        from grounding import CoverageGate, build_response, lookup_treatment
        from okf import load_bundle
        from phonetic import PhoneticIndex
        from retrieval import HybridRetriever
        from router import Route, build_product_index, route
        self._build_response, self._lookup = build_response, lookup_treatment
        self._route, self._Route = route, Route
        self._PI = PhoneticIndex
        concepts = load_bundle(RAG / "bundle")
        self.by_id = {c.concept_id: c for c in concepts}
        self.retriever = HybridRetriever.load(RAG / "index" / "krishi.pkl")
        self.gate = CoverageGate(self.by_id)
        self.products = build_product_index(concepts)

        self._fs2 = None
        self._vocoder = None
        self._pre = None
        print("[load] ready\n", flush=True)

    # ---------------------------------------------------------------- stages
    def _ensure_asr(self):
        """Rebuild the ASR if a swap dropped it. Costs ~3s, frees 2169 MB."""
        if getattr(self, "asr", None) is not None:
            return
        self._build_asr()

    def transcribe(self, wav: Path, lang: str) -> str:
        self._ensure_asr()
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
        if not text.strip():
            return ""
        return self.nmt_in.paragraphs_batch_translate__multilingual(
            [[text, src, "en"]])[0]

    def to_native(self, text: str, tgt: str) -> str:
        """English answer back to the farmer's language.

        Deliberately NOT paragraphs_batch_translate__multilingual: for an
        English source that routes through MosesSentenceSplitter, which shells
        out to a Perl subprocess and died with a MemoryError on the very first
        case here. batch_translate takes already-split sentences and touches
        none of that. Splitting on sentence-final punctuation is enough because
        RAG answers are two or three short sentences by construction.
        """
        import re
        if not text.strip():
            return ""
        if self.nmt_out is None:
            from inference.engine import Model
            self.nmt_out = Model(
                str(NMT_DIR / "checkpoints" / "en-indic" / "ct2_int8_model"),
                device="cpu", input_lang_code_format="iso",
                model_type="ctranslate2")
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
        if not sents:
            return ""
        out = self.nmt_out.batch_translate(sents, "en", tgt)
        return " ".join(out)

    def diagnose(self, english: str):
        d = self._route(english, has_image=False, crop=None,
                        coverage_gate=self.gate, product_names=self.products,
                        product_index=self._PI(self.products),
                        crop_index=self._PI(self.gate.canonical))
        if d.route == self._Route.PESTICIDE and d.product:
            return self._lookup(d.product, self.by_id), d
        if not d.needs_retrieval:
            from grounding import Outcome, Response
            return Response(outcome=Outcome.OUT_OF_SCOPE,
                            spoken_text="(model may answer this directly)"), d
        return self._build_response(
            english, self.retriever, self.by_id, crop=d.crop,
            require_crop=d.route in (self._Route.DIAGNOSE,),
            boost_source=d.boost_source), d

    def _load_fs2(self):
        """FastSpeech2_HS uses its own text frontend and relative paths.

        Its repo ships an inference.py at the root AND another inside hifigan/,
        so a bare `import inference` picks the wrong one. It must be loaded by
        explicit path, and the working directory has to be the repo root
        because the model config files are addressed relatively.
        """
        import importlib.util
        import os
        cwd = os.getcwd()
        os.chdir(FS2_DIR)
        sys.path.insert(0, str(FS2_DIR))
        sys.path.insert(0, str(FS2_DIR / "hifigan"))
        spec = importlib.util.spec_from_file_location(
            "fs2_root_inference", str(FS2_DIR / "inference.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        os.chdir(cwd)
        self._fs2 = mod
        self._pre = {"dur": mod.TTSDurAlignPreprocessor(),
                     "char": mod.CharTextPreprocessor()}
        self._phone_dict = {}

    # ------------------------------------------------------------ VITS
    #
    # AI4Bharat's RASA VITS. Non-autoregressive, one model for many languages,
    # and 154 MB on disk against FastSpeech2's 1537 MB for Hindi alone.
    #
    # It MUST be loaded through AutoModel with trust_remote_code. The repo
    # declares architectures=['IndicVitsModel'] with an auto_map to its own
    # modeling_vits.py; loading it as the stock transformers VitsModel appears
    # to succeed while reporting every decoder weight as MISSING - all 12
    # resblocks and all 4 upsamplers get randomly initialised. It then emits
    # noise, but with a correctly shaped waveform and a plausible timing
    # figure, so nothing downstream notices.
    VITS_REPO = "ai4bharat/vits_rasa_13"
    VITS_LANG_ID = {"hi": 0, "bn": 1, "gu": 2, "kn": 3, "ml": 4,
                    "mr": 5, "or": 6, "pa": 7, "ta": 8, "te": 9}

    def _load_vits(self):
        from transformers import AutoModel, AutoTokenizer
        self._vits_tok = AutoTokenizer.from_pretrained(
            self.VITS_REPO, trust_remote_code=True)
        self._vits = AutoModel.from_pretrained(
            self.VITS_REPO, trust_remote_code=True).to(self.dev).eval()

    def _speak_vits(self, text: str, lang: str, out_path: Path) -> float:
        import numpy as np
        from scipy.io.wavfile import write as wavwrite
        if getattr(self, "_vits", None) is None:
            self._load_vits()
        # Synthesise sentence by sentence, not the whole answer at once.
        #
        # VITS is non-autoregressive: one forward pass produces the entire
        # waveform, so the intermediate tensors scale with utterance length.
        # Loading the model costs 440 MB, but generating a full RAG answer in a
        # single pass spiked GPU memory to 2411 MB - it was the largest single
        # allocation in the whole pipeline, and a four-sentence bench never saw
        # it because the sentences were short.
        #
        # Splitting on sentence boundaries caps the largest tensor at one
        # sentence. The audio is identical apart from the joins, and RAG
        # answers are already short declarative sentences by construction.
        import re as _re
        parts = [x.strip() for x in _re.split(r"(?<=[।.!?])\s+", text.strip()) if x.strip()]
        if not parts:
            parts = [text]

        chunks = []
        sr = self._vits.config.sampling_rate
        for part in parts:
            ins = self._vits_tok(text=part, return_tensors="pt").to(self.dev)
            kw = {}
            try:
                kw["speaker_id"] = self.torch.tensor([16], device=self.dev)
                kw["lang_id"] = self.torch.tensor(
                    [self.VITS_LANG_ID.get(lang, 0)], device=self.dev)
            except Exception:
                kw = {}
            with self.torch.no_grad():
                try:
                    out = self._vits(**ins, **kw)
                except TypeError:
                    out = self._vits(**ins)
            chunks.append(out.waveform[0].detach().cpu().numpy().astype("float32"))
            del out, ins
            # Hand the block back rather than letting the caching allocator
            # hold every sentence's workspace for the rest of the run.
            if self.torch.cuda.is_available():
                self.torch.cuda.empty_cache()

        import numpy as _np
        gap = _np.zeros(int(sr * 0.12), dtype="float32")   # small pause at joins
        wav = _np.concatenate(
            [c for pair in zip(chunks, [gap] * len(chunks)) for c in pair][:-1])
        wavwrite(str(out_path), sr, (wav * 32767).astype("int16"))
        return len(wav) / sr

    # ------------------------------------------------------------ parler
    #
    # David's int4 AWQ export, loaded through his tts_exports module. It ships
    # a state_dict.pt rather than safetensors, so the stock from_pretrained
    # cannot read it - his QuantizedParlerTTS wrapper is the supported path,
    # and it is also what provides load()/unload().
    PARLER_DESC = ("A female speaker delivers a clear and steady explanation in "
                   "a calm voice, with very close recording and almost no "
                   "background noise.")

    def _load_parler(self):
        import sys as _sys
        _sys.path.insert(0, str(Path.home() / "vyoma_hackathon"))
        from tts_exports import QuantizedParlerTTS, TTSInferencer
        self._parler_engine = QuantizedParlerTTS()
        self._parler_engine.load()
        self._parler = TTSInferencer(self._parler_engine)

    def _speak_parler(self, text: str, lang: str, out_path: Path) -> float:
        import soundfile as sf
        if getattr(self, "_parler", None) is None:
            self._load_parler()
        # Signature is synthesize(text, description, speaker, language, ...).
        # Passing lang positionally would land it in `description`, which is
        # the free-text voice prompt - the model would try to read it aloud.
        out = self._parler.synthesize(text, description=self.PARLER_DESC,
                                      language=lang)
        wav, sr = out if isinstance(out, tuple) else (out, 24000)
        import numpy as _np
        wav = _np.asarray(wav, dtype="float32").squeeze()
        sf.write(str(out_path), wav, sr)
        return len(wav) / sr

    # ------------------------------------------------- load / unload
    #
    # Ishaan's point: the stages run strictly in sequence, so only one need be
    # resident at a time and the peak becomes the largest single stage instead
    # of the sum. Measured to work - parler went 2258 MB -> 370 MB of GPU on
    # unload, FastSpeech2 760 MB -> 368 MB.
    def unload_tts(self) -> None:
        import gc
        eng = getattr(self, "_parler_engine", None)
        if eng is not None and hasattr(eng, "unload"):
            eng.unload()
        self._parler = None
        self._parler_engine = None
        self._vits = None
        self._mms = {}
        self._vocoder = None
        self._fs2_models = {}
        gc.collect()
        if self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()

    def unload_asr(self) -> None:
        import gc
        self.asr = None
        gc.collect()
        if self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()

    # -------------------------------------------------------------- MMS
    #
    # Meta's MMS-TTS: one small VITS per language, 145 MB each. Measured across
    # 18 Indian languages at 713 MB peak GPU and 0.059 s per utterance, the
    # smallest and fastest of everything tried.
    #
    # Licence is CC-BY-NC. Fine for the hackathon and for our own testing;
    # it would have to be replaced before anything is sold.
    MMS_LANG = {"hi": "hin", "bn": "ben", "mr": "mar", "te": "tel", "ta": "tam",
                "gu": "guj", "kn": "kan", "ml": "mal", "pa": "pan", "or": "ory",
                "as": "asm", "ur": "urd-script_arabic"}

    def _speak_mms(self, text: str, lang: str, out_path: Path) -> float:
        import numpy as np
        import soundfile as sf
        from transformers import AutoTokenizer, VitsModel

        code = self.MMS_LANG.get(lang, "hin")
        if not hasattr(self, "_mms"):
            self._mms = {}
        pair = self._mms.get(code)
        if pair is None:
            repo = "facebook/mms-tts-" + code
            tok = AutoTokenizer.from_pretrained(repo)
            m = VitsModel.from_pretrained(repo).to(self.dev).eval()
            pair = (tok, m)
            self._mms[code] = pair
        tok, m = pair

        ins = tok(text, return_tensors="pt").to(self.dev)
        with self.torch.no_grad():
            out = m(**ins)
        w = out.waveform[0].detach().cpu().numpy().astype("float32")
        sr = m.config.sampling_rate
        sf.write(str(out_path), w, sr)
        return len(w) / sr

    def speak(self, text: str, lang: str, out_path: Path) -> float:
        """Returns audio seconds. Writes a wav."""
        if self.tts_kind == "mms":
            return self._speak_mms(text, lang, out_path)
        if self.tts_kind == "parler":
            return self._speak_parler(text, lang, out_path)
        if self.tts_kind == "vits":
            return self._speak_vits(text, lang, out_path)
        import os
        if self._fs2 is None:
            self._load_fs2()
        fslang = FS2_LANG.get(lang, "hindi")
        cwd = os.getcwd()
        os.chdir(FS2_DIR)
        try:
            if self._vocoder is None:
                self._vocoder = self._fs2.load_hifigan_vocoder(
                    fslang, "female", self.dev)
            pre = self._pre["char"] if fslang in ("urdu", "punjabi") else self._pre["dur"]
            ptext, _ = pre.preprocess(text, fslang, "female", self._phone_dict)
            ptext = " ".join(ptext)

            # The shipped text_synthesis() calls load_fastspeech2_model() on
            # every invocation, so the whole model is rebuilt from disk for each
            # sentence. Caching it per language costs nothing and measured
            # 3288 MB -> 2173 MB unified, with load time 8.0s -> 0.5s.
            if not hasattr(self, "_fs2_models"):
                self._fs2_models = {}
            tts = self._fs2_models.get(fslang)
            if tts is None:
                tts = self._fs2.load_fastspeech2_model(fslang, "female", self.dev)
                self._fs2_models[fslang] = tts

            with self.torch.no_grad():
                out = tts(ptext, decode_conf={"alpha": 1.0})
                x = out["feat_gen_denorm"].T.unsqueeze(0) * 2.3262
                # The shipped text_synthesis() returned a host array; keep that
                # contract or the numpy conversion downstream fails.
                audio = self._vocoder(x.to(self.dev)).squeeze().detach().cpu().numpy()
        finally:
            os.chdir(cwd)
        import numpy as np
        from scipy.io.wavfile import write as wavwrite
        a = np.asarray(audio).squeeze()
        if a.dtype.kind == "f":
            a = (a * self._fs2.MAX_WAV_VALUE).astype("int16")
        else:
            a = a.astype("int16")
        wavwrite(str(out_path), self._fs2.SAMPLING_RATE, a)
        return len(a) / self._fs2.SAMPLING_RATE


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True,
                    help="folder name, e.g. fp32-fastspeech2")
    ap.add_argument("--asr", choices=["fp32", "int8"], default="fp32")
    ap.add_argument("--swap", action="store_true",
                    help="unload each model after its stage (Ishaan's plan)")
    ap.add_argument("--asr-device", default="cuda", choices=["cuda", "cpu"],
                    help="ONNX Runtime device for the ASR sessions")
    ap.add_argument("--tts", default="fastspeech2",
                    choices=["fastspeech2", "vits", "parler", "mms"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", type=int, nargs="*")
    a = ap.parse_args()

    cases = json.loads((TESTS / "manifest.json").read_text(encoding="utf-8"))
    if a.only:
        cases = [c for c in cases if c["id"] in a.only]
    if a.limit:
        cases = cases[:a.limit]

    import jiwer
    import asr_scoring as scoring

    root = HERE / a.config
    root.mkdir(parents=True, exist_ok=True)
    # Measure the cost of loading each model before any case runs, so the
    # per-stage numbers below are inference cost and not load cost.
    res = Resources()
    res.snapshot("00_baseline_before_any_model")
    t_load = time.time()
    p = Pipeline(asr_variant=a.asr, tts=a.tts, asr_device=a.asr_device)
    load_secs = round(time.time() - t_load, 2)
    try:
        res.torch = p.torch
    except Exception:
        pass
    res.snapshot("01_after_asr_and_nmt_loaded")

    # On-disk footprint. This is what has to fit on the device's SSD, and it is
    # a different number from what has to fit in memory.
    disk = {
        "asr_" + a.asr + "_mb": round(_dir_mb(ASR_DIRS[a.asr]), 1),
        "nmt_mb": round(_dir_mb(NMT_DIR), 1),
        "tts_fastspeech2_mb": round(_dir_mb(FS2_DIR), 1),
        "rag_bundle_mb": round(_dir_mb(RAG / "bundle"), 1),
        "rag_index_mb": round(_dir_mb(RAG / "index"), 1),
    }
    disk["total_mb"] = round(sum(disk.values()), 1)
    print("\n  ON DISK")
    for k, v in disk.items():
        print(f"    {k:24} {v:9.1f} MB")
    print(f"    {'model load time':24} {load_secs:9.2f} s\n")

    summary, t_all = [], time.time()
    for c in cases:
        cid = f"{c['id']:02d}"
        d = root / cid
        d.mkdir(exist_ok=True)
        rec: dict = {"id": c["id"], "category": c["category"],
                     "config": a.config, "asr_variant": a.asr,
                     "reference_hindi": c["reference_hindi"],
                     "expect": c["expect"], "must_not": c["must_not"]}
        print("=" * 78)
        print(f"CASE {cid}  [{c['category']}]  ->  {d}")
        print(f"  reference : {c['reference_hindi'][:70]}")
        try:
            src = TESTS / c["audio"]
            shutil.copy2(src, d / f"01_input{src.suffix}")

            # Length of the clip itself. Every speed number below is reported
            # per second of audio as well as per case, because a 3 s question
            # and a 15 s question are not comparable otherwise, and the Jetson
            # decision depends on the ratio, not the absolute.
            try:
                import soundfile as _sf
                _info = _sf.info(str(src))
                rec["audio_seconds"] = round(_info.frames / _info.samplerate, 2)
            except Exception:
                rec["audio_seconds"] = None

            res.reset_peak()
            t = time.time()
            heard = p.transcribe(src, c["lang"])
            rec["t_asr"] = round(time.time() - t, 2)
            rec["res_after_asr"] = res.snapshot(f"case{cid}_asr")
            if a.swap:
                # The ASR is the single biggest item in the stack: 2169 MB of
                # 4817, mostly its 28 ONNX Runtime sessions and their arenas.
                # It has finished for this question and is not needed again
                # until the next one, so drop it before the TTS loads. This is
                # the swap that actually matters - unloading the 142 MB of
                # FastSpeech2 weights never could.
                p.unload_asr()
                rec["res_after_asr_unload"] = res.snapshot(f"case{cid}_asr_unloaded")
            nr, nh = scoring.normalise(c["reference_hindi"]), scoring.normalise(heard)
            rec["asr_text"] = heard
            rec["asr_wer"] = round(100 * jiwer.wer(nr, nh), 1) if nr else None
            rec["asr_cer"] = round(100 * jiwer.cer(nr, nh), 1) if nr else None
            (d / "02_asr.txt").write_text(
                f"REFERENCE (human annotator):\n{c['reference_hindi']}\n\n"
                f"ASR HEARD ({a.asr}):\n{heard}\n\n"
                f"WER {rec['asr_wer']}%   CER {rec['asr_cer']}%   "
                f"{rec['t_asr']}s\n", encoding="utf-8")
            print(f"  ASR       : {heard[:70]}")
            print(f"              WER {rec['asr_wer']}%  CER {rec['asr_cer']}%")

            t = time.time()
            eng = p.to_english(heard, c["lang"])
            rec["t_nmt_in"] = round(time.time() - t, 2)
            rec["english"] = eng
            (d / "03_nmt_en.txt").write_text(
                f"HINDI IN:\n{heard}\n\nENGLISH OUT (what the RAG sees):\n{eng}\n",
                encoding="utf-8")
            print(f"  English   : {eng[:70]}")

            t = time.time()
            r, dec = p.diagnose(eng)
            rec["t_rag"] = round(time.time() - t, 2)
            labels = list(r.label_ids or [])
            rec.update({"route": dec.route.value,
                        "outcome": str(r.outcome).replace("Outcome.", ""),
                        "condition": r.condition_id,
                        "label_ids": labels,
                        "answer_en": r.spoken_text,
                        "confidence": getattr(r, "confidence", None)})
            (d / "04_rag.json").write_text(json.dumps({
                "query_english": eng, "route": dec.route.value,
                "route_reason": dec.reason, "outcome": rec["outcome"],
                "condition_id": r.condition_id, "condition": r.condition,
                "label_ids": labels, "confidence": rec["confidence"],
                "trust_tier": getattr(r, "trust_tier", None),
                "runner_up": getattr(r, "runner_up", None),
                "treatments": getattr(r, "treatments", None),
                "spoken_text": r.spoken_text,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            (d / "05_answer_en.txt").write_text(r.spoken_text or "", encoding="utf-8")
            print(f"  RAG       : {rec['outcome']}  {r.condition_id}")
            print(f"              prescribed: {labels or '(nothing)'}")

            t = time.time()
            back = p.to_native(r.spoken_text or "", c["lang"])
            rec["t_nmt_out"] = round(time.time() - t, 2)
            rec["answer_native"] = back
            (d / "06_nmt_back.txt").write_text(
                f"ENGLISH:\n{r.spoken_text}\n\nBACK TO {c['lang'].upper()}:\n{back}\n",
                encoding="utf-8")
            print(f"  reply     : {back[:70]}")

            if back.strip():
                t = time.time()
                secs = p.speak(back, c["lang"], d / "07_output.wav")
                rec["t_tts"] = round(time.time() - t, 2)
                rec["res_after_tts"] = res.snapshot(f"case{cid}_tts")
                if a.swap:
                    # Drop the TTS before the next case's ASR. On the Orin the
                    # pool is shared, so what matters is never holding two
                    # large models at once - not which device they sit on.
                    p.unload_tts()
                    rec["res_after_tts_unload"] = res.snapshot(f"case{cid}_tts_unloaded")
                rec["tts_audio_seconds"] = round(secs, 2)
                print(f"  TTS       : {secs:.1f}s audio in {rec['t_tts']}s")

            # The one machine-checkable safety property.
            if c["category"] in ("deficiency_like", "deficiency_khaira",
                                 "nutrient_question", "out_of_scope",
                                 "uncovered_crop"):
                rec["auto_check"] = "SAFE" if not labels else \
                    "UNSAFE - prescribed a pesticide for a non-disease"
                print(f"  check     : {rec['auto_check']}")
            rec["status"] = "ok"
            # A re-run that succeeds must clear the previous run's marker.
            # Without this, 34 cases carried an ERROR.txt from a run that died
            # on a full disk while their case.json said status=ok, which reads
            # as a failed run to anyone browsing the folder.
            stale = d / "ERROR.txt"
            if stale.exists():
                stale.rename(d / "ERROR-cleared-by-later-successful-run.txt")
        except Exception as e:
            rec["status"] = "error"
            rec["error"] = traceback.format_exc()[-1200:]
            (d / "ERROR.txt").write_text(rec["error"], encoding="utf-8")
            print(f"  ERROR     : {str(e)[:100]}")

        (d / "case.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append(rec)
        print()

    (root / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    done = [r for r in summary if r.get("status") == "ok"]
    wers = [r["asr_wer"] for r in done if r.get("asr_wer") is not None]
    unsafe = [r for r in summary if "UNSAFE" in str(r.get("auto_check", ""))]
    errs = [r for r in summary if r.get("status") == "error"]
    print("=" * 78)
    print(f"SUMMARY  config={a.config}  asr={a.asr}  tts={a.tts}")
    print("=" * 78)
    print(f"  completed        : {len(done)}/{len(summary)}"
          f"{'   errors: ' + ','.join(str(r['id']) for r in errs) if errs else ''}")
    if wers:
        print(f"  ASR mean WER     : {sum(wers)/len(wers):.1f}%")
        cers = [r["asr_cer"] for r in done if r.get("asr_cer") is not None]
        print(f"  ASR mean CER     : {sum(cers)/len(cers):.1f}%")
    print(f"  unsafe prescribes: {len(unsafe)}"
          f"{'  -> cases ' + ','.join(str(r['id']) for r in unsafe) if unsafe else ''}")
    print(f"  wall clock       : {time.time()-t_all:.0f}s")

    # --- speed per second of audio -------------------------------------
    ok = [r for r in summary if r.get("status") == "ok" and r.get("audio_seconds")]
    if ok:
        tot_audio = sum(r["audio_seconds"] for r in ok)
        print(f"\n  SPEED   ({len(ok)} clips, {tot_audio:.0f}s of audio total)")
        print(f"    {'stage':12} {'mean s/case':>12} {'s per audio-s':>15} {'xRT':>8}")
        for key, label in (("t_asr", "ASR"), ("t_nmt_in", "NMT in"),
                           ("t_rag", "RAG"), ("t_nmt_out", "NMT out"),
                           ("t_tts", "TTS")):
            vals = [r[key] for r in ok if r.get(key) is not None]
            if not vals:
                continue
            tot = sum(vals)
            per_audio = tot / tot_audio
            # xRT: how many times faster than real time. Above 1 means the
            # stage keeps up with speech; below 1 means the farmer waits.
            print(f"    {label:12} {tot/len(vals):12.2f} {per_audio:15.3f} "
                  f"{(1/per_audio if per_audio else 0):8.1f}")
        end2end = sum(sum(r.get(k) or 0 for k in
                          ("t_asr", "t_nmt_in", "t_rag", "t_nmt_out", "t_tts"))
                      for r in ok)
        print(f"    {'END TO END':12} {end2end/len(ok):12.2f} "
              f"{end2end/tot_audio:15.3f} {(tot_audio/end2end):8.1f}")

    # --- memory --------------------------------------------------------
    print("\n  MEMORY")
    print(f"    {'point':34} {'GPU MB':>9} {'torch peak':>11} {'host RSS':>10}")
    for label in ("00_baseline_before_any_model", "01_after_asr_and_nmt_loaded"):
        r = res.rows.get(label)
        if r:
            print(f"    {label:34} {str(r['gpu_used_mb']):>9} "
                  f"{str(r['torch_peak_mb']):>11} {str(r['host_rss_mb']):>10}")
    gpu_peak = max((v["gpu_used_mb"] or 0) for v in res.rows.values()) if res.rows else 0
    host_peak = max((v["host_rss_mb"] or 0) for v in res.rows.values()) if res.rows else 0
    print(f"    {'PEAK across whole run':34} {gpu_peak:9} {'':>11} {host_peak:10.1f}")

    resource_report = {
        "config": a.config, "asr_variant": a.asr, "tts": a.tts,
        "disk_mb": disk, "model_load_seconds": load_secs,
        "gpu_peak_mb": gpu_peak, "host_peak_rss_mb": host_peak,
        "snapshots": res.rows,
    }
    (root / "_resources.json").write_text(
        json.dumps(resource_report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  artefacts        : {root}")
    return 1 if unsafe else 0


if __name__ == "__main__":
    raise SystemExit(main())
