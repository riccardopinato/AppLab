#!/usr/bin/env bash
set -Eeuo pipefail

APK_PATH="${1:-}"
PACKAGE_ID="${2:-${APP_ID:-}}"
REPORT_DIR="${REPORT_DIR:-applab-report}"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-180}"
START_TIMEOUT="${START_TIMEOUT:-30}"
SETTLE_SECONDS="${SETTLE_SECONDS:-5}"
MAESTRO_FLOW="${MAESTRO_FLOW:-}"

fail() {
  echo "[AppLab] ERROR: $*" >&2
  mkdir -p "$REPORT_DIR"
  {
    echo "# AppLab report"
    echo
    echo "- Result: FAIL"
    echo "- Reason: $*"
  } > "$REPORT_DIR/summary.md"
  exit 1
}

log() { echo "[AppLab] $*"; }

[[ -n "$APK_PATH" ]] || fail "APK path is required."
[[ -f "$APK_PATH" ]] || fail "APK not found: $APK_PATH"
command -v adb >/dev/null 2>&1 || fail "adb is not available on PATH."

mkdir -p "$REPORT_DIR"
rm -f "$REPORT_DIR"/launch.png "$REPORT_DIR"/window.xml "$REPORT_DIR"/logcat.txt

detect_package() {
  local apk="$1"
  local result=""
  if command -v apkanalyzer >/dev/null 2>&1; then
    result="$(apkanalyzer manifest application-id "$apk" 2>/dev/null | head -n1 | tr -d '\r' || true)"
  fi
  if [[ -z "$result" ]] && command -v aapt2 >/dev/null 2>&1; then
    result="$(aapt2 dump badging "$apk" 2>/dev/null | sed -n "s/^package: name='\([^']*\)'.*/\1/p" | head -n1)"
  fi
  if [[ -z "$result" ]] && command -v aapt >/dev/null 2>&1; then
    result="$(aapt dump badging "$apk" 2>/dev/null | sed -n "s/^package: name='\([^']*\)'.*/\1/p" | head -n1)"
  fi
  printf '%s' "$result"
}

if [[ -z "$PACKAGE_ID" ]]; then PACKAGE_ID="$(detect_package "$APK_PATH")"; fi
[[ -n "$PACKAGE_ID" ]] || fail "Unable to detect package id. Pass it as the second argument."

log "APK: $APK_PATH"
log "Package: $PACKAGE_ID"

"$(dirname "$0")/wait_for_android.sh" "$BOOT_TIMEOUT"

adb devices -l > "$REPORT_DIR/device.txt" || true
adb shell getprop >> "$REPORT_DIR/device.txt" 2>/dev/null || true
adb logcat -c || true

log "installing APK..."
if ! adb install -r -t "$APK_PATH" > "$REPORT_DIR/install.txt" 2>&1; then
  cat "$REPORT_DIR/install.txt" >&2
  fail "APK installation failed."
fi

adb shell pm list packages | sort > "$REPORT_DIR/packages.txt" || true

log "launching application..."
adb shell am force-stop "$PACKAGE_ID" || true
adb shell monkey -p "$PACKAGE_ID" -c android.intent.category.LAUNCHER 1   > "$REPORT_DIR/launch.txt" 2>&1 || true

STARTED_AT=$(date +%s)
PID=""
while true; do
  PID="$(adb shell pidof "$PACKAGE_ID" 2>/dev/null | tr -d '\r' | awk '{print $1}' || true)"
  [[ -n "$PID" ]] && break
  NOW=$(date +%s)
  if (( NOW - STARTED_AT >= START_TIMEOUT )); then
    adb logcat -d -v threadtime > "$REPORT_DIR/logcat.txt" 2>&1 || true
    fail "Application process did not start within ${START_TIMEOUT}s."
  fi
  sleep 1
done

log "process started with PID $PID; settling for ${SETTLE_SECONDS}s..."
sleep "$SETTLE_SECONDS"

adb exec-out screencap -p > "$REPORT_DIR/launch.png" || true
adb shell uiautomator dump /sdcard/applab-window.xml > "$REPORT_DIR/uiautomator.txt" 2>&1 || true
adb pull /sdcard/applab-window.xml "$REPORT_DIR/window.xml" > /dev/null 2>&1 || true
adb shell dumpsys activity activities > "$REPORT_DIR/activity.txt" 2>&1 || true
adb shell dumpsys window windows > "$REPORT_DIR/window-dumpsys.txt" 2>&1 || true
adb logcat -d -v threadtime > "$REPORT_DIR/logcat.txt" 2>&1 || true

PID_AFTER="$(adb shell pidof "$PACKAGE_ID" 2>/dev/null | tr -d '\r' | awk '{print $1}' || true)"
[[ -n "$PID_AFTER" ]] || fail "Application process died after launch."

if grep -Fq "ANR in $PACKAGE_ID" "$REPORT_DIR/logcat.txt"; then
  fail "ANR detected for $PACKAGE_ID."
fi
if grep -Fq "Process: $PACKAGE_ID" "$REPORT_DIR/logcat.txt" && grep -Fq "FATAL EXCEPTION" "$REPORT_DIR/logcat.txt"; then
  fail "Fatal exception detected for $PACKAGE_ID."
fi

MAESTRO_RESULT="SKIPPED"
if [[ -n "$MAESTRO_FLOW" ]]; then
  [[ -f "$MAESTRO_FLOW" ]] || fail "MAESTRO_FLOW does not exist: $MAESTRO_FLOW"
  command -v maestro >/dev/null 2>&1 || fail "Maestro flow requested but maestro is not installed."
  log "running Maestro flow: $MAESTRO_FLOW"
  if maestro test "$MAESTRO_FLOW" --test-output-dir "$REPORT_DIR/maestro"; then
    MAESTRO_RESULT="PASS"
  else
    MAESTRO_RESULT="FAIL"
    adb logcat -d -v threadtime > "$REPORT_DIR/logcat.txt" 2>&1 || true
    fail "Maestro flow failed."
  fi
fi

{
  echo "# AppLab report"
  echo
  echo "- Result: PASS"
  printf -- '- APK: `%s`\\n' "$(basename \"$APK_PATH\")"
  printf -- '- Package: `%s`\\n' "$PACKAGE_ID"
  printf -- '- PID after settle: `%s`\\n' "$PID_AFTER"
  echo "- Maestro: $MAESTRO_RESULT"
  printf -- '- Screenshot: `launch.png`\\n'
  printf -- '- UI hierarchy: `window.xml`\\n'
  printf -- '- Logcat: `logcat.txt`\\n'
} > "$REPORT_DIR/summary.md"

log "PASS — report written to $REPORT_DIR"
