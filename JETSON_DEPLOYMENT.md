# Running GramSahayak on the real Suno Sutra devboard

How to run the actual voice-farming-assistant app on this Jetson, how the mic/camera/button/
screen wiring works, and how to make the backend start (and the agent be warm) on boot. Written
2026-08-12 after a real, successful, end-to-end run of everything described here on this exact
device -- not a theoretical writeup. If a command here ever stops working, something changed;
this file describes what was verified working on that date, not an aspiration.

## 1. The two pieces, and why there are two

**`~/gramsahayak`** -- the actual AI pipeline. FastAPI gateway (`api_server/`) fronting Ollama
(agent + embedder) and three model workers (ASR/NMT/TTS, each its own subprocess), the
tool-calling agent (`agent/`), and the RAG corpus (`rag/` + `datasets/rag/*.sqlite`). This is
everything the rest of tonight's session built and tested. Runs in its own venv
(`~/gramsahayak/venv`) because its dependencies (torch, ctranslate2, fastapi/uvicorn) are heavy
and shouldn't be forced onto anything else on the device.

**`~/suno-sutra-sw/python`** (the `pocketinfer` package) -- the hardware layer. Knows how to
talk to the mic, camera, trigger button, LCD screen, and speaker on the actual devboard (or fake
all of that via `DummyBoard` for testing without hardware). Ships a `pocketinfer-service` CLI
that runs one registered "application" in a loop. Runs in ITS OWN venv
(`~/suno-sutra-sw/python/venv`) -- separate from gramsahayak's, on purpose (see
`_gramsahayak_python()`'s docstring in the file below).

**`pocketinfer/applications/gramsahayak_app.py`** is the bridge: a pocketinfer "application"
that, on start, launches gramsahayak's gateway as a subprocess (using gramsahayak's OWN venv
python, not pocketinfer's), waits for `/health`, then loads the agent -- and from then on, each
trigger-button press runs one real ASR -> NMT -> Agent -> NMT -> TTS -> playback turn, exactly
mirroring `test_orchestrated_pipeline.py`'s own pipeline shape but driven by the physical button
instead of a file argument. Full flow is documented in that file's own module docstring; read it
before changing anything here.

Both pieces already have real, working venvs on this device as of tonight -- see §5 if you ever
need to rebuild either from scratch.

## 2. Doing a real run

### 2a. No hardware needed -- DummyBoard, file-based input

This is the fastest way to confirm the whole stack works after any change, and doesn't touch
mic/speaker/GPIO at all:

```bash
cd ~/suno-sutra-sw/python
venv/bin/pocketinfer-service --app GramSahayak --dummy-board \
    --audio-file ~/gramsahayak/sample_audio/multiturn_stress/hi/turn1.wav \
    --image-file ~/gramsahayak/datasets/sample-images/late-blight-potatoes_file.jpg \
    --log-level INFO \
    --setting input_language=hi --setting output_language=hi
```

