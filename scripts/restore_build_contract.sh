#!/usr/bin/env bash
set -Eeuo pipefail

ARTIFACT_NAME=""
OUTPUT_DIR=""
EXPECTED_REPOSITORY=""
EXPECTED_SHA=""
EXPECTED_ENGINE=""
EXPECTED_ANALYSIS_MODE=""
EXPECTED_APPLAB_SHA=""
REPORT_DIR=""
GITHUB_OUTPUT_FILE="${GITHUB_OUTPUT:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact-name) ARTIFACT_NAME="$2"; shift 2 ;;
    --output) OUTPUT_DIR="$2"; shift 2 ;;
    --expected-repository) EXPECTED_REPOSITORY="$2"; shift 2 ;;
    --expected-sha) EXPECTED_SHA="$2"; shift 2 ;;
    --expected-engine) EXPECTED_ENGINE="$2"; shift 2 ;;
    --expected-analysis-mode) EXPECTED_ANALYSIS_MODE="$2"; shift 2 ;;
    --expected-applab-sha) EXPECTED_APPLAB_SHA="$2"; shift 2 ;;
    --report-dir) REPORT_DIR="$2"; shift 2 ;;
    --github-output) GITHUB_OUTPUT_FILE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

: "${GH_TOKEN:?GH_TOKEN is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE is required}"

for value in "$ARTIFACT_NAME" "$OUTPUT_DIR" "$EXPECTED_REPOSITORY" "$EXPECTED_SHA" "$EXPECTED_ENGINE" "$EXPECTED_ANALYSIS_MODE" "$EXPECTED_APPLAB_SHA"; do
  [[ -n "$value" ]] || { echo "Missing required build-reuse argument" >&2; exit 2; }
done

emit() {
  if [[ -n "$GITHUB_OUTPUT_FILE" ]]; then
    printf '%s=%s\n' "$1" "$2" >> "$GITHUB_OUTPUT_FILE"
  fi
}

miss() {
  local reason="$1"
  rm -rf "$OUTPUT_DIR"
  emit hit false
  emit reason "$reason"
  echo "Build reuse MISS: $reason"
  exit 0
}

emit hit false
emit reason not-found

JSON_FILE="$(mktemp)"
if ! gh api   -H "Accept: application/vnd.github+json"   "/repos/$GITHUB_REPOSITORY/actions/artifacts?name=$ARTIFACT_NAME&per_page=100"   > "$JSON_FILE"; then
  rm -f "$JSON_FILE"
  miss "artifact-list-unavailable"
fi

ARTIFACT_ID="$(
  python3 - "$JSON_FILE" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
rows = [item for item in payload.get("artifacts", []) if not item.get("expired")]
rows.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
print(rows[0].get("id", "") if rows else "")
PY
)" || {
  rm -f "$JSON_FILE"
  miss "artifact-list-invalid"
}
rm -f "$JSON_FILE"

[[ -n "$ARTIFACT_ID" ]] || miss "artifact-not-found"

rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"
ZIP_FILE="$(mktemp --suffix=.zip)"

if ! gh api   -H "Accept: application/vnd.github+json"   "/repos/$GITHUB_REPOSITORY/actions/artifacts/$ARTIFACT_ID/zip"   > "$ZIP_FILE"; then
  rm -f "$ZIP_FILE"
  miss "artifact-download-unavailable"
fi

if ! unzip -q "$ZIP_FILE" -d "$OUTPUT_DIR"; then
  rm -f "$ZIP_FILE"
  miss "artifact-unzip-failed"
fi
rm -f "$ZIP_FILE"

if ! python "$GITHUB_WORKSPACE/.applab/scripts/validate_build_contract.py"   --root "$OUTPUT_DIR"   --expected-repository "$EXPECTED_REPOSITORY"   --expected-sha "$EXPECTED_SHA"   --expected-engine "$EXPECTED_ENGINE"   --expected-analysis-mode "$EXPECTED_ANALYSIS_MODE"   --expected-trusted-applab-sha "$EXPECTED_APPLAB_SHA"; then
  miss "contract-validation-failed"
fi

if [[ -n "$REPORT_DIR" ]]; then
  mkdir -p "$REPORT_DIR"
  cp "$OUTPUT_DIR/adaptive-quality.json" "$REPORT_DIR/adaptive-quality.json" 2>/dev/null || true
  cp "$OUTPUT_DIR/apksigner.txt" "$REPORT_DIR/apksigner.txt" 2>/dev/null || true
fi

emit hit true
emit reason validated
emit artifact_id "$ARTIFACT_ID"
echo "Build reuse HIT: $ARTIFACT_NAME ($ARTIFACT_ID)"
