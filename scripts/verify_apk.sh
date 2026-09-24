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
APPLAB_VERSION="${APPLAB_VERSION:-0.6.2}"
VISUAL_BASELINE_DIR="${VISUAL_BASELINE_DIR:-${APPLAB_VISUAL_BASELINE_DIR:-}}"
TARGET_ROOT="${APPLAB_TARGET_ROOT:-}"
VISUAL_JOURNEY_MANIFEST="${APPLAB_VISUAL_JOURNEY_MANIFEST:-}"
VISUAL_QA_RESULT="SKIPPED"
VISUAL_REGRESSION_RESULT="NO_BASELINE"
VISUAL_JOURNEY_RESULT="SKIPPED"

write_result_json() {
  local result="$1"
  local reason="${2:-}"
  local pid_value="${3:-}"
  local maestro_result="${4:-SKIPPED}"

  mkdir -p "$REPORT_DIR"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$REPORT_DIR/result.json" "$result" "${PACKAGE_ID:-}" "$maestro_result" "$pid_value" "$reason" "$APPLAB_VERSION" "${APK_PATH:-}" "${VISUAL_QA_RESULT:-SKIPPED}" "${VISUAL_REGRESSION_RESULT:-NO_BASELINE}" "${VISUAL_JOURNEY_RESULT:-SKIPPED}" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

output, result, package_id, maestro, pid_value, reason, version, apk_path, visual_qa, visual_regression, visual_journey = sys.argv[1:]
payload = {
    "schema_version": 1,
    "applab_version": version,
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "result": result,
    "reason": reason or None,
    "apk": Path(apk_path).name if apk_path else "",
    "package_id": package_id,
    "pid": pid_value,
    "maestro": maestro,
    "visual_qa": visual_qa,
    "visual_regression": visual_regression,
    "visual_journey": visual_journey,
    "evidence": {
        "summary": "summary.md",
        "launch_screenshot": "launch.png",
        "post_maestro_screenshot": "post-maestro.png",
        "ui_hierarchy": "window.xml",
        "logcat": "logcat.txt",
        "app_logcat": "app-logcat.txt",
        "visual_qa_json": "visual-qa.json",
        "visual_qa_summary": "visual-qa.md",
        "visual_regression_json": "visual-regression.json",
        "visual_regression_summary": "visual-regression.md",
        "visual_journey_json": "visual-journey.json",
        "visual_journey_summary": "visual-journey.md",
    },
}
Path(output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  else
    printf '{"result":"%s","applab_version":"%s"}\n' "$result" "$APPLAB_VERSION" > "$REPORT_DIR/result.json"
  fi
}

fail() {
  local reason="$*"
  echo "[AppLab] ERROR: $reason" >&2
  mkdir -p "$REPORT_DIR"
  {
    echo "# AppLab report"
    echo
    echo "- Result: FAIL"
    echo "- AppLab: $APPLAB_VERSION"
    echo "- Reason: $reason"
  } > "$REPORT_DIR/summary.md"
  write_result_json "FAIL" "$reason" "" "${MAESTRO_RESULT:-SKIPPED}"
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
rm -f   "$REPORT_DIR/launch.png"   "$REPORT_DIR/post-maestro.png"   "$REPORT_DIR/window.xml"   "$REPORT_DIR/post-maestro-window.xml"   "$REPORT_DIR/logcat.txt" \
  "$REPORT_DIR/visual-qa.json" \
  "$REPORT_DIR/visual-qa.md" \
  "$REPORT_DIR/visual-regression.json" \
  "$REPORT_DIR/visual-regression.md" \
  "$REPORT_DIR/visual-journey.json" \
  "$REPORT_DIR/visual-journey.md"
rm -rf "$REPORT_DIR/visual-journey"
mkdir -p "$REPORT_DIR/visual-journey/current"

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
  adb logcat --pid="$pid" -d -v threadtime > "$REPORT_DIR/app-logcat.txt" 2>&1 || true

  if grep -Fq "ANR in $PACKAGE_ID" "$REPORT_DIR/logcat.txt"; then
    capture_evidence "failure-${stage}"
    fail "ANR detected for $PACKAGE_ID during ${stage}."
  fi

  if grep -F -A 40 "FATAL EXCEPTION" "$REPORT_DIR/logcat.txt" | grep -Fq "Process: $PACKAGE_ID"; then
    capture_evidence "failure-${stage}"
    fail "Fatal exception detected for $PACKAGE_ID during ${stage}."
  fi

  if grep -Eqi "Unhandled Exception:|EXCEPTION CAUGHT BY (WIDGETS|RENDERING|SCHEDULER) LIBRARY|Failed assertion:|Another exception was thrown" "$REPORT_DIR/app-logcat.txt"; then
    capture_evidence "failure-${stage}"
    fail "Unhandled Flutter/framework exception detected for $PACKAGE_ID during ${stage}."
  fi

  printf '%s' "$pid"
}

run_visual_qa() {
  local screenshot="$REPORT_DIR/launch.png"
  local hierarchy="$REPORT_DIR/launch-window.xml"
  local status=0

  if [[ -s "$REPORT_DIR/post-maestro.png" && -s "$REPORT_DIR/post-maestro-window.xml" ]]; then
    screenshot="$REPORT_DIR/post-maestro.png"
    hierarchy="$REPORT_DIR/post-maestro-window.xml"
  fi

  [[ -s "$screenshot" ]] || fail "Smart Visual QA screenshot is missing."
  [[ -s "$hierarchy" ]] || fail "Smart Visual QA UI hierarchy is missing."

  log "running Smart Visual QA..."
  set +e
  python3 "$(dirname "$0")/visual_qa.py" \
    --screenshot "$screenshot" \
    --ui-hierarchy "$hierarchy" \
    --package-id "$PACKAGE_ID" \
    --output-json "$REPORT_DIR/visual-qa.json" \
    --output-md "$REPORT_DIR/visual-qa.md"
  status="$?"
  set -e

  if [[ -s "$REPORT_DIR/visual-qa.json" ]]; then
    VISUAL_QA_RESULT="$(
      python3 - "$REPORT_DIR/visual-qa.json" <<'PY'
import json
import sys
from pathlib import Path

try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(str(payload.get("result", "UNKNOWN")))
except Exception:
    print("UNKNOWN")
PY
    )"
  else
    VISUAL_QA_RESULT="ERROR"
  fi

  if [[ "$status" -ne 0 || "$VISUAL_QA_RESULT" == "FAIL" || "$VISUAL_QA_RESULT" == "ERROR" ]]; then
    fail "Smart Visual QA detected a high-confidence visual/runtime anomaly."
  fi

  log "Smart Visual QA: $VISUAL_QA_RESULT"
}