Runs exactly ONE real turn (real ASR/NMT/Agent/RAG/TTS, only the board I/O is faked -- see the
module docstring's "Test without hardware" section) then tears the backend down and exits. Any
16kHz/16-bit mono WAV works for `--audio-file`; check with `soxi <file>` if unsure.
`--image-file` is optional (omit it for a voice-only question). Swap `--setting
input_language=`/`output_language=` for `ta`/`ml`/`en` to test other languages (`en` input is
transcribed locally via Vosk, not gramsahayak's own ASR -- see the module docstring).

**Confirmed working end-to-end 2026-08-12**: real Hindi ASR transcription of a farmer describing
black spots on potato leaves, `analyze_photo` correctly read the attached image, real
`plant_disease_lookup` -> `get_treatment_details` -> `get_guidelines_and_safety` tool calls
against the actual RAG corpus, a coherent Hindi answer synthesized and played back, and a clean
teardown (`real_used` dropped from a 7.33GB peak back to 1.77GB, zero tracebacks in the log).

### 2b. Real hardware -- the actual button/mic/screen/speaker

```bash
cd ~/suno-sutra-sw/python
venv/bin/pocketinfer-service --app GramSahayak --log-level INFO
```

No `--dummy-board`, no file args. `Board.get_board()` (`pocketinfer/boards/base.py`) auto-detects
the real board by reading `/proc/device-tree/model` and the Jetson module/carrier-board EEPROMs
over i2c -- nothing to configure by hand. Once running: statusbar on the LCD reads "Ready - Press
Button"; hold the trigger button, speak, release it; the LCD shows the transcript (top) then the
answer text (bottom) while the answer plays through the speaker. Runs forever (one turn per
button press) until killed -- this is what the boot-time service in §4 actually runs.

### 2c. Backend only, no hardware layer at all

For pure backend/model debugging unrelated to the hardware bridge, `test_orchestrated_pipeline.py`
(in `~/gramsahayak/`, uses gramsahayak's own venv directly, no pocketinfer involved) is the
right tool -- see its own `--help`. This is what most of tonight's session actually ran.

## 3. Hardware: what's connected and how

This device is a **Suno Sutra Devboard** (see `suno-sutra-hw/SunoSutraDevboard/README.md` in the
`suno-sutra-hw` repo for the physical assembly guide with photos and the BOM) -- a Jetson Orin
Nano dev kit plus an LCD screen and trigger button wired directly to the 40-pin expansion header
(GPIO/SPI, no separate microcontroller), a USB speaker/soundcard, and a USB camera. Confirmed
live on this exact device:

| Function | Real device | How it's found |
|---|---|---|
| Camera | USB webcam (`0c45:6366 Microdia Webcam Vitade AF`) | `V4L_CAMERA_NAME` match in `boards/jetson.py` |
| Mic + speaker | USB audio adapter (`Jieli UACDemoV1.0`, ALSA name `UACDemoV1.0`) | `ALSA_CAPTURE_NAME`/`ALSA_PLAYBACK_NAME` match, see `boards/base.py`'s device-selection logic (falls back to first available device with a warning if the named one isn't found -- that warning in the logs is normal, not an error) |
| Trigger button | GPIO pin `GP167` (physical pin 7) | `boards/jetson.py`'s `PocketInferDevboard.TRIGGER_BOARD_IDX` |
| LCD screen | ILI9341 320x240 SPI display, wired per `suno-sutra-hw/assets/jetson_suno_sutra_expansion_pinout.png` | `boards/jetson.py`'s `PocketInferDevboardUI` (reset/CS/DC/touch pins listed there) |

The expansion-header pinmux (i2c2/i2c8/spi1/uarta) needed for the LCD/button was already
provisioned on this device via the ansible role's `jetson-io` step (see
`suno-sutra-sw/rootfs/roles/app/tasks/main.yaml`) -- not something you need to redo unless this
Jetson gets reflashed from scratch, in which case follow `suno-sutra-sw/rootfs/Jetson_Flash.md`
first, then the SunoSutraDevboard assembly README for the physical wiring.

**If you're assembling a new unit from parts**: follow
`suno-sutra-hw/SunoSutraDevboard/README.md` step by step (it has photos for every connector) --
this file only covers the software side of a devboard that's already wired.

## 4. Output: screen, "LED", and speaker

- **LCD screen** is the real, primary output on this board variant -- `board.top_text()` (the
  transcript), `board.bottom_text()` (the answer), `board.statusbar()` (current pipeline stage,
  e.g. "Running: Agent"), `board.mode_text()`/`board.memory_text()` (which app is running / live
  RAM%). All real, wired to the physical screen via `PocketInferDevboardUI`
  (`pocketinfer/boards/jetson.py`).
- **"LED"**: the code does call `board.led_animation()`/`board.button_led()` during a turn (e.g.
  while the agent is "thinking") -- but on THIS board variant those are harmless no-ops (`Board`'s
  base class implementation just `return True`, see `boards/base.py`). This devboard has no
  discrete LED wired -- only the OTHER product variant (`PocketInferDemo`/"Suno Sutra Demo", the
  enclosed handheld with a serial IO-expander MCU, see `boards/jetson.py`'s `PocketInferDemo`
  class) has a real `rgb_led()`/`button_led()`. If a real status LED gets added to this devboard
  later, `PocketInferDevboardUI` is where to wire it in -- don't assume it's already connected.
- **Speaker**: real playback through the USB audio adapter via `AudioPlayer` (`pocketinfer/audio.py`),
  using whatever ALSA device `board.alsa_playback_device` resolved to (see §3's table).

## 5. Boot-time service -- backend up and agent warm on boot

`suno-sutra-sw/python/pocketinfer.service` is a systemd unit already adapted to this device's
real paths (the version checked into git upstream used generic `/home/ubuntu/pocket-infer-sw`
placeholders -- this copy points at `~/suno-sutra-sw` and `~/gramsahayak`, this device's actual
checkouts). It runs `pocketinfer-service --app GramSahayak` -- which per §1/§2b means by the time
systemd reports the unit as started, gramsahayak's gateway is already healthy AND the agent model
is already loaded into Ollama (`ensure_agent_loaded_for_session()` runs inside `_setup()`, before
the trigger-button loop starts accepting input) -- a real prewarm, not just "the process exists".

**Not installed/enabled yet on purpose** -- this claims the mic/speaker/GPIO/LCD for a
long-running service, which should be a deliberate step by whoever is actively working on the
hardware, not something that silently happens on the next reboot. To install:

```bash
sudo cp ~/suno-sutra-sw/python/pocketinfer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pocketinfer
sudo systemctl start pocketinfer
```

Watch it come up: `journalctl -f -u pocketinfer` -- you should see the same `[ORCH] LOAD agent`/
`agent ready in Ns`/`Statusbar: Ready - Press Button` sequence §2b describes, just under
systemd's log capture instead of a terminal. `sudo systemctl restart pocketinfer` after any code
change under `~/gramsahayak` or `~/suno-sutra-sw` -- neither venv's code is hot-reloaded.

**Stopping it during hardware work**: `sudo systemctl stop pocketinfer` releases the mic/speaker/
GPIO/LCD back for manual testing (e.g. running §2a/§2b by hand) without needing to disable the
unit first.

## 6. Updating this device to a newer gramsahayak

`~/gramsahayak` here is a **plain file checkout, not a git repo** -- it was synced directly from
the dev machine's working tree (`rsync`, excluding `venv/`/`__pycache__`/`archive/`/`logs/`), not
cloned. To bring it up to date with a newer version of the app:

1. From the dev machine: `rsync -av --exclude=venv --exclude=__pycache__ --exclude=archive
   --exclude=logs gramsahayak/ jetson:~/gramsahayak/` (or the equivalent scp for individual
   files) -- this preserves `~/gramsahayak/venv` and its already-installed packages.
2. Diff `requirements.txt` for anything new, then `~/gramsahayak/venv/bin/pip install -r
   requirements.txt` -- **but first check the ASR section**: the checked-in `requirements.txt`
   pins plain `onnxruntime` (the GX10/CPU pin); on Jetson this needs to stay
   `onnxruntime-gpu==1.24.0` (already the case in this device's own copy, with a comment marking
   it as a Jetson override) or ASR/NMT silently lose their CUDA/TensorRT providers. See §7's
   first gotcha for what actually happens if this gets missed.
3. If `~/gramsahayak`'s RAG corpus (`datasets/rag/*.sqlite`) needs updating independently of a
   full code sync, use the `sqlite-rag` branch's ingestion toolkit instead of a raw file copy --
   see that branch's own README for the real workflow (pull current DB, append/reingest, push
   back).
4. Re-run §2a's dummy-board test before trusting a real hardware run -- it's the fastest real
   confirmation that nothing broke.

## 7. Known gotchas (all hit and fixed live on this device, 2026-08-12)

- **`onnxruntime` vs `onnxruntime-gpu` in the same venv is a real conflict, not just clutter.**
  They share the same `onnxruntime` import path. Installing the plain CPU wheel into a venv that
  already has `onnxruntime-gpu` risks silently losing the CUDA/TensorRT providers (confirmed by
  triggering this for real, in both gramsahayak's venv AND, worse, `dev-local-test`'s venv via a
  broken-shebang mixup -- see next point). If `import onnxruntime; onnxruntime.get_available_providers()`
  ever stops listing `CUDAExecutionProvider`, this is the first thing to check --
  `pip list | grep onnxruntime` should show exactly one package, `onnxruntime-gpu`. Fix: `pip
  uninstall onnxruntime -y` (leave `-gpu` alone), or if providers are already gone, `pip install
  --force-reinstall --no-deps onnxruntime-gpu==1.24.0 --index-url=https://pypi.jetson-ai-lab.io/jp6/cu126`
  (the plain PyPI index doesn't carry Jetson CUDA wheels at all).
- **A venv's `bin/pip` can have a hardcoded shebang pointing at a DIFFERENT venv's interpreter**
  if it was ever created by copying another venv wholesale rather than `python -m venv`. This is
  a real, silent trap: `venv/bin/pip install X` then appears to succeed, `pip list`/`pip show`
  report sensible-looking output -- but everything actually happens against the OTHER venv,
  leaving the one you meant to change untouched (and the other one polluted). Confirmed this had
  already happened between `~/gramsahayak/venv` and `~/dev-local-test/.../gramsahayak/venv`
  before tonight (both created at the same timestamp, one copied from the other). Always sanity-
  check with `head -1 venv/bin/pip` (the shebang path should match the venv it's inside) or just
  use `venv/bin/python -m pip ...` instead of `venv/bin/pip ...` -- that form can't be fooled by
  a bad shebang since it uses the binary you actually invoked. Fix if found broken: `venv/bin/python
  -m pip install --force-reinstall --no-deps pip` regenerates a correct, self-referential shebang.
- **`gramsahayak_app.py`'s `verify_dependencies()` used to do a real cross-venv import** (`from
  agent import GramSahayakAgent`) using pocketinfer's OWN interpreter, before the real gateway
  subprocess (which uses gramsahayak's venv) ever starts -- guaranteed to fail on a genuine
  two-venv deployment the moment gramsahayak's code imports anything pocketinfer's venv doesn't
  have (hit this for real: `pandas`, pulled in by the weather tools). Fixed to just check the
  directory exists, matching what its own docstring already claimed it did.
- **`GramSahayakAgent` itself runs IN-PROCESS inside `pocketinfer-service`, not inside the
  gateway subprocess.** Only the heavy model-serving stack (torch/ctranslate2/fastapi/Ollama) is
  isolated into gramsahayak's own venv via the gateway subprocess -- the agent object and its RAG
  tools (`apsw`, `sqlite-vec`, `rank_bm25`, `pyyaml`) and the weather tools (`pandas`) import
  directly into pocketinfer's interpreter. All of these are now installed in
  `~/suno-sutra-sw/python/venv` too (confirmed necessary the hard way, one `ModuleNotFoundError`
  at a time) -- if `pocketinfer-service --app GramSahayak` ever throws one of these again after a
  gramsahayak code change that adds a new light dependency, install it into
  **pocketinfer's** venv, not gramsahayak's (which already has it, for the gateway's own use).
