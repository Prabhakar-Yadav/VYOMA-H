"""Run the pipeline as a chain of short-lived processes and measure the peak.

The point of the exercise: peak should become the LARGEST SINGLE STAGE rather
than the sum of everything ever loaded, because a process that exits returns
its memory to the OS unconditionally - unlike in-process unloading, which
returns it only to the allocator.

Each stage is spawned, watched at ~20 Hz for its true peak, and reaped before
the next one starts.
"""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path.home() / "vyoma_pipeline"
PY = str(HERE / ".venv/bin/python")
STAGE = str(Path.home() / "stage.py")
WORK = Path("/tmp/chain")
WORK.mkdir(exist_ok=True)


def gpu_mb():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5)
        return int(o.stdout.split()[0])
    except Exception:
        return 0


def watch(proc, out):
    """Sample the child's anonymous RSS and the GPU while it runs."""
    pk_anon = pk_gpu = 0
    while proc.poll() is None:
        try:
            for line in open("/proc/{}/smaps_rollup".format(proc.pid)):
                if line.startswith("Anonymous:"):
                    pk_anon = max(pk_anon, int(line.split()[1]) / 1024)
                    break
        except Exception:
            pass
        pk_gpu = max(pk_gpu, gpu_mb())
        time.sleep(0.05)
    out["anon"] = pk_anon
    out["gpu"] = pk_gpu


def run(stage, src, dst, lang="hi"):
    m = {}
    t = time.time()
    # cwd=/tmp with PYTHONSAFEPATH: NLTK refuses to import defusedxml when the
    # working directory is on sys.path, and the repo root triggers it. Keep
    # stderr so a failure is diagnosable rather than a silent FAILED.
    import os as _os
    env = dict(_os.environ, PYTHONSAFEPATH="1")
    p = subprocess.Popen([PY, STAGE, stage, str(src), str(dst), lang],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, cwd="/tmp", env=env)
    th = threading.Thread(target=watch, args=(p, m))
    th.start()
    out, err = p.communicate()
    th.join()
    dt = time.time() - t
    ok = p.returncode == 0 and Path(dst).exists()
    print("  {:9} {:6.2f}s   anon {:6.0f} MB   gpu {:5.0f} MB   {}".format(
        stage, dt, m.get("anon", 0), m.get("gpu", 0), "ok" if ok else "FAILED"))
    if not ok and err:
        print("      " + (err.strip().splitlines() or ["?"])[-1][:130])
    return dict(stage=stage, secs=round(dt, 2), anon=round(m.get("anon", 0)),
                gpu=round(m.get("gpu", 0)), ok=ok)


clip = sys.argv[1] if len(sys.argv) > 1 else str(
    HERE / "pipeline/audio-tests/audio/11.ogg")
lang = sys.argv[2] if len(sys.argv) > 2 else "hi"

print("PROCESS-ISOLATED PIPELINE  (each stage loads, works, and exits)")
print("clip:", clip)
print()
rows = []
rows.append(run("asr", clip, WORK / "1_asr.txt", lang))
rows.append(run("nmt_in", WORK / "1_asr.txt", WORK / "2_en.txt", lang))
rows.append(run("rag", WORK / "2_en.txt", WORK / "3_rag.json"))

rag = json.loads((WORK / "3_rag.json").read_text(encoding="utf-8"))
(WORK / "4_reply_en.txt").write_text(rag["text"], encoding="utf-8")
rows.append(run("nmt_out", WORK / "4_reply_en.txt", WORK / "5_native.txt", lang))
rows.append(run("tts", WORK / "5_native.txt", WORK / "6_out.wav", lang))

ok = [r for r in rows if r["ok"]]
print()
print("=" * 62)
if len(ok) == len(rows):
    peak_anon = max(r["anon"] for r in rows)
    peak_gpu = max(r["gpu"] for r in rows)
    worst = max(rows, key=lambda r: r["anon"])
    total_if_resident = sum(r["anon"] for r in rows)
    print("PEAK = the largest single stage, not the sum")
    print("  largest stage            {} at {:.0f} MB".format(worst["stage"], worst["anon"]))
    print("  peak anonymous RAM       {:6.0f} MB".format(peak_anon))
    print("  peak GPU                 {:6.0f} MB".format(peak_gpu))
    print("  PEAK UNIFIED             {:6.0f} MB".format(peak_anon + peak_gpu))
    print()
    print("  if all stages were resident at once: {:.0f} MB".format(total_if_resident))
    print("  saved by process isolation:          {:.0f} MB".format(
        total_if_resident - peak_anon))
    print("  total wall clock                     {:.2f}s".format(
        sum(r["secs"] for r in rows)))
else:
    print("FAILED stages: {}".format([r["stage"] for r in rows if not r["ok"]]))

print()
print("heard   :", (WORK / "1_asr.txt").read_text(encoding="utf-8")[:70])
print("english :", (WORK / "2_en.txt").read_text(encoding="utf-8")[:70])
print("rag     :", rag["outcome"], rag.get("label_ids"))
print("spoke   :", (WORK / "6_out.wav").exists() and
      "{:.1f}s wav".format(
          __import__("soundfile").info(str(WORK / "6_out.wav")).duration))
(WORK / "_chain.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
