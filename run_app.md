# Running GramSahayak on the Jetson

Quick-reference cheat sheet. Full details (hardware wiring, output mapping, gotchas already hit
and fixed) live in `~/gramsahayak/JETSON_DEPLOYMENT.md` on the device itself -- this file is the
commands, that one is the why.

## Connect

```bash
ssh jetson@100.117.13.115  # tailscale ssh
```
Password (only needed for `sudo`): 

Two separate checkouts live on the device, each with its own venv -- see
`JETSON_DEPLOYMENT.md` §1 for why they're split:
- `~/gramsahayak` -- the AI pipeline (agent, RAG, ASR/NMT/TTS gateway). Plain rsync'd checkout,
  not a git repo.
- `~/suno-sutra-sw/python` (`pocketinfer` package) -- the hardware layer (mic/camera/button/LCD/
  speaker) that drives it. Real git checkout.

There's also `~/dev-local-test/vyoma-hackathon-bhashini/gramsahayak` -- an older working copy
used during development. `~/gramsahayak` is the one the real app (`pocketinfer-service`) points
at by default (`GRAMSAHAYAK_DIR`), and the one to keep current -- see "Updating" below.

## Speaker volume (temporarily muted during a late-night debugging session)

2026-08-13/14: speaker output (card 1, `UACDemoV1.0`) was first turned down to 20%, then fully
**muted** (`amixer -c 1 sset PCM mute`) partway through, since testing was happening late at
night in India and real TTS playback would otherwise be audible to people sleeping near the
device. Restore when you're back at the device:
```bash
amixer -c 1 sset PCM unmute 100%
```

## First steps: optimize the environment before running anything

Real, one-time (or one-per-boot) device tuning -- do this before a real session, not part of
the app itself. Two independent things: freeing RAM the desktop/services don't need, and
setting the power mode that actually gives the CPU/GPU real headroom (this is the one that
already had a real, measured, load-bearing effect once before -- see below).

### Free RAM: disable the desktop GUI + unneeded services

Source: [jetson-ai-lab.com RAM optimization guide](https://www.jetson-ai-lab.com/tutorials/ram-optimization/),
confirmed applicable to this device (`systemctl get-default` currently shows `graphical.target`,
`nvargus-daemon.service` is currently enabled) -- 2026-08-13.

```bash
# Recovers ~800MB the window manager/desktop normally holds. Only matters for headless/SSH
# operation (this device's own real screen is pocketinfer's own embedded LCD, driven directly
# by the app -- not the same thing as the Jetson OS's own desktop session over HDMI).
sudo systemctl set-default multi-user.target   # boots to text/console mode from now on
sudo init 3                                    # drop out of the desktop right now, no reboot needed
# sudo systemctl set-default graphical.target  # to undo, if you ever need the desktop back

# NVIDIA's camera-argus daemon -- not used by this pipeline (pocketinfer talks to the camera
# directly), safe to disable.
sudo systemctl disable nvargus-daemon.service
```

**Swap**: the guide also recommends disabling `nvzramconfig` in favor of a real swapfile on
storage -- already a non-issue on this device: `nvzramconfig` doesn't even exist on this
JetPack 7.2 image (`systemctl is-enabled nvzramconfig` -> `not-found`), and a real 32GB
swapfile is already active (`swapon --show`). Nothing to change here.

### Power mode: real, measured effect on LLM decode speed

**Real finding from the old (pre-wipe) device, 2026-08-11** (`JETSON_SESSION_LOG_2026-08-11.md`):
`nvpmodel -m 2` (MAXN, full power -- not the default) + `jetson_clocks` closed a real gap in
qwen3.5:2b's own decode speed and was part of the final validated config. This was a real,
load-bearing fix then, not a nice-to-have -- redo it on this recovered device too.

This device's real mode table (`< POWER_MODEL ID=... NAME=... >` in `/etc/nvpmodel.conf`,
confirmed directly, 2026-08-13 -- don't assume the old device's mode *number* carries over,
only check by name):

```
ID=0  NAME=15W
ID=1  NAME=25W          <- current default mode on this device
ID=2  NAME=MAXN_SUPER   <- what we want
```

```bash
sudo nvpmodel -m 2       # MAXN_SUPER on this device -- confirm the ID for MAXN/MAXN_SUPER
                          # via `sudo nvpmodel -q --verbose` first if this is ever a different
                          # device/image, the number is not guaranteed to stay 2
sudo jetson_clocks        # locks clocks at the selected mode's max, don't skip this part --
                          # nvpmodel alone sets the ceiling, jetson_clocks is what actually
                          # runs there instead of scaling down when idle
sudo nvpmodel -q          # confirm: should print "NV Power Mode: MAXN_SUPER"
```

`nvpmodel`'s mode selection persists across reboots on its own (`nvpmodel.service` is already
enabled on this device and reapplies the saved mode at boot). `jetson_clocks` does NOT persist
by itself, so a small systemd oneshot unit now handles it (installed 2026-08-13,
`/etc/systemd/system/jetson-power.service`, `WantedBy=multi-user.target`, runs `jetson_clocks`
once at every boot after `nvpmodel.service`):

