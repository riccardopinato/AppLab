#!/usr/bin/env bash
set -Eeuo pipefail

APK_FILE="${APPLAB_APK_FILE:?APPLAB_APK_FILE is required}"
TARGET_ROOT="${APPLAB_TARGET_ROOT:?APPLAB_TARGET_ROOT is required}"
REPORT_DIR="${APPLAB_REPORT_DIR:-$GITHUB_WORKSPACE/applab-report}"
RUN_MAESTRO="${APPLAB_RUN_MAESTRO:-true}"
MAESTRO_FLOW_INPUT="${APPLAB_MAESTRO_FLOW:-}"
ANDROID_PREPARE_COMMAND="${APPLAB_ANDROID_PREPARE_COMMAND:-}"
PACKAGE_ID="${APPLAB_PACKAGE_ID:-}"
VERSION="${APPLAB_VERSION:-0.9.0}"
TRUSTED_ROOT="${APPLAB_TRUSTED_ROOT:-}"
TRUSTED_SHA="${APPLAB_TRUSTED_SHA:-}"

FLOW_PATH=""
if [[ -n "$MAESTRO_FLOW_INPUT" ]]; then
  if [[ "$MAESTRO_FLOW_INPUT" == /* ]]; then
    FLOW_PATH="$MAESTRO_FLOW_INPUT"
    case "$FLOW_PATH" in
      "$TARGET_ROOT"/*) ;;
      *)
        echo "[AppLab] ERROR: absolute Maestro flow escapes trusted evidence root." >&2
        exit 2
        ;;
    esac
  else
    FLOW_PATH="$TARGET_ROOT/$MAESTRO_FLOW_INPUT"
  fi
  if [[ ! -f "$FLOW_PATH" ]]; then
    echo "[AppLab] ERROR: Maestro flow not found: $FLOW_PATH" >&2
    exit 2
  fi
fi

validate_android_prepare_hook() {
  local line trimmed
  while IFS= read -r line || [[ -n "$line" ]]; do
    trimmed="$(printf '%s' "$line" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
    [[ -z "$trimmed" ]] && continue
    if [[ ! "$trimmed" =~ ^adb[[:space:]]+shell[[:space:]]+pm[[:space:]]+grant[[:space:]]+[A-Za-z0-9._]+[[:space:]]+android\.permission\.[A-Z0-9_]+([[:space:]]+\|\|[[:space:]]+true)?$ ]]; then
      echo "[AppLab] ERROR: unsafe android_prepare_command rejected: $trimmed" >&2
      exit 2
    fi
  done <<< "$ANDROID_PREPARE_COMMAND"
}

restore_trusted_verifier() {
  [[ -n "$TRUSTED_ROOT" && -n "$TRUSTED_SHA" ]] || return 0
  [[ -d "$TRUSTED_ROOT/.git" ]] || {
    echo "[AppLab] ERROR: trusted AppLab checkout is missing." >&2
    exit 2
  }
  git -C "$TRUSTED_ROOT" reset --hard "$TRUSTED_SHA" >/dev/null
  git -C "$TRUSTED_ROOT" clean -ffd >/dev/null
  actual="$(git -C "$TRUSTED_ROOT" rev-parse HEAD)"
  [[ "$actual" == "$TRUSTED_SHA" ]] || {
    echo "[AppLab] ERROR: trusted verifier SHA mismatch." >&2
    exit 2
  }
}

if [[ -n "$ANDROID_PREPARE_COMMAND" ]]; then
  validate_android_prepare_hook
  echo "[AppLab] installing APK for restricted Android preparation hook..."
  adb install -r -t "$APK_FILE"
  echo "[AppLab] running restricted Android preparation hook..."
  bash -Eeuo pipefail -c "$ANDROID_PREPARE_COMMAND"
fi

restore_trusted_verifier
echo "[AppLab] starting external Android gate..."
RUN_MAESTRO="$RUN_MAESTRO" \
MAESTRO_FLOW="$FLOW_PATH" \
REPORT_DIR="$REPORT_DIR" \
APPLAB_VERSION="$VERSION" \
bash "$(dirname "$0")/verify_apk.sh" "$APK_FILE" "$PACKAGE_ID"
