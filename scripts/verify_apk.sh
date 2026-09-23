#!/usr/bin/env bash
set -Eeuo pipefail

APK_PATH="${1:-}"
PACKAGE_ID="${2:-${APP_ID:-}}"
REPORT_DIR="${REPORT_DIR:-applab-report}"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-180}"
START_TIMEOUT="${START_TIMEOUT:-30}"
SETTLE_SECONDS="${SETTLE_SECONDS:-5}"
MAESTRO_FLOW="${MAESTRO_FLOW:-}"
RUN_MAESTRO="${RUN_MAESTRO:-false}"

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

is_true() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

[[ -n "$APK_PATH" ]] || fail "APK path is required."
[[ -f "$APK_PATH" ]] || fail "APK not found: $APK_PATH"
command -v adb >/dev/null 2>&1 || fail "adb is not available on PATH."

mkdir -p "$REPORT_DIR"
rm -f   "$REPORT_DIR/launch.png"   "$REPORT_DIR/post-maestro.png"   "$REPORT_DIR/window.xml"   "$REPORT_DIR/post-maestro-window.xml"   "$REPORT_DIR/logcat.txt"

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

runtime_pid() {
  adb shell pidof "$PACKAGE_ID" 2>/dev/null | tr -d '\r' | awk '{print $1}' || true
}

capture_evidence() {
  local prefix="$1"
  local remote_xml="/sdcard/applab-${prefix}.xml"

  adb exec-out screencap -p > "$REPORT_DIR/${prefix}.png" || true
  adb shell uiautomator dump "$remote_xml" > "$REPORT_DIR/${prefix}-uiautomator.txt" 2>&1 || true
  adb pull "$remote_xml" "$REPORT_DIR/${prefix}-window.xml" > /dev/null 2>&1 || true
  adb shell dumpsys activity activities > "$REPORT_DIR/${prefix}-activity.txt" 2>&1 || true
  adb shell dumpsys window windows > "$REPORT_DIR/${prefix}-window-dumpsys.txt" 2>&1 || true
  adb logcat -b all -d -v threadtime > "$REPORT_DIR/logcat.txt" 2>&1 || true
}

assert_runtime_healthy() {
  local stage="$1"
  local pid
  pid="$(runtime_pid)"

  if [[ -z "$pid" ]]; then
    capture_evidence "failure-${stage}"
    fail "Application process died during ${stage}."
  fi

  adb logcat -b all -d -v threadtime > "$REPORT_DIR/logcat.txt" 2>&1 || true

  if grep -Fq "ANR in $PACKAGE_ID" "$REPORT_DIR/logcat.txt"; then
    capture_evidence "failure-${stage}"
    fail "ANR detected for $PACKAGE_ID during ${stage}."
  fi

  if grep -F -A 40 "FATAL EXCEPTION" "$REPORT_DIR/logcat.txt" | grep -Fq "Process: $PACKAGE_ID"; then
    capture_evidence "failure-${stage}"
    fail "Fatal exception detected for $PACKAGE_ID during ${stage}."
  fi

  printf '%s' "$pid"
}

if [[ -z "$PACKAGE_ID" ]]; then
  PACKAGE_ID="$(detect_package "$APK_PATH")"
fi
[[ -n "$PACKAGE_ID" ]] || fail "Unable to detect package id. Pass it as the second argument."

log "APK: $APK_PATH"
log "Package: $PACKAGE_ID"

"$(dirname "$0")/wait_for_android.sh" "$BOOT_TIMEOUT"

adb devices -l > "$REPORT_DIR/device.txt" || true
adb shell getprop >> "$REPORT_DIR/device.txt" 2>/dev/null || true
# Hosted Android emulators can surface launcher/SystemUI ANR dialogs over the
# app under test. Suppress those modal dialogs during automation; AppLab still
# detects package-specific ANRs and fatal exceptions directly from logcat.
adb shell settings put global hide_error_dialogs 1 >/dev/null 2>&1 || true
adb logcat -b all -c || true

log "installing APK..."
if ! adb install -r -t "$APK_PATH" > "$REPORT_DIR/install.txt" 2>&1; then
  cat "$REPORT_DIR/install.txt" >&2
  fail "APK installation failed."
fi

adb shell pm list packages | sort > "$REPORT_DIR/packages.txt" || true

log "launching application..."
adb shell am force-stop "$PACKAGE_ID" || true
adb shell monkey -p "$PACKAGE_ID" -c android.intent.category.LAUNCHER 1   > "$REPORT_DIR/launch.txt" 2>&1 || true

STARTED_AT="$(date +%s)"
PID=""
while true; do
  PID="$(runtime_pid)"
  [[ -n "$PID" ]] && break

  NOW="$(date +%s)"
  if (( NOW - STARTED_AT >= START_TIMEOUT )); then
    capture_evidence "failure-start"
    fail "Application process did not start within ${START_TIMEOUT}s."
  fi
  sleep 1
