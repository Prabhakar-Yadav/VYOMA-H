"""The process-isolated pipeline over the real test clips.

Same 20 farmer recordings as every other configuration, so the numbers are
comparable. Each stage runs as its own process and exits, so peak memory is the
largest single stage rather than the sum - the design in-process unloading
could not deliver, because freed pages go back to the allocator, not the OS.

Archives the same per-case artefacts as the resident runner and scores WER
against the reference transcripts.
"""
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path.home() / "vyoma_pipeline"
PY = str(HERE / ".venv/bin/python")
STAGE = str(Path.home() / "stage.py")
TESTS = HERE / "pipeline/audio-tests"
OUT = HERE / "pipeline/results/gpu20-chain-swap"
OUT.mkdir(parents=True, exist_ok=True)
WORK = Path("/tmp/chain")
WORK.mkdir(exist_ok=True)

sys.path.insert(0, str(HERE / "bhashini-eval"))
import asr_scoring as scoring


def gpu_mb():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5)
        return int(o.stdout.split()[0])
    except Exception:
        return 0


def watch(proc, out):
    pk_a = pk_g = 0
    while proc.poll() is None:
        try:
            for line in open("/proc/{}/smaps_rollup".format(proc.pid)):
                if line.startswith("Anonymous:"):
                    pk_a = max(pk_a, int(line.split()[1]) / 1024)
                    break
        except Exception:
            pass
        pk_g = max(pk_g, gpu_mb())
        time.sleep(0.05)
    out["anon"], out["gpu"] = pk_a, pk_g


import os
ENV = dict(os.environ, PYTHONSAFEPATH="1")


def run(stage, src, dst, lang="hi"):
    m = {}
    t = time.time()
    p = subprocess.Popen([PY, STAGE, stage, str(src), str(dst), lang],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, cwd="/tmp", env=ENV)
    th = threading.Thread(target=watch, args=(p, m))
    th.start()
    _, err = p.communicate()
    th.join()
    ok = p.returncode == 0 and Path(dst).exists()
    return dict(stage=stage, secs=round(time.time() - t, 2),
                anon=round(m.get("anon", 0)), gpu=round(m.get("gpu", 0)),
                ok=ok, err="" if ok else (err.strip().splitlines() or [""])[-1][:120])


cases = json.loads((TESTS / "manifest.json").read_text(encoding="utf-8"))
if isinstance(cases, dict):
    cases = cases.get("cases", [])
# ids are strings in the manifest, and the audio path is relative to it
for c in cases:
    c["id"] = int(c["id"])
cases = [c for c in cases if c["id"] <= 20]

print("PROCESS-ISOLATED PIPELINE over {} clips".format(len(cases)))
print("{:>3} {:>7} {:>9} {:>9} {:>8}  {}".format(
    "id", "peakMB", "wall_s", "WER%", "outcome", "heard"))
print("-" * 92)

records = []
for c in cases:
    cid = c["id"]
    d = OUT / "{:02d}".format(cid)
    d.mkdir(exist_ok=True)
    src = TESTS / c["audio"]
    shutil.copy2(src, d / "01_input.ogg")
    lang = c.get("lang", "hi")

    rows = [run("asr", src, WORK / "1.txt", lang)]
    if rows[-1]["ok"]:
        rows.append(run("nmt_in", WORK / "1.txt", WORK / "2.txt", lang))
    if rows[-1]["ok"]:
        rows.append(run("rag", WORK / "2.txt", WORK / "3.json"))
    if rows[-1]["ok"]:
        rag = json.loads((WORK / "3.json").read_text(encoding="utf-8"))
        (WORK / "4.txt").write_text(rag["text"], encoding="utf-8")
        rows.append(run("nmt_out", WORK / "4.txt", WORK / "5.txt", lang))
    else:
        rag = {"outcome": "ERROR", "label_ids": [], "text": ""}
    if rows[-1]["ok"]:
        rows.append(run("tts", WORK / "5.txt", d / "07_output.wav", lang))

    heard = (WORK / "1.txt").read_text(encoding="utf-8").strip() if (WORK / "1.txt").exists() else ""
    eng = (WORK / "2.txt").read_text(encoding="utf-8").strip() if (WORK / "2.txt").exists() else ""
    native = (WORK / "5.txt").read_text(encoding="utf-8").strip() if (WORK / "5.txt").exists() else ""
    for name, txt in (("02_asr.txt", heard), ("03_nmt_en.txt", eng),
                      ("05_answer_en.txt", rag.get("text", "")),
                      ("06_nmt_back.txt", native)):
        (d / name).write_text(txt, encoding="utf-8")
    (d / "04_rag.json").write_text(json.dumps(rag, ensure_ascii=False, indent=2),
                                   encoding="utf-8")

    ref = c.get("reference_hindi") or ""
    try:
        wer = scoring.wer(ref, heard) * 100 if ref and heard else None
    except Exception:
        import jiwer
        wer = jiwer.wer(ref, heard) * 100 if ref and heard else None

    peak = max([r["anon"] for r in rows] or [0]) + max([r["gpu"] for r in rows] or [0])
    wall = sum(r["secs"] for r in rows)
    all_ok = all(r["ok"] for r in rows) and len(rows) == 5
    rec = dict(id=cid, category=c.get("category"), peak_mb=peak,
               peak_anon=max([r["anon"] for r in rows] or [0]),
               peak_gpu=max([r["gpu"] for r in rows] or [0]),
               wall_s=round(wall, 2), wer=None if wer is None else round(wer, 1),
               outcome=rag.get("outcome"), label_ids=rag.get("label_ids", []),
               heard=heard, english=eng, stages=rows, ok=all_ok)
    records.append(rec)
    (d / "case.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print("{:3} {:7} {:9.1f} {:9} {:>8}  {}".format(
        cid, peak, wall, "-" if wer is None else round(wer, 1),
        str(rag.get("outcome"))[:8], heard[:34]))

ok = [r for r in records if r["ok"]]
wers = [r["wer"] for r in ok if r["wer"] is not None]
SAFE = {"deficiency_like", "deficiency_khaira", "nutrient_question",
        "out_of_scope", "uncovered_crop"}
unsafe = [r["id"] for r in ok if r["category"] in SAFE and r["label_ids"]]

print()
print("=" * 66)
print("SUMMARY  process-isolated (true load/unload)")
print("  completed            {}/{}".format(len(ok), len(records)))
if wers:
    print("  ASR mean WER         {:.1f}%".format(sum(wers) / len(wers)))
print("  unsafe prescribes    {}  {}".format(len(unsafe), unsafe or ""))
if ok:
    print("  PEAK UNIFIED         {} MB   (worst case across all clips)".format(
        max(r["peak_mb"] for r in ok)))
    print("    peak anon RAM      {} MB".format(max(r["peak_anon"] for r in ok)))
    print("    peak GPU           {} MB".format(max(r["peak_gpu"] for r in ok)))
    print("  mean per question    {:.1f}s".format(
        sum(r["wall_s"] for r in ok) / len(ok)))
    print("  total wall clock     {:.0f}s".format(sum(r["wall_s"] for r in records)))
(OUT / "_summary.json").write_text(json.dumps(records, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
print("  artefacts            {}".format(OUT))
