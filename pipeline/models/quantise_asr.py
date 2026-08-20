"""Scoped INT8 export of IndicConformer. Writes to a SEPARATE directory.

The fp32 model is what the first pipeline test runs on; this produces an int8
twin beside it so the two can be compared on identical audio afterwards.
Nothing here modifies the fp32 files.

WHY "SCOPED" AND NOT JUST quantize_dynamic ON EVERYTHING

A published community attempt at naive full-int8 on this exact model doubled
Hindi WER (0.1645 -> 0.2985). Weight-only quantisation is not uniformly safe
across op types: MatMul weights in the conformer blocks tolerate int8 well
because their values are well-conditioned and the error averages out over large
reductions, while normalisation scales, embeddings and the small per-language
joint networks carry few parameters with high leverage - squashing those costs
accuracy for almost no memory.

So this quantises MatMul only, and only in the encoder, which is where
essentially all 600M parameters live. The decoders and the 22 per-language
joint heads are left alone: together they are under 70 MB, so there is nothing
to win and real accuracy to lose.

VERIFY BEFORE TRUSTING

Size is not the test. Re-run the 400-utterance FLEURS eval on the int8 model
and compare per-language WER against the fp32 numbers already measured
(hi 9.5, bn 10.6, gu 10.6, te 13.6, kn 14.5, mr 15.1, pa 17.5, or 18.1,
ml 20.8, ta 25.1). Anything beyond about a point of regression means the
scoping needs tightening, not that int8 is impossible.

Usage:
    python quantise_asr.py            # produce the int8 twin
    python quantise_asr.py --check    # report sizes only
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "ai4bharat" / "indic-conformer-600m-multilingual"
DST = HERE / "ai4bharat-int8" / "indic-conformer-600m-multilingual"

# The encoder holds essentially all the parameters. The decoders and the 22
# per-language joint heads are tiny; quantising them risks accuracy for no
# meaningful saving, so they are copied through untouched.
QUANTISE = ["encoder.onnx"]

# Populated when a component falls back to fp32. Non-empty => exit non-zero.
FAILURES: list[str] = []


def mb(p: Path) -> float:
    if p.is_file():
        return p.stat().st_size / 1048576
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1048576


def report() -> None:
    print(f"fp32 : {mb(SRC):8.0f} MB   {SRC}")
    if DST.exists():
        print(f"int8 : {mb(DST):8.0f} MB   {DST}")
        print(f"saved: {mb(SRC) - mb(DST):8.0f} MB "
              f"({100 * (1 - mb(DST) / mb(SRC)):.0f}% smaller)")
    else:
        print("int8 : not built yet")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        report()
        return 0

    if not SRC.exists():
        print(f"source model missing: {SRC}", file=sys.stderr)
        return 1

    from onnxruntime.quantization import QuantType, quantize_dynamic

    DST.mkdir(parents=True, exist_ok=True)
    print(f"copying non-weight files to {DST} ...", flush=True)
    for f in SRC.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(SRC)
        if rel.name in QUANTISE:
            continue
        out = DST / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            shutil.copy2(f, out)

    for name in QUANTISE:
        src = SRC / "assets" / name
        if not src.exists():
            src = SRC / name
        if not src.exists():
            print(f"  skip {name} (not found)", flush=True)
            continue
        dst = DST / src.relative_to(SRC)
        dst.parent.mkdir(parents=True, exist_ok=True)
        print(f"quantising {name} (MatMul only, weight-only int8) ...", flush=True)
        t = time.time()
        try:
            # This model stores its weights as EXTERNAL data files beside the
            # graph, because a 600M-parameter model exceeds protobuf's 2 GB
            # single-file limit. quantize_dynamic resolves external data
            # relative to the CURRENT WORKING DIRECTORY, not the model path, so
            # a first attempt silently found no weights and "saved" 3 MB - the
            # graph without any of its tensors. Running from the model's own
            # directory is what makes the weights reachable.
            import onnx
            from onnx.external_data_helper import (convert_model_to_external_data,
                                                   load_external_data_for_model)

            cwd = Path.cwd()
            import os
            os.chdir(src.parent)
            try:
                model = onnx.load(src.name, load_external_data=False)
                load_external_data_for_model(model, str(src.parent))

                # onnx.save refuses to overwrite an existing external-data
                # file, so a run that died partway leaves a 2.7 GB .weights
                # behind and every later run then fails with a message about
                # the temp file rather than about anything real. That is what
                # happened on the first rebuild: it failed, fell back to
                # copying fp32 through, and still exited 0, so an "int8" tree
                # that was byte-identical to fp32 nearly went into a
                # comparison. Clear the pair before writing.
                #
                # These do have to live in the model's own directory: ORT
                # resolves external data relative to the working directory,
                # which is why the chdir above exists. They are removed on
                # success and cleared on the next run if a crash leaves them.
                tmpdir = src.parent
                tmp = tmpdir / "_tmp_fp32_merged.onnx"
                tmpw = tmpdir / "_tmp_fp32_merged.weights"
                for stale in (tmp, tmpw):
                    if stale.exists():
                        print(f"  clearing stale {stale.name}", flush=True)
                        stale.unlink()

                convert_model_to_external_data(
                    model, all_tensors_to_one_file=True,
                    location="_tmp_fp32_merged.weights", size_threshold=1024)
                onnx.save(model, str(tmp))

                quantize_dynamic(
                    model_input=str(tmp),
                    model_output=str(dst),
                    weight_type=QuantType.QInt8,
                    op_types_to_quantize=["MatMul"],   # the scoping that matters
                    use_external_data_format=True,
                    extra_options={"EnableSubgraph": True},
                )
                tmp.unlink(missing_ok=True)
                tmpw.unlink(missing_ok=True)
            finally:
                os.chdir(cwd)
            print(f"  done in {time.time() - t:.0f}s", flush=True)
        except Exception as e:
            # The fp32 fallback keeps the tree loadable, but it also produces a
            # directory named "int8" that is bit-identical to fp32. That went
            # unnoticed once already: the script printed FAILED, copied fp32
            # through, reported "0% smaller", and still exited 0. Record the
            # failure so the caller cannot treat this as a build.
            print(f"  FAILED: {str(e)[:250]}", flush=True)
            print("  copying fp32 through so the tree stays usable", flush=True)
            shutil.copy2(src, dst)
            FAILURES.append(f"{name}: {str(e)[:200]}")

    # External weight files live beside the graph; the quantised graph rewrites
    # the ones it owns, but any it did not touch must still be present.
    print()
    report()
    if FAILURES:
        print("\nBUILD FAILED - the int8 tree is fp32 copied through:")
        for f in FAILURES:
            print(f"  {f}")
        print("Do NOT compare against this tree; it is not quantised.")
        return 1

    print("\nNext: run the 400-utterance FLEURS eval against this tree and "
          "compare per-language WER with the fp32 numbers before adopting it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
