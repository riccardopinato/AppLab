#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_plan(triage: dict[str, Any]) -> dict[str, Any]:
    classification = str(triage.get("classification", "UNKNOWN_FAILURE"))
    surfaces = [str(x) for x in triage.get("likely_surfaces", []) if str(x)]
    regressions = [str(x) for x in triage.get("required_regression_evidence", []) if str(x)]
    action = str(triage.get("recommended_action", "INVESTIGATE_BEFORE_RETRY"))

    if classification == "NONE":
        state = "NO_FIX_REQUIRED"
    elif classification in {"INFRA_ERROR", "FLAKY_SUSPECT", "UNKNOWN_FAILURE"}:
        state = "INVESTIGATION_REQUIRED"
    else:
        state = "FIX_CANDIDATE_READY"

    acceptance = list(regressions)
    if classification in {"APP_RUNTIME_FAILURE", "APP_VISUAL_FAILURE", "BUILD_OR_QUALITY_FAILURE"}:
        acceptance.append("original failure evidence no longer reproduces on exact head")
    if classification == "INFRA_ERROR":
        acceptance.append("targeted same-head retry compared with preserved failed attempt")
    if classification == "UNKNOWN_FAILURE":
        acceptance.append("failure reclassified from deterministic diagnostics before code change")

    return {
        "schema_version": 1,
        "record_type": "FIX_CANDIDATE_PLAN_V58B",
        "authority": "PROPOSAL_ONLY",
        "repository": str(triage.get("repository", "")),
        "resolved_sha": str(triage.get("resolved_sha", "")),
        "baseline_sha": str(triage.get("baseline_sha", "")),
        "classification": classification,
        "state": state,
        "recommended_action": action,
        "scope": {
            "candidate_surfaces": surfaces,
            "candidate_files": [],
            "file_discovery_required": bool(surfaces),
            "unrelated_cleanup_allowed": False,
        },
        "acceptance_criteria": list(dict.fromkeys(acceptance)),
        "rollback": {
            "strategy": "revert bounded fix commit/PR delta",
            "preserve_failure_evidence": True,
            "do_not_weaken_assertions": True,
        },
        "guardrails": {
            "automatic_code_change": False,
            "automatic_retry": False,
            "automatic_merge": False,
            "automatic_release": False,
            "exact_head_validation_required_after_fix": True,
        },
    }


def self_test() -> None:
    app = build_plan({
        "classification": "APP_RUNTIME_FAILURE",
        "repository": "owner/app",
        "resolved_sha": "b" * 40,
        "likely_surfaces": ["network client"],
        "required_regression_evidence": ["focused regression for network"],
        "recommended_action": "FIX_APPLICATION_BEFORE_RETRY",
    })
    assert app["state"] == "FIX_CANDIDATE_READY"
    assert app["scope"]["candidate_files"] == []
    assert app["guardrails"]["automatic_code_change"] is False
    assert any("exact head" in x for x in app["acceptance_criteria"])

    infra = build_plan({
        "classification": "INFRA_ERROR",
        "recommended_action": "TARGETED_SAME_HEAD_RETRY_ALLOWED",
    })
    assert infra["state"] == "INVESTIGATION_REQUIRED"
    assert infra["scope"]["unrelated_cleanup_allowed"] is False

    unknown = build_plan({"classification": "UNKNOWN_FAILURE"})
    assert unknown["state"] == "INVESTIGATION_REQUIRED"
    assert any("reclassified" in x for x in unknown["acceptance_criteria"])
    print("AppLab v5.8B fix candidate planner self-test PASS")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--triage", default="")
    p.add_argument("--output", default="")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        self_test()
        return 0
    if not a.triage:
        raise SystemExit("--triage is required")
    triage = json.loads(Path(a.triage).read_text(encoding="utf-8"))
    report = build_plan(triage)
    if a.output:
        Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
