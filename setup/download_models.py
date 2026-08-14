#!/usr/bin/env python3
"""Downloads every checkpoint this pipeline needs into gramsahayak/models/checkpoints/ --
run this ONCE on a fresh machine (Jetson or otherwise) before anything else in this repo.

Checkpoints created (see each engine's own model_loader.py for the full rationale):
  checkpoints/mms-tts-{en,hi,ml,ta,as,bn,dgo,gu,kn,mai,mr,or,pa,te,ur}/  -- MMS-TTS (VITS),
    the default TTS engine (config.TTS_ENGINE). ~139MB each, ~2.1GB total. Public repos, no
    HF_TOKEN needed. CC-BY-NC 4.0 -- non-commercial only, see
    gramsahayak/models/mms_tts/model_loader.py's module docstring before any commercial use.
  checkpoints/indic-parler-tts-awq-int4/  -- Parler-TTS (AWQ+int4), the fallback engine used
    for the 8 India languages MMS-TTS has no checkpoint for (Bodo, Kashmiri, Konkani,
    Manipuri, Nepali, Sanskrit, Santali, Sindhi) and selectable as the primary engine via
    config.TTS_ENGINE="parler". ~833MB. Public repo, no HF_TOKEN needed.
  checkpoints/indic-conformer-600m-fp32/  -- ASR (ai4bharat/indic-conformer-600m-multilingual,
    22 Indian languages, no English). ~2.4GB. **GATED repo -- HF_TOKEN required**, and your
    HF account must have accepted the model's access terms on huggingface.co first (visiting
    the model page and clicking through the gate once is enough, it's not a paid/restricted
    license -- just a click-through).

NOT downloaded here -- see the printed instructions at the end of this script:
  checkpoints/indic-trans2-nmt/  -- NMT (IndicTrans2 ct2-int8, 3 directions). No verified
    clean HuggingFace source was found for this exact checkpoint (it was originally vendored
    from a locally-extracted "Bhashini" toolkit bundle, not a standard snapshot_download) --
    copy this directory in manually from wherever your team keeps it. See
    gramsahayak/models/nmt/model_loader.py's module docstring for the exact expected layout
    ({en-indic,indic-en,indic-indic}/ct2_int8_model/).

Usage:
    export HF_TOKEN=hf_...          # needed for the gated ASR repo
    python setup/download_models.py                  # download everything
    python setup/download_models.py --skip-asr        # skip the gated repo (e.g. no token yet)
    python setup/download_models.py --only mms_tts     # just one component
"""
import argparse
import os
import sys
import time

SETUP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SETUP_DIR)  # gramsahayak/
CHECKPOINTS_DIR = os.path.join(ROOT_DIR, "models", "checkpoints")

MMS_TTS_LANGUAGES = {
    "en": "facebook/mms-tts-eng", "hi": "facebook/mms-tts-hin",
    "ml": "facebook/mms-tts-mal", "ta": "facebook/mms-tts-tam",
    "as": "facebook/mms-tts-asm", "bn": "facebook/mms-tts-ben",
    "dgo": "facebook/mms-tts-dgo", "gu": "facebook/mms-tts-guj",
    "kn": "facebook/mms-tts-kan", "mai": "facebook/mms-tts-mai",
    "mr": "facebook/mms-tts-mar", "or": "facebook/mms-tts-ory",
    "pa": "facebook/mms-tts-pan", "te": "facebook/mms-tts-tel",
    "ur": "facebook/mms-tts-urd-script_arabic",
}
PARLER_REPO = "hazardscarn10/indic-parler-tts-awq-int4"
ASR_REPO = "ai4bharat/indic-conformer-600m-multilingual"


def banner(msg):
    print("\n" + "=" * 78)
    print(msg)
    print("=" * 78)


def download_mms_tts(token):
    from huggingface_hub import snapshot_download

    banner(f"MMS-TTS ({len(MMS_TTS_LANGUAGES)} languages)")
    for code, repo in MMS_TTS_LANGUAGES.items():
        dest = os.path.join(CHECKPOINTS_DIR, f"mms-tts-{code}")
        if os.path.exists(os.path.join(dest, "config.json")):
            print(f"  [{code}] already present, skipping ({dest})")
            continue
        t0 = time.time()
        snapshot_download(
            repo_id=repo, local_dir=dest,
            allow_patterns=["*.json", "*.safetensors", "vocab.json", "tokenizer*"],
            token=token,
        )
        print(f"  [{code}] {repo} -> {dest} ({time.time() - t0:.1f}s)")


