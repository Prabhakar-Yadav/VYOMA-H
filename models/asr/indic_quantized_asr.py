"""Per-language, torch-free, INT8-quantized IndicConformer CTC ASR -- vendored from
`model_quantizer/indic_quantized_asr.py` (blue-parrot repo root). See
`model_quantizer/asr_indic_confirmer_quantizer.py` for how these artifacts are produced
(AI4Bharat's real per-language `.nemo` hybrid RNNT-CTC checkpoint -> NeMo's own
`EncDecCTCModel.export()` with `cur_decoder='ctc'` -> CTC-only ONNX graph -> `quantize_dynamic`
INT8 weights) and `model_quantizer/asr_compression_and_quantization.ipynb` for the real
end-to-end run that produced the checkpoints under `models/checkpoints/indic-conformer-quantized/`.

**Why this replaces `ctc_only.py`/`model_loader.py`'s multilingual-model approach**: that fix
cut ONNX Runtime session count (29 -> 3) on top of the same large *shared, 22-language* encoder
(~2.4GB). This is a different, larger lever -- a genuinely single-language encoder (exported
directly from AI4Bharat's per-language checkpoint, not sliced out of the multilingual one) that's
already an order of magnitude smaller before quantization even applies, plus INT8 dynamic
quantization on top. Measured directly (GX10, see `ASR_QUANTIZED_TIMING.md`): 0.78s load / +302MB
vs the multilingual CTC-only fix's 2.76-2.9GB / 9-46s. Runs CPU-only (`CPUExecutionProvider`) --
deliberately, not a limitation: at this size, CPU is fast enough (RTF 0.17-0.28 observed) that
GPU's CUDA-session-build overhead (the dominant cost fought throughout this investigation) isn't
worth paying for.

**Correctness**: verified directly against the multilingual model's output on the same real
audio files -- Hindi came back byte-identical; Tamil/Malayalam showed small character-level
differences (expected INT8 quantization accuracy loss, not a decoding bug -- both old and new
model garble the same word in one Malayalam sample, a pre-existing model weakness either way).

**2026-08-13 update -- provider selection is now device-conditional, not hardcoded CPU**: the
"CPU is fast enough" call above was measured on GX10's CPU (RTF 0.17-0.28) and does NOT hold on
Jetson Orin's much weaker CPU cores -- measured directly on real Jetson hardware post-recovery:
RTF 3.83 on CPU (34.5s to transcribe a 9s clip -- a real, severe per-turn latency problem for a
voice assistant) vs RTF 0.03 on CUDA (~130x faster, same session's `onnxruntime-gpu` wheel built
for JetPack 7.2/sm_87), at a real, measured cost of +1.9GB RSS (session build + CUDA context,
unified memory) for the CUDA path. `load()` now picks CUDA when `onnxruntime-gpu`'s
CUDAExecutionProvider is actually importable (Jetson), and silently stays CPU-only otherwise
(GX10, which only installs plain `onnxruntime`, not `-gpu`, per `requirements.txt`) -- no
platform-sniffing needed, `ort.get_available_providers()` already reflects which wheel is
installed. `load()` also now warms up both librosa's first-call JIT cost and (CUDA only) the
session's own first-call kernel-selection cost, so neither lands on a real user's first
question -- see the inline comments in `load()` for the real numbers behind each.

Only CTC decoding exists in this export -- there is no RNNT path here at all, not even an
optional one (unlike `ctc_only.py`, which chose not to build RNNT sessions from a hybrid model
that still has them). `transcribe()` has no `decoding=` parameter for that reason.

Expects a directory structured like:
    models/
      hi/
        indicconformer_hi_ctc.int8.onnx
        tokens.txt
        config.json
      ta/
        ...
      ml/
        ...

Usage:
    asr = IndicConformerASR(base_dir='models/checkpoints/indic-conformer-quantized', lang='hi')
    asr.load()
    text = asr.transcribe('sample.wav')
    asr.unload()
"""
import os
import gc
import json
import time
import numpy as np
import librosa
import onnxruntime as ort
import psutil


def _rss_mb():
    """Current process resident memory in MB."""
    return psutil.Process(os.getpid()).memory_info().rss / (1024 ** 2)


