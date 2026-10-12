#!/usr/bin/env bash
set -Eeuo pipefail

repository="${1:-}"
baseline_sha="${2:-}"
source_ref="${3:-}"
destination="${4:-}"
workflow_repository="${GITHUB_REPOSITORY:-}"
runner_temp="${RUNNER_TEMP:-/tmp}"
server_url="${GITHUB_SERVER_URL:-https://github.com}"
gh_host="${server_url#*://}"

scope_for_repository() {
  printf '%s' "$1" | sha256sum | cut -c1-20
}

select_matching_feedback() {
  local root="$1"
  local repo="$2"
  local baseline="$3"
  local ref="$4"
  local output="$5"
  python - "$root" "$repo" "$baseline" "$ref" "$output" <<'PY'
import json
import re
import shutil
import sys
from pathlib import Path

root, repository, baseline, source_ref, output = sys.argv[1:]
def clean_ref(value: str) -> str:
    for prefix in ("refs/heads/", "origin/"):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value

expected_ref = clean_ref(source_ref.strip())
ref_is_sha = bool(re.fullmatch(r"[0-9a-fA-F]{40}", expected_ref))
matches = []
for path in sorted(Path(root).rglob("*.json")):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    if not isinstance(payload, dict) or payload.get("record_type") != "EVIDENCE_GRAPH_PLANNER_FEEDBACK":
        continue
    source = payload.get("source")
    if not isinstance(source, dict):
        continue
    if str(source.get("repository", "")).strip() != repository:
        continue
    if str(source.get("resolved_sha", "")).strip().lower() != baseline.lower():
        continue
    lineage = clean_ref(str(source.get("lineage_ref", "")).strip())
    if not ref_is_sha and expected_ref and lineage and lineage != expected_ref:
        continue
    matches.append(path)

if not matches:
    raise SystemExit(3)
selected = matches[-1]
Path(output).parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(selected, output)
print(f"Selected planner feedback: {selected}")
PY
}

if [[ "$repository" == "--self-test" ]]; then
  test "$(scope_for_repository "owner/app")" = "$(printf '%s' "owner/app" | sha256sum | cut -c1-20)"
  test "$gh_host" = "github.com"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  mkdir -p "$tmp/history"
  cat > "$tmp/history/main.json" <<'JSON'
{"record_type":"EVIDENCE_GRAPH_PLANNER_FEEDBACK","source":{"repository":"owner/app","resolved_sha":"1111111111111111111111111111111111111111","lineage_ref":"main"}}
JSON
  cat > "$tmp/history/other.json" <<'JSON'
{"record_type":"EVIDENCE_GRAPH_PLANNER_FEEDBACK","source":{"repository":"owner/app","resolved_sha":"1111111111111111111111111111111111111111","lineage_ref":"feature-x"}}
JSON
  select_matching_feedback "$tmp/history" "owner/app" "1111111111111111111111111111111111111111" "main" "$tmp/selected.json"
  grep -Fq '"lineage_ref":"main"' "$tmp/selected.json"
  echo "AppLab planner feedback restore helper self-test PASS"
  exit 0
fi

if [[ -z "$repository" || -z "$baseline_sha" || -z "$destination" ]]; then
  echo "usage: restore_planner_feedback.sh owner/repository baseline_sha source_ref destination.json" >&2
  exit 2
fi
if [[ ! "$baseline_sha" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "Invalid planner-feedback baseline SHA: $baseline_sha" >&2
  exit 2
fi
if [[ -z "$workflow_repository" ]]; then
  echo "GITHUB_REPOSITORY is required" >&2
  exit 2
fi

if [[ "$gh_host" != "github.com" && -n "${GH_TOKEN:-}" && -z "${GH_ENTERPRISE_TOKEN:-}" ]]; then
  export GH_ENTERPRISE_TOKEN="$GH_TOKEN"
fi

scope="$(scope_for_repository "$repository")"
artifact_name="applab-longitudinal-history-$scope"
work_root="$runner_temp/applab-planner-feedback-$scope"
rm -rf "$work_root"
mkdir -p "$work_root" "$(dirname "$destination")"
rm -f "$destination"

mapfile -t artifact_ids < <(
  gh api --hostname "$gh_host"     -H "Accept: application/vnd.github+json"     "/repos/$workflow_repository/actions/artifacts?name=$artifact_name&per_page=100"     --jq '.artifacts | map(select(.expired == false)) | sort_by(.created_at) | reverse | .[:20] | .[].id'
)
if [[ "${#artifact_ids[@]}" -eq 0 ]]; then
  echo "No prior planner-feedback artifact found for $repository."
  exit 0
fi

for artifact_id in "${artifact_ids[@]}"; do
  work_dir="$work_root/$artifact_id"
  zip_path="$work_root/$artifact_id.zip"
  mkdir -p "$work_dir"
  gh api --hostname "$gh_host"     -H "Accept: application/vnd.github+json"     "/repos/$workflow_repository/actions/artifacts/$artifact_id/zip"     > "$zip_path"
  unzip -q -o "$zip_path" -d "$work_dir"
  if select_matching_feedback "$work_dir" "$repository" "$baseline_sha" "$source_ref" "$destination"; then
    echo "Restored exact-baseline planner feedback from artifact $artifact_id for $repository@$baseline_sha."
    exit 0
  fi
done

echo "No compatible planner feedback found across recent longitudinal artifacts for $repository@$baseline_sha."
rm -f "$destination"
