#!/usr/bin/env bash
set -Eeuo pipefail

OUTPUT_DIR="${1:-runtime-fixture}"
WAIT_SECONDS="${APPLAB_FIXTURE_WAIT_SECONDS:-1320}"
POLL_SECONDS="${APPLAB_FIXTURE_POLL_SECONDS:-10}"

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_SHA:?GITHUB_SHA is required}"
if [[ -z "${GH_TOKEN:-}" ]]; then
  : "${GITHUB_TOKEN:?GH_TOKEN or GITHUB_TOKEN is required}"
  export GH_TOKEN="$GITHUB_TOKEN"
fi

ARTIFACT_NAME="${APPLAB_FIXTURE_ARTIFACT_NAME:-applab-runtime-fixture-$GITHUB_SHA}"
STARTED_AT="$(date +%s)"
ARTIFACT_ID=""

while :; do
  ARTIFACT_ID=""
  JSON_FILE="$(mktemp)"

  if gh api \
    -H "Accept: application/vnd.github+json" \
    "/repos/$GITHUB_REPOSITORY/actions/artifacts?name=$ARTIFACT_NAME&per_page=100" \
    > "$JSON_FILE"; then
    if ARTIFACT_ID="$(
      python3 - "$JSON_FILE" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
# Artifact identity is encoded in the exact name with GITHUB_SHA. On
# pull_request, GITHUB_SHA is the synthetic merge SHA while REST
# workflow_run.head_sha is the branch head SHA, so those fields must not be
# compared. The downloaded manifest and APK are verified below.
rows = [
    item
    for item in payload.get("artifacts", [])
    if not item.get("expired")
]
rows.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
print(rows[0].get("id", "") if rows else "")
PY
    )"; then
      :
    else
      ARTIFACT_ID=""
      echo "Runtime fixture artifact response was invalid; retrying within wait budget." >&2
    fi
  else
    echo "Runtime fixture artifact lookup failed; retrying within wait budget." >&2
  fi
  rm -f "$JSON_FILE"

  if [[ -n "$ARTIFACT_ID" ]]; then
    rm -rf "$OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR"
    ZIP_FILE="$(mktemp --suffix=.zip)"
    DOWNLOAD_OK=false

    if gh api \
      -H "Accept: application/vnd.github+json" \
      "/repos/$GITHUB_REPOSITORY/actions/artifacts/$ARTIFACT_ID/zip" \
      > "$ZIP_FILE"; then
      if unzip -q "$ZIP_FILE" -d "$OUTPUT_DIR"; then
        DOWNLOAD_OK=true
      else
        echo "Runtime fixture artifact unzip failed; retrying within wait budget." >&2
      fi
    else
      echo "Runtime fixture artifact download failed; retrying within wait budget." >&2
    fi
    rm -f "$ZIP_FILE"

    if [[ "$DOWNLOAD_OK" == "true" ]]; then
      break
    fi
    rm -rf "$OUTPUT_DIR"
    ARTIFACT_ID=""
  fi

  NOW="$(date +%s)"
  if (( NOW - STARTED_AT >= WAIT_SECONDS )); then
    echo "Timed out waiting for canonical runtime fixture: $ARTIFACT_NAME" >&2
    exit 1
  fi
  echo "Waiting for canonical runtime fixture $ARTIFACT_NAME..."
  sleep "$POLL_SECONDS"
done

MANIFEST="$OUTPUT_DIR/manifest.json"
APK="$OUTPUT_DIR/app-debug.apk"
test -s "$MANIFEST"
test -s "$APK"

python3 - "$MANIFEST" "$APK" "$GITHUB_SHA" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
apk = Path(sys.argv[2])
expected_sha = sys.argv[3]
if manifest.get("source_sha") != expected_sha:
    raise SystemExit(
        f"fixture source SHA mismatch: {manifest.get('source_sha')} != {expected_sha}"
    )
digest = hashlib.sha256(apk.read_bytes()).hexdigest()
if manifest.get("apk_sha256") != digest:
    raise SystemExit(
        f"fixture APK SHA-256 mismatch: {manifest.get('apk_sha256')} != {digest}"
    )
if manifest.get("engine_version") != "4.1.0":
    raise SystemExit(f"unsupported runtime fixture engine: {manifest.get('engine_version')}")
print(f"Canonical runtime fixture verified: {digest}")
PY
