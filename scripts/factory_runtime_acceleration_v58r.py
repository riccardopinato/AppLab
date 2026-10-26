#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

RUNNER_TOKENS = {
    "FLUTTER": "riccardopinato/AppLab/.github/workflows/external-project-runner.yml@",
    "NATIVE_ANDROID": "riccardopinato/AppLab/.github/workflows/external-native-android-runner.yml@",
    "UNIVERSAL": "riccardopinato/AppLab/.github/workflows/universal-project-runner.yml@",
}
MODE_RE = re.compile(r"(?m)^\s*analysis_mode:\s*([^#\n]+)")
BASELINE_RE = re.compile(r"(?m)^\s*baseline_sha:\s*([^#\n]+)")
CACHE_RE = re.compile(r"(?m)^\s*cache_verification:\s*(true|false)\s*$", re.I)
JOB_RE = re.compile(r"^  ([A-Za-z0-9_.-]+):\s*(?:#.*)?$")


def api_json(url: str, token: str = "") -> Any:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "AppLab-v5.8R"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def content(repository: str, path: str, ref: str, token: str = "") -> str | None:
    q = urllib.parse.urlencode({"ref": ref})
    url = (
        f"https://api.github.com/repos/{repository}/contents/"
        f"{urllib.parse.quote(path, safe='/')}?{q}"
    )
    payload = api_json(url, token)
    if not isinstance(payload, dict):
        return None
    raw = payload.get("content")
    if not isinstance(raw, str):
        return None
    return base64.b64decode(raw).decode("utf-8", errors="replace")


def workflow_paths(repository: str, ref: str, token: str = "") -> list[str]:
    q = urllib.parse.urlencode({"ref": ref})
    payload = api_json(
        f"https://api.github.com/repos/{repository}/contents/.github/workflows?{q}",
        token,
    )
    if not isinstance(payload, list):
        return []
    return sorted(
        f".github/workflows/{item.get('name')}"
        for item in payload
        if isinstance(item, dict)
        and item.get("type") == "file"
        and str(item.get("name", "")).endswith((".yml", ".yaml"))
    )


def scalar(match: re.Match[str] | None) -> str:
    if match is None:
        return ""
    return match.group(1).strip().strip('"').strip("'")


