"""Loads/unloads the AWQ+TorchAO int4-packed indic-parler-tts checkpoint.

Vendored from https://github.com/hazardscarn/vyoma_hackathon (tts_exports/) — see that
repo's TECHNICAL_REPORT.md for the full quantization methodology and results.

Checkpoint weights are hosted on Hugging Face Hub (not stored in this repo -- the raw
state_dict is ~820MB, over GitHub's 100MB file limit): hazardscarn10/indic-parler-tts-awq-int4
-- a public, non-gated repo, no token needed.

The checkpoint is a raw `state_dict.pt`, not a directly-loadable `from_pretrained` directory --
`model.save_pretrained()` fails on models containing TorchAO's tensor-subclass weights
(`Int4TilePackedTo4dTensor`), so it falls back to a plain `torch.save(state_dict())`.
Reloading requires re-creating the packed tensor-subclass structure (via `quantize_()`) before
`load_state_dict()` can restore the checkpoint's actual int4 values onto it.

**Two hard-won correctness lessons, from two different incidents:**

1. **The skeleton's weight *values* before `quantize_()` don't matter, but the model's
   `generation_config` absolutely does.** An earlier version of this module built the
   pre-quantization skeleton from config alone (`ParlerTTSForConditionalGeneration(config)`,
   no weight download, to avoid needing the gated `ai4bharat/indic-parler-tts` repo). That
   produced silently broken audio -- 30+ seconds of near-silent output that never found a
   natural stopping point -- on some real inputs, while the same checkpoint loaded via
   `from_pretrained()` first (real base-model weights, then quantize, then overwrite via
   `load_state_dict`) worked correctly. Root-caused directly, not guessed: the actual cause
   had nothing to do with weight values or tensor-subclass reload correctness at all. HF's
   `from_pretrained()` auto-loads a `generation_config.json` (setting `do_sample=True`, the
   correct `eos_token_id`, etc.); plain `ParlerTTSForConditionalGeneration(config)` never
   does this, silently falling back to library defaults (effectively greedy decoding) --
   which degenerates into near-silent runaway output on this codec-token decoder. Confirmed
   directly: loading the checkpoint's own `generation_config.json` onto a skeleton built via
   `accelerate`'s `init_empty_weights()` (meta device -- no weight download of any kind, real
   or random) produces output numerically identical to the proven-correct `from_pretrained`
   path under matched seeds. **A "0 missing/0 unexpected keys" `load_state_dict` result says
   nothing about `generation_config`, since it isn't a model parameter or buffer at all** --
   this is a distinct, easy-to-miss gap from the state-dict-key-matching blind spot the first
   incident suggested. This project's own testing independently reproduced the near-silent
   failure mode (Hindi/Telugu, and a separate multi-paragraph collapse) before this fix landed
   upstream -- see dev/agents/vyoma_main.ipynb's Demo 9 history and this file's git log.
2. **Whole-model pickling was investigated as an alternative and abandoned.** Serializing the
   full `nn.Module` (not just its `state_dict()`) was tried as a way to skip rebuilding the
   quantized structure at every load. It hit a reproducible `functools.partial` pickling
   error somewhere in the object graph that resisted isolation, including one inconsistent
   repro between two nominally-identical attempts -- not something to trust in a shipped
   deployment path. It also turned out to be unnecessary: the meta-device skeleton + explicit
   `generation_config` fix below is faster (~2-4s vs 20+ seconds building a real base model)
   and needs no base-model download or token at all.

This module now builds the model skeleton on a meta device from the checkpoint's own saved
`config.json` (via `accelerate.init_empty_weights()`) -- no base-model download, no gated
repo, no `hf_token`, and no `save_pretrained`/`from_pretrained` round trip of the ~2GB base
model. `load()` on the dev machine this was built on takes ~2-4s, versus ~24-26s when routing
through the base model's `from_pretrained()` (even with a warm Hugging Face cache -- that
time is disk I/O and model construction, not network). Re-verified against the identical real
test cases that caught the first incident (multiple languages, short and long text) plus a
seed-matched direct comparison against the proven-correct `from_pretrained` path -- outputs
matched exactly. Also re-verified through 3 full load/generate/unload cycles via this exact
class to confirm no VRAM leak across repeated load/unload (relevant for memory-constrained
deployment, e.g. sharing a Jetson with other models).

**No-internet / offline deployment**: `huggingface_hub` itself isn't really avoidable here --
`transformers`/`parler_tts` depend on it internally for local cache management even when
loading purely local files -- but *network calls at runtime* are avoidable. Two ways:
1. Run once with internet available to populate the local HF cache (or pre-copy a populated
   cache / this checkpoint's files onto the target device some other way), then set
   `HF_HUB_OFFLINE=1` before running again -- the `snapshot_download` call below will then use
   only the local cache and never touch the network, raising a clear error instead of hanging
   if it isn't cached.
2. Pass `checkpoint_dir=` (a local directory containing state_dict.pt, config.json, the
   tokenizers, etc.) to skip the Hugging Face Hub download entirely.

See TECHNICAL_REPORT.md section 9 in the source repo for the full writeup.
"""
import ctypes
import gc
import os
import platform

