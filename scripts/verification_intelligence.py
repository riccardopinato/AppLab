#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

LAB_FIELDS = {
    "system": "system_lab",
    "performance": "performance_lab",
    "network": "network_lab",
    "persistence": "persistence_lab",
    "configuration": "configuration_lab",
    "resource_pressure": "resource_pressure_lab",
    "background": "background_lab",
    "storage": "storage_lab",
    "upgrade": "upgrade_lab",
}
INFRA_KEYWORDS = (
    "timeout", "timed out", "runner", "emulator", "adb connection",
    "connection reset", "network error", "rate limit", "artifact download",
    "cache", "kvm", "no space left", "temporary failure", "service unavailable",
)


def failed_labs(result: dict[str, Any]) -> list[str]:
    return [
        lab for lab, field in LAB_FIELDS.items()
        if str(result.get(field, "")).upper() in {"FAIL", "ERROR"}
    ]


def warning_labs(result: dict[str, Any]) -> list[str]:
    return [
        lab for lab, field in LAB_FIELDS.items()
        if str(result.get(field, "")).upper() == "WARN"
    ]


def classify_failure(result: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    if str(result.get("result", "")).upper() == "PASS":
        return {"kind": "NONE", "retryable": False, "reason": "verification passed", "failed_labs": []}

    reason = " ".join(
        str(result.get(key, "") or "")
        for key in ("reason", "pipeline_status", "build_error", "error")
    ).lower()
    failures = failed_labs(result)
    unstable = set(((plan.get("learning_profile") or {}).get("unstable_labs") or []))

    if failures and any(lab in unstable for lab in failures):
        kind, retryable = "FLAKY_SUSPECT", True
        explanation = "failed specialist lab has an unstable historical profile"
    elif failures:
        kind, retryable = "APP_RUNTIME_FAILURE", False
        explanation = "trusted runtime specialist evidence failed"
    elif str(result.get("visual_qa", "")).upper() == "FAIL" or str(result.get("visual_regression", "")).upper() == "FAIL":
        kind, retryable = "APP_VISUAL_FAILURE", False
        explanation = "trusted visual evidence failed"
    elif any(keyword in reason for keyword in INFRA_KEYWORDS):
        kind, retryable = "INFRA_ERROR", True
        explanation = "failure matches transient infrastructure/runtime signals"
    elif any(token in reason for token in ("compile error", "compilation failed", "unit test failed", "lint failed", "quality gate failed", "target build failed")):
        kind, retryable = "BUILD_OR_QUALITY_FAILURE", False
        explanation = "deterministic target build or quality evidence failed"
    else:
        kind, retryable = "UNKNOWN_FAILURE", True
        explanation = "failure source is not proven; bounded retry remains safer than suppression"

    return {
        "kind": kind,
        "retryable": retryable,
        "reason": explanation,
        "failed_labs": failures,
        "unstable_failed_labs": sorted(set(failures) & unstable),
    }


def release_readiness(result: dict[str, Any]) -> dict[str, Any]:
    runtime_executed = bool(result.get("runtime_executed", True))
    gates = {
        "verification_pass": str(result.get("result", "")).upper() == "PASS",
        "quality_evidence": str(result.get("pipeline_status", "success")).lower() == "success",
        "runtime_trust": runtime_executed or bool(result.get("runtime_reused_from")),
        "visual_gate": str(result.get("visual_qa", "SKIPPED")).upper() not in {"FAIL", "ERROR"},
        "specialist_labs": not failed_labs(result),
    }
    certification = str(result.get("certification_status", "NOT_REQUESTED")).upper()
    if certification != "NOT_REQUESTED":
        gates["certification"] = certification == "CERTIFIED"

    missing = [name for name, passed in gates.items() if not passed]
    if missing:
        status = "BLOCKED"
    elif certification == "CERTIFIED":
        status = "RELEASE_READY"
    else:
        status = "VERIFIED_NOT_CERTIFIED"

    return {
        "schema_version": 1,
        "status": status,
        "gates": gates,
        "missing_gates": missing,
        "certification_status": certification,
    }


def flaky_detection(result: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    profile = plan.get("learning_profile") or {}
    unstable = set(profile.get("unstable_labs") or [])
    suspects = sorted((set(failed_labs(result)) | set(warning_labs(result))) & unstable)
    return {
        "schema_version": 1,
        "suspected": bool(suspects),
        "labs": suspects,
        "historical_sample_count": int(profile.get("sample_count", 0) or 0),
        "policy": "signal only; never convert FAIL to PASS",
    }


def knowledge_feedback(
    result: dict[str, Any],
    plan: dict[str, Any],
    failure: dict[str, Any],
) -> dict[str, Any]:
    lessons: list[dict[str, str]] = []
    for lab in failed_labs(result):
        lessons.append({
            "domain": lab,
            "severity": "error",
            "lesson": f"Preserve regression coverage for {lab}; the current change produced trusted failure evidence.",
        })
    for lab in warning_labs(result):
        lessons.append({
            "domain": lab,
            "severity": "warning",
            "lesson": f"Track {lab} warning recurrence before reducing future coverage.",
        })
    if failure.get("kind") == "INFRA_ERROR":
        lessons.append({
            "domain": "infrastructure",
            "severity": "warning",
            "lesson": "Retry transient infrastructure failure without treating it as an application defect.",
        })
    if bool(plan.get("analysis_truncated")):
        lessons.append({
            "domain": "impact-analysis",
            "severity": "warning",
            "lesson": "Keep conservative FULL fallback when dependency or semantic evidence is truncated.",
        })
    return {"schema_version": 1, "has_feedback": bool(lessons), "lessons": lessons[:20]}


def project_state_snapshot(
    result: dict[str, Any],
    plan: dict[str, Any],
    readiness: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "applab_version": result.get("applab_version", "1.0.0"),
        "repository": result.get("repository", plan.get("repository", "")),
        "ref": result.get("requested_ref", result.get("ref", "")),
        "resolved_sha": result.get("resolved_sha", plan.get("head_sha", "")),
        "baseline_sha": plan.get("baseline_sha", ""),
        "result": result.get("result", "UNKNOWN"),
        "analysis_lane": result.get("analysis_lane", plan.get("lane", "")),
        "risk_score": result.get("risk_score", plan.get("risk_score")),
        "confidence": result.get("confidence", plan.get("confidence")),
        "playbook": plan.get("playbook", {}),
        "learning_applied_labs": plan.get("learning_applied_labs", []),
        "verification_budget_seconds": plan.get("verification_budget_seconds"),
        "release_readiness": readiness.get("status"),
        "known_limits": [
            "emulator evidence does not replace required physical-device evidence",
            "learning changes coverage only after sufficient project history",
        ],
    }


def enrich_result(result: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    payload = dict(result)
    failure = classify_failure(payload, plan)
    readiness = release_readiness(payload)
    flaky = flaky_detection(payload, plan)
    feedback = knowledge_feedback(payload, plan, failure)
    state = project_state_snapshot(payload, plan, readiness)
    payload.update({
        "failure_intelligence": failure,
        "flaky_detection": flaky,
        "release_readiness": readiness,
        "knowledge_feedback": feedback,
        "project_state": state,
        "playbook": plan.get("playbook", {}),
        "learning_profile": plan.get("learning_profile", {}),
        "learning_applied_labs": plan.get("learning_applied_labs", []),
        "verification_budget_seconds": plan.get("verification_budget_seconds"),
        "budget_pressure": bool(plan.get("budget_pressure", False)),
    })
    return payload


def write_sidecars(report_dir: Path, payload: dict[str, Any]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "failure-intelligence.json": payload.get("failure_intelligence", {}),
        "flaky-detection.json": payload.get("flaky_detection", {}),
        "release-readiness.json": payload.get("release_readiness", {}),
        "project-state.json": payload.get("project_state", {}),
        "knowledge-feedback.json": payload.get("knowledge_feedback", {}),
    }
    for name, value in mapping.items():
        (report_dir / name).write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def self_test() -> None:
    plan = {
        "lane": "FAST_RUNTIME",
        "baseline_sha": "a" * 40,
        "head_sha": "b" * 40,
        "playbook": {"category": "ui_change", "recommended_playbook": "UI_REDESIGN_PLAYBOOK"},
        "learning_profile": {"sample_count": 8, "unstable_labs": ["network"]},
        "verification_budget_seconds": 900,
    }
    fail = {
        "applab_version": "1.0.0",
        "repository": "owner/app",
        "resolved_sha": "b" * 40,
        "result": "FAIL",
        "pipeline_status": "success",
        "network_lab": "FAIL",
        "visual_qa": "PASS",
    }
    enriched = enrich_result(fail, plan)
    assert enriched["failure_intelligence"]["kind"] == "FLAKY_SUSPECT"
    assert enriched["failure_intelligence"]["retryable"]
    assert enriched["flaky_detection"]["suspected"]
    assert enriched["release_readiness"]["status"] == "BLOCKED"

    passed = enrich_result(
        {
            "result": "PASS",
            "pipeline_status": "success",
            "visual_qa": "PASS",
            "runtime_executed": True,
            "certification_status": "CERTIFIED",
        },
        plan,
    )
    assert passed["release_readiness"]["status"] == "RELEASE_READY"
    assert passed["failure_intelligence"]["kind"] == "NONE"
    print("AppLab verification intelligence self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", default="")
    parser.add_argument("--plan", default="")
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.result or not args.plan:
        raise SystemExit("--result and --plan are required")
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    payload = enrich_result(result, plan)
    if args.report_dir:
        write_sidecars(Path(args.report_dir), payload)
    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
