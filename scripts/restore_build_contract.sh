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

for value in   "$ARTIFACT_NAME"   "$OUTPUT_DIR"   "$EXPECTED_REPOSITORY"   "$EXPECTED_SHA"   "$EXPECTED_ENGINE"   "$EXPECTED_ANALYSIS_MODE"   "$EXPECTED_APPLAB_SHA"; do
  [[ -n "$value" ]] || {
    echo "Missing required build-reuse argument" >&2
    exit 2
  }
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

validate_candidate() {
  local artifact_id="$1"
  local zip_file

  rm -rf "$OUTPUT_DIR"
  mkdir -p "$OUTPUT_DIR"
  zip_file="$(mktemp --suffix=.zip)"

  if ! gh api \
    -H "Accept: application/vnd.github+json" \
    "/repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id/zip" \
    > "$zip_file"; then
    rm -f "$zip_file"
    rm -rf "$OUTPUT_DIR"
    echo "Skipping build-cache artifact $artifact_id: download unavailable." >&2
    return 1
  fi

  if ! unzip -q "$zip_file" -d "$OUTPUT_DIR"; then
    rm -f "$zip_file"
    rm -rf "$OUTPUT_DIR"
    echo "Skipping build-cache artifact $artifact_id: invalid archive." >&2
    return 1
  fi
  rm -f "$zip_file"

  if ! python "$GITHUB_WORKSPACE/.applab/scripts/validate_build_contract.py" \
    --root "$OUTPUT_DIR" \
    --expected-repository "$EXPECTED_REPOSITORY" \
    --expected-sha "$EXPECTED_SHA" \
    --expected-engine "$EXPECTED_ENGINE" \
    --expected-analysis-mode "$EXPECTED_ANALYSIS_MODE" \
    --expected-trusted-applab-sha "$EXPECTED_APPLAB_SHA"; then
    rm -rf "$OUTPUT_DIR"
    echo "Skipping build-cache artifact $artifact_id: contract validation failed." >&2
    return 1
  fi

  return 0
}

emit hit false
emit reason not-found

json_file="$(mktemp)"
if ! gh api \
  -H "Accept: application/vnd.github+json" \
  "/repos/$GITHUB_REPOSITORY/actions/artifacts?name=$ARTIFACT_NAME&per_page=100" \
  > "$json_file"; then
  rm -f "$json_file"
  miss "artifact-list-unavailable"
fi

ids_file="$(mktemp)"
if ! python3 - "$json_file" > "$ids_file" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
rows = [item for item in payload.get("artifacts", []) if not item.get("expired")]
rows.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
for item in rows[:20]:
    artifact_id = item.get("id")
    if artifact_id:
        print(artifact_id)
PY
then
  rm -f "$json_file" "$ids_file"
  miss "artifact-list-invalid"
fi
rm -f "$json_file"

mapfile -t ARTIFACT_IDS < "$ids_file"
rm -f "$ids_file"

(("${#ARTIFACT_IDS[@]}" > 0)) || miss "artifact-not-found"

for ARTIFACT_ID in "${ARTIFACT_IDS[@]}"; do
  if ! validate_candidate "$ARTIFACT_ID"; then
    continue
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
  exit 0
done

miss "no-valid-artifact"