import torch
import torch.nn as nn
from transformers import AutoTokenizer, GenerationConfig
from parler_tts import ParlerTTSForConditionalGeneration, ParlerTTSConfig
from accelerate import init_empty_weights
from huggingface_hub import snapshot_download
# torchao is NOT imported at module level, on purpose -- confirmed a real problem, not
# theoretical: on at least one real device (Jetson, JetPack 6.2 / torch 2.11.0 from the
# Jetson AI Lab index), torchao 0.13.0 itself fails to import (its own internal
# `torch._inductor.kernel.flex_attention` reference doesn't exist in that torch build).
# Since `transformers.modeling_utils` imports torchao unconditionally the moment ANY model
# loads via `AutoModel`/`PreTrainedModel.from_pretrained()` (to register it as an available
# quantizer backend) -- not just when Parler-TTS's quantized path is actually used -- a
# broken torchao install used to take down this ENTIRE module at import time, which in turn
# broke every other TTS engine (mms_tts) and even unrelated components (ASR) that import
# anything from this package, since Python must execute this module (and __init__.py) before
# any of its siblings can be reached. Importing torchao lazily, inside load() where it's
# actually used, means: this class can always be *defined* regardless of whether torchao
# works on the target device; only calling QuantizedParlerTTS().load() -- i.e. actually using
# the Parler-TTS fallback -- can fail on a broken torchao, with a clear error at that point
# instead of poisoning the whole package's importability.

CHECKPOINT_REPO_ID = "hazardscarn10/indic-parler-tts-awq-int4"
GROUP_SIZE = 64


def _quantized_linear_filter(module, fqn):
    # Every nn.Linear except the LM heads was packed. No need to reconstruct the AWQ
    # group/fold structure here: that was only needed to *compute* the quantized values
    # during quantization, not to know which layers hold them at reload time.
    return isinstance(module, nn.Linear) and "lm_heads" not in fqn