class IndicConformerASR:
    """
    Generic loader for any AI4Bharat IndicConformer language export.

    Expects a directory structured like:
        models/
          ml/
            model.int8.onnx
            tokens.txt
            preprocessor_config.json
          hi/
            model.int8.onnx
            tokens.txt
            preprocessor_config.json
          ...

    Usage:
        asr = IndicConformerASR(base_dir='models', lang='ml')
        asr.load()
        text = asr.transcribe('sample.wav')
        asr.unload()
    """

    def __init__(self, base_dir, lang,
                 onnx_filename='model.int8.onnx',
                 tokens_filename='tokens.txt',
                 config_filename='config.json'):
        self.lang = lang
        self.model_dir = os.path.join(base_dir, lang)
        self.onnx_path = os.path.join(self.model_dir, onnx_filename)
        self.tokens_path = os.path.join(self.model_dir, tokens_filename)
        self.config_path = os.path.join(self.model_dir, config_filename)

        self.sess = None
        self.vocab = None
        self.blank_id = None
        self.cfg = None

    def load(self):
        mem_before = _rss_mb()
        t0 = time.perf_counter()

        with open(self.config_path) as f:
            self.cfg = json.load(f)

        vocab = []
        with open(self.tokens_path) as f:
            for line in f:
                token, idx = line.rsplit(' ', 1)
                vocab.append(token)
        self.vocab = vocab
        self.blank_id = len(vocab) - 1

        # CUDA when the installed onnxruntime wheel actually provides it (Jetson's
        # onnxruntime-gpu), CPU-only fallback otherwise (GX10's plain onnxruntime) -- see the
        # 2026-08-13 module-docstring note for the real RTF numbers that motivated this.
        #
        # cudnn_conv_algo_search="HEURISTIC" (2026-08-13, was unset -- CUDAExecutionProvider's
        # own real default is "EXHAUSTIVE") -- real, confirmed root cause of a separate, much
        # bigger regression: real production ASR calls (through the actual gateway/orchestrator
        # pipeline, both pocketinfer's app and test_orchestrated_pipeline.py independently) were
        # measured at 8-33s per call, vs 0.03-0.05 RTF (0.2-0.5s) for the exact same model/audio
        # called directly in an isolated script -- confirmed NOT explained by memory pressure,
        # background-process contamination, network/HTTP overhead, CPU nice/cgroup restriction,
        # or GPU-activity adjacency to a real Ollama generation (all directly tested and ruled
        # out). EXHAUSTIVE mode makes cuDNN actually run and time every candidate convolution
        # algorithm for each new input shape it sees before picking one -- real audio clips are
        # different lengths turn to turn, so the Conformer's subsampling conv layers see a new
        # shape on nearly every real call, paying this real timed-search cost fresh each time
        # (this session's own load()-time dummy warmup below only ever primes ONE fixed shape,
        # so it can't cover this). HEURISTIC picks a good algorithm immediately via cuDNN's own
        # fast heuristics instead of timing every candidate -- the standard, documented fix for
        # exactly this onnxruntime CUDA EP gotcha. No effect on the CPU-only fallback path.
        providers = ([("CUDAExecutionProvider", {"cudnn_conv_algo_search": "HEURISTIC"}), "CPUExecutionProvider"]
                     if 'CUDAExecutionProvider' in ort.get_available_providers()
                     else ['CPUExecutionProvider'])
        self.sess = ort.InferenceSession(self.onnx_path, providers=providers)
        self.active_providers = self.sess.get_providers()

        # librosa's own first real STFT/mel-spectrogram call pays a separate, real ~3.2s
        # one-time cost (numba JIT-compiling its DSP code, confirmed directly by timing a
        # fresh-process first call vs a second call: 3.2s -> 0.02s) -- and this is completely
        # unrelated to onnxruntime/CUDA, it hits the CPU-only path (GX10) exactly as hard.
        # Absorb it here, for every provider, with a short synthetic silence buffer (no real
        # audio file needed) instead of paying it on a real user's first question.
        sr = self.cfg['sample_rate']
        dummy_audio = np.zeros(sr * 2, dtype=np.float32)
        librosa.feature.melspectrogram(
            y=dummy_audio, sr=sr, n_fft=self.cfg['n_fft'],
            hop_length=int(self.cfg['window_stride'] * sr),
            win_length=int(self.cfg['window_size'] * sr),
            n_mels=self.cfg['features'], window=self.cfg['window'],
        )

        if 'CUDAExecutionProvider' in self.active_providers:
            # CUDA's first real call also pays its own one-time kernel-selection cost on top
            # of session creation -- absorb that here too with a throwaway synthetic input.
            n_mels = self.cfg['features']
            dummy_signal = np.zeros((1, n_mels, 1000), dtype=np.float32)
            dummy_length = np.array([1000], dtype=np.int64)
            self.sess.run(['logprobs'], {'audio_signal': dummy_signal, 'length': dummy_length})

        t1 = time.perf_counter()
        mem_after = _rss_mb()

        stats = {
            "lang": self.lang,
            "load_time_s": round(t1 - t0, 3),
            "rss_before_mb": round(mem_before, 1),
            "rss_after_mb": round(mem_after, 1),
            "delta_mb": round(mem_after - mem_before, 1),
            "providers": self.active_providers,
        }
        print(f"[load:{self.lang}] time={stats['load_time_s']}s "
              f"RSS {stats['rss_before_mb']}MB -> {stats['rss_after_mb']}MB "
              f"(+{stats['delta_mb']}MB) providers={self.active_providers}")
        return stats

    def unload(self):
        mem_before = _rss_mb()
        t0 = time.perf_counter()

        self.sess = None
        self.vocab = None
        self.cfg = None
        gc.collect()

        t1 = time.perf_counter()
        mem_after = _rss_mb()

        stats = {
            "lang": self.lang,
            "unload_time_s": round(t1 - t0, 3),
            "rss_before_mb": round(mem_before, 1),
            "rss_after_mb": round(mem_after, 1),
            "freed_mb": round(mem_before - mem_after, 1),
        }
        print(f"[unload:{self.lang}] time={stats['unload_time_s']}s "
              f"RSS {stats['rss_before_mb']}MB -> {stats['rss_after_mb']}MB "
              f"(freed {stats['freed_mb']}MB)")
        return stats

    def _extract_features(self, wav_path):
        sr = self.cfg['sample_rate']
        n_mels = self.cfg['features']
        n_fft = self.cfg['n_fft']
        win_length = int(self.cfg['window_size'] * sr)
        hop_length = int(self.cfg['window_stride'] * sr)

        audio, _ = librosa.load(wav_path, sr=sr, mono=True)
        mel = librosa.feature.melspectrogram(
            y=audio, sr=sr, n_fft=n_fft, hop_length=hop_length,
            win_length=win_length, n_mels=n_mels, window=self.cfg['window']
        )
        log_mel = np.log(mel + 1e-5)
        log_mel = (log_mel - log_mel.mean(axis=1, keepdims=True)) / (
            log_mel.std(axis=1, keepdims=True) + 1e-5
        )
        return log_mel.astype(np.float32)

    def _ctc_greedy_decode(self, logprobs):
        ids = logprobs[0].argmax(axis=-1)
        tokens, prev = [], None
        for i in ids:
            if i != self.blank_id and i != prev:
                tokens.append(self.vocab[i])
            prev = i
        return ''.join(tokens).replace('▁', ' ').strip()

    def transcribe(self, wav_path, verbose=True):
        if self.sess is None:
            raise RuntimeError(f"Model for '{self.lang}' not loaded — call .load() first.")

        t0 = time.perf_counter()
        feats = self._extract_features(wav_path)
        audio_signal = feats[np.newaxis, :, :]
        length = np.array([feats.shape[1]], dtype=np.int64)
        logprobs = self.sess.run(['logprobs'], {'audio_signal': audio_signal, 'length': length})[0]
        text = self._ctc_greedy_decode(logprobs)
        t1 = time.perf_counter()

        if verbose:
            duration_s = feats.shape[1] * (self.cfg['window_stride'])
            rtf = (t1 - t0) / duration_s if duration_s > 0 else float('nan')
            print(f"[transcribe:{self.lang}] infer_time={t1 - t0:.3f}s "
                  f"audio_dur={duration_s:.2f}s RTF={rtf:.3f}")

        return text
