#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

STUDIO_VERSION = "4.7.0"
TERMINAL_CERTIFIED_STATES = {"CERTIFIED"}
UNRESOLVED_STATES = {"FAIL", "BLOCKED", "NOT_VERIFIED", "ERROR", "NOT_CERTIFIED"}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _text(value).upper()


def _bounded_stage(row: dict[str, Any]) -> dict[str, Any]:
    evidence = [str(value) for value in _list(row.get("evidence"))[:6]]
    return {
        "key": _text(row.get("key")),
        "label": _text(row.get("label")),
        "state": _upper(row.get("state")) or "NOT_VERIFIED",
        "reason": _text(row.get("reason")),
        "evidence": evidence,
    }


def _blocker_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _upper(row.get("type") or row.get("state")),
        _text(row.get("gate") or row.get("key") or row.get("label")),
        _text(row.get("observed") or row.get("reason")),
    )


def project_summary(
    release_reality: dict[str, Any],
    evidence_graph: dict[str, Any] | None = None,
    longitudinal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = _dict(release_reality.get("source"))
    artifact = _dict(release_reality.get("artifact"))
    workflow = _dict(release_reality.get("workflow"))
    certification = _dict(release_reality.get("certification"))
    physical = _dict(release_reality.get("physical_evidence"))
    next_gate = _dict(release_reality.get("next_gate"))
    graph = _dict(evidence_graph)
    graph_summary = _dict(graph.get("summary"))
    graph_insights = _dict(graph.get("insights"))
    graph_freshness = _dict(graph_insights.get("freshness"))
    graph_recurring = _list(graph_insights.get("recurring_findings"))
    longitudinal_payload = _dict(longitudinal)
    longitudinal_summary = _dict(longitudinal_payload.get("summary"))
    regression_rows = _list(longitudinal_payload.get("regression_candidates"))

    levels = [
        _bounded_stage(row)
        for row in _list(release_reality.get("levels"))
        if isinstance(row, dict)
    ]
    unresolved = [
        _bounded_stage(row)
        for row in _list(release_reality.get("unresolved_stages"))
        if isinstance(row, dict)
        and _upper(row.get("state")) in UNRESOLVED_STATES
    ]

    blocker_rows: list[dict[str, Any]] = []
    for raw in _list(release_reality.get("certification_blockers")):
        if not isinstance(raw, dict):
            continue
        blocker_rows.append(
            {
                "type": _upper(raw.get("type")) or "BLOCKER",
                "gate": _text(raw.get("gate") or raw.get("key")),
                "label": _text(raw.get("label") or raw.get("gate") or raw.get("key")),
                "observed": _text(raw.get("observed") or raw.get("reason")),
            }
        )

    certification_status = _upper(certification.get("status")) or "NOT_VERIFIED"
    certified = bool(certification.get("certified")) or certification_status in TERMINAL_CERTIFIED_STATES

    why_not_certified: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for row in blocker_rows:
        key = _blocker_key(row)
        if key in seen:
            continue
        seen.add(key)
        why_not_certified.append(row)

    if not certified and next_gate:
        row = {
            "type": _upper(next_gate.get("state")) or "NOT_VERIFIED",
            "gate": _text(next_gate.get("key")),
            "label": _text(next_gate.get("label") or next_gate.get("key")),
            "observed": _text(next_gate.get("reason")),
        }
        key = _blocker_key(row)
        if key not in seen:
            seen.add(key)
            why_not_certified.append(row)

    for stage in unresolved:
        row = {
            "type": stage["state"],
            "gate": stage["key"],
            "label": stage["label"] or stage["key"],
            "observed": stage["reason"],
        }
        key = _blocker_key(row)
        if key in seen:
            continue
        seen.add(key)
        why_not_certified.append(row)

    required_capabilities = sorted(
        {
            _text(value)
            for value in _list(physical.get("required_capabilities"))
            if _text(value)
        }
    )

    invalidated_rows = _list(graph_freshness.get("invalidated"))
    stale_count = int(graph_summary.get("stale_or_historical_evidence", 0) or 0)
    invalidated_count = int(
        graph_summary.get(
            "invalidated_evidence",
            graph_freshness.get("invalidated_count", len(invalidated_rows)),
        )
        or 0
    )
    recurring_count = int(graph_summary.get("recurring_findings", len(graph_recurring)) or 0)
    regression_count = int(
        graph_summary.get(
            "regression_candidates",
            longitudinal_summary.get("regression_candidates", len(regression_rows)),
        )
        or 0
    )

    return {
        "studio_version": STUDIO_VERSION,
        "read_only": True,
        "release_id": _text(release_reality.get("release_id")),
        "current_level": _upper(release_reality.get("current_level")) or "NOT_VERIFIED",
        "highest_observed_pass": _upper(release_reality.get("highest_observed_pass")) or "NOT_VERIFIED",
        "certification_status": certification_status,
        "certified": certified,
        "identity_complete": bool(release_reality.get("identity_complete", False)),
        "source": {
            "repository": _text(source.get("repository")),
            "ref": _text(source.get("ref")),
            "resolved_sha": _text(source.get("resolved_sha")),
            "engine": _text(source.get("engine")),
        },
        "artifact": {
            "package_id": _text(artifact.get("package_id")),
            "version_name": _text(artifact.get("version_name")),
            "version_code": _text(artifact.get("version_code")),
            "build_variant": _text(artifact.get("build_variant")),
            "sha256": _text(artifact.get("sha256")),
            "signing_cert_sha256": _text(artifact.get("signing_cert_sha256")),
            "signing_identity_state": _upper(artifact.get("signing_identity_state")) or "NOT_VERIFIED",
            "same_bytes_verified": bool(artifact.get("same_bytes_verified", False)),
        },
        "runtime": {
            "workflow_run_id": _text(workflow.get("workflow_run_id")),
            "trusted_applab_sha": _text(workflow.get("trusted_applab_sha")),
            "analysis_mode": _text(workflow.get("analysis_mode")),
            "pipeline_status": _upper(workflow.get("pipeline_status")) or "UNKNOWN",
            "aggregate_result": _upper(workflow.get("aggregate_result")) or "UNKNOWN",
            "runtime_result": _upper(workflow.get("runtime_result")) or "UNKNOWN",
            "runtime_step_outcome": _upper(workflow.get("runtime_step_outcome")) or "UNKNOWN",
        },
        "physical": {
            "required": bool(required_capabilities),
            "required_capabilities": required_capabilities,
            "present": bool(physical.get("present", False)),
            "result": _upper(physical.get("result")) or "NOT_VERIFIED",
            "device": _dict(physical.get("device")),
            "scenario": _dict(physical.get("scenario")),
        },
        "freshness": {
            "stale_or_historical_evidence": stale_count,
            "invalidated_evidence": invalidated_count,
            "top_invalidated": [
                {
                    "evidence_id": _text(item.get("evidence_id")),
                    "label": _text(item.get("label")),
                    "invalidated_by_files": [
                        _text(value)
                        for value in _list(item.get("invalidated_by_files"))[:6]
                        if _text(value)
                    ],
                }
                for item in invalidated_rows[:6]
                if isinstance(item, dict)
            ],
        },
        "recurrence": {
            "recurring_findings": recurring_count,
            "regression_candidates": regression_count,
            "top_recurring": [
                {
                    "kind": _text(item.get("kind")),
                    "subject": _text(item.get("subject")),
                    "seen_count": int(item.get("seen_count", 0) or 0),
                }
                for item in graph_recurring[:6]
                if isinstance(item, dict)
            ],
            "top_regressions": [
                {
                    "source": _text(item.get("source")),
                    "kind": _text(item.get("kind")),
                    "subject": _text(item.get("subject")),
                    "reason": _text(item.get("reason")),
                }
                for item in regression_rows[:6]
                if isinstance(item, dict)
            ],
        },
        "levels": levels,
        "missing_evidence": unresolved[:12],
        "why_not_certified": why_not_certified[:12],
    }


def project_from_directory(
    project_dir: Path,
    evidence_graph: dict[str, Any] | None = None,
    longitudinal: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    path = project_dir / "release-reality.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return project_summary(payload, evidence_graph=evidence_graph, longitudinal=longitudinal)


def portfolio_summary(projects: list[dict[str, Any]]) -> dict[str, int]:
    cockpit_rows = [
        row["release_cockpit"]
        for row in projects
        if isinstance(row.get("release_cockpit"), dict)
    ]
    return {
        "with_release_reality": len(cockpit_rows),
        "certified_releases": sum(bool(row.get("certified", False)) for row in cockpit_rows),
        "certification_blocked": sum(
            row.get("certification_status") == "BLOCKED" for row in cockpit_rows
        ),
        "physical_required": sum(
            bool(_dict(row.get("physical")).get("required", False))
            for row in cockpit_rows
        ),
        "stale_release_evidence": sum(
            int(_dict(row.get("freshness")).get("stale_or_historical_evidence", 0) or 0)
            for row in cockpit_rows
        ),
    }


def self_test_release_reality() -> dict[str, Any]:
    return {
        "release_id": "release-1",
        "source": {"repository": "owner/demo", "ref": "main", "resolved_sha": "a" * 40, "engine": "flutter"},
        "artifact": {
            "package_id": "com.example.demo", "version_name": "1.2.3", "version_code": "12",
            "build_variant": "release", "sha256": "b" * 64, "signing_cert_sha256": "c" * 64,
            "signing_identity_state": "VERIFIED", "same_bytes_verified": True,
        },
        "workflow": {
            "workflow_run_id": "123", "trusted_applab_sha": "d" * 40,
            "analysis_mode": "certification", "pipeline_status": "SUCCESS",
            "aggregate_result": "BLOCKED", "runtime_result": "PASS", "runtime_step_outcome": "SUCCESS",
        },
        "identity_complete": True,
        "current_level": "TRUSTED_RUNTIME_VERIFIED",
        "highest_observed_pass": "TRUSTED_RUNTIME_VERIFIED",
        "levels": [
            {"key": "TRUSTED_RUNTIME_VERIFIED", "label": "Trusted runtime verified", "state": "PASS",
             "reason": "Trusted runtime evidence matches.", "evidence": ["trusted-evidence-manifest.json"]},
            {"key": "PHYSICAL_DEVICE_VERIFIED", "label": "Physical device verified", "state": "BLOCKED",
             "reason": "GPS requires a real device.", "evidence": ["physical-evidence.json"]},
        ],
        "next_gate": {"key": "PHYSICAL_DEVICE_VERIFIED", "label": "Physical device verified",
                      "state": "BLOCKED", "reason": "GPS requires a real device."},
        "unresolved_stages": [
            {"key": "PHYSICAL_DEVICE_VERIFIED", "label": "Physical device verified", "state": "BLOCKED",
             "reason": "GPS requires a real device.", "evidence": ["physical-evidence.json"]}
        ],
        "certification": {"attempted": True, "status": "BLOCKED", "certified": False},
        "certification_blockers": [
            {"type": "BLOCKER", "gate": "real_device", "label": "Required physical-device evidence",
             "observed": "NOT_TESTED"}
        ],
        "physical_evidence": {"present": False, "required_capabilities": ["gps"]},
    }


def self_test() -> None:
    reality = self_test_release_reality()
    graph = {
        "summary": {
            "stale_or_historical_evidence": 2, "invalidated_evidence": 1,
            "recurring_findings": 1, "regression_candidates": 1,
        },
        "insights": {
            "freshness": {
                "invalidated_count": 1,
                "invalidated": [{"evidence_id": "Evidence:1", "label": "lib/location.dart",
                                 "invalidated_by_files": ["lib/location.dart"]}],
            },
            "recurring_findings": [{"kind": "BACKGROUND_RESTART", "subject": "location", "seen_count": 3}],
        },
    }
    longitudinal = {
        "summary": {"regression_candidates": 1},
        "regression_candidates": [{"source": "runtime", "kind": "GPS_REGRESSION",
                                   "subject": "tracking", "reason": "Returned after previous resolution."}],
    }

    row = project_summary(reality, graph, longitudinal)
    assert row["read_only"] is True
    assert row["current_level"] == "TRUSTED_RUNTIME_VERIFIED"
    assert row["certification_status"] == "BLOCKED"
    assert row["artifact"]["same_bytes_verified"] is True
    assert row["source"]["resolved_sha"] == "a" * 40
    assert row["runtime"]["runtime_result"] == "PASS"
    assert row["physical"]["required_capabilities"] == ["gps"]
    assert row["freshness"]["invalidated_evidence"] == 1
    assert row["recurrence"]["recurring_findings"] == 1
    assert row["recurrence"]["regression_candidates"] == 1
    assert any(item["gate"] == "real_device" for item in row["why_not_certified"])
    assert any(item["gate"] == "PHYSICAL_DEVICE_VERIFIED" for item in row["why_not_certified"])
    assert row["missing_evidence"][0]["state"] == "BLOCKED"
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "release-reality.json").write_text(json.dumps(reality), encoding="utf-8")
        loaded = project_from_directory(root, graph, longitudinal)
        assert loaded is not None and loaded["release_id"] == "release-1"
    summary = portfolio_summary([{"release_cockpit": row}, {"release_cockpit": None}])
    assert summary["with_release_reality"] == 1
    assert summary["certification_blocked"] == 1
    assert summary["physical_required"] == 1
    assert summary["stale_release_evidence"] == 2
    print("AppLab v4.7 Certification Studio projection self-test PASS")


if __name__ == "__main__":
    self_test()
