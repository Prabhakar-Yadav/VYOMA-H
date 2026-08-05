"""Rebuild a run's summary from the per-case records, and report it.

Reads <config>/*/case.json rather than the _summary.json the runner writes,
because a partial re-run (say, of three failed cases) overwrites that file with
only those three. The per-case records are the durable truth.

Usage:
    python aggregate.py fp32-fastspeech2
    python aggregate.py fp32-fastspeech2 int8-fastspeech2    # compare two runs
"""

from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

SAFETY_CATEGORIES = {"deficiency_like", "deficiency_khaira", "nutrient_question",
                     "out_of_scope", "uncovered_crop"}


def load(config: str) -> list[dict]:
    root = HERE / config
    out = []
    for d in sorted(root.iterdir()):
        f = d / "case.json"
        if d.is_dir() and f.exists():
            out.append(json.loads(f.read_text(encoding="utf-8")))
    (root / "_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def report(config: str, cases: list[dict]) -> None:
    ok = [c for c in cases if c.get("status") == "ok"]
    wers = [c["asr_wer"] for c in ok if c.get("asr_wer") is not None]
    cers = [c["asr_cer"] for c in ok if c.get("asr_cer") is not None]

    print("=" * 80)
    print(f"{config}   {len(ok)}/{len(cases)} completed")
    print("=" * 80)
    if wers:
        print(f"  ASR   mean WER {sum(wers)/len(wers):5.1f}%   "
              f"median {st.median(wers):5.1f}%   "
              f"perfect {sum(1 for w in wers if w == 0):2}   "
              f"under 20% {sum(1 for w in wers if w < 20):2}   "
              f"over 50% {sum(1 for w in wers if w > 50):2}")
        print(f"        mean CER {sum(cers)/len(cers):5.1f}%")

    unsafe = [c for c in cases if "UNSAFE" in str(c.get("auto_check", ""))]
    print(f"  SAFETY  prescribed on a non-disease: {len(unsafe)}"
          f"{'  -> ' + ', '.join(str(c['id']) for c in unsafe) if unsafe else ''}")

    outcomes: dict[str, int] = {}
    for c in ok:
        outcomes[c.get("outcome", "?")] = outcomes.get(c.get("outcome", "?"), 0) + 1
    print("  OUTCOMES")
    for k, v in sorted(outcomes.items(), key=lambda kv: -kv[1]):
        print(f"    {v:3}  {k}")

    print("  BY CATEGORY  (prescribed = gave a pesticide)")
    cats: dict[str, list[dict]] = {}
    for c in ok:
        cats.setdefault(c["category"], []).append(c)
    for cat, cs in sorted(cats.items()):
        pres = sum(1 for c in cs if c.get("label_ids"))
        w = [c["asr_wer"] for c in cs if c.get("asr_wer") is not None]
        flag = "  <-- should never prescribe" if cat in SAFETY_CATEGORIES and pres else ""
        print(f"    {cat:22} n={len(cs):2}  prescribed {pres:2}  "
              f"ASR WER {sum(w)/len(w) if w else 0:5.1f}%{flag}")

    slow = [c for c in ok if c.get("t_asr")]
    if slow:
        for k, label in (("t_asr", "ASR"), ("t_nmt_in", "NMT in"),
                         ("t_rag", "RAG"), ("t_nmt_out", "NMT out"),
                         ("t_tts", "TTS")):
            v = [c[k] for c in ok if c.get(k) is not None]
            if v:
                print(f"  {label:8} mean {sum(v)/len(v):5.2f}s")


def compare(a: str, b: str) -> None:
    ca = {c["id"]: c for c in load(a)}
    cb = {c["id"]: c for c in load(b)}
    ids = sorted(set(ca) & set(cb))
    print("\n" + "=" * 80)
    print(f"PER-CASE COMPARISON   {a}  vs  {b}")
    print("=" * 80)
    print(f"{'id':>3}  {'category':22} {'WER A':>7} {'WER B':>7}  {'outcome A':22} {'outcome B':22}")
    wa, wb, diff = [], [], 0
    for i in ids:
        x, y = ca[i], cb[i]
        if x.get("asr_wer") is not None and y.get("asr_wer") is not None:
            wa.append(x["asr_wer"])
            wb.append(y["asr_wer"])
        same = x.get("condition") == y.get("condition")
        diff += not same
        mark = "" if same else "  <-- differs"
        print(f"{i:3}  {x['category'][:22]:22} {x.get('asr_wer', -1):6.1f}% "
              f"{y.get('asr_wer', -1):6.1f}%  {str(x.get('outcome'))[:22]:22} "
              f"{str(y.get('outcome'))[:22]:22}{mark}")
    if wa:
        print(f"\n  mean WER   {a}: {sum(wa)/len(wa):.1f}%    "
              f"{b}: {sum(wb)/len(wb):.1f}%    "
              f"delta {sum(wb)/len(wb) - sum(wa)/len(wa):+.1f} points")
    print(f"  different diagnosis on {diff} of {len(ids)} cases")


if __name__ == "__main__":
    args = sys.argv[1:] or ["fp32-fastspeech2"]
    for cfg in args:
        report(cfg, load(cfg))
        print()
    if len(args) == 2:
        compare(*args)
