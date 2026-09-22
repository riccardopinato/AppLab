#!/usr/bin/env bash
set -Eeuo pipefail

TIMEOUT="${1:-180}"
INTERVAL=2
STARTED_AT=$(date +%s)

echo "[AppLab] waiting for ADB device..."
adb wait-for-device

while true; do
  BOOTED="$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"
  ANIM="$(adb shell getprop init.svc.bootanim 2>/dev/null | tr -d '\r' || true)"
  if [[ "$BOOTED" == "1" && "$ANIM" != "running" ]]; then
    echo "[AppLab] Android boot completed."
    exit 0
  fi
  NOW=$(date +%s)
  if (( NOW - STARTED_AT >= TIMEOUT )); then
    echo "[AppLab] ERROR: Android did not boot within ${TIMEOUT}s." >&2
    adb devices -l || true
    exit 1
  fi
  sleep "$INTERVAL"
done