done

log "process started with PID $PID; settling for ${SETTLE_SECONDS}s..."
sleep "$SETTLE_SECONDS"

capture_evidence "launch"
cp "$REPORT_DIR/launch-window.xml" "$REPORT_DIR/window.xml" 2>/dev/null || true
cp "$REPORT_DIR/launch-activity.txt" "$REPORT_DIR/activity.txt" 2>/dev/null || true
cp "$REPORT_DIR/launch-window-dumpsys.txt" "$REPORT_DIR/window-dumpsys.txt" 2>/dev/null || true

PID_AFTER="$(assert_runtime_healthy "launch")"

MAESTRO_RESULT="SKIPPED"
if [[ -n "$MAESTRO_FLOW" ]] || is_true "$RUN_MAESTRO"; then
  command -v maestro >/dev/null 2>&1 || fail "Maestro was requested but is not installed."

  if [[ -z "$MAESTRO_FLOW" ]]; then
    MAESTRO_FLOW="$REPORT_DIR/generated-smoke.yaml"
    "$(dirname "$0")/create_maestro_smoke.sh" "$PACKAGE_ID" "$MAESTRO_FLOW" >/dev/null
  fi

  [[ -f "$MAESTRO_FLOW" ]] || fail "MAESTRO_FLOW does not exist: $MAESTRO_FLOW"

  # Run emulator-dialog handling and app assertions in one Maestro process.
  # Starting Maestro twice can race Android's package service on hosted AVDs.
  MAESTRO_RUNTIME_DIR="$REPORT_DIR/maestro-runtime"
  mkdir -p "$MAESTRO_RUNTIME_DIR" "$REPORT_DIR/maestro"
  cp "$MAESTRO_FLOW" "$MAESTRO_RUNTIME_DIR/app-flow.yaml"

  WRAPPER_FLOW="$MAESTRO_RUNTIME_DIR/applab-wrapper.yaml"
  cat > "$WRAPPER_FLOW" <<EOF
appId: $PACKAGE_ID
---
- launchApp:
    clearState: false
- runFlow:
    when:
      visible: "Pixel Launcher isn't responding"
    commands:
      - tapOn:
          text: "Close app"
          optional: true
- runFlow:
    file: app-flow.yaml
EOF

  run_maestro_attempt() {
    local attempt="$1"
    local attempt_dir="$REPORT_DIR/maestro/attempt-$attempt"
    local console_log="$REPORT_DIR/maestro/attempt-$attempt.log"
    local command_status

    mkdir -p "$attempt_dir"
    set +e
    maestro test "$WRAPPER_FLOW" --test-output-dir "$attempt_dir" 2>&1 | tee "$console_log"
    command_status="${PIPESTATUS[0]}"
    set -e
    return "$command_status"
  }

  MAESTRO_RESULT="FAIL"
  for attempt in 1 2 3; do
    log "running Maestro flow (attempt $attempt/3): $MAESTRO_FLOW"
    if run_maestro_attempt "$attempt"; then
      MAESTRO_RESULT="PASS"
      break
    fi

    CONSOLE_LOG="$REPORT_DIR/maestro/attempt-$attempt.log"
    if ! grep -Eqi "Broken pipe|Failure calling service package|device offline|device not found|connection reset|closed.*transport|transport.*error" "$CONSOLE_LOG"; then
      capture_evidence "maestro-failure"
      fail "Maestro flow failed."
    fi

    log "transient emulator/ADB failure detected; recovering before retry..."
    adb wait-for-device || true
    for _ in {1..15}; do
      if adb shell cmd package list packages android >/dev/null 2>&1; then
        break
      fi
      sleep 2
    done
    sleep 3
  done

  if [[ "$MAESTRO_RESULT" != "PASS" ]]; then
    capture_evidence "maestro-failure"
    fail "Maestro flow failed after transient-error retries."
  fi

  sleep 2
  capture_evidence "post-maestro"
  PID_AFTER="$(assert_runtime_healthy "post-maestro")"
fi

{
  echo "# AppLab report"
  echo
  echo "- Result: PASS"
  printf -- '- APK: %s\n' "$(basename "$APK_PATH")"
  printf -- '- Package: %s\n' "$PACKAGE_ID"
  printf -- '- PID after verification: %s\n' "$PID_AFTER"
  echo "- Maestro: $MAESTRO_RESULT"
  printf -- '- Screenshot: launch.png\n'
  if [[ "$MAESTRO_RESULT" == "PASS" ]]; then
    printf -- '- Post-Maestro screenshot: post-maestro.png\n'
    printf -- '- Post-Maestro UI hierarchy: post-maestro-window.xml\n'
  fi
  printf -- '- UI hierarchy: window.xml\n'
  printf -- '- Logcat: logcat.txt\n'
} > "$REPORT_DIR/summary.md"

log "PASS — report written to $REPORT_DIR"
