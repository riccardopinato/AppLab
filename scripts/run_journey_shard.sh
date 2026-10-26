#!/usr/bin/env bash
set -Eeuo pipefail

APK_FILE="${APPLAB_APK_FILE:?APPLAB_APK_FILE is required}"
TARGET_ROOT="${APPLAB_TARGET_ROOT:?APPLAB_TARGET_ROOT is required}"
TRUSTED_ROOT="${APPLAB_TRUSTED_ROOT:?APPLAB_TRUSTED_ROOT is required}"
PLAN_FILE="${APPLAB_ANALYSIS_PLAN_JSON:?APPLAB_ANALYSIS_PLAN_JSON is required}"
REPORT_DIR="${APPLAB_REPORT_DIR:?APPLAB_REPORT_DIR is required}"
REPOSITORY="${APPLAB_REPOSITORY:?APPLAB_REPOSITORY is required}"
PACKAGE_ID="${APPLAB_PACKAGE_ID:?APPLAB_PACKAGE_ID is required}"
JOURNEY_IDS_JSON="${APPLAB_JOURNEY_IDS_JSON:?APPLAB_JOURNEY_IDS_JSON is required}"
SHARD_ID="${APPLAB_SHARD_ID:?APPLAB_SHARD_ID is required}"
ANDROID_PREPARE_COMMAND="${APPLAB_ANDROID_PREPARE_COMMAND:-}"
BUILD_CONTRACT_JSON="${APPLAB_BUILD_CONTRACT_JSON:?APPLAB_BUILD_CONTRACT_JSON is required}"

validate_prepare_hook() {
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

mkdir -p "$REPORT_DIR"
cp "$BUILD_CONTRACT_JSON" "$REPORT_DIR/contract.json"
adb install -r -t "$APK_FILE"
if [[ -n "$ANDROID_PREPARE_COMMAND" ]]; then
  validate_prepare_hook
  bash -Eeuo pipefail -c "$ANDROID_PREPARE_COMMAND"
fi

python3 "$TRUSTED_ROOT/scripts/journey_shard_runtime.py"   --target-root "$TARGET_ROOT"   --trusted-root "$TRUSTED_ROOT"   --plan "$PLAN_FILE"   --repository "$REPOSITORY"   --package-id "$PACKAGE_ID"   --report-dir "$REPORT_DIR"   --journey-ids-json "$JOURNEY_IDS_JSON"   --shard-id "$SHARD_ID"
