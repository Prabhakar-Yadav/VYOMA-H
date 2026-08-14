"""Embedding via granite-embedding:30m over Ollama -- decision + real numbers in
G1-G2-VECTORDB-PLAN.md Β§4: 30.15M params, 384-dim, ~62MB, English-only (confirmed via
`ollama show`), chosen over the multilingual models already on this machine because
retrieval only ever sees English here (NMT happens before the agent/tool step, same as
krishi-rag's own documented architecture) -- multilingual capacity would be wasted
capacity, not a safety margin.
"""

from __future__ import annotations

import struct

import ollama

MODEL = "granite-embedding:30m"
DIM = 384

# Forced CPU-only (2026-08-11) -- confirmed directly on real Jetson hardware during a live
# multi-turn stress test: loading this model on GPU (Ollama's default) spins up a genuinely
# SEPARATE llama-server process from the agent's own qwen3.5:2b one, and that second process
# pays its own one-time CUDA-context/GPU-runtime-init tax -- the same real phenomenon already
# rigorously identified for PyTorch/TTS earlier this project (see tts_quantization/'s own
# module docstrings), just showing up again here in a completely different component. Real
# before/after on Jetson: GPU-loaded, `ollama ps` reported this 30M-param/~62MB model's
# combined real system-memory impact in the multi-GB range (part of a real confirmed crash);
# forced to CPU (`options={"num_gpu": 0}`), `size_vram` drops to 0 and the real memory delta
# is ~100MB -- matching the model's own actual weight size, no separate GPU context at all.
# One-time load cost ~1.85s. Worth the tradeoff: this is an occasional query-time embedding
# call (retrieval, not generation), nowhere near as latency-sensitive as TTS/agent turns.
CPU_ONLY_OPTIONS = {"num_gpu": 0}


def embed_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Real Ollama /api/embed calls, batched. No client-side caching -- this is a
    one-time index-build cost, not a per-query cost (queries embed one string at a
    time via embed_one(), see rag/retrieval.py)."""
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = ollama.embed(model=MODEL, input=batch, options=CPU_ONLY_OPTIONS)
        out.extend(resp.embeddings)
    return out


def embed_one(text: str) -> list[float]:
    resp = ollama.embed(model=MODEL, input=[text], options=CPU_ONLY_OPTIONS)
    return resp.embeddings[0]


def to_f32_bytes(vec: list[float]) -> bytes:
    """sqlite-vec's own serialize_float32 does exactly this, but written out directly
    here so this module has no import-order dependency on sqlite_vec."""
    return struct.pack(f"{len(vec)}f", *vec)
