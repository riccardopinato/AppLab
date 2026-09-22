#!/usr/bin/env bash
set -Eeuo pipefail

APP_ID="${1:?usage: create_maestro_smoke.sh <app-id> [output-file]}"
OUTPUT="${2:-applab-report/generated-smoke.yaml}"
mkdir -p "$(dirname "$OUTPUT")"

cat > "$OUTPUT" <<EOF
appId: $APP_ID
---
- launchApp:
    clearState: false
- pressKey: HOME
- launchApp
EOF

echo "$OUTPUT"