def job_blocks(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    jobs_index = next((i for i, line in enumerate(lines) if line.strip() == "jobs:" and not line.startswith(" ")), -1)
    if jobs_index < 0:
        return []
    blocks: list[tuple[str, str]] = []
    current_id = ""
    current: list[str] = []
    for line in lines[jobs_index + 1:]:
        if line and not line.startswith(" "):
            break
        match = JOB_RE.match(line)
        if match:
            if current_id:
                blocks.append((current_id, "\n".join(current) + "\n"))
            current_id = match.group(1)
            current = [line]
        elif current_id:
            current.append(line)
    if current_id:
        blocks.append((current_id, "\n".join(current) + "\n"))
    return blocks


def runner_type(block: str) -> str:
    for kind, token in RUNNER_TOKENS.items():
        if token in block:
            return kind
    return ""


def multiline_hook_present(text: str, key: str) -> bool:
    pattern = re.compile(rf"(?m)^([ \t]*){re.escape(key)}:\s*(>?-?|\|?-?)?\s*$")
    match = pattern.search(text)
    if not match:
        inline = re.search(rf"(?m)^\s*{re.escape(key)}:\s*(\S.+)$", text)
        return bool(inline and inline.group(1).strip() not in {"''", '""'})
    indent = len(match.group(1))
    for line in text[match.end():].splitlines():
        if not line.strip():
            continue
        current = len(line) - len(line.lstrip(" "))
        return current > indent
    return False


def assess_job(repository: str, path: str, job_id: str, block: str) -> dict[str, Any] | None:
    kind = runner_type(block)
    if not kind:
        return None
    mode = scalar(MODE_RE.search(block)) or "full"
    baseline = scalar(BASELINE_RE.search(block))
    cache_match = CACHE_RE.search(block)
    cache_enabled = bool(cache_match and cache_match.group(1).lower() == "true")
    prepare = multiline_hook_present(block, "prepare_command")
    post = multiline_hook_present(block, "post_pub_get_command")

    findings: list[str] = []
    if mode == "full":
        findings.append("FULL_FORCED")
    elif mode == "fast":
        if not baseline:
            findings.append("FAST_WITHOUT_BASELINE")
    elif mode == "certification":
        findings.append("CERTIFICATION_EXPLICIT")
    else:
        findings.append("UNKNOWN_ANALYSIS_MODE")

    if mode == "fast" and not cache_enabled:
        findings.append("EXACT_HEAD_CACHE_DISABLED")
    if prepare or post:
        findings.append("BUILD_REUSE_BLOCKED_MUTABLE_HOOK")

    if mode == "fast" and baseline and cache_enabled:
        runtime_state = "ADAPTIVE_FAST_READY"
    elif mode == "certification":
        runtime_state = "CERTIFICATION_UNCHANGED"
    else:
        runtime_state = "OPTIMIZATION_AVAILABLE"

    return {
        "repository": repository,
        "workflow": path,
        "job_id": job_id,
        "runner_type": kind,
        "analysis_mode": mode,
        "baseline_declared": bool(baseline),
        "cache_verification": cache_enabled,
        "mutable_prepare_hook": prepare,
        "mutable_post_hook": post,
        "runtime_state": runtime_state,
        "findings": findings,
        "recommended_changes": [
            change for change in (
                "USE_FAST_FOR_NORMAL_PR" if "FULL_FORCED" in findings else "",
                "PASS_EXACT_PR_BASELINE" if "FAST_WITHOUT_BASELINE" in findings else "",
                "ENABLE_EXACT_HEAD_CACHE" if "EXACT_HEAD_CACHE_DISABLED" in findings else "",
                "SEPARATE_GENERATED_SCAFFOLD_CONTRACT"
                if "BUILD_REUSE_BLOCKED_MUTABLE_HOOK" in findings else "",
            ) if change
        ],
    }


def assess_workflow(repository: str, path: str, text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for job_id, block in job_blocks(text):
        assessment = assess_job(repository, path, job_id, block)
        if assessment is not None:
            out.append(assessment)
    return out


def build_report(observatory: dict[str, Any], fetcher, token: str = "") -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in observatory.get("repositories", []):
        if not isinstance(item, dict):
            continue
        if item.get("status") != "ADOPTED" and not item.get("pilot"):
            continue
        repository = str(item.get("repository", "")).strip()
        ref = str(item.get("ref", "main")).strip() or "main"
        if not repository:
            continue
        found = False
        for path in fetcher("paths", repository, ref, token):
            text = fetcher("content", repository, ref, token, path)
            if text is None:
                continue
            assessments = assess_workflow(repository, path, text)
            for assessment in assessments:
                assessment["ref"] = ref
                assessment["pilot"] = bool(item.get("pilot"))
                assessment["adoption_status"] = str(item.get("status", "UNKNOWN"))
                rows.append(assessment)
                found = True
        if not found:
            rows.append({
                "repository": repository,
                "ref": ref,
                "pilot": bool(item.get("pilot")),
                "adoption_status": str(item.get("status", "UNKNOWN")),
                "runtime_state": "NO_APPLAB_EXTERNAL_RUNNER",
                "findings": ["NO_APPLAB_EXTERNAL_RUNNER"],
                "recommended_changes": [],
            })

    summary = {
        "jobs": len(rows),
        "adaptive_fast_ready": sum(x.get("runtime_state") == "ADAPTIVE_FAST_READY" for x in rows),
        "optimization_available": sum(x.get("runtime_state") == "OPTIMIZATION_AVAILABLE" for x in rows),
        "forced_full": sum("FULL_FORCED" in x.get("findings", []) for x in rows),
        "cache_disabled": sum("EXACT_HEAD_CACHE_DISABLED" in x.get("findings", []) for x in rows),
        "build_reuse_blocked_hooks": sum(
            "BUILD_REUSE_BLOCKED_MUTABLE_HOOK" in x.get("findings", []) for x in rows
        ),
    }
    return {
        "schema_version": 1,
        "record_type": "FACTORY_RUNTIME_ACCELERATION_V58R",
        "authority": "OBSERVATION_AND_PLANNING_ONLY",
        "summary": summary,
        "repositories": rows,
        "guardrails": {
            "smart_test_plan_remains_authority": True,
            "fast_may_escalate_to_full": True,
            "coverage_reduction_enabled": False,
            "certification_unchanged": True,
            "external_review_wait_blocks_next_independent_step": False,
        },
    }


def render_md(report: dict[str, Any]) -> str:
    lines = [
        "# Factory Android Runtime Acceleration v5.8R",
        "",
        "| Repository | Workflow / job | Runner | State | Findings |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report["repositories"]:
        identity = f"{row.get('workflow','-')} / {row.get('job_id','-')}"
        lines.append(
            f"| {row['repository']} | {identity} | {row.get('runner_type','-')} | "
            f"{row['runtime_state']} | {', '.join(row.get('findings', [])) or '-'} |"
        )
    lines += [
        "",
        "FAST remains fail-closed: missing/unprovable baseline or elevated risk may escalate to FULL_RUNTIME.",
        "External code-review latency blocks merge, not preparation of the next independent roadmap step.",
        "",
    ]
    return "\n".join(lines)


def self_test() -> None:
    multi = """
jobs:
  fast_gate:
    uses: riccardopinato/AppLab/.github/workflows/external-project-runner.yml@abc
    with:
      analysis_mode: fast
      baseline_sha: ${{ github.event.pull_request.base.sha || '' }}
      cache_verification: true
  certify:
    uses: riccardopinato/AppLab/.github/workflows/external-native-android-runner.yml@abc
    with:
      analysis_mode: certification
      cache_verification: false
  full_universal:
    uses: riccardopinato/AppLab/.github/workflows/universal-project-runner.yml@abc
    with:
      analysis_mode: full
      prepare_command: >-
        ./gradlew prepare
"""
    assessments = assess_workflow("owner/app", ".github/workflows/gates.yml", multi)
    assert len(assessments) == 3
    by_job = {item["job_id"]: item for item in assessments}
    assert by_job["fast_gate"]["runtime_state"] == "ADAPTIVE_FAST_READY"
    assert by_job["fast_gate"]["runner_type"] == "FLUTTER"
    assert by_job["certify"]["runner_type"] == "NATIVE_ANDROID"
    assert by_job["certify"]["runtime_state"] == "CERTIFICATION_UNCHANGED"
    assert by_job["full_universal"]["runner_type"] == "UNIVERSAL"
    assert "FULL_FORCED" in by_job["full_universal"]["findings"]
    assert "BUILD_REUSE_BLOCKED_MUTABLE_HOOK" in by_job["full_universal"]["findings"]

    observatory = {"repositories": [{"repository": "owner/app", "ref": "main", "status": "ADOPTED"}]}
    def fake(kind: str, repository: str, ref: str, token: str, path: str = ""):
        return [".github/workflows/gates.yml"] if kind == "paths" else multi
    report = build_report(observatory, fake)
    assert report["summary"]["jobs"] == 3
    assert report["summary"]["adaptive_fast_ready"] == 1
    assert report["summary"]["forced_full"] == 1

    pilot_waiting = {
        "repositories": [{
            "repository": "owner/app",
            "ref": "main",
            "status": "MISSING_MANIFEST",
            "pilot": True,
        }]
    }
    pilot_report = build_report(pilot_waiting, fake)
    assert pilot_report["summary"]["jobs"] == 3
    assert pilot_report["repositories"][0]["adoption_status"] == "MISSING_MANIFEST"
    print("AppLab v5.8R runtime acceleration self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observatory", default="")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.observatory:
        raise SystemExit("--observatory is required")

    observatory = json.loads(Path(args.observatory).read_text(encoding="utf-8"))

    def github_fetch(kind: str, repository: str, ref: str, token: str, path: str = ""):
        if kind == "paths":
            return workflow_paths(repository, ref, token)
        return content(repository, path, ref, token)

    report = build_report(observatory, github_fetch, args.token)
    if args.output_json:
        Path(args.output_json).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.output_md:
        Path(args.output_md).write_text(render_md(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
