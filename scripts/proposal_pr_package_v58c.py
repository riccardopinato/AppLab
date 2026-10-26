#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_package(triage: dict[str, Any], fix_plan: dict[str, Any]) -> dict[str, Any]:
    repository = str(fix_plan.get("repository") or triage.get("repository") or "")
    sha = str(fix_plan.get("resolved_sha") or triage.get("resolved_sha") or "")
    classification = str(fix_plan.get("classification") or triage.get("classification") or "UNKNOWN_FAILURE")
    surfaces = list((fix_plan.get("scope") or {}).get("candidate_surfaces") or [])
    criteria = [str(x) for x in fix_plan.get("acceptance_criteria", []) if str(x)]
    diagnostics = [str(x) for x in triage.get("root_cause_hypotheses", []) if str(x)]
    failed_labs = [str(x) for x in triage.get("failed_labs", []) if str(x)]
    state = str(fix_plan.get("state", "INVESTIGATION_REQUIRED"))

    title = f"Fix: {classification.lower().replace('_', ' ')}"
    body_sections = {
        "scope": surfaces or ["Repository discovery required before proposing file changes."],
        "diagnostics": diagnostics or ["No concrete diagnostic retained; investigate before edit."],
        "failed_labs": failed_labs,
        "acceptance_criteria": criteria,
        "rollback": [
            str((fix_plan.get("rollback") or {}).get("strategy", "revert bounded fix delta"))
        ],
        "evidence": [
            f"source exact head: {sha or 'UNKNOWN'}",
            f"triage classification: {classification}",
            "preserve original failed attempt",
        ],
    }

    return {
        "schema_version": 1,
        "record_type": "PROPOSAL_PR_PACKAGE_V58C",
        "authority": "PROPOSAL_ONLY",
        "repository": repository,
        "resolved_sha": sha,
        "classification": classification,
        "state": "READY_FOR_AGENT" if state == "FIX_CANDIDATE_READY" else "INVESTIGATION_PACKAGE",
        "suggested_title": title,
        "body_sections": body_sections,
        "agent_instructions": {
            "discover_candidate_files_before_edit": True,
            "keep_change_bounded": True,
            "add_or_update_regression_coverage": True,
            "run_focused_validation": True,
            "require_exact_head_green_before_merge": True,
        },
        "guardrails": {
            "can_create_pr": False,
            "can_push_code": False,
            "can_merge": False,
            "can_release": False,
            "can_weaken_assertions": False,
        },
    }


def self_test() -> None:
    triage = {
        "repository": "owner/app",
        "resolved_sha": "b" * 40,
        "classification": "APP_RUNTIME_FAILURE",
        "root_cause_hypotheses": ["network request fails after reconnect"],
        "failed_labs": ["network"],
    }
    fix = {
        "repository": "owner/app",
        "resolved_sha": "b" * 40,
        "classification": "APP_RUNTIME_FAILURE",
        "state": "FIX_CANDIDATE_READY",
        "scope": {"candidate_surfaces": ["network client"]},
        "acceptance_criteria": ["focused regression for network"],
        "rollback": {"strategy": "revert bounded fix commit/PR delta"},
    }
    pkg = build_package(triage, fix)
    assert pkg["state"] == "READY_FOR_AGENT"
    assert pkg["guardrails"]["can_create_pr"] is False
    assert pkg["agent_instructions"]["require_exact_head_green_before_merge"] is True
    assert pkg["body_sections"]["diagnostics"] == ["network request fails after reconnect"]
    assert pkg["body_sections"]["failed_labs"] == ["network"]

    investigating = build_package(
        {"classification": "UNKNOWN_FAILURE"},
        {"classification": "UNKNOWN_FAILURE", "state": "INVESTIGATION_REQUIRED"},
    )
    assert investigating["state"] == "INVESTIGATION_PACKAGE"
    print("AppLab v5.8C proposal PR package self-test PASS")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--triage", default="")
    p.add_argument("--fix-plan", default="")
    p.add_argument("--output", default="")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        self_test()
        return 0
    if not a.triage or not a.fix_plan:
        raise SystemExit("--triage and --fix-plan are required")
    triage = json.loads(Path(a.triage).read_text(encoding="utf-8"))
    fix = json.loads(Path(a.fix_plan).read_text(encoding="utf-8"))
    report = build_package(triage, fix)
    if a.output:
        Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
