#!/usr/bin/env bash
set -Eeuo pipefail

APK_FILE="${APPLAB_APK_FILE:?APPLAB_APK_FILE is required}"
TARGET_ROOT="${APPLAB_TARGET_ROOT:?APPLAB_TARGET_ROOT is required}"
REPORT_DIR="${APPLAB_REPORT_DIR:-$GITHUB_WORKSPACE/applab-report}"
RUN_MAESTRO="${APPLAB_RUN_MAESTRO:-true}"
MAESTRO_FLOW_INPUT="${APPLAB_MAESTRO_FLOW:-}"
ANDROID_PREPARE_COMMAND="${APPLAB_ANDROID_PREPARE_COMMAND:-}"
PACKAGE_ID="${APPLAB_PACKAGE_ID:-}"
VERSION="${APPLAB_VERSION:-0.6.0}"

FLOW_PATH=""
if [[ -n "$MAESTRO_FLOW_INPUT" ]]; then
  FLOW_PATH="$TARGET_ROOT/$MAESTRO_FLOW_INPUT"
  if [[ ! -f "$FLOW_PATH" ]]; then
    echo "[AppLab] ERROR: Maestro flow not found: $FLOW_PATH" >&2
    exit 2
  fi
fi

if [[ -n "$ANDROID_PREPARE_COMMAND" ]]; then
  echo "[AppLab] installing APK for Android preparation hook..."
  adb install -r -t "$APK_FILE"
  echo "[AppLab] running Android preparation hook..."
  bash -Eeuo pipefail -c "$ANDROID_PREPARE_COMMAND"
fi

echo "[AppLab] starting external Android gate..."
RUN_MAESTRO="$RUN_MAESTRO" \
MAESTRO_FLOW="$FLOW_PATH" \
REPORT_DIR="$REPORT_DIR" \
APPLAB_VERSION="$VERSION" \
bash "$(dirname "$0")/verify_apk.sh" "$APK_FILE" "$PACKAGE_ID"
