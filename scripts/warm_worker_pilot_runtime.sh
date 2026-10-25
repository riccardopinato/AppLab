#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-}"
PACKAGE_ID="dev.applab.selftest"
APK="${GITHUB_WORKSPACE}/runtime-fixture/app-debug.apk"
PLAN="${GITHUB_WORKSPACE}/warm-plan.json"

record_startup() {
  local start_file="$1"
  local output_file="$2"
  python3 - "$start_file" "$output_file" <<'PY'
import sys
import time
from pathlib import Path

start = int(Path(sys.argv[1]).read_text(encoding="utf-8").strip())
ready = int(time.time() * 1000)
Path(sys.argv[2]).write_text(
    f"{max(0, ready-start)/1000:.3f}\n",
    encoding="utf-8",
)
PY
}

assert_package_absent() {
  if adb shell pm path "$PACKAGE_ID" 2>/dev/null | grep -q '^package:'; then
    echo "Target package unexpectedly present before verification"
    exit 1
  fi
}

run_fast_verifier() {
  local report_dir="$1"
  chmod +x scripts/*.sh
  RUN_MAESTRO=false \
  REPORT_DIR="$report_dir" \
  APPLAB_TARGET_ROOT="$GITHUB_WORKSPACE" \
  APPLAB_PROJECT_ROOT="$GITHUB_WORKSPACE" \
  APPLAB_VERSION="5.3.5" \
  APPLAB_ANALYSIS_MODE="fast" \
  APPLAB_ANALYSIS_PLAN_JSON="$PLAN" \
  ./scripts/verify_apk.sh "$APK" "$PACKAGE_ID"

  python3 - "$report_dir/result.json" <<'PY'
import json
import sys
from pathlib import Path

result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert result["result"] == "PASS", result
PY
}

case "$MODE" in
  pristine)
    assert_package_absent
    adb logcat -c
    test "$(adb shell getprop sys.boot_completed | tr -d '\r')" = "1"
    ;;

  cold)
    record_startup \
      "$RUNNER_TEMP/control-start-ms.txt" \
      "$RUNNER_TEMP/control-startup-seconds.txt"
    assert_package_absent
    run_fast_verifier "$GITHUB_WORKSPACE/warm-control-report"
    adb shell run-as "$PACKAGE_ID" sh -c \
      'mkdir -p files && echo control-state > files/applab-warm-marker'
    adb shell run-as "$PACKAGE_ID" cat files/applab-warm-marker | grep -q '^control-state$'
    ;;

  warm)
    record_startup \
      "$RUNNER_TEMP/warm-start-ms.txt" \
      "$RUNNER_TEMP/warm-startup-seconds.txt"
    assert_package_absent
    echo true > "$RUNNER_TEMP/isolation-clean.txt"
    run_fast_verifier "$GITHUB_WORKSPACE/warm-clone-report"
    if adb shell run-as "$PACKAGE_ID" cat files/applab-warm-marker 2>/dev/null | grep -q control-state; then
      echo "Warm clone leaked private app data from cold control"
      exit 1
    fi
    ;;

  *)
    echo "Usage: $0 {pristine|cold|warm}" >&2
    exit 2
    ;;
esac
