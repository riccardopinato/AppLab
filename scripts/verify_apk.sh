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
APPLAB_VERSION="${APPLAB_VERSION:-0.9.0}"
ANALYSIS_PLAN_JSON="${APPLAB_ANALYSIS_PLAN_JSON:-}"
ANALYSIS_MODE="${APPLAB_ANALYSIS_MODE:-full}"
export APPLAB_EFFECTIVE_ANALYSIS_MODE="$ANALYSIS_MODE"

should_run_lab() {
  local lab="$1"
  if [[ "$ANALYSIS_MODE" != "fast" || -z "$ANALYSIS_PLAN_JSON" || ! -s "$ANALYSIS_PLAN_JSON" ]]; then
    return 0
  fi
  python3 - "$ANALYSIS_PLAN_JSON" "$lab" <<'PY'
import json
import sys
from pathlib import Path
try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    selected = payload.get("selected_labs", {})
    if not isinstance(selected, dict):
        raise ValueError("selected_labs must be an object")
    run_lab = selected.get(sys.argv[2], True)
    if not isinstance(run_lab, bool):
        raise ValueError("lab selection must be boolean")
except Exception as exc:
    print(f"[AppLab] WARN: invalid FAST analysis plan; running {sys.argv[2]} fail-safe: {exc}", file=sys.stderr)
    raise SystemExit(0)
raise SystemExit(0 if run_lab else 1)
PY
}
VISUAL_BASELINE_DIR="${VISUAL_BASELINE_DIR:-${APPLAB_VISUAL_BASELINE_DIR:-}}"
TARGET_ROOT="${APPLAB_TARGET_ROOT:-}"
PROJECT_ROOT="${APPLAB_PROJECT_ROOT:-$TARGET_ROOT}"
VISUAL_QA_RESULT="SKIPPED"
VISUAL_REGRESSION_RESULT="NO_BASELINE"
VISUAL_JOURNEY_RESULT="SKIPPED"
INTERACTION_CRAWL_RESULT="SKIPPED"
SYSTEM_LAB_RESULT="SKIPPED"
NETWORK_LAB_RESULT="SKIPPED"
PERSISTENCE_LAB_RESULT="SKIPPED"
CONFIGURATION_LAB_RESULT="SKIPPED"
RESOURCE_PRESSURE_LAB_RESULT="SKIPPED"
BACKGROUND_LAB_RESULT="SKIPPED"
STORAGE_LAB_RESULT="SKIPPED"
UPGRADE_LAB_RESULT="NO_BASELINE"
PERFORMANCE_LAB_RESULT="SKIPPED"