run_visual_regression() {
  local current_screenshot="$REPORT_DIR/launch.png"
  local current_hierarchy="$REPORT_DIR/launch-window.xml"
  local baseline_screenshot=""
  local baseline_hierarchy=""
  local baseline_metadata=""
  local status=0

  if [[ -s "$REPORT_DIR/post-maestro.png" && -s "$REPORT_DIR/post-maestro-window.xml" ]]; then
    current_screenshot="$REPORT_DIR/post-maestro.png"
    current_hierarchy="$REPORT_DIR/post-maestro-window.xml"
  fi

  if [[ -z "$VISUAL_BASELINE_DIR" || ! -d "$VISUAL_BASELINE_DIR" ]]; then
    VISUAL_REGRESSION_RESULT="NO_BASELINE"
    log "Visual Regression: NO_BASELINE — current PASS will become the first baseline."
    return 0
  fi

  baseline_screenshot="$VISUAL_BASELINE_DIR/screenshot.png"
  baseline_hierarchy="$VISUAL_BASELINE_DIR/window.xml"
  baseline_metadata="$VISUAL_BASELINE_DIR/metadata.json"

  if [[ ! -s "$baseline_screenshot" || ! -s "$baseline_hierarchy" ]]; then
    VISUAL_REGRESSION_RESULT="NO_BASELINE"
    log "Visual Regression: NO_BASELINE — baseline cache is incomplete."
    return 0
  fi

  log "running Visual Regression against last passing baseline..."
  set +e
  python3 "$(dirname "$0")/visual_regression.py" \
    --baseline-screenshot "$baseline_screenshot" \
    --baseline-ui "$baseline_hierarchy" \
    --baseline-metadata "$baseline_metadata" \
    --current-screenshot "$current_screenshot" \
    --current-ui "$current_hierarchy" \
    --package-id "$PACKAGE_ID" \
    --output-json "$REPORT_DIR/visual-regression.json" \
    --output-md "$REPORT_DIR/visual-regression.md"
  status="$?"
  set -e

  if [[ -s "$REPORT_DIR/visual-regression.json" ]]; then
    VISUAL_REGRESSION_RESULT="$(
      python3 - "$REPORT_DIR/visual-regression.json" <<'PY'
import json
import sys
from pathlib import Path

try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(str(payload.get("result", "UNKNOWN")))
except Exception:
    print("UNKNOWN")
PY
    )"
  else
    VISUAL_REGRESSION_RESULT="ERROR"
  fi

  if [[ "$status" -ne 0 || "$VISUAL_REGRESSION_RESULT" == "FAIL" || "$VISUAL_REGRESSION_RESULT" == "ERROR" ]]; then
    fail "Visual Regression detected a high-confidence regression against the last passing baseline."
  fi

  log "Visual Regression: $VISUAL_REGRESSION_RESULT"
}

