#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import simulated_human_qa as simulated


def _read(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _identity_match(
    project_dir: Path,
    payload: dict[str, Any],
) -> tuple[bool, list[str]]:
    graph = _read(project_dir / "evidence-graph.json")
    identity = payload.get("identity")
    if not isinstance(graph, dict) or not isinstance(identity, dict):
        return False, ["missing_identity_source"]
    try:
        expected = simulated.evidence_identity(graph)
    except ValueError:
        return False, ["invalid_evidence_graph_identity"]
    observed = {
        "repository": str(identity.get("repository", "")).strip(),
        "resolved_sha": str(identity.get("resolved_sha", "")).strip().lower(),
        "run_id": str(identity.get("run_id", "")).strip(),
        "package_id": str(identity.get("package_id", "")).strip(),
        "artifact_sha256": str(identity.get("artifact_sha256", "")).strip().lower(),
        "version_name": str(identity.get("version_name", "")).strip(),
        "version_code": str(identity.get("version_code", "")).strip(),
    }
    mismatches = [
        key
        for key, value in expected.items()
        if not value or observed.get(key) != value
    ]
    return not mismatches, mismatches


def _derived_state(
    personas: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> str:
    return simulated.advisory_state(personas, actions)


def _validated_record(
    project_dir: Path,
    payload: dict[str, Any],
) -> tuple[bool, list[str], list[dict[str, Any]], list[dict[str, Any]], str, list[str]]:
    errors: list[str] = []
    if payload.get("schema_version") != simulated.SCHEMA_VERSION:
        errors.append("schema_version")
    if str(payload.get("lab_version", "")).strip() != simulated.LAB_VERSION:
        errors.append("lab_version")
    if str(payload.get("record_type", "")).strip() != simulated.RECORD_TYPE:
        errors.append("record_type")
    if str(payload.get("authority", "")).strip() != simulated.AUTHORITY:
        errors.append("authority")
    if str(payload.get("classification", "")).strip() != simulated.CLASSIFICATION:
        errors.append("classification")

    personas_raw = payload.get("personas")
    personas = [row for row in personas_raw if isinstance(row, dict)] if isinstance(personas_raw, list) else []
    names = [str(row.get("persona", "")).strip() for row in personas]
    if (
        names != list(simulated.PERSONAS)
        or len(names) != len(set(names))
        or len(personas) != len(simulated.PERSONAS)
    ):
        errors.append("canonical_personas")

    for row in personas:
        if str(row.get("classification", "")).strip() != simulated.CLASSIFICATION:
            errors.append("persona_classification")
        tasks = row.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            errors.append("persona_tasks")
            continue
        for task in tasks:
            if not isinstance(task, dict):
                errors.append("task_structure")
                continue
            outcome = str(task.get("outcome", "")).strip().upper()
            if outcome not in simulated.ALLOWED_OUTCOMES:
                errors.append("task_outcome")
            walkthrough = task.get("cognitive_walkthrough")
            if not isinstance(walkthrough, list) or not walkthrough:
                errors.append("cognitive_walkthrough")

    actions_raw = payload.get("actions")
    actions = [row for row in actions_raw if isinstance(row, dict)] if isinstance(actions_raw, list) else []
    if not isinstance(actions_raw, list) or len(actions) != len(actions_raw):
        errors.append("actions")
    for row in actions:
        route = str(row.get("route", "")).strip().upper()
        if route not in simulated.ALLOWED_ROUTES or route == "FIX_NOW":
            errors.append("action_route")

    declared = str(payload.get("state", "")).strip().upper()
    derived = _derived_state(personas, actions) if personas else "EVIDENCE_INCOMPLETE"
    if declared not in simulated.ADVISORY_STATES:
        errors.append("state")
    elif declared != derived:
        errors.append("state_mismatch")

    guardrails = payload.get("guardrails")
    if not isinstance(guardrails, dict):
        errors.append("guardrails")
    else:
        required_guardrails = (
            "simulated_review_is_not_real_user_validation",
            "simulated_review_is_not_physical_device_evidence",
            "simulated_review_has_no_release_verdict",
            "simulated_review_cannot_override_technical_gates",
            "simulated_review_never_emits_fix_now",
            "source_evidence_remains_authoritative",
            "missing_evidence_does_not_become_user_failure",
            "no_numeric_persona_or_ux_score",
            "deterministic_core_no_llm_required",
        )
        if any(guardrails.get(key) is not True for key in required_guardrails):
            errors.append("guardrails")

    identity_match, identity_mismatches = _identity_match(project_dir, payload)
    if not identity_match:
        errors.append("evidence_identity")

    expected_digest = str(payload.get("record_digest_sha256", "")).strip().lower()
    try:
        actual_digest = simulated.report_digest(payload)
    except (KeyError, TypeError, ValueError):
        errors.append("record_digest_sha256")
    else:
        if expected_digest != actual_digest:
            errors.append("record_digest_sha256")

    return (
        not errors,
        sorted(set(errors)),
        personas,
        actions,
        derived,
        identity_mismatches,
    )


def _invalid_projection(
    *,
    validation_errors: list[str],
    identity_mismatches: list[str],
) -> dict[str, Any]:
    return {
        "state": "EVIDENCE_INCOMPLETE",
        "persona_count": 0,
        "task_count": 0,
        "friction_sessions": 0,
        "evidence_incomplete_sessions": 0,
        "consensus_findings": 0,
        "disagreements": 0,
        "verify_next": 0,
        "improve": 0,
        "top_findings": [],
        "identity_match": not identity_mismatches,
        "identity_mismatches": identity_mismatches,
        "record_valid": False,
        "validation_errors": validation_errors,
        "classification": simulated.CLASSIFICATION,
    }


def project_from_directory(project_dir: Path) -> dict[str, Any] | None:
    path = project_dir / "simulated-human-qa.json"
    if not path.is_file():
        return None
    payload = _read(path)
    if payload is None or not payload:
        return _invalid_projection(
            validation_errors=["unreadable_or_empty_record"],
            identity_mismatches=[],
        )

    valid, errors, personas, actions, derived, mismatches = _validated_record(
        project_dir,
        payload,
    )
    if not valid:
        return _invalid_projection(
            validation_errors=errors,
            identity_mismatches=mismatches,
        )

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    findings = (
        payload.get("consensus_findings")
        if isinstance(payload.get("consensus_findings"), list)
        else []
    )
    top_findings = [
        {
            "kind": str(row.get("kind", "")),
            "subject": str(row.get("subject", "")),
            "route": str(row.get("route", "")),
            "support_count": int(row.get("support_count", 0) or 0),
        }
        for row in findings[:8]
        if isinstance(row, dict)
    ]
    return {
        "state": derived,
        "persona_count": len(personas),
        "task_count": sum(len(row.get("tasks") or []) for row in personas),
        "friction_sessions": int(summary.get("friction_sessions", 0) or 0),
        "evidence_incomplete_sessions": int(summary.get("evidence_incomplete_sessions", 0) or 0),
        "consensus_findings": int(summary.get("consensus_findings", 0) or 0),
        "disagreements": int(summary.get("disagreements", 0) or 0),
        "verify_next": sum(1 for row in actions if row.get("route") == "VERIFY_NEXT"),
        "improve": sum(1 for row in actions if row.get("route") == "IMPROVE"),
        "top_findings": top_findings,
        "identity_match": True,
        "identity_mismatches": [],
        "record_valid": True,
        "validation_errors": [],
        "classification": simulated.CLASSIFICATION,
    }


def portfolio_summary(projects: list[dict[str, Any]]) -> dict[str, int]:
    rows = [
        row.get("simulated_human")
        for row in projects
        if isinstance(row.get("simulated_human"), dict)
    ]
    return {
        "with_simulated_human": len(rows),
        "simulated_review_required": sum(
            1 for row in rows if row.get("state") == "REVIEW_REQUIRED"
        ),
        "simulated_evidence_incomplete": sum(
            1 for row in rows if row.get("state") == "EVIDENCE_INCOMPLETE"
        ),
        "simulated_no_strong_signal": sum(
            1 for row in rows if row.get("state") == "NO_STRONG_SIGNAL"
        ),
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        identity = {
            "repository": "owner/demo",
            "resolved_sha": "a" * 40,
            "run_id": "123",
            "package_id": "com.example.demo",
            "artifact_sha256": "b" * 64,
            "version_name": "1.0.0",
            "version_code": "1",
        }
        (root / "evidence-graph.json").write_text(json.dumps({
            "schema_version": 2,
            "graph_version": "2.0",
            "identity": {
                "repository": identity["repository"],
                "resolved_sha": identity["resolved_sha"],
                "run_id": identity["run_id"],
                "package_id": identity["package_id"],
            },
            "root_nodes": {"build_artifact": "artifact:demo"},
            "nodes": [{
                "id": "artifact:demo",
                "type": "BuildArtifact",
                "attributes": {
                    "package_id": identity["package_id"],
                    "apk_sha256": identity["artifact_sha256"],
                    "version_name": identity["version_name"],
                    "version_code": identity["version_code"],
                },
            }],
        }), encoding="utf-8")
        personas = []
        for name in simulated.PERSONAS:
            personas.append({
                "persona": name,
                "classification": simulated.CLASSIFICATION,
                "focus": sorted(simulated.PERSONA_FOCUS[name]),
                "tasks": [{
                    "task_id": f"{name}_task",
                    "goal": "Bounded test task",
                    "outcome": "NO_STRONG_SIGNAL",
                    "rationale": "fixture",
                    "signal_ids": [],
                    "cognitive_walkthrough": [{
                        "criterion": "goal_discoverability",
                        "state": "EVIDENCE_AVAILABLE_NO_SIGNAL",
                        "signal_ids": [],
                    }],
                }],
                "summary": {
                    "friction_signals": 0,
                    "evidence_incomplete": 0,
                    "no_strong_signal": 1,
                    "not_applicable": 0,
                },
            })
        payload = {
            "schema_version": simulated.SCHEMA_VERSION,
            "lab_version": simulated.LAB_VERSION,
            "record_type": simulated.RECORD_TYPE,
            "authority": simulated.AUTHORITY,
            "classification": simulated.CLASSIFICATION,
            "generated_at": "2026-01-01T00:00:00+00:00",
            "identity": identity,
            "state": "NO_STRONG_SIGNAL",
            "personas": personas,
            "heuristic_review": [],
            "consensus_findings": [],
            "actions": [],
            "source_evidence": {},
            "summary": {
                "friction_sessions": 0,
                "evidence_incomplete_sessions": 0,
                "consensus_findings": 0,
                "disagreements": 0,
            },
            "guardrails": {
                "simulated_review_is_not_real_user_validation": True,
                "simulated_review_is_not_physical_device_evidence": True,
                "simulated_review_has_no_release_verdict": True,
                "simulated_review_cannot_override_technical_gates": True,
                "simulated_review_never_emits_fix_now": True,
                "source_evidence_remains_authoritative": True,
                "missing_evidence_does_not_become_user_failure": True,
                "no_numeric_persona_or_ux_score": True,
                "deterministic_core_no_llm_required": True,
            },
            "record_digest_sha256": "",
        }
        payload["record_digest_sha256"] = simulated.report_digest(payload)
        (root / "simulated-human-qa.json").write_text(json.dumps(payload), encoding="utf-8")

        projection = project_from_directory(root)
        assert projection is not None
        assert projection["record_valid"] is True
        assert projection["persona_count"] == 7
        assert projection["state"] == "NO_STRONG_SIGNAL"

        stale = json.loads(json.dumps(payload))
        stale["identity"]["resolved_sha"] = "b" * 40
        stale["record_digest_sha256"] = simulated.report_digest(stale)
        (root / "simulated-human-qa.json").write_text(json.dumps(stale), encoding="utf-8")
        blocked = project_from_directory(root)
        assert blocked is not None
        assert blocked["state"] == "EVIDENCE_INCOMPLETE"
        assert blocked["identity_match"] is False

        stale_artifact = json.loads(json.dumps(payload))
        stale_artifact["identity"]["artifact_sha256"] = "d" * 64
        stale_artifact["record_digest_sha256"] = simulated.report_digest(stale_artifact)
        (root / "simulated-human-qa.json").write_text(json.dumps(stale_artifact), encoding="utf-8")
        blocked = project_from_directory(root)
        assert blocked is not None
        assert blocked["identity_match"] is False
        assert "artifact_sha256" in blocked["identity_mismatches"]

        bad_route = json.loads(json.dumps(payload))
        bad_route["actions"] = [{"route": "FIX_NOW"}]
        bad_route["state"] = "REVIEW_REQUIRED"
        bad_route["record_digest_sha256"] = simulated.report_digest(bad_route)
        (root / "simulated-human-qa.json").write_text(json.dumps(bad_route), encoding="utf-8")
        blocked = project_from_directory(root)
        assert blocked is not None
        assert blocked["record_valid"] is False
        assert "action_route" in blocked["validation_errors"]

        (root / "simulated-human-qa.json").write_text("{broken", encoding="utf-8")
        blocked = project_from_directory(root)
        assert blocked is not None
        assert blocked["state"] == "EVIDENCE_INCOMPLETE"
        assert "unreadable_or_empty_record" in blocked["validation_errors"]

        summary = portfolio_summary([{"simulated_human": projection}])
        assert summary["with_simulated_human"] == 1
        assert summary["simulated_no_strong_signal"] == 1

    print("AppLab v5.0 Simulated Human Studio projection self-test PASS")


if __name__ == "__main__":
    self_test()