write_result_json() {
  local result="$1"
  local reason="${2:-}"
  local pid_value="${3:-}"
  local maestro_result="${4:-SKIPPED}"

  mkdir -p "$REPORT_DIR"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$REPORT_DIR/result.json" "$result" "${PACKAGE_ID:-}" "$maestro_result" "$pid_value" "$reason" "$APPLAB_VERSION" "${APK_PATH:-}" "${VISUAL_QA_RESULT:-SKIPPED}" "${VISUAL_REGRESSION_RESULT:-NO_BASELINE}" "${VISUAL_JOURNEY_RESULT:-SKIPPED}" "${INTERACTION_CRAWL_RESULT:-SKIPPED}" "${SYSTEM_LAB_RESULT:-SKIPPED}" "${NETWORK_LAB_RESULT:-SKIPPED}" "${PERSISTENCE_LAB_RESULT:-SKIPPED}" "${CONFIGURATION_LAB_RESULT:-SKIPPED}" "${RESOURCE_PRESSURE_LAB_RESULT:-SKIPPED}" "${BACKGROUND_LAB_RESULT:-SKIPPED}" "${STORAGE_LAB_RESULT:-SKIPPED}" "${UPGRADE_LAB_RESULT:-NO_BASELINE}" "${PERFORMANCE_LAB_RESULT:-SKIPPED}" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

output, result, package_id, maestro, pid_value, reason, version, apk_path, visual_qa, visual_regression, visual_journey, interaction_crawl, system_lab, network_lab, persistence_lab, configuration_lab, resource_pressure_lab, background_lab, storage_lab, upgrade_lab, performance_lab = sys.argv[1:]
payload = {
    "schema_version": 1,
    "applab_version": version,
    "analysis_mode": os.environ.get("APPLAB_EFFECTIVE_ANALYSIS_MODE", "full"),
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
    "interaction_crawl": interaction_crawl,
    "system_lab": system_lab,
    "network_lab": network_lab,
    "persistence_lab": persistence_lab,
    "configuration_lab": configuration_lab,
    "resource_pressure_lab": resource_pressure_lab,
    "background_lab": background_lab,
    "storage_lab": storage_lab,
    "upgrade_lab": upgrade_lab,
    "performance_lab": performance_lab,
    "evidence": {
        "summary": "summary.md",
        "analysis_plan": "analysis-plan.json",
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
        "interaction_crawl_json": "interaction-crawl.json",
        "interaction_crawl_summary": "interaction-crawl.md",
        "system_lab_json": "system-lab.json",
        "system_lab_summary": "system-lab.md",
        "network_lab_json": "network-lab.json",
        "network_lab_summary": "network-lab.md",
        "network_offline_screenshot": "network-offline.png",
        "network_recovered_screenshot": "network-recovered.png",
        "persistence_lab_json": "persistence-lab.json",
        "persistence_lab_summary": "persistence-lab.md",
        "configuration_lab_json": "configuration-lab.json",
        "configuration_lab_summary": "configuration-lab.md",
        "resource_pressure_lab_json": "resource-pressure-lab.json",
        "resource_pressure_lab_summary": "resource-pressure-lab.md",
        "background_lab_json": "background-lab.json",
        "background_lab_summary": "background-lab.md",
        "storage_lab_json": "storage-lab.json",
        "storage_lab_summary": "storage-lab.md",
        "upgrade_lab_json": "upgrade-lab.json",
        "upgrade_lab_summary": "upgrade-lab.md",
        "upgrade_before_screenshot": "upgrade-before.png",
        "upgrade_after_screenshot": "upgrade-after.png",
        "performance_lab_json": "performance-lab.json",
        "performance_lab_summary": "performance-lab.md",
    },
}
performance_path = Path(output).parent / "performance-lab.json"
if performance_path.is_file():
    try:
        performance_payload = json.loads(performance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        performance_payload = {}
    if isinstance(performance_payload, dict):
        payload["performance"] = performance_payload.get("metrics", {})
        payload["performance_findings"] = performance_payload.get("findings", [])

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
  echo "- Analysis mode: $ANALYSIS_MODE"
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
  "$REPORT_DIR/visual-journey.md" \
  "$REPORT_DIR/interaction-crawl.json" \
  "$REPORT_DIR/interaction-crawl.md" \
  "$REPORT_DIR/system-lab.json" \
  "$REPORT_DIR/system-lab.md" \
  "$REPORT_DIR/network-lab.json" \
  "$REPORT_DIR/network-lab.md" \
  "$REPORT_DIR/network-offline.png" \
  "$REPORT_DIR/network-recovered.png" \
  "$REPORT_DIR/persistence-lab.json" \
  "$REPORT_DIR/persistence-lab.md" \
  "$REPORT_DIR/persistence-cycle-"*.png \
  "$REPORT_DIR/persistence-cycle-"*.xml \
  "$REPORT_DIR/configuration-lab.json" \
  "$REPORT_DIR/configuration-lab.md" \
  "$REPORT_DIR/config-"*.png \
  "$REPORT_DIR/config-"*.xml \
  "$REPORT_DIR/resource-pressure-lab.json" \
  "$REPORT_DIR/resource-pressure-lab.md" \
  "$REPORT_DIR/resource-recovery-"*.png \
  "$REPORT_DIR/resource-recovery-"*.xml \
  "$REPORT_DIR/background-lab.json" \
  "$REPORT_DIR/background-lab.md" \
  "$REPORT_DIR/background-recovery-"*.png \
  "$REPORT_DIR/background-recovery-"*.xml \
  "$REPORT_DIR/storage-lab.json" \
  "$REPORT_DIR/storage-lab.md" \
  "$REPORT_DIR/storage-recovery.png" \
  "$REPORT_DIR/storage-recovery.xml" \
  "$REPORT_DIR/upgrade-lab.json" \
  "$REPORT_DIR/upgrade-lab.md" \
  "$REPORT_DIR/upgrade-before.png" \
  "$REPORT_DIR/upgrade-before.xml" \
  "$REPORT_DIR/upgrade-after.png" \
  "$REPORT_DIR/upgrade-after.xml" \
  "$REPORT_DIR/performance-lab.json" \
  "$REPORT_DIR/performance-lab.md"
rm -rf "$REPORT_DIR/visual-journey" "$REPORT_DIR/interaction-crawl"
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

capture_ui_hierarchy() {
  local prefix="$1"
  local remote_xml="/sdcard/applab-${prefix}.xml"
  local output="$REPORT_DIR/${prefix}-window.xml"
  local log_file="$REPORT_DIR/${prefix}-uiautomator.txt"
  local attempt

  rm -f "$output"
  : > "$log_file"

  for attempt in 1 2 3 4; do
    adb shell rm -f "$remote_xml" >/dev/null 2>&1 || true
    if adb shell uiautomator dump "$remote_xml" >> "$log_file" 2>&1 &&
       adb pull "$remote_xml" "$output" >/dev/null 2>&1 &&
       [[ -s "$output" ]]; then
      return 0
    fi

    adb shell rm -f "$remote_xml" >/dev/null 2>&1 || true
    if adb shell uiautomator dump --compressed "$remote_xml" >> "$log_file" 2>&1 &&
       adb pull "$remote_xml" "$output" >/dev/null 2>&1 &&
       [[ -s "$output" ]]; then
      return 0
    fi

    sleep 2
  done

  return 1
}

capture_evidence() {
  local prefix="$1"

  adb exec-out screencap -p > "$REPORT_DIR/${prefix}.png" || true
  capture_ui_hierarchy "$prefix" || true
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
  if grep -Eqi "INSTALL_FAILED_UPDATE_INCOMPATIBLE|signatures do not match" "$REPORT_DIR/install.txt"; then
    log "existing package signature differs; removing stale test install and retrying clean..."
    adb uninstall "$PACKAGE_ID" >> "$REPORT_DIR/install.txt" 2>&1 || true
    if ! adb install -t "$APK_PATH" >> "$REPORT_DIR/install.txt" 2>&1; then
      cat "$REPORT_DIR/install.txt" >&2
      fail "APK installation failed after stale-signature recovery."
    fi
  else
    cat "$REPORT_DIR/install.txt" >&2
    fail "APK installation failed."
  fi
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

python3 "$(dirname "$0")/dismiss_foreign_anr.py" --package-id "$PACKAGE_ID" || true

capture_evidence "launch"
[[ -s "$REPORT_DIR/launch.png" ]] || fail "Launch screenshot could not be captured."
[[ -s "$REPORT_DIR/launch-window.xml" ]] ||
  fail "Launch UI hierarchy could not be captured after retries."
mkdir -p "$REPORT_DIR/visual-journey/current/launch"
cp "$REPORT_DIR/launch.png" "$REPORT_DIR/visual-journey/current/launch/screenshot.png"
cp "$REPORT_DIR/launch-window.xml" "$REPORT_DIR/visual-journey/current/launch/window.xml"
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

  is_transient_maestro_failure() {
    local attempt="$1"
    local console_log="$REPORT_DIR/maestro/attempt-$attempt.log"
    local system_log="$REPORT_DIR/maestro/attempt-$attempt-system-logcat.txt"

    if grep -Eqi "Broken pipe|Failure calling service package|device offline|device not found|connection reset|closed.*transport|transport.*error" "$console_log"; then
      return 0
    fi

    adb logcat -b all -d -v threadtime > "$system_log" 2>&1 || true
    if grep -Eqi "DeadSystemException|registerUiTestAutomationService.*null object reference|UiAutomationConnection.*NullPointerException|system_server.*(died|crash|restarting)|ServiceManager.*(dead|Bad file descriptor)" "$system_log"; then
      return 0
    fi
    return 1
  }

  recover_emulator_after_transient_failure() {
    log "transient emulator/system failure detected; recovering before retry..."
    adb wait-for-device || true
    for _ in {1..30}; do
      BOOT_COMPLETED="$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"
      if [[ "$BOOT_COMPLETED" == "1" ]] &&
         adb shell cmd package list packages android >/dev/null 2>&1 &&
         adb shell service check accessibility >/dev/null 2>&1; then
        break
      fi
      sleep 2
    done
    adb shell am force-stop "$PACKAGE_ID" >/dev/null 2>&1 || true
    adb logcat -b all -c >/dev/null 2>&1 || true
    sleep 3
  }

  MAESTRO_RESULT="FAIL"
  for attempt in 1 2 3; do
    log "running Maestro flow (attempt $attempt/3): $MAESTRO_FLOW"
    if run_maestro_attempt "$attempt"; then
      MAESTRO_RESULT="PASS"
      break
    fi

    if ! is_transient_maestro_failure "$attempt"; then
      capture_evidence "maestro-failure"
      fail "Maestro flow failed."
    fi

    recover_emulator_after_transient_failure
  done

  if [[ "$MAESTRO_RESULT" != "PASS" ]]; then
    capture_evidence "maestro-failure"
    fail "Maestro flow failed after transient-error retries."
  fi

  sleep 2
  python3 "$(dirname "$0")/dismiss_foreign_anr.py" --package-id "$PACKAGE_ID" || true
  capture_evidence "post-maestro"
  PID_AFTER="$(assert_runtime_healthy "post-maestro")"
fi

mkdir -p "$REPORT_DIR/visual-journey/current/final"
if [[ -s "$REPORT_DIR/post-maestro.png" && -s "$REPORT_DIR/post-maestro-window.xml" ]]; then
  cp "$REPORT_DIR/post-maestro.png" "$REPORT_DIR/visual-journey/current/final/screenshot.png"
  cp "$REPORT_DIR/post-maestro-window.xml" "$REPORT_DIR/visual-journey/current/final/window.xml"
else
  cp "$REPORT_DIR/launch.png" "$REPORT_DIR/visual-journey/current/final/screenshot.png"
  cp "$REPORT_DIR/launch-window.xml" "$REPORT_DIR/visual-journey/current/final/window.xml"
fi

if [[ -n "$TARGET_ROOT" ]] && is_true "$RUN_MAESTRO"; then
  python3 "$(dirname "$0")/visual_journey_runtime.py" \
    --target-root "$TARGET_ROOT" \
    --project-root "$PROJECT_ROOT" \
    --report-dir "$REPORT_DIR" \
    --package-id "$PACKAGE_ID"
  PID_AFTER="$(assert_runtime_healthy "visual-journey")"
elif [[ -n "$TARGET_ROOT" ]]; then
  log "custom Visual Journey skipped because Maestro is disabled."
fi

VISUAL_CONFIG_ARGS=()
if [[ -n "$PROJECT_ROOT" && -f "$PROJECT_ROOT/.maestro/applab-visual.json" ]]; then
  VISUAL_CONFIG_ARGS=(--visual-config "$PROJECT_ROOT/.maestro/applab-visual.json")
  log "Visual Regression Pro config: project checkpoint policy"
elif [[ -n "$TARGET_ROOT" && -f "$TARGET_ROOT/.maestro/applab-visual.json" ]]; then
  VISUAL_CONFIG_ARGS=(--visual-config "$TARGET_ROOT/.maestro/applab-visual.json")
  log "Visual Regression Pro config: repository checkpoint policy"
fi

CRAWL_STATUS=0
set +e
python3 "$(dirname "$0")/interaction_crawler.py" \
  --package-id "$PACKAGE_ID" \
  --report-dir "$REPORT_DIR" \
  --max-actions 4 \
  --settle-seconds 1.5
CRAWL_STATUS="$?"
set -e

if [[ -s "$REPORT_DIR/interaction-crawl.json" ]]; then
  INTERACTION_CRAWL_RESULT="$(
    python3 - "$REPORT_DIR/interaction-crawl.json" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("result", "ERROR"))
PY
  )"
else
  INTERACTION_CRAWL_RESULT="ERROR"
fi

if [[ "$CRAWL_STATUS" -ne 0 || "$INTERACTION_CRAWL_RESULT" == "FAIL" || "$INTERACTION_CRAWL_RESULT" == "ERROR" ]]; then
  fail "Safe Interaction Crawler detected an application runtime failure."
fi
PID_AFTER="$(assert_runtime_healthy "interaction-crawl")"
log "Safe Interaction Crawler: $INTERACTION_CRAWL_RESULT"

JOURNEY_STATUS=0
set +e
if [[ -n "$VISUAL_BASELINE_DIR" && -d "$VISUAL_BASELINE_DIR/journey" ]]; then
  python3 "$(dirname "$0")/visual_journey.py" \
    --current-root "$REPORT_DIR/visual-journey/current" \
    --baseline-root "$VISUAL_BASELINE_DIR/journey" \
    --package-id "$PACKAGE_ID" \
    --output-json "$REPORT_DIR/visual-journey.json" \
    --output-md "$REPORT_DIR/visual-journey.md" \
    --compat-report-dir "$REPORT_DIR" \
    "${VISUAL_CONFIG_ARGS[@]}"
else
  python3 "$(dirname "$0")/visual_journey.py" \
    --current-root "$REPORT_DIR/visual-journey/current" \
    --package-id "$PACKAGE_ID" \
    --output-json "$REPORT_DIR/visual-journey.json" \
    --output-md "$REPORT_DIR/visual-journey.md" \
    --compat-report-dir "$REPORT_DIR" \
    "${VISUAL_CONFIG_ARGS[@]}"
fi
JOURNEY_STATUS="$?"
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

if [[ "$JOURNEY_STATUS" -ne 0 || "$VISUAL_JOURNEY_RESULT" == "FAIL" || "$VISUAL_JOURNEY_RESULT" == "ERROR" ]]; then
  fail "Multi-Screen Visual Journey detected a high-confidence visual regression."
fi

log "Multi-Screen Visual Journey: $VISUAL_JOURNEY_RESULT (single visual engine)"

if should_run_lab "system"; then
SYSTEM_CONFIG_ARGS=()
if [[ -n "$PROJECT_ROOT" && -f "$PROJECT_ROOT/.maestro/applab-system.json" ]]; then
  SYSTEM_CONFIG_ARGS=(--config "$PROJECT_ROOT/.maestro/applab-system.json")
  log "System UI Lab config: project policy"
elif [[ -n "$TARGET_ROOT" && -f "$TARGET_ROOT/.maestro/applab-system.json" ]]; then
  SYSTEM_CONFIG_ARGS=(--config "$TARGET_ROOT/.maestro/applab-system.json")
  log "System UI Lab config: repository policy"
fi

SYSTEM_STATUS=0
set +e
python3 "$(dirname "$0")/system_lab.py" \
  --package-id "$PACKAGE_ID" \
  --report-dir "$REPORT_DIR" \
  "${SYSTEM_CONFIG_ARGS[@]}"
SYSTEM_STATUS="$?"
set -e

if [[ -s "$REPORT_DIR/system-lab.json" ]]; then
  SYSTEM_LAB_RESULT="$(
    python3 - "$REPORT_DIR/system-lab.json" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("result", "ERROR"))