def download_parler(token):
    from huggingface_hub import snapshot_download

    banner("Parler-TTS (indic-parler-tts-awq-int4)")
    dest = os.path.join(CHECKPOINTS_DIR, "indic-parler-tts-awq-int4")
    if os.path.exists(os.path.join(dest, "config.json")):
        print(f"  already present, skipping ({dest})")
        return
    t0 = time.time()
    snapshot_download(repo_id=PARLER_REPO, local_dir=dest, token=token)
    print(f"  {PARLER_REPO} -> {dest} ({time.time() - t0:.1f}s)")


def download_asr(token):
    banner("ASR (indic-conformer-600m-multilingual) -- GATED, needs HF_TOKEN")
    if not token:
        print("  SKIPPED -- no HF_TOKEN set. Get one at https://huggingface.co/settings/tokens,")
        print(f"  accept the model's access terms at https://huggingface.co/{ASR_REPO},")
        print("  then re-run: HF_TOKEN=hf_... python setup/download_models.py --only asr")
        return

    dest = os.path.join(CHECKPOINTS_DIR, "indic-conformer-600m-fp32")
    # This checkpoint's own model_loader.py (models/asr/model_loader.py) needs a full
    # HF_HOME-shaped cache directory (hub/, modules/, xet/), not a flat snapshot_download
    # target -- trust_remote_code=True pulls custom modeling code that gets cached alongside
    # the weights. Populating it via the exact same AutoModel.from_pretrained() call the
    # loader itself makes (rather than snapshot_download) guarantees the cache ends up in
    # precisely the shape load() expects -- confirmed directly, this is the same mechanism
    # models/asr/model_loader.py's own IndicConformerASR.load() uses.
    already_populated = os.path.isdir(os.path.join(dest, "hub"))
    if already_populated:
        print(f"  already present, skipping ({dest})")
        return

    os.environ["HF_HOME"] = dest
    os.environ["HF_TOKEN"] = token
    from transformers import AutoModel

    t0 = time.time()
    AutoModel.from_pretrained(ASR_REPO, trust_remote_code=True, token=token)
    print(f"  {ASR_REPO} -> {dest} ({time.time() - t0:.1f}s)")


def print_nmt_instructions():
    banner("NMT (IndicTrans2 ct2-int8) -- MANUAL STEP, not auto-downloaded")
    dest = os.path.join(CHECKPOINTS_DIR, "indic-trans2-nmt")
    print(f"""  No verified clean download source exists for this exact checkpoint (see this
  script's module docstring). Copy it in manually so this directory ends up containing:

      {dest}/
        en-indic/ct2_int8_model/     {{config.json, model.bin, source_vocabulary.txt,
                                        target_vocabulary.txt, vocab/}}
        indic-en/ct2_int8_model/     (same file set)
        indic-indic/ct2_int8_model/  (same file set)

  Ask a teammate who already has this repo checked out where their copy lives, or use
  whatever internal source your team tracks it from -- see
  gramsahayak/models/nmt/model_loader.py's module docstring for the full context on why
  this one's different from every other checkpoint here.

  NMT is only used for non-English languages (translating farmer input -> English for the
  agent, and the agent's answer -> the farmer's language for TTS) -- an English-only setup
  can skip this entirely.""")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["mms_tts", "parler", "asr"], default=None,
                         help="download just one component instead of everything")
    parser.add_argument("--skip-asr", action="store_true", help="skip the gated ASR repo")
    args = parser.parse_args()

    os.makedirs(CHECKPOINTS_DIR, exist_ok=True)
    token = os.environ.get("HF_TOKEN")

    if args.only:
        {"mms_tts": download_mms_tts, "parler": download_parler, "asr": download_asr}[args.only](token)
    else:
        download_mms_tts(token)
        download_parler(token)
        if not args.skip_asr:
            download_asr(token)
        print_nmt_instructions()

    banner("Done")
    print(f"Checkpoints directory: {CHECKPOINTS_DIR}")
    print("Next: python test_orchestrated_pipeline.py --language hi --no-play  (or --all)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
