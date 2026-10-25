#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE is required}"

PACKAGE_ID="dev.applab.selftest"
APK="$GITHUB_WORKSPACE/runtime-fixture/app-debug.apk"
PLAN="$GITHUB_WORKSPACE/warm-plan.json"

record_startup() {
  local source_file="$1"
  local output_file="$2"
  python3 - "$source_file" "$output_file" <<'PY'
import sys
import time
from pathlib import Path

source = Path(sys.argv[1])
output = Path(sys.argv[2])
start = int(source.read_text(encoding="utf-8").strip())
ready = int(time.time() * 1000)
output.write_text(f"{max(0, ready - start) / 1000:.3f}\n", encoding="utf-8")
PY
}

assert_package_absent() {
  if adb shell pm path "$PACKAGE_ID" 2>/dev/null | grep -q '^package:'; then
    echo "Target package unexpectedly present before runtime verification" >&2
    exit 1
  fi
}

verify_report_pass() {
  local report="$1"
  python3 - "$report" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("result") != "PASS":
    raise SystemExit(f"runtime verification did not PASS: {payload.get('result')}")
PY
}

run_verifier() {
  local report_dir="$1"
  chmod +x "$GITHUB_WORKSPACE"/scripts/*.sh
  RUN_MAESTRO=false \
  REPORT_DIR="$report_dir" \
  APPLAB_TARGET_ROOT="$GITHUB_WORKSPACE" \
  APPLAB_PROJECT_ROOT="$GITHUB_WORKSPACE" \
  APPLAB_VERSION="5.3.5" \
  APPLAB_ANALYSIS_MODE="fast" \
  APPLAB_ANALYSIS_PLAN_JSON="$PLAN" \
  "$GITHUB_WORKSPACE/scripts/verify_apk.sh" "$APK" "$PACKAGE_ID"
}

case "$MODE" in
  pristine)
    assert_package_absent
    adb logcat -c
    test "$(adb shell getprop sys.boot_completed | tr -d '\r')" = "1"
    ;;

  control)
    record_startup \
      "$RUNNER_TEMP/control-start-ms.txt" \
      "$RUNNER_TEMP/control-startup-seconds.txt"
    assert_package_absent
    run_verifier "$GITHUB_WORKSPACE/warm-control-report"
    verify_report_pass "$GITHUB_WORKSPACE/warm-control-report/result.json"
    adb shell run-as "$PACKAGE_ID" sh -c \
      'mkdir -p files && echo control-state > files/applab-warm-marker'
    test "$(adb shell run-as "$PACKAGE_ID" cat files/applab-warm-marker | tr -d '\r')" = "control-state"
    ;;

  warm)
    record_startup \
      "$RUNNER_TEMP/warm-start-ms.txt" \
      "$RUNNER_TEMP/warm-startup-seconds.txt"
    assert_package_absent
    echo true > "$RUNNER_TEMP/isolation-clean.txt"
    run_verifier "$GITHUB_WORKSPACE/warm-clone-report"
    verify_report_pass "$GITHUB_WORKSPACE/warm-clone-report/result.json"
    if adb shell run-as "$PACKAGE_ID" cat files/applab-warm-marker 2>/dev/null | grep -q control-state; then
      echo "Warm clone leaked private app data from cold control" >&2
      exit 1
    fi
    ;;

  *)
    echo "usage: $0 {pristine|control|warm}" >&2
    exit 2
    ;;
esac