PY
  )"
else
  SYSTEM_LAB_RESULT="ERROR"
fi

if [[ "$SYSTEM_STATUS" -ne 0 || "$SYSTEM_LAB_RESULT" == "FAIL" || "$SYSTEM_LAB_RESULT" == "ERROR" ]]; then
  fail "System UI Lab detected a required Android system/runtime failure."
fi
PID_AFTER="$(assert_runtime_healthy "system-lab")"
log "System UI Lab: $SYSTEM_LAB_RESULT"
else
  log "System UI Lab: SKIPPED by Smart Test Planner"
fi



if should_run_lab "performance"; then
PERFORMANCE_BASELINE_ARGS=()
if [[ -n "${APPLAB_PERFORMANCE_BASELINE_JSON:-}" && -f "${APPLAB_PERFORMANCE_BASELINE_JSON}" ]]; then
  PERFORMANCE_BASELINE_ARGS=(--baseline-json "$APPLAB_PERFORMANCE_BASELINE_JSON")
fi

python3 "$(dirname "$0")/performance_lab.py" \
  --package-id "$PACKAGE_ID" \
  --apk "$APK_PATH" \
  --report-dir "$REPORT_DIR" \
  "${PERFORMANCE_BASELINE_ARGS[@]}"

if [[ -s "$REPORT_DIR/performance-lab.json" ]]; then
  PERFORMANCE_LAB_RESULT="$(
    python3 - "$REPORT_DIR/performance-lab.json" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("result", "WARN"))
