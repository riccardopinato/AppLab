#!/usr/bin/env bash
set -Eeuo pipefail

OUTPUT_DIR="${1:-runtime-fixture}"

: "${GITHUB_SHA:?GITHUB_SHA is required}"

rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

gradle -p selftest :app:assembleDebug --stacktrace

SOURCE_APK="selftest/app/build/outputs/apk/debug/app-debug.apk"
test -s "$SOURCE_APK"
cp "$SOURCE_APK" "$OUTPUT_DIR/app-debug.apk"

APK_SHA="$(sha256sum "$OUTPUT_DIR/app-debug.apk" | awk '{print $1}')"
APK_SIZE="$(stat -c '%s' "$OUTPUT_DIR/app-debug.apk")"

python3 - "$OUTPUT_DIR" "$APK_SHA" "$APK_SIZE" <<'PY'
import json
import os
import sys
from pathlib import Path

output = Path(sys.argv[1])
payload = {
    "schema_version": 1,
    "engine_version": "4.1.0",
    "source_sha": os.environ["GITHUB_SHA"],
    "workflow_run_id": os.environ.get("GITHUB_RUN_ID", ""),
    "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
    "apk_sha256": sys.argv[2],
    "apk_size": int(sys.argv[3]),
    "build_command": "gradle -p selftest :app:assembleDebug --stacktrace",
    "build_once_verify_many": False,
    "producer": "manual-workflow-fallback",
}
(output / "manifest.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

python3 - "$OUTPUT_DIR/manifest.json" "$OUTPUT_DIR/app-debug.apk" "$GITHUB_SHA" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
apk = Path(sys.argv[2])
expected_sha = sys.argv[3]
if manifest.get("source_sha") != expected_sha:
    raise SystemExit("manual fixture source SHA mismatch")
digest = hashlib.sha256(apk.read_bytes()).hexdigest()
if manifest.get("apk_sha256") != digest:
    raise SystemExit("manual fixture APK SHA-256 mismatch")
print(f"Manual runtime fixture verified: {digest}")
PY