```bash
sudo systemctl status jetson-power.service   # confirm it ran and stayed "active (exited)"
sudo nvpmodel -q                              # should still show MAXN_SUPER after a reboot
sudo jetson_clocks --show                     # CPU/GPU MinFreq should equal MaxFreq (locked)
```

### Clean slate before testing

`venv/bin/python reset_session.py` (in `~/gramsahayak`) forces everything back to empty --
unloads Ollama's agent/embedder (`keep_alive=0`, doesn't need a running gateway), gracefully
unloads any live ASR/NMT/TTS worker through the gateway if one's up, and `pkill`s any orphaned
worker process as a hard fallback. Real gotcha this exists to close: Ollama's own
`keep_alive=-1` keeps qwen3.5:2b resident across *separate* script runs, not just within one --
starting a "fresh" test right after a previous one without this can silently inherit a warm
agent the new run never itself loaded, which throws off its own memory accounting (confirmed
real, 2026-08-13). Run this before any real test if you want genuinely comparable before/after
numbers.

## Ways to run it

### 1. Backend only, no hardware layer -- fastest way to test a pipeline/model/RAG change

```bash
cd ~/gramsahayak
venv/bin/python test_orchestrated_pipeline.py --language hi --with-image --no-play
```
`--language` any of `hi`/`ta`/`ml`/`en`. `--with-image` optional. `--help` for the rest. Talks
directly to gramsahayak's own gateway -- pocketinfer/hardware layer isn't involved at all. This
is what most of the pipeline tuning work actually ran against.

### 2. Full real app, no physical hardware needed -- dummy-board test

Runs the actual `GramSahayak` pocketinfer application (real ASR/NMT/Agent/RAG/TTS, only the
mic/camera/button/screen I/O is swapped for file input), including real playback through
whatever speaker is actually plugged into the device:

```bash
cd ~/suno-sutra-sw/python
venv/bin/pocketinfer-service --app GramSahayak --dummy-board \
    --audio-file ~/gramsahayak/sample_audio/multiturn_stress/hi/turn1.wav \
    --image-file ~/gramsahayak/datasets/sample-images/late-blight-potatoes_file.jpg \
    --log-level INFO \
    --setting input_language=hi --setting output_language=hi
```

Runs exactly one turn, prints the full `[ORCH]` trace, tears down cleanly, exits. Takes a few
minutes end to end (agent load if not already warm, ASR, NMT, the tool-calling agent turn, NMT
back, TTS, playback).

- Swap `input_language`/`output_language` to `ta`, `ml`, or `en` for other languages (`en` input
  transcribes locally via Vosk, not gramsahayak's ASR).
- Drop `--image-file` for a voice-only question.
- `--audio-file` needs to be 16kHz/16-bit mono -- check with `soxi <file>`. Other real
  pre-recorded questions live under `~/gramsahayak/sample_audio/multiturn_stress/<lang>/turn{1..5}.wav`.
- **Confirmed working live, 2026-08-12**: real Hindi transcription of a farmer describing black
  spots on a potato photo, real `analyze_photo` -> `plant_disease_lookup` -> `get_treatment_details`
  -> `get_guidelines_and_safety` tool calls against the live RAG corpus, coherent Hindi answer,
  real TTS synthesis and playback through the device's actual USB speaker (`aplay -l` shows it as
  `card 0: UACDemoV1.0`; confirmed separately with a raw `speaker-test` tone), clean teardown
  back to near-idle memory.

### 3. Real hardware -- actual button press, live mic, LCD, speaker

```bash
cd ~/suno-sutra-sw/python
venv/bin/pocketinfer-service --app GramSahayak --log-level INFO
```

No `--dummy-board`, no file args. `Board.get_board()` auto-detects the real board (reads
`/proc/device-tree/model` + i2c EEPROM -- nothing to configure). Runs forever, one turn per
trigger-button press. Ctrl+C to stop. Watch the LCD for `"Ready - Press Button"`.