PY
  )"
else
  PERFORMANCE_LAB_RESULT="WARN"
fi
PID_AFTER="$(assert_runtime_healthy "performance-lab")"
log "Performance Lab: $PERFORMANCE_LAB_RESULT"
else
  log "Performance Lab: SKIPPED by Smart Test Planner"
fi

if should_run_lab "network"; then
NETWORK_CONFIG_ARGS=()
if [[ -n "$PROJECT_ROOT" && -f "$PROJECT_ROOT/.maestro/applab-network.json" ]]; then
  NETWORK_CONFIG_ARGS=(--config "$PROJECT_ROOT/.maestro/applab-network.json")
  log "Network & Offline Lab config: project policy"
elif [[ -n "$TARGET_ROOT" && -f "$TARGET_ROOT/.maestro/applab-network.json" ]]; then
  NETWORK_CONFIG_ARGS=(--config "$TARGET_ROOT/.maestro/applab-network.json")
  log "Network & Offline Lab config: repository policy"
fi

NETWORK_STATUS=0
set +e
python3 "$(dirname "$0")/network_lab.py" \
  --package-id "$PACKAGE_ID" \
  --report-dir "$REPORT_DIR" \
  "${NETWORK_CONFIG_ARGS[@]}"
NETWORK_STATUS="$?"
set -e

