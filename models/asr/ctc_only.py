"""A trimmed clone of the HF-cached `model_onnx.py` (ai4bharat/indic-conformer-600m-multilingual,
see model_loader.py's module docstring) that builds only the ONNX Runtime sessions the CTC decode
path actually touches.

**Why this exists**: the real `IndicASRModel.__init__` (the trust_remote_code class pulled from
the HF cache) eagerly creates 29 separate model artifacts at load time regardless of which
`decoding=` mode is ever used -- `preprocessor` (torch.jit) + `encoder` + `ctc_decoder` +
`rnnt_decoder` + `joint_enc` + `joint_pred` + `joint_pre_net` + one `joint_post_net_<lang>` ONNX
session PER of the 22 supported languages. `asr_worker.py` always calls `decoding="ctc"` in
production (the only place `decoding="rnnt"` is ever requested is the standalone comparison test,
`dev/local_model_test/test_asr_memory.py`) -- so 26 of those 29 loads (rnnt_decoder + the 3 joint_*
nets + all 22 joint_post_net_<lang> files) build real `ort.InferenceSession` objects, each paying
its own CUDA-EP session-creation overhead (graph parse, provider registration, CUDA context/kernel
setup), for a decode path that's never invoked. The RNNT-side files are individually small (57MB
total vs. the shared encoder's ~2.4GB, confirmed directly) so this isn't a checkpoint-size fix --
it's a session-count fix: 3 sessions/artifacts at load time (preprocessor, encoder, ctc_decoder)
instead of 29. See `dev/agents/api_server/TIMING_RESULTS.md` and `ASR_CTC_ONLY_TIMING.md` for the
measured before/after.

Only `decoding="ctc"` is supported -- `forward(..., decoding="rnnt")` raises clearly rather than
silently doing the wrong thing, since the RNNT-side sessions were never built.

Loaded from the exact same on-disk checkpoint as the full model (`ts_folder` = the same
`snapshot_download()`-resolved HF cache snapshot dir) -- no new download, no conversion, no new
dependency. `_ctc_decode`/`compute_timestamps` below are byte-for-byte the same logic as the
cached `model_onnx.py`'s (confirmed against `IndicASRModel`) since the CTC path never touches any
of the RNNT-only sessions we're skipping -- output should be identical to the full model's CTC
output for the same input.
"""
import json
import os

import torch
import onnxruntime as ort
from transformers import PretrainedConfig, PreTrainedModel


class IndicASRConfig(PretrainedConfig):
    model_type = "iasr_ctc_only"

    def __init__(self, ts_folder: str = "path", BLANK_ID: int = 256, FRAME_DURATION_MS: float = 0.08,
                 **kwargs):
        super().__init__(**kwargs)
        self.ts_folder = ts_folder
        self.BLANK_ID = BLANK_ID
        self.FRAME_DURATION_MS = FRAME_DURATION_MS


