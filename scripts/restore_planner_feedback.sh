#!/usr/bin/env bash
set -Eeuo pipefail

repository="${1:-}"
destination="${2:-}"
api_url="${GITHUB_API_URL:-https://api.github.com}"
workflow_repository="${GITHUB_REPOSITORY:-}"
runner_temp="${RUNNER_TEMP:-/tmp}"

scope_for_repository() {
  printf '%s' "$1" | sha256sum | cut -c1-20
}

if [[ "${repository}" == "--self-test" ]]; then
  test "$(scope_for_repository "owner/app")" = "$(printf '%s' "owner/app" | sha256sum | cut -c1-20)"
  echo "AppLab planner feedback restore helper self-test PASS"
  exit 0
fi

if [[ -z "$repository" || -z "$destination" ]]; then
  echo "usage: restore_planner_feedback.sh owner/repository destination.json" >&2
  exit 2
fi

if [[ -z "$workflow_repository" ]]; then
  echo "GITHUB_REPOSITORY is required" >&2
  exit 2
fi

scope="$(scope_for_repository "$repository")"
artifact_name="applab-longitudinal-history-$scope"
work_dir="$runner_temp/applab-planner-feedback-$scope"
zip_path="$runner_temp/applab-planner-feedback-$scope.zip"
rm -rf "$work_dir" "$zip_path"
mkdir -p "$work_dir" "$(dirname "$destination")"

artifact_id="$(
  gh api     -H "Accept: application/vnd.github+json"     "/repos/$workflow_repository/actions/artifacts?name=$artifact_name&per_page=100"     --jq '.artifacts | map(select(.expired == false)) | sort_by(.created_at) | reverse | .[0].id // empty'
)"

if [[ -z "$artifact_id" ]]; then
  echo "No prior planner-feedback artifact found for $repository."
  exit 0
fi

gh api   -H "Accept: application/vnd.github+json"   "/repos/$workflow_repository/actions/artifacts/$artifact_id/zip"   > "$zip_path"
unzip -q -o "$zip_path" -d "$work_dir"

candidate="$(find "$work_dir" -type f -name planner-feedback.json -print -quit)"
if [[ -z "$candidate" ]]; then
  echo "Longitudinal artifact $artifact_id has no planner-feedback.json; ignoring."
  exit 0
fi

cp "$candidate" "$destination"
echo "Restored planner feedback artifact $artifact_id for $repository."