if [[ -s "$REPORT_DIR/network-lab.json" ]]; then
  NETWORK_LAB_RESULT="$(
    python3 - "$REPORT_DIR/network-lab.json" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("result", "ERROR"))
PY
  )"
else
  NETWORK_LAB_RESULT="ERROR"
fi

if [[ "$NETWORK_STATUS" -ne 0 || "$NETWORK_LAB_RESULT" == "FAIL" || "$NETWORK_LAB_RESULT" == "ERROR" ]]; then
  fail "Network & Offline Lab detected an application connectivity/runtime failure."
fi
PID_AFTER="$(assert_runtime_healthy "network-lab")"
log "Network & Offline Lab: $NETWORK_LAB_RESULT"
else
  log "Network & Offline Lab: SKIPPED by Smart Test Planner"
fi

if should_run_lab "persistence"; then
PERSISTENCE_CONFIG_ARGS=()
if [[ -n "$PROJECT_ROOT" && -f "$PROJECT_ROOT/.maestro/applab-persistence.json" ]]; then
  PERSISTENCE_CONFIG_ARGS=(--config "$PROJECT_ROOT/.maestro/applab-persistence.json")
  log "Persistence & Restart Lab config: project policy"
elif [[ -n "$TARGET_ROOT" && -f "$TARGET_ROOT/.maestro/applab-persistence.json" ]]; then
  PERSISTENCE_CONFIG_ARGS=(--config "$TARGET_ROOT/.maestro/applab-persistence.json")
  log "Persistence & Restart Lab config: repository policy"
