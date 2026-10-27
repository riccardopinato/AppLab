#!/usr/bin/env bash
set -Eeuo pipefail

NODE="${1:-}"
[[ -n "$NODE" ]] || { echo "node required" >&2; exit 2; }
shift
[[ "$#" -gt 0 ]] || { echo "producer command required" >&2; exit 2; }

EVIDENCE_DIR="${APPLAB_EVIDENCE_DIR:-$GITHUB_WORKSPACE/applab-autonomous-review}"
TRUSTED_DIR="${APPLAB_TRUSTED_DIR:-$GITHUB_WORKSPACE/trusted-runtime}"
TARGET_DIR="${APPLAB_TARGET_DIR:-$GITHUB_WORKSPACE/target}"
CACHE_ROOT="${APPLAB_EVIDENCE_DAG_CACHE:-$GITHUB_WORKSPACE/.applab-longitudinal/evidence-dag}"

mkdir -p "$EVIDENCE_DIR" "$CACHE_ROOT"

RESTORE_JSON="$(
  python "$GITHUB_WORKSPACE/.applab/scripts/self_evidence_dag_v60g.py"     --evidence-dir "$EVIDENCE_DIR"     --trusted-dir "$TRUSTED_DIR"     --target-dir "$TARGET_DIR"     --cache-root "$CACHE_ROOT"     --node "$NODE"     --restore
)"
HIT="$(python -c 'import json,sys; print(str(bool(json.load(sys.stdin).get("cache_hit"))).lower())' <<<"$RESTORE_JSON")"

if [[ "$HIT" == "true" ]]; then
  echo "AppLab v6.0G Evidence DAG cache HIT: $NODE"
  exit 0
fi

echo "AppLab v6.0G Evidence DAG cache MISS: $NODE"
"$@"

python "$GITHUB_WORKSPACE/.applab/scripts/self_evidence_dag_v60g.py"   --evidence-dir "$EVIDENCE_DIR"   --trusted-dir "$TRUSTED_DIR"   --target-dir "$TARGET_DIR"   --cache-root "$CACHE_ROOT"   --node "$NODE"   --save
