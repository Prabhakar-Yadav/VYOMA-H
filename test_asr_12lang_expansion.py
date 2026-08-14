"""Real validation for the 2026-08-14 ASR expansion (config.py's WORKERS["asr"]["languages"]
going from ("hi", "ta", "ml") to all 12 quantized checkpoints). Two things this checks that
neither `ls` nor `du` can:

1. **Load integrity** -- every one of the 9 newly-activated languages' ONNX sessions actually
   builds without error (catches file corruption, truncated copies, a config.json/tokens.txt
   mismatch -- exactly the class of bug the dev-local-test `te` copy hit earlier, 278MB instead
   of 188MB, before this test existed). hi/ta/ml included too, as a control -- those were
   already known-good in production, so if THEY failed here it'd mean the test itself is broken,
   not the checkpoints.

2. **Lazy-load isolation** -- confirms `quantized_multilang_loader.py`'s per-language laziness
   (see that module's docstring) actually holds at the new, larger scope: constructing
   QuantizedMultiLangASR with all 12 languages and calling load() with none specified must load
   ZERO engines; transcribing in exactly one language must load exactly that one, not all 12.
   This matters more now than it did at 3 languages -- eagerly loading all 12 would be
   ~2.2GB (12 x ~188MB) instead of 3's ~780MB.

No real audio fixtures exist for the 9 newly-activated languages (only hi/ta/ml/en have them,
per sample_outputfromjetson/ and the config.py comment this test is validating) -- so this
doesn't attempt transcription correctness for the new 9. That's a real, separate open question,
not silently assumed to be fine; noted at the end of this script's output rather than skipped
past quietly.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.asr.quantized_multilang_loader import QuantizedMultiLangASR, DEFAULT_LANGUAGES
from models.asr.indic_quantized_asr import IndicConformerASR

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "models", "checkpoints", "indic-conformer-quantized")

ALL_12 = ("hi", "ta", "ml", "as", "bn", "gu", "kn", "mai", "mr", "pa", "te", "ur")


def check_config_matches():
    assert set(DEFAULT_LANGUAGES) == set(ALL_12), (
        f"quantized_multilang_loader.py's DEFAULT_LANGUAGES {sorted(DEFAULT_LANGUAGES)} != "
        f"expected {sorted(ALL_12)}"
    )
    print(f"[OK] DEFAULT_LANGUAGES matches expected 12-language set: {sorted(DEFAULT_LANGUAGES)}")


def check_load_integrity():
    print("\n=== Load integrity: each of 12 languages' ONNX session builds cleanly ===")
    failures = []
    for lang in ALL_12:
        onnx_filename = f"indicconformer_{lang}_ctc.int8.onnx"
        t0 = time.time()
        try:
            engine = IndicConformerASR(base_dir=BASE_DIR, lang=lang, onnx_filename=onnx_filename)
            engine.load()
            dt = time.time() - t0
            assert engine.sess is not None, f"{lang}: load() returned but sess is still None"
            engine.unload()
            print(f"  [OK] {lang}: loaded+unloaded cleanly ({dt:.2f}s)")
        except Exception as e:
            dt = time.time() - t0
            print(f"  [FAIL] {lang}: {type(e).__name__}: {e} (after {dt:.2f}s)")
            failures.append(lang)
    if failures:
        raise SystemExit(f"\nLoad integrity FAILED for: {failures}")
    print(f"\n[OK] All 12 languages loaded cleanly.")


def check_lazy_isolation():
    print("\n=== Lazy-load isolation at 12-language scope ===")
    engine = QuantizedMultiLangASR(base_dir=BASE_DIR, languages=ALL_12)
    engine.load()  # no language specified
    assert engine.is_loaded, "load() should mark engine ready"
    assert len(engine._engines) == 0, (
        f"load() with no language should load ZERO engines, got {list(engine._engines)}"
    )
    print("  [OK] load() with no language loaded zero engines (ready=True, _engines={})")

    engine._load_language("gu")  # pick one of the newly-activated 9, not hi/ta/ml
    assert list(engine._engines.keys()) == ["gu"], (
        f"expected only 'gu' loaded, got {list(engine._engines)}"
    )
    print("  [OK] loading 'gu' loaded only 'gu' -- other 11 languages untouched")

    engine._load_language("mr")
    assert set(engine._engines.keys()) == {"gu", "mr"}, (
        f"expected {{gu, mr}}, got {set(engine._engines)}"
    )
    print("  [OK] loading 'mr' added only 'mr' -- gu stayed resident, no other languages pulled in")

    engine.unload()
    assert len(engine._engines) == 0 and not engine.is_loaded
    print("  [OK] unload() cleared everything")


if __name__ == "__main__":
    check_config_matches()
    check_load_integrity()
    check_lazy_isolation()
    print("\n" + "=" * 70)
    print("ALL CHECKS PASSED for the 12-language ASR expansion (load integrity + laziness).")
    print("NOT covered here: transcription correctness for the 9 newly-activated languages")
    print("(as/bn/gu/kn/mai/mr/pa/te/ur) -- no real audio fixtures exist for them yet, only")
    print("hi/ta/ml/en do. Open item, not silently assumed fine.")
    print("=" * 70)