**Confirmed live, 2026-08-12**: board auto-detect correctly identifies this device as the real
Devboard-UI variant, real capture device (`Arducam_8mp`) and playback device (`UACDemoV1.0`)
found by name (both individually confirmed working via `arecord`/`speaker-test` too), gateway
starts, agent loads. **Not yet confirmed**: a full turn actually triggered by a physical button
press -- that needs someone physically at the device to hold the button and speak (not something
safely simulated over SSH -- driving a real GPIO input pin remotely without knowing the button
module's exact pull wiring risks the hardware).

## Setting up a fresh device (or recovering one)

Real gaps hit and fixed getting this working on 2026-08-12 -- check these first if a fresh clone
of `suno-sutra-sw` fails in a similar way:

1. **Binary assets need `git lfs pull`.** `suno-sutra-sw` stores fonts etc. via git-lfs; a plain
   `git clone` (or one where `git lfs pull` was skipped) leaves them as small pointer text files.
   Symptom: `ValueError: Unknown magic number b'vers'` loading the LCD font, the instant the real
   (non-dummy) board tries to start. Fix: `cd ~/suno-sutra-sw && git lfs pull --include "python/**"`.
2. **`Jetson.GPIO` isn't in `requirements.txt`** but `boards/jetson.py` needs it. Symptom:
   `ModuleNotFoundError: No module named 'Jetson'` the moment real (non-dummy) board detection
   runs (dummy-board never imports this file, so this only surfaces on a real-hardware attempt).
   Fix: `~/suno-sutra-sw/python/venv/bin/pip install Jetson.GPIO`.
3. **pocketinfer's venv needs gramsahayak's *light* deps too**, not just its heavy ones staying
   isolated -- `GramSahayakAgent` itself runs in-process inside `pocketinfer-service` (only the
   ASR/NMT/TTS/Ollama gateway is a separate subprocess in gramsahayak's own venv). Confirmed
   needed in pocketinfer's venv: `pandas`, `apsw`, `sqlite-vec`, `rank_bm25`, `pyyaml`. If a
   future gramsahayak change adds a new lightweight top-level import to `agent.py` or its tools,
   it needs installing here too, not just in `~/gramsahayak/venv`.
4. **`onnxruntime` (CPU) and `onnxruntime-gpu` conflict if both land in the same venv** -- they
   share the same import path. `~/gramsahayak/requirements.txt` is deliberately patched to pin
   `onnxruntime-gpu==1.24.0` instead of the plain `onnxruntime` GX10/dev-machine pin -- don't
   overwrite it with an unmodified copy from the dev machine's `requirements.txt` without
   re-applying that swap. If providers ever look wrong: `python -c "import onnxruntime;
   print(onnxruntime.get_available_providers())"` should list `CUDAExecutionProvider`. Fix:
   `pip uninstall onnxruntime -y` (keep `-gpu`), or if that's already broken,
   `pip install --force-reinstall --no-deps onnxruntime-gpu==1.24.0 --index-url=https://pypi.jetson-ai-lab.io/jp6/cu126`.
5. **A venv's own `bin/pip` can silently point at a DIFFERENT venv's interpreter** if it was ever
   created by copying another venv wholesale instead of a real `python -m venv`. `pip
   list`/`pip show` will look completely normal while actually operating on the wrong
   environment. Check with `head -1 venv/bin/pip` -- the shebang path must match the venv it's
   physically inside. Prefer `venv/bin/python -m pip ...` over `venv/bin/pip ...` in general;
   the former can't be fooled by a bad shebang. Fix a broken one: `venv/bin/python -m pip install
   --force-reinstall --no-deps pip`.

## Deploying for production -- start on boot, agent prewarmed

`~/suno-sutra-sw/python/pocketinfer.service` is a systemd unit already adapted to this device's
real paths (checked into the repo with `~/suno-sutra-sw` / `~/gramsahayak` baked in, not the
generic `/home/ubuntu/pocket-infer-sw` placeholder the upstream template uses). It runs
`pocketinfer-service --app GramSahayak` -- by the time systemd reports the unit started, the
gateway is healthy AND the agent is already loaded into Ollama, not just "the process exists".

**Not installed/enabled by default** -- this claims the mic/speaker/GPIO/LCD for a long-running
service, so it's a deliberate step, not something that happens on a random reboot:

```bash
sudo cp ~/suno-sutra-sw/python/pocketinfer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pocketinfer   # survives reboot
sudo systemctl start pocketinfer
```

Watch it come up: `journalctl -f -u pocketinfer` -- same `[ORCH] LOAD agent` / `agent ready in
Ns` / `Statusbar: Ready - Press Button` sequence as running it by hand, just under systemd's log
capture. `sudo systemctl restart pocketinfer` after any code change under `~/gramsahayak` or
`~/suno-sutra-sw` -- neither venv hot-reloads.

To free the hardware for manual testing (§2/§3 above) without disabling the unit permanently:
`sudo systemctl stop pocketinfer`.

## Updating `~/gramsahayak` to a newer build

`~/gramsahayak` is a plain rsync'd checkout, not a git repo. From the dev machine:

```bash
rsync -av --exclude=venv --exclude=__pycache__ --exclude=archive --exclude=logs \
    gramsahayak/ jetson:~/gramsahayak/
```

This preserves `~/gramsahayak/venv` and everything already installed in it. Then on the Jetson:
diff `requirements.txt` for anything new, re-apply the `onnxruntime-gpu` swap (gotcha #4 above)
if it got overwritten, and `venv/bin/pip install -r requirements.txt`. Re-run §2's dummy-board
test before trusting a real hardware run.

See `~/gramsahayak/JETSON_DEPLOYMENT.md` for the fuller version of everything above, including
the exact hardware wiring (mic/camera/button/LCD/speaker), what the LCD actually displays at
each pipeline stage, and why the code's `led_animation()`/`button_led()` calls are harmless
no-ops on this specific board variant (no discrete LED wired on the Devboard -- only the other
enclosed "Suno Sutra Demo" product variant has one).