capture_visual_checkpoint() {
  local name="$1"
  local checkpoint_dir="$REPORT_DIR/visual-journey/current/$name"
  local remote_xml="/sdcard/applab-journey-$name.xml"

  mkdir -p "$checkpoint_dir"
  adb exec-out screencap -p > "$checkpoint_dir/screenshot.png" || true
  adb shell uiautomator dump "$remote_xml" > "$checkpoint_dir/uiautomator.txt" 2>&1 || true
  adb pull "$remote_xml" "$checkpoint_dir/window.xml" > /dev/null 2>&1 || true

  [[ -s "$checkpoint_dir/screenshot.png" ]] ||
    fail "Visual Journey checkpoint $name has no screenshot."
  [[ -s "$checkpoint_dir/window.xml" ]] ||
    fail "Visual Journey checkpoint $name has no UI hierarchy."
}

run_custom_visual_journey() {
  local manifest="$VISUAL_JOURNEY_MANIFEST"
  local normalized="$REPORT_DIR/visual-journey/manifest.json"

  if [[ -z "$manifest" && -n "$TARGET_ROOT" && -f "$TARGET_ROOT/.maestro/applab-journey.json" ]]; then
    manifest="$TARGET_ROOT/.maestro/applab-journey.json"
  elif [[ -n "$manifest" && "$manifest" != /* && -n "$TARGET_ROOT" ]]; then
    manifest="$TARGET_ROOT/$manifest"
  fi

  [[ -n "$manifest" ]] || return 0
  [[ -f "$manifest" ]] || fail "Visual Journey manifest not found: $manifest"
  command -v maestro >/dev/null 2>&1 ||
    fail "Visual Journey manifest requires Maestro."

  python3 "$(dirname "$0")/visual_journey.py" \
    --validate-manifest "$manifest" \
    --normalized-manifest "$normalized"

  while IFS=  PACKAGE_ID="$(detect_package "$APK_PATH")"
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
capture_visual_checkpoint "launch"
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
# verify_apk.sh already launched the package through ADB. Do not launch it
# again here: repeated immediate launches can recreate platform views (MapLibre,
# CameraX, WebView) while their native side is still initializing.
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

if [[ "$MAESTRO_RESULT" == "PASS" ]]; then
  cp "$REPORT_DIR/post-maestro.png" "$REPORT_DIR/visual-journey/current/final-snapshot.png" 2>/dev/null || true
  capture_visual_checkpoint "final"
else
  capture_visual_checkpoint "final"
fi

run_custom_visual_journey
run_visual_qa
run_visual_regression
run_visual_journey

{
  echo "# AppLab report"
  echo
  echo "- Result: PASS"
  echo "- AppLab: $APPLAB_VERSION"
  printf -- '- APK: %s\n' "$(basename "$APK_PATH")"
  printf -- '- Package: %s\n' "$PACKAGE_ID"
  printf -- '- PID after verification: %s\n' "$PID_AFTER"
  echo "- Maestro: $MAESTRO_RESULT"
  echo "- Smart Visual QA: $VISUAL_QA_RESULT"
  echo "- Visual Regression: $VISUAL_REGRESSION_RESULT"
  echo "- Multi-Screen Visual Journey: $VISUAL_JOURNEY_RESULT"
  printf -- '- Screenshot: launch.png\n'
  if [[ "$MAESTRO_RESULT" == "PASS" ]]; then
    printf -- '- Post-Maestro screenshot: post-maestro.png\n'
    printf -- '- Post-Maestro UI hierarchy: post-maestro-window.xml\n'
  fi
  printf -- '- UI hierarchy: window.xml\n'
  printf -- '- Logcat: logcat.txt\n'
  printf -- '- App Logcat: app-logcat.txt\n'
  printf -- '- Visual QA JSON: visual-qa.json\n'
  printf -- '- Visual QA summary: visual-qa.md\n'
  if [[ "$VISUAL_REGRESSION_RESULT" != "NO_BASELINE" ]]; then
    printf -- '- Visual Regression JSON: visual-regression.json\n'
    printf -- '- Visual Regression summary: visual-regression.md\n'
  fi
  printf -- '- Visual Journey JSON: visual-journey.json\n'
  printf -- '- Visual Journey summary: visual-journey.md\n'
} > "$REPORT_DIR/summary.md"

write_result_json "PASS" "" "$PID_AFTER" "$MAESTRO_RESULT"
log "PASS — report written to $REPORT_DIR"
\t' read -r checkpoint_name checkpoint_flow; do
    [[ -n "$checkpoint_name" ]] || continue
    local flow_path="$checkpoint_flow"
    if [[ "$flow_path" != /* ]]; then
      [[ -n "$TARGET_ROOT" ]] ||
        fail "Relative Visual Journey flow requires APPLAB_TARGET_ROOT."
      flow_path="$TARGET_ROOT/$flow_path"
    fi
    [[ -f "$flow_path" ]] ||
      fail "Visual Journey flow not found for $checkpoint_name: $flow_path"

    log "running Visual Journey checkpoint: $checkpoint_name"
    local succeeded="false"
    for attempt in 1 2; do
      local attempt_dir="$REPORT_DIR/maestro/journey-$checkpoint_name-attempt-$attempt"
      local attempt_log="$REPORT_DIR/maestro/journey-$checkpoint_name-attempt-$attempt.log"
      mkdir -p "$attempt_dir"

      set +e
      maestro test "$flow_path" --test-output-dir "$attempt_dir" 2>&1 | tee "$attempt_log"
      local status="${PIPESTATUS[0]}"
      set -e

      if [[ "$status" -eq 0 ]]; then
        succeeded="true"
        break
      fi

      if ! grep -Eqi "Broken pipe|Failure calling service package|device offline|device not found|connection reset|closed.*transport|transport.*error" "$attempt_log"; then
        break
      fi
      adb wait-for-device || true
      sleep 3
    done

    [[ "$succeeded" == "true" ]] ||
      fail "Visual Journey checkpoint flow failed: $checkpoint_name"

    sleep 1
    assert_runtime_healthy "journey-$checkpoint_name" >/dev/null
    capture_visual_checkpoint "$checkpoint_name"
  done < <(
    python3 - "$normalized" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for item in payload.get("checkpoints", []):
    print(f"{item['name']}\t{item['flow']}")
PY
  )
}

run_visual_journey() {
  local baseline_root=""
  local status=0

  if [[ -n "$VISUAL_BASELINE_DIR" && -d "$VISUAL_BASELINE_DIR/journey" ]]; then
    baseline_root="$VISUAL_BASELINE_DIR/journey"
  fi

  log "running Multi-Screen Visual Journey..."
  set +e
  if [[ -n "$baseline_root" ]]; then
    python3 "$(dirname "$0")/visual_journey.py" \
      --current-root "$REPORT_DIR/visual-journey/current" \
      --baseline-root "$baseline_root" \
      --package-id "$PACKAGE_ID" \
      --output-json "$REPORT_DIR/visual-journey.json" \
      --output-md "$REPORT_DIR/visual-journey.md"
  else
    python3 "$(dirname "$0")/visual_journey.py" \
      --current-root "$REPORT_DIR/visual-journey/current" \
      --package-id "$PACKAGE_ID" \
      --output-json "$REPORT_DIR/visual-journey.json" \
      --output-md "$REPORT_DIR/visual-journey.md"
  fi
  status="$?"
  set -e

  if [[ -s "$REPORT_DIR/visual-journey.json" ]]; then
    read -r VISUAL_JOURNEY_RESULT VISUAL_QA_RESULT VISUAL_REGRESSION_RESULT < <(
      python3 - "$REPORT_DIR/visual-journey.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(
    payload.get("result", "ERROR"),
    payload.get("visual_qa", "ERROR"),
    payload.get("visual_regression", "ERROR"),
)
PY
    )
  else
    VISUAL_JOURNEY_RESULT="ERROR"
  fi

  if [[ "$status" -ne 0 || "$VISUAL_JOURNEY_RESULT" == "FAIL" || "$VISUAL_JOURNEY_RESULT" == "ERROR" ]]; then
    fail "Multi-Screen Visual Journey detected a high-confidence regression."
  fi

  log "Multi-Screen Visual Journey: $VISUAL_JOURNEY_RESULT"
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
# verify_apk.sh already launched the package through ADB. Do not launch it
# again here: repeated immediate launches can recreate platform views (MapLibre,
# CameraX, WebView) while their native side is still initializing.
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

run_visual_qa
run_visual_regression

{
  echo "# AppLab report"
  echo
  echo "- Result: PASS"
  echo "- AppLab: $APPLAB_VERSION"
  printf -- '- APK: %s\n' "$(basename "$APK_PATH")"
  printf -- '- Package: %s\n' "$PACKAGE_ID"
  printf -- '- PID after verification: %s\n' "$PID_AFTER"
  echo "- Maestro: $MAESTRO_RESULT"
  echo "- Smart Visual QA: $VISUAL_QA_RESULT"
  echo "- Visual Regression: $VISUAL_REGRESSION_RESULT"
  printf -- '- Screenshot: launch.png\n'
  if [[ "$MAESTRO_RESULT" == "PASS" ]]; then
    printf -- '- Post-Maestro screenshot: post-maestro.png\n'
    printf -- '- Post-Maestro UI hierarchy: post-maestro-window.xml\n'
  fi
  printf -- '- UI hierarchy: window.xml\n'
  printf -- '- Logcat: logcat.txt\n'
  printf -- '- App Logcat: app-logcat.txt\n'
  printf -- '- Visual QA JSON: visual-qa.json\n'
  printf -- '- Visual QA summary: visual-qa.md\n'
  if [[ "$VISUAL_REGRESSION_RESULT" != "NO_BASELINE" ]]; then
    printf -- '- Visual Regression JSON: visual-regression.json\n'
    printf -- '- Visual Regression summary: visual-regression.md\n'
  fi
} > "$REPORT_DIR/summary.md"

write_result_json "PASS" "" "$PID_AFTER" "$MAESTRO_RESULT"
log "PASS — report written to $REPORT_DIR"