fi

PERSISTENCE_STATUS=0
set +e
python3 "$(dirname "$0")/persistence_lab.py" \
  --package-id "$PACKAGE_ID" \
  --report-dir "$REPORT_DIR" \
  "${PERSISTENCE_CONFIG_ARGS[@]}"
PERSISTENCE_STATUS="$?"
set -e

if [[ -s "$REPORT_DIR/persistence-lab.json" ]]; then
  PERSISTENCE_LAB_RESULT="$(
    python3 - "$REPORT_DIR/persistence-lab.json" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("result", "ERROR"))
PY
  )"
else
  PERSISTENCE_LAB_RESULT="ERROR"
fi

if [[ "$PERSISTENCE_STATUS" -ne 0 || "$PERSISTENCE_LAB_RESULT" == "FAIL" || "$PERSISTENCE_LAB_RESULT" == "ERROR" ]]; then
  fail "Persistence & Restart Lab detected a lifecycle/state failure."
fi
PID_AFTER="$(assert_runtime_healthy "persistence-lab")"
log "Persistence & Restart Lab: $PERSISTENCE_LAB_RESULT"
else
  log "Persistence & Restart Lab: SKIPPED by Smart Test Planner"
fi

if should_run_lab "configuration"; then
CONFIGURATION_CONFIG_ARGS=()
if [[ -n "$PROJECT_ROOT" && -f "$PROJECT_ROOT/.maestro/applab-configuration.json" ]]; then
  CONFIGURATION_CONFIG_ARGS=(--config "$PROJECT_ROOT/.maestro/applab-configuration.json")
  log "Configuration & Lifecycle Stress Lab config: project policy"
elif [[ -n "$TARGET_ROOT" && -f "$TARGET_ROOT/.maestro/applab-configuration.json" ]]; then
  CONFIGURATION_CONFIG_ARGS=(--config "$TARGET_ROOT/.maestro/applab-configuration.json")
  log "Configuration & Lifecycle Stress Lab config: repository policy"
fi

CONFIGURATION_STATUS=0
set +e
python3 "$(dirname "$0")/configuration_lab.py" \
  --package-id "$PACKAGE_ID" \
  --report-dir "$REPORT_DIR" \
  "${CONFIGURATION_CONFIG_ARGS[@]}"
CONFIGURATION_STATUS="$?"
set -e

if [[ -s "$REPORT_DIR/configuration-lab.json" ]]; then
  CONFIGURATION_LAB_RESULT="$(
    python3 - "$REPORT_DIR/configuration-lab.json" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("result", "ERROR"))
PY
  )"
else
  CONFIGURATION_LAB_RESULT="ERROR"
fi

if [[ "$CONFIGURATION_STATUS" -ne 0 || "$CONFIGURATION_LAB_RESULT" == "FAIL" || "$CONFIGURATION_LAB_RESULT" == "ERROR" ]]; then
  fail "Configuration & Lifecycle Stress Lab detected an application lifecycle/configuration failure."
fi
PID_AFTER="$(assert_runtime_healthy "configuration-lab")"
log "Configuration & Lifecycle Stress Lab: $CONFIGURATION_LAB_RESULT"
else
  log "Configuration & Lifecycle Stress Lab: SKIPPED by Smart Test Planner"
fi

if should_run_lab "resource_pressure"; then
RESOURCE_CONFIG_ARGS=()
if [[ -n "$PROJECT_ROOT" && -f "$PROJECT_ROOT/.maestro/applab-resource.json" ]]; then
  RESOURCE_CONFIG_ARGS=(--config "$PROJECT_ROOT/.maestro/applab-resource.json")
  log "Resource Pressure & Process Death Lab config: project policy"
elif [[ -n "$TARGET_ROOT" && -f "$TARGET_ROOT/.maestro/applab-resource.json" ]]; then
  RESOURCE_CONFIG_ARGS=(--config "$TARGET_ROOT/.maestro/applab-resource.json")
  log "Resource Pressure & Process Death Lab config: repository policy"
fi

RESOURCE_STATUS=0
set +e
python3 "$(dirname "$0")/resource_pressure_lab.py" \
  --package-id "$PACKAGE_ID" \
  --report-dir "$REPORT_DIR" \
  "${RESOURCE_CONFIG_ARGS[@]}"
RESOURCE_STATUS="$?"
set -e

if [[ -s "$REPORT_DIR/resource-pressure-lab.json" ]]; then
  RESOURCE_PRESSURE_LAB_RESULT="$(
    python3 - "$REPORT_DIR/resource-pressure-lab.json" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("result", "ERROR"))
PY
  )"
else
  RESOURCE_PRESSURE_LAB_RESULT="ERROR"
fi