class QuantizedParlerTTS:
    """Owns the loaded model + tokenizers and their GPU memory.

    Usage:
        engine = QuantizedParlerTTS()
        engine.load()
        ...
        engine.unload()

    Or as a context manager:
        with QuantizedParlerTTS() as engine:
            ...
    """

    def __init__(self, checkpoint_repo_id=CHECKPOINT_REPO_ID, checkpoint_dir=None,
                 device=None, hf_cache_dir=None):
        self.checkpoint_repo_id = checkpoint_repo_id
        self.checkpoint_dir = checkpoint_dir  # local path override -- skips snapshot_download if set
        # torchao's quantize_() materializes some internal state on the qualified "cuda:0"
        # form specifically; a bare "cuda" here causes a device-mismatch error during
        # load_state_dict(assign=True) even though both refer to the same physical device.
        self.device = device or (f"cuda:{torch.cuda.current_device()}" if torch.cuda.is_available() else "cpu")
        if hf_cache_dir:
            os.environ["HF_HOME"] = str(hf_cache_dir)

        self.model = None
        self.tokenizer = None
        self.description_tokenizer = None

    @property
    def is_loaded(self):
        return self.model is not None

    def load(self):
        """Rebuild the quantized structure and load the checkpoint's weights onto it.
        No-op if already loaded. Downloads the checkpoint from Hugging Face Hub (cached
        after the first call, no token needed) unless `checkpoint_dir=` was passed to
        __init__, in which case that local directory is used directly and the Hub is never
        contacted at all. No base model download, ever."""
        if self.is_loaded:
            return

        # See the module-level comment (top of file) for why this import is here, not at
        # module scope -- lets the whole tts_exports package stay importable (mms_tts, ASR,
        # everything else) even on a device where torchao itself is broken, only failing
        # here, with a clear traceback, if something actually tries to use Parler-TTS.
        from torchao.quantization import quantize_, Int4WeightOnlyConfig

        checkpoint_dir = self.checkpoint_dir or snapshot_download(repo_id=self.checkpoint_repo_id)

        config = ParlerTTSConfig.from_pretrained(checkpoint_dir)
        with init_empty_weights():
            model = ParlerTTSForConditionalGeneration(config)
        model = model.to(torch.bfloat16)
        quantize_(
            model,
            Int4WeightOnlyConfig(group_size=GROUP_SIZE, int4_packing_format="tile_packed_to_4d"),
            filter_fn=_quantized_linear_filter,
        )

        state_dict = torch.load(
            os.path.join(checkpoint_dir, "state_dict.pt"), map_location=self.device, weights_only=False
        )
        # assign=True attaches these tensors directly (required for a meta-device skeleton --
        # there's no existing real storage to copy into) rather than copying values into the
        # skeleton's placeholder tensors.
        missing, unexpected = model.load_state_dict(state_dict, strict=True, assign=True)
        del state_dict
        if missing or unexpected:
            raise RuntimeError(
                f"Checkpoint reload mismatch: {len(missing)} missing, {len(unexpected)} unexpected keys"
            )
        model = model.to(self.device)
        model.eval()

        # Not a parameter or buffer, so load_state_dict() never touches it -- but generate()
        # depends on it (do_sample, eos/decoder_start tokens). See module docstring incident #1.
        model.generation_config = GenerationConfig.from_pretrained(checkpoint_dir)

        self.model = model
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint_dir)
        self.description_tokenizer = AutoTokenizer.from_pretrained(
            os.path.join(checkpoint_dir, "description_tokenizer")
        )
        torch.cuda.empty_cache()

    def unload(self):
        """Free the model and tokenizers from memory. No-op if not loaded.

        Fully releases GPU memory: verified directly (torch.cuda.memory_allocated()
        and memory_reserved() both drop to ~0.03GB here, down from a measured
        peak of ~2.99GB / ~4.28GB after a worst-case 3000-token generation --
        dev/local_model_test/test_tts_memory.py, dev/local_model_test/tts_memory_log.txt).

        Does NOT fully return host (CPU) RSS to pre-load levels within the same
        process. gc.collect() + malloc_trim(0) below recover what's actually
        reclaimable Python/glibc heap slack (confirmed ~40MB in that same test),
        but most of what's left resident is the CUDA driver context plus
        cuDNN/cuBLAS workspace, which PyTorch keeps alive for the process's
        lifetime once touched -- empty_cache() only frees the caching
        allocator's tensor blocks, never the context itself. This is a
        PyTorch/CUDA constraint, not something any Python-level call can undo.
        If you need that memory back for *other* processes sharing a fixed
        pool (not just reused by the next model loaded in this same process),
        run this engine in its own subprocess and exit that process --
        process exit is the only thing that guarantees a full reclaim."""
        if not self.is_loaded:
            return
        del self.model
        self.model = None
        self.tokenizer = None
        self.description_tokenizer = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
        if platform.system() == "Linux":
            try:
                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except OSError:
                pass

    def vram_allocated_gb(self):
        if not torch.cuda.is_available():
            return None
        return torch.cuda.memory_allocated(self.device) / 1e9

    def __enter__(self):
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload()
