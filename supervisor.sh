#!/bin/bash
set -u
DEADLINE_TS=$1
export DEVICE_TEST_DEADLINE_TS=$DEADLINE_TS
LOG=~/gramsahayak/device_test_audio_batch2/supervisor.log
echo "[SUPERVISOR] starting, deadline_ts=$DEADLINE_TS, now=$(date +%s)" >> "$LOG"
while [ "$(date +%s)" -lt "$DEADLINE_TS" ]; do
  cd ~/gramsahayak
  echo "[SUPERVISOR] $(date): resetting session before (re)launch" >> "$LOG"
  venv/bin/python reset_session.py >> "$LOG" 2>&1
  echo "[SUPERVISOR] $(date): launching driver, $(( DEADLINE_TS - $(date +%s) ))s remaining" >> "$LOG"
  venv/bin/python run_device_test_suite_v3.py >> "$LOG" 2>&1
  EXIT_CODE=$?
  echo "[SUPERVISOR] $(date): driver exited code=$EXIT_CODE, $(( DEADLINE_TS - $(date +%s) ))s remaining" >> "$LOG"
  if [ "$(date +%s)" -lt "$DEADLINE_TS" ]; then
    echo "[SUPERVISOR] time remains -- relaunching in 5s" >> "$LOG"
    sleep 5
  fi
done
echo "[SUPERVISOR] deadline reached at $(date), stopping" >> "$LOG"
touch ~/gramsahayak/device_test_audio_batch2/SUPERVISOR_DONE
