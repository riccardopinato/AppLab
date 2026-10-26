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

RUNNER_TOKEN = "riccardopinato/AppLab/.github/workflows/external-project-runner.yml@"
MODE_RE = re.compile(r"(?m)^\s*analysis_mode:\s*([^#\n]+)")
BASELINE_RE = re.compile(r"(?m)^\s*baseline_sha:\s*([^#\n]+)")
CACHE_RE = re.compile(r"(?m)^\s*cache_verification:\s*(true|false)\s*$", re.I)
PREPARE_RE = re.compile(r"(?m)^\s*prepare_command:\s*(.*)$")
POST_RE = re.compile(r"(?m)^\s*post_pub_get_command:\s*(.*)$")


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


def multiline_hook_present(text: str, key: str) -> bool:
    pattern = re.compile(rf"(?m)^([ \t]*){re.escape(key)}:\s*(>?-?|\|?-?)?\s*$")
    match = pattern.search(text)
    if not match:
        inline = re.search(rf"(?m)^\s*{re.escape(key)}:\s*(\S.+)$", text)
        return bool(inline and inline.group(1).strip() not in {"''", '""'})
    indent = len(match.group(1))
    remainder = text[match.end():].splitlines()
    for line in remainder:
        if not line.strip():
            continue
        current = len(line) - len(line.lstrip(" "))
        return current > indent
    return False


def assess_workflow(repository: str, path: str, text: str) -> dict[str, Any] | None:
    if RUNNER_TOKEN not in text:
        return None
    mode = scalar(MODE_RE.search(text)) or "full"
    baseline = scalar(BASELINE_RE.search(text))
    cache_match = CACHE_RE.search(text)
    cache_enabled = bool(cache_match and cache_match.group(1).lower() == "true")
    prepare = multiline_hook_present(text, "prepare_command")
    post = multiline_hook_present(text, "post_pub_get_command")

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
            assessment = assess_workflow(repository, path, text)
            if assessment is not None:
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
        "workflows": len(rows),
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
        "| Repository | Workflow | State | Findings |",
        "| --- | --- | --- | --- |",
    ]
    for row in report["repositories"]:
        lines.append(
            f"| {row['repository']} | {row.get('workflow','-')} | "
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
    forced = """
jobs:
  gate:
    uses: riccardopinato/AppLab/.github/workflows/external-project-runner.yml@abc
    with:
      analysis_mode: full
      cache_verification: false
      prepare_command: >-
        flutter create /tmp/app
"""
    a = assess_workflow("owner/a", ".github/workflows/applab.yml", forced)
    assert a is not None
    assert "FULL_FORCED" in a["findings"]
    assert "BUILD_REUSE_BLOCKED_MUTABLE_HOOK" in a["findings"]

    fast = """
jobs:
  gate:
    uses: riccardopinato/AppLab/.github/workflows/external-project-runner.yml@abc
    with:
      analysis_mode: fast
      baseline_sha: ${{ github.event.pull_request.base.sha || '' }}
      cache_verification: true
"""
    b = assess_workflow("owner/b", ".github/workflows/applab.yml", fast)
    assert b is not None
    assert b["runtime_state"] == "ADAPTIVE_FAST_READY"
    assert b["findings"] == []

    no_baseline = fast.replace(
        "      baseline_sha: ${{ github.event.pull_request.base.sha || '' }}\n", ""
    )
    c = assess_workflow("owner/c", ".github/workflows/applab.yml", no_baseline)
    assert c is not None and "FAST_WITHOUT_BASELINE" in c["findings"]

    observatory = {"repositories": [{"repository": "owner/b", "ref": "main", "status": "ADOPTED"}]}
    def fake(kind: str, repository: str, ref: str, token: str, path: str = ""):
        return [".github/workflows/applab.yml"] if kind == "paths" else fast
    report = build_report(observatory, fake)
    assert report["summary"]["adaptive_fast_ready"] == 1

    pilot_waiting = {
        "repositories": [{
            "repository": "owner/b",
            "ref": "main",
            "status": "MISSING_MANIFEST",
            "pilot": True,
        }]
    }
    pilot_report = build_report(pilot_waiting, fake)
    assert pilot_report["summary"]["adaptive_fast_ready"] == 1
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
