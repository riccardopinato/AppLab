#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verification_intelligence import classify_failure

LAB_SURFACES = {
    "system": ["AndroidManifest/native integration", "permissions/system UI"],
    "performance": ["rendering/hot paths", "startup/runtime performance"],
    "network": ["network client", "sync/connectivity"],
    "persistence": ["repository/store", "restart persistence"],
    "configuration": ["screen lifecycle", "configuration changes"],
    "resource_pressure": ["process recovery", "memory/resource ownership"],
    "background": ["background scheduling", "notifications/workers"],
    "storage": ["file/media/backup storage", "storage lifecycle"],
    "upgrade": ["schema/migration", "upgrade compatibility"],
}

CLASS_ACTION = {
    "APP_RUNTIME_FAILURE": "FIX_APPLICATION_BEFORE_RETRY",
    "APP_VISUAL_FAILURE": "FIX_VISUAL_REGRESSION_BEFORE_RETRY",
    "BUILD_OR_QUALITY_FAILURE": "FIX_BUILD_OR_TEST_BEFORE_RETRY",
    "INFRA_ERROR": "TARGETED_SAME_HEAD_RETRY_ALLOWED",
    "FLAKY_SUSPECT": "INVESTIGATE_THEN_TARGETED_RETRY",
    "UNKNOWN_FAILURE": "INVESTIGATE_BEFORE_RETRY",
    "NONE": "NO_TRIAGE_REQUIRED",
}


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


def build_triage(result: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    intelligence = result.get("failure_intelligence")
    if not isinstance(intelligence, dict):
        intelligence = classify_failure(result, plan)

    kind = str(intelligence.get("kind", "UNKNOWN_FAILURE"))
    failed_labs = [str(x) for x in intelligence.get("failed_labs", []) if str(x)]
    likely_surfaces: list[str] = []
    for lab in failed_labs:
        likely_surfaces.extend(LAB_SURFACES.get(lab, [f"{lab} domain"]))

    playbook = plan.get("playbook") if isinstance(plan.get("playbook"), dict) else {}
    category = str(playbook.get("category", "")).strip()
    if category:
        likely_surfaces.append(f"change category: {category}")

    required_regressions = []
    for lab in failed_labs:
        required_regressions.append(f"focused regression for {lab}")
    if kind == "APP_VISUAL_FAILURE":
        required_regressions.append("visual checkpoint/regression reproduction")
    if kind == "BUILD_OR_QUALITY_FAILURE":
        required_regressions.append("failing build/test/lint reproduced locally or in focused CI")
    if kind in {"INFRA_ERROR", "FLAKY_SUSPECT"}:
        required_regressions.append("preserve failed attempt and compare targeted same-head retry")
    if kind == "UNKNOWN_FAILURE":
        required_regressions.append("collect deterministic diagnostics before any retry")

    hypotheses = []
    reason = str(result.get("reason", "") or intelligence.get("reason", "")).strip()
    if reason:
        hypotheses.append(reason[:500])
    for lab in failed_labs:
        hypotheses.append(f"{lab} failure is causally related to the current changed-file impact set")

    retryable = bool(intelligence.get("retryable", False))
    return {
        "schema_version": 1,
        "record_type": "AUTONOMOUS_FAILURE_TRIAGE_V58A",
        "authority": "PROPOSAL_ONLY",
        "repository": str(result.get("repository", plan.get("repository", ""))),
        "resolved_sha": str(result.get("resolved_sha", plan.get("head_sha", ""))),
        "baseline_sha": str(plan.get("baseline_sha", "")),
        "analysis_lane": str(result.get("analysis_lane", plan.get("lane", ""))),
        "classification": kind,
        "retryable": retryable,
        "recommended_action": CLASS_ACTION.get(kind, "INVESTIGATE_BEFORE_RETRY"),
        "failed_labs": failed_labs,
        "likely_surfaces": _unique(likely_surfaces),
        "root_cause_hypotheses": _unique(hypotheses),
        "required_regression_evidence": _unique(required_regressions),
        "guardrails": {
            "automatic_code_change": False,
            "automatic_retry": False,
            "automatic_merge": False,
            "automatic_release": False,
            "failed_attempt_must_be_preserved": True,
            "unknown_is_not_infra": True,
        },
    }


def self_test() -> None:
    plan = {
        "repository": "owner/app",
        "head_sha": "b" * 40,
        "baseline_sha": "a" * 40,
        "lane": "FAST_RUNTIME",
        "playbook": {"category": "ui_change"},
        "learning_profile": {"unstable_labs": []},
    }
    runtime = build_triage(
        {"result": "FAIL", "network_lab": "FAIL", "reason": "network regression"},
        plan,
    )
    assert runtime["classification"] == "APP_RUNTIME_FAILURE"
    assert runtime["retryable"] is False
    assert "network client" in runtime["likely_surfaces"]
    assert runtime["guardrails"]["automatic_code_change"] is False

    infra = build_triage(
        {"result": "FAIL", "reason": "emulator connection reset"},
        plan,
    )
    assert infra["classification"] == "INFRA_ERROR"
    assert infra["recommended_action"] == "TARGETED_SAME_HEAD_RETRY_ALLOWED"
    assert infra["guardrails"]["automatic_retry"] is False

    unknown = build_triage(
        {"result": "FAIL", "reason": "unclassified stop"},
        plan,
    )
    assert unknown["classification"] == "UNKNOWN_FAILURE"
    assert unknown["retryable"] is False
    print("AppLab v5.8A autonomous failure triage self-test PASS")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--result", default="")
    p.add_argument("--plan", default="")
    p.add_argument("--output", default="")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        self_test()
        return 0
    if not a.result or not a.plan:
        raise SystemExit("--result and --plan are required")
    result = json.loads(Path(a.result).read_text(encoding="utf-8"))
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    report = build_triage(result, plan)
    if a.output:
        Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