if [[ "$RESOURCE_STATUS" -ne 0 || "$RESOURCE_PRESSURE_LAB_RESULT" == "FAIL" || "$RESOURCE_PRESSURE_LAB_RESULT" == "ERROR" ]]; then
  fail "Resource Pressure & Process Death Lab detected an application recovery/runtime failure."
fi
PID_AFTER="$(assert_runtime_healthy "resource-pressure-lab")"
log "Resource Pressure & Process Death Lab: $RESOURCE_PRESSURE_LAB_RESULT"
else
  log "Resource Pressure & Process Death Lab: SKIPPED by Smart Test Planner"
fi

if should_run_lab "background"; then
BACKGROUND_CONFIG_ARGS=()
if [[ -n "$PROJECT_ROOT" && -f "$PROJECT_ROOT/.maestro/applab-background.json" ]]; then
  BACKGROUND_CONFIG_ARGS=(--config "$PROJECT_ROOT/.maestro/applab-background.json")
  log "Background Execution, Doze & Recovery Lab config: project policy"
elif [[ -n "$TARGET_ROOT" && -f "$TARGET_ROOT/.maestro/applab-background.json" ]]; then
  BACKGROUND_CONFIG_ARGS=(--config "$TARGET_ROOT/.maestro/applab-background.json")
  log "Background Execution, Doze & Recovery Lab config: repository policy"
fi

BACKGROUND_STATUS=0
set +e
python3 "$(dirname "$0")/background_lab.py" \
  --package-id "$PACKAGE_ID" \
  --report-dir "$REPORT_DIR" \
  "${BACKGROUND_CONFIG_ARGS[@]}"
BACKGROUND_STATUS="$?"
set -e

if [[ -s "$REPORT_DIR/background-lab.json" ]]; then
  BACKGROUND_LAB_RESULT="$(
    python3 - "$REPORT_DIR/background-lab.json" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("result", "ERROR"))
PY
  )"
else
  BACKGROUND_LAB_RESULT="ERROR"
fi

if [[ "$BACKGROUND_STATUS" -ne 0 || "$BACKGROUND_LAB_RESULT" == "FAIL" || "$BACKGROUND_LAB_RESULT" == "ERROR" ]]; then
  fail "Background Execution, Doze & Recovery Lab detected an application background/runtime failure."
fi
PID_AFTER="$(assert_runtime_healthy "background-lab")"
log "Background Execution, Doze & Recovery Lab: $BACKGROUND_LAB_RESULT"
else
  log "Background Execution, Doze & Recovery Lab: SKIPPED by Smart Test Planner"
fi

if should_run_lab "storage"; then
STORAGE_CONFIG_ARGS=()
if [[ -n "$PROJECT_ROOT" && -f "$PROJECT_ROOT/.maestro/applab-storage.json" ]]; then
  STORAGE_CONFIG_ARGS=(--config "$PROJECT_ROOT/.maestro/applab-storage.json")
  log "Storage & Data Integrity Lab config: project policy"
elif [[ -n "$TARGET_ROOT" && -f "$TARGET_ROOT/.maestro/applab-storage.json" ]]; then
  STORAGE_CONFIG_ARGS=(--config "$TARGET_ROOT/.maestro/applab-storage.json")
  log "Storage & Data Integrity Lab config: repository policy"
fi

STORAGE_STATUS=0
set +e
python3 "$(dirname "$0")/storage_lab.py" \
  --package-id "$PACKAGE_ID" \
  --report-dir "$REPORT_DIR" \
  "${STORAGE_CONFIG_ARGS[@]}"
STORAGE_STATUS="$?"
set -e

if [[ -s "$REPORT_DIR/storage-lab.json" ]]; then
  STORAGE_LAB_RESULT="$(
    python3 - "$REPORT_DIR/storage-lab.json" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("result", "ERROR"))
PY
  )"
else
  STORAGE_LAB_RESULT="ERROR"
fi

if [[ "$STORAGE_STATUS" -ne 0 || "$STORAGE_LAB_RESULT" == "FAIL" || "$STORAGE_LAB_RESULT" == "ERROR" ]]; then
  fail "Storage & Data Integrity Lab detected a storage/recovery failure."
fi
PID_AFTER="$(assert_runtime_healthy "storage-lab")"
log "Storage & Data Integrity Lab: $STORAGE_LAB_RESULT"
else
  log "Storage & Data Integrity Lab: SKIPPED by Smart Test Planner"
fi

if should_run_lab "upgrade"; then
UPGRADE_CONFIG_ARGS=()
if [[ -n "$PROJECT_ROOT" && -f "$PROJECT_ROOT/.maestro/applab-upgrade.json" ]]; then
  UPGRADE_CONFIG_ARGS=(--config "$PROJECT_ROOT/.maestro/applab-upgrade.json")
  log "Upgrade & Migration Lab config: project policy"
