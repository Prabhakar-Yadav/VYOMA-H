"""Real agent prefix-cache warmup -- run once at session/device start, before any real turn.

Why this exists (2026-08-12): confirmed directly on real Jetson hardware that a turn's first
`ollama.chat()` call pays a real, substantial prefill cost for the system prompt + tool schema
(~7445 chars, 14 tools -> ~5570+ tokens) -- 6.2-7.6s of pure prefill time across several real
pipeline runs, before any actual thinking/generation starts. This is a real, documented,
mainstream technique (prompt/prefix-cache warmup for agent system prompts -- see e.g.
vllm-mlx's `--warm-prompts`: "runs a max_tokens=1 chat completion for each [system prompt] at
startup, the KV state lands in the prefix cache, and the first real request matches via
strict-prefix"), confirmed to work on THIS Ollama/llama.cpp setup specifically via a real
before/after test: cold prefill 7435ms (5572 tok) -> warmed prefill 1599ms (5802 tok) for the
next real call sharing the same system-prompt+tools prefix, a ~4.6x reduction, matching the
research's general "50-85% TTFT reduction" expectation for this class of fix.

Scope, deliberately narrow: this warms ONLY the system_prompt+tools prefix (a throwaway
placeholder user message, `keep_alive=-1` so it doesn't evict itself), not a full fake
conversation -- "cache only the static prefix, not dynamic tool results" is itself the
literature's own recommended boundary (naive full-context caching can paradoxically increase
latency). Every REAL turn's own user message differs anyway, so there's nothing more to
usefully pre-cache beyond this shared prefix.

Does NOT replace `orchestrator.ensure_agent_loaded_for_session()` -- that just loads the model
weights (`/api/generate` load-only call, no real forward pass). This does a REAL forward pass
with the real system-prompt+tools shape, which is the part that actually needs warming.

Usage (device/session start, once):
    from agent.warmup import warmup_agent
    warmup_agent()  # blocking, ~10-50s depending on model/hardware -- do this BEFORE the
                     # farmer's first turn starts, not during it

CLI usage (from the repo root, e.g. a device-boot script):
    python3 -m agent.warmup
"""
import os
import sys
import time

import ollama

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prompts import SYSTEM_PROMPT, SYSTEM_PROMPTS  # noqa: E402
from agent.agent import TOOLS  # noqa: E402 -- package-qualified: this file lives inside the
# `agent` package itself (imported as `agent.warmup`), so a bare `from agent import TOOLS`
# resolves to the already-loaded package (`agent/__init__.py`, which only exports
# GramSahayakAgent) instead of the `agent/agent.py` module file that actually defines TOOLS --
# confirmed directly, real ImportError on first run. `agent.agent` is unambiguous either way.
from api_server import config  # noqa: E402


def warmup_agent(model=None, num_ctx=None, think=None, verbose=True, system_prompt=None):
    """Real, blocking warmup call -- same system_prompt+tools shape agent.run_turn()'s own
    first `ollama.chat()` call uses, just with a throwaway placeholder user message. Returns
    the real elapsed time and prefill stats so a caller (or a device-boot script) can log/
    verify it actually happened, not just assume it did.

    2026-08-17 real fix: `system_prompt=` resolution now mirrors `GramSahayakAgent.__init__`'s
    own logic EXACTLY (same registry lookup, same "default" fallback) -- this used to always
    warm `SYSTEM_PROMPT` regardless of `model=`, a real bug once a second per-model prompt
    existed: warming the WRONG prefix means the real first turn's actual prefix (built from
    THIS model's own resolved system_prompt) doesn't strict-prefix-match what got cached, so
    the whole point of warmup -- a fast first prefill -- would have silently stopped working
    for any model whose real prompt differs from the default, with no visible error, just a
    slow turn 1 for the wrong reason. Passing `system_prompt=` explicitly still wins (matches
    the agent's own override precedent) for a caller warming something ad hoc."""
    model = model or config.OLLAMA_MODELS[0]
    num_ctx = num_ctx or config.OLLAMA_NUM_CTX
    # 2026-08-17 real fix: same per-model resolution as GramSahayakAgent.__init__'s own think=
    # fix, same real reason -- this used to always fall back to config.AGENT_THINK (tied to the
    # STATIC config.AGENT_MODEL_CHOICE) regardless of what `model=` was actually passed here,
    # so warming e.g. LFM2.5-VL-1.6B without an explicit think= override warmed it at whatever
    # think level the DEFAULT model happened to be tuned for, not this model's own.
    if think is None:
        think = config.AVAILABLE_AGENT_MODELS.get(model, {}).get("think", config.AGENT_THINK)
    if system_prompt is None:
        prompt_key = config.AVAILABLE_AGENT_MODELS.get(model, {}).get("system_prompt", "default")
        system_prompt = SYSTEM_PROMPTS.get(prompt_key, SYSTEM_PROMPT)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "hello"},
    ]

    if verbose:
        print(f"[warmup] warming {model} (num_ctx={num_ctx}) with the real system_prompt+tools "
              f"prefix ({len(system_prompt)} chars, {len(TOOLS)} tools)...", flush=True)

    t0 = time.perf_counter()
    resp = ollama.chat(
        model=model, messages=messages, tools=TOOLS,
        keep_alive=-1, options={"num_ctx": num_ctx}, stream=False, think=think,
    )
    elapsed = time.perf_counter() - t0

    prefill_ms = resp.get("prompt_eval_duration", 0) / 1e6
    prefill_tok = resp.get("prompt_eval_count", 0)
    gen_ms = resp.get("eval_duration", 0) / 1e6
    gen_tok = resp.get("eval_count", 0)

    if verbose:
        print(f"[warmup] done in {elapsed:.2f}s -- prefill={prefill_ms:.0f}ms ({prefill_tok} tok), "
              f"gen={gen_ms:.0f}ms ({gen_tok} tok). Real turns sharing this same system_prompt+"
              f"tools prefix should now see a fast prefill (confirmed ~4.6x on real hardware, "
              f"7435ms cold -> 1599ms warmed for a comparable token count).", flush=True)

    return {
        "elapsed_s": elapsed,
        "prefill_ms": prefill_ms,
        "prefill_tokens": prefill_tok,
        "gen_ms": gen_ms,
        "gen_tokens": gen_tok,
    }


if __name__ == "__main__":
    warmup_agent()