class IndicASRModelCTCOnly(PreTrainedModel):
    """CTC-only sibling of the cached `IndicASRModel` -- see module docstring for why."""

    config_class = IndicASRConfig
    # Names for which we build a real ort.InferenceSession -- everything RNNT/joint-net related
    # (rnnt_decoder, joint_enc, joint_pred, joint_pre_net, joint_post_net_<lang> x22) is skipped
    # entirely, matching the full model's `names` list minus those six-plus-22 entries.
    ONNX_SESSION_NAMES = ["encoder", "ctc_decoder"]

    def __init__(self, config):
        super().__init__(config)
        self.d = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if torch.cuda.is_available() \
            else ["CPUExecutionProvider"]

        self.models = {}
        self.models["preprocessor"] = torch.jit.load(
            f"{config.ts_folder}/assets/preprocessor.ts", map_location=self.d
        )
        for n in self.ONNX_SESSION_NAMES:
            path = f"{config.ts_folder}/assets/{n}.onnx"
            self.models[n] = ort.InferenceSession(path, providers=providers)

        with open(f"{config.ts_folder}/assets/vocab.json") as reader:
            self.vocab = json.load(reader)
        with open(f"{config.ts_folder}/assets/language_masks.json") as reader:
            self.language_masks = json.load(reader)

    def forward(self, wav, lang, decoding="ctc", compute_timestamps=None):
        if decoding != "ctc":
            raise ValueError(
                f"IndicASRModelCTCOnly only supports decoding='ctc' (got {decoding!r}) -- "
                "the rnnt_decoder/joint_* sessions were never built. Use the full "
                "trust_remote_code model (IndicConformerASR(ctc_only=False)) for RNNT."
            )
        encoder_outputs, encoded_lengths = self.encode(wav)
        return self._ctc_decode(encoder_outputs, encoded_lengths, lang, compute_timestamps)

    def encode(self, wav):
        audio_signal, length = self.models["preprocessor"](
            input_signal=wav.to(self.d), length=torch.tensor([wav.shape[-1]]).to(self.d)
        )
        outputs, encoded_lengths = self.models["encoder"].run(
            ["outputs", "encoded_lengths"],
            {"audio_signal": audio_signal.cpu().numpy(), "length": length.cpu().numpy()},
        )
        return outputs, encoded_lengths

    def _ctc_decode(self, encoder_outputs, encoded_lengths, lang, compute_timestamps=None):
        logprobs = self.models["ctc_decoder"].run(["logprobs"], {"encoder_output": encoder_outputs})[0]
        logprobs = torch.from_numpy(logprobs[:, :, self.language_masks[lang]]).log_softmax(dim=-1)

        indices = torch.argmax(logprobs[0], dim=-1)
        collapsed_indices = torch.unique_consecutive(indices, dim=-1)
        hyp = "".join(
            [self.vocab[lang][x] for x in collapsed_indices if x != self.config.BLANK_ID]
        ).replace("▁", " ").strip()

        if compute_timestamps:
            return hyp, self.compute_timestamps(logprobs, encoded_lengths, lang, _type=compute_timestamps)
        del logprobs, indices, collapsed_indices
        return hyp

    def compute_timestamps(self, batch_logprobs, lens, lang, _type="w"):
        """Byte-for-byte the same as the cached `model_onnx.py`'s -- CTC-only, doesn't touch
        any RNNT/joint session, kept identical so timestamp output matches the full model's."""
        assert _type in ["w", "c"]
        results, results_word = [], []
        for b in range(batch_logprobs.size(0)):
            T = lens[b].item()
            lp = batch_logprobs[b, :T]
            path = lp.argmax(dim=-1).cpu()
            step_sec = self.config.FRAME_DURATION_MS

            segments, cur_tok, start_f = [], None, 0
            segments_word = []
            for f, tok in enumerate(path):
                tok = tok.item()
                if tok == self.config.BLANK_ID:
                    if cur_tok is not None:
                        segments.append((self.vocab[lang][cur_tok], start_f * step_sec, f * step_sec))
                        cur_tok = None
                elif tok != cur_tok:
                    if cur_tok is not None:
                        segments.append((self.vocab[lang][cur_tok], start_f * step_sec, f * step_sec))
                    cur_tok, start_f = tok, f

            if cur_tok is not None:
                segments.append((self.vocab[lang][cur_tok], start_f * step_sec, T * step_sec))

            if _type == "w":
                word, start_t, prev_t1 = "", None, None
                for token, t0, t1 in segments:
                    if "▁" in token:
                        if word:
                            segments_word.append((word, start_t, prev_t1))
                        word = token.replace("▁", "")
                        start_t = t0
                    else:
                        word += token
                    prev_t1 = t1
                if word:
                    segments_word.append((word, start_t, prev_t1))

            results.append(segments)
            results_word.append(segments_word)
        return results if _type == "c" else results_word

    @classmethod
    def from_pretrained(cls, pretrained_model_name_or_path, *, token=None, **kwargs):
        """Mirrors the cached `model_onnx.py`'s own `from_pretrained` classmethod -- same
        `snapshot_download()` call, so it resolves to the exact same local HF cache snapshot
        (no re-download) when `HF_HOME` is already pointed at a populated cache dir."""
        from huggingface_hub import snapshot_download

        loc = snapshot_download(repo_id=pretrained_model_name_or_path, token=token)
        return cls(IndicASRConfig(ts_folder=loc))