elif [[ -n "$TARGET_ROOT" && -f "$TARGET_ROOT/.maestro/applab-upgrade.json" ]]; then
  UPGRADE_CONFIG_ARGS=(--config "$TARGET_ROOT/.maestro/applab-upgrade.json")
  log "Upgrade & Migration Lab config: repository policy"
fi

UPGRADE_BASELINE_ARGS=()
if [[ -n "${APPLAB_UPGRADE_BASELINE_APK:-}" && -f "${APPLAB_UPGRADE_BASELINE_APK}" ]]; then
  UPGRADE_BASELINE_ARGS=(--baseline-apk "$APPLAB_UPGRADE_BASELINE_APK")
fi

UPGRADE_STATUS=0
set +e
python3 "$(dirname "$0")/upgrade_lab.py" \
  --package-id "$PACKAGE_ID" \
  --current-apk "$APK_PATH" \
  --report-dir "$REPORT_DIR" \
  "${UPGRADE_BASELINE_ARGS[@]}" \
  "${UPGRADE_CONFIG_ARGS[@]}"
UPGRADE_STATUS="$?"
set -e

if [[ -s "$REPORT_DIR/upgrade-lab.json" ]]; then
  UPGRADE_LAB_RESULT="$(
    python3 - "$REPORT_DIR/upgrade-lab.json" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("result", "ERROR"))
PY
  )"
else
  UPGRADE_LAB_RESULT="ERROR"
fi

if [[ "$UPGRADE_STATUS" -ne 0 || "$UPGRADE_LAB_RESULT" == "FAIL" || "$UPGRADE_LAB_RESULT" == "ERROR" ]]; then
  fail "Upgrade & Migration Lab detected an in-place upgrade failure."
fi
PID_AFTER="$(assert_runtime_healthy "upgrade-lab")"
log "Upgrade & Migration Lab: $UPGRADE_LAB_RESULT"
else
  log "Upgrade & Migration Lab: SKIPPED by Smart Test Planner"
fi

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
  echo "- Safe Interaction Crawler: $INTERACTION_CRAWL_RESULT"
  echo "- System UI Lab: $SYSTEM_LAB_RESULT"
  echo "- Network & Offline Lab: $NETWORK_LAB_RESULT"
  echo "- Persistence & Restart Lab: $PERSISTENCE_LAB_RESULT"
  echo "- Configuration & Lifecycle Stress Lab: $CONFIGURATION_LAB_RESULT"
  echo "- Resource Pressure & Process Death Lab: $RESOURCE_PRESSURE_LAB_RESULT"
  echo "- Background Execution, Doze & Recovery Lab: $BACKGROUND_LAB_RESULT"
  echo "- Storage & Data Integrity Lab: $STORAGE_LAB_RESULT"
  echo "- Upgrade & Migration Lab: $UPGRADE_LAB_RESULT"
  echo "- Performance Lab: $PERFORMANCE_LAB_RESULT"
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
  printf -- '- Interaction Crawler JSON: interaction-crawl.json\n'
  printf -- '- Interaction Crawler summary: interaction-crawl.md\n'
  printf -- '- System UI Lab JSON: system-lab.json\n'
  printf -- '- System UI Lab summary: system-lab.md\n'
  printf -- '- Network Lab JSON: network-lab.json\n'
  printf -- '- Network Lab summary: network-lab.md\n'
  printf -- '- Network offline screenshot: network-offline.png\n'
  printf -- '- Network recovered screenshot: network-recovered.png\n'
  printf -- '- Persistence Lab JSON: persistence-lab.json\n'
  printf -- '- Persistence Lab summary: persistence-lab.md\n'
  printf -- '- Configuration Lab JSON: configuration-lab.json\n'
  printf -- '- Configuration Lab summary: configuration-lab.md\n'
  printf -- '- Resource Pressure Lab JSON: resource-pressure-lab.json\n'
  printf -- '- Resource Pressure Lab summary: resource-pressure-lab.md\n'
  printf -- '- Background Lab JSON: background-lab.json\n'
  printf -- '- Background Lab summary: background-lab.md\n'
  printf -- '- Storage Lab JSON: storage-lab.json\n'
  printf -- '- Storage Lab summary: storage-lab.md\n'
  printf -- '- Upgrade Lab JSON: upgrade-lab.json\n'
  printf -- '- Upgrade Lab summary: upgrade-lab.md\n'
  printf -- '- Upgrade before screenshot: upgrade-before.png\n'
  printf -- '- Upgrade after screenshot: upgrade-after.png\n'
  printf -- '- Performance Lab JSON: performance-lab.json\n'
  printf -- '- Performance Lab summary: performance-lab.md\n'
} > "$REPORT_DIR/summary.md"

write_result_json "PASS" "" "$PID_AFTER" "$MAESTRO_RESULT"
log "PASS — report written to $REPORT_DIR"
