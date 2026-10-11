#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
LAB_VERSION = "5.1.0"
RECORD_TYPE = "DESIGN_SYSTEM_UI_LIBRARY_ADVISOR"
AUTHORITY = "APPLAB_DESIGN_SYSTEM_ADVISOR_ADVISORY"
CLASSIFICATION = "DESIGN SYSTEM ADVISORY"
ALLOWED_RECOMMENDATIONS = {"KEEP", "ADAPT", "REPLACE_CANDIDATE", "EVIDENCE_INCOMPLETE"}
ALLOWED_DIMENSION_STATES = {"FIT", "REVIEW", "EVIDENCE_INCOMPLETE", "NOT_APPLICABLE"}

def clean(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""

def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None

def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def digest_payload(record: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(record))
    clone.pop("generated_at", None)
    clone["record_digest_sha256"] = ""
    return clone

def record_digest(record: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(digest_payload(record))).hexdigest()

def graph_identity(graph: dict[str, Any]) -> dict[str, str]:
    if graph.get("schema_version") != 2 or clean(graph.get("graph_version")) != "2.0":
        raise ValueError("Evidence Graph schema/version is invalid")
    identity = graph.get("identity") if isinstance(graph.get("identity"), dict) else {}
    roots = graph.get("root_nodes") if isinstance(graph.get("root_nodes"), dict) else {}
    artifact_id = clean(roots.get("build_artifact"))
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    artifact = next((row for row in nodes if isinstance(row, dict) and clean(row.get("id")) == artifact_id and clean(row.get("type")) == "BuildArtifact"), None)
    if not artifact:
        raise ValueError("Evidence Graph canonical build artifact is missing")
    attrs = artifact.get("attributes") if isinstance(artifact.get("attributes"), dict) else {}
    return {
        "repository": clean(identity.get("repository")),
        "resolved_sha": clean(identity.get("resolved_sha")).lower(),
        "run_id": clean(identity.get("run_id")),
        "package_id": clean(identity.get("package_id")),
        "artifact_sha256": clean(attrs.get("apk_sha256")).lower(),
        "version_name": clean(attrs.get("version_name")),
        "version_code": clean(attrs.get("version_code")),
    }

def validation_errors(record: dict[str, Any], graph: dict[str, Any] | None) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version")
    if clean(record.get("lab_version")) != LAB_VERSION:
        errors.append("lab_version")
    if clean(record.get("record_type")) != RECORD_TYPE:
        errors.append("record_type")
    if clean(record.get("authority")) != AUTHORITY:
        errors.append("authority")
    if clean(record.get("classification")) != CLASSIFICATION:
        errors.append("classification")

    recommendation = record.get("recommendation")
    if not isinstance(recommendation, dict):
        errors.append("recommendation")
    else:
        if clean(recommendation.get("decision")) not in ALLOWED_RECOMMENDATIONS:
            errors.append("recommendation.decision")
        if recommendation.get("replacement_is_not_default") is not True:
            errors.append("recommendation.replacement_is_not_default")

    dimensions = record.get("dimensions")
    expected = {"hierarchy", "typography", "spacing", "density", "component_consistency", "feedback", "empty_loading_error_states", "interaction_affordances", "accessibility", "responsive", "dark_mode", "localization"}
    observed: set[str] = set()
    if not isinstance(dimensions, list) or not dimensions:
        errors.append("dimensions")
    else:
        for row in dimensions:
            if not isinstance(row, dict):
                errors.append("dimensions.row")
                continue
            identifier = clean(row.get("id"))
            observed.add(identifier)
            if clean(row.get("state")) not in ALLOWED_DIMENSION_STATES:
                errors.append(f"dimensions.{identifier}.state")
        if observed != expected:
            errors.append("dimensions.canonical_set")

    guardrails = record.get("guardrails") if isinstance(record.get("guardrails"), dict) else {}
    for key in ("advisory_only", "no_release_verdict", "cannot_override_fast_full_certification", "no_numeric_aesthetic_score", "no_automatic_library_replacement", "different_library_is_not_automatically_better", "recommendations_require_observed_evidence", "missing_evidence_fails_closed", "source_evidence_remains_authoritative"):
        if guardrails.get(key) is not True:
            errors.append(f"guardrails.{key}")

    digest = clean(record.get("record_digest_sha256")).lower()
    if len(digest) != 64 or digest != record_digest(record):
        errors.append("record_digest_sha256")

    identity = record.get("identity") if isinstance(record.get("identity"), dict) else {}
    if not graph:
        errors.append("evidence_graph")
    else:
        try:
            expected_identity = graph_identity(graph)
        except ValueError:
            errors.append("evidence_graph.identity")
        else:
            for key, expected_value in expected_identity.items():
                if clean(identity.get(key)).lower() != expected_value.lower():
                    errors.append(f"identity.{key}")

    findings = record.get("findings")
    if not isinstance(findings, list):
        errors.append("findings")
    else:
        for row in findings:
            if not isinstance(row, dict) or clean(row.get("route")) not in {"VERIFY_NEXT", "IMPROVE"}:
                errors.append("findings.route")
    return sorted(set(errors))

def fail_closed_projection(errors: list[str]) -> dict[str, Any]:
    return {
        "state": "EVIDENCE_INCOMPLETE",
        "recommendation": "EVIDENCE_INCOMPLETE",
        "product_context": "UNKNOWN",
        "interaction_style": "UNKNOWN",
        "primary_system": "UNKNOWN",
        "detected_systems": 0,
        "fit_dimensions": 0,
        "review_dimensions": 0,
        "evidence_incomplete_dimensions": 12,
        "finding_count": 0,
        "record_valid": False,
        "validation_errors": errors or ["record_missing_or_invalid"],
        "classification": CLASSIFICATION,
        "top_findings": [],
    }

def project_from_directory(project_dir: Path) -> dict[str, Any] | None:
    path = project_dir / "design-system-advisor.json"
    if not path.is_file():
        return None
    record = read_json(path)
    graph = read_json(project_dir / "evidence-graph.json")
    if not record:
        return fail_closed_projection(["record_json"])
    errors = validation_errors(record, graph)
    if errors:
        return fail_closed_projection(errors)

    context = record.get("product_context") if isinstance(record.get("product_context"), dict) else {}
    ui = record.get("ui_system") if isinstance(record.get("ui_system"), dict) else {}
    summary = record.get("summary") if isinstance(record.get("summary"), dict) else {}
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), dict) else {}
    findings = record.get("findings") if isinstance(record.get("findings"), list) else []
    decision = clean(recommendation.get("decision")) or "EVIDENCE_INCOMPLETE"
    return {
        "state": decision,
        "recommendation": decision,
        "product_context": clean(context.get("category")) or "UNKNOWN",
        "interaction_style": clean(context.get("interaction_style")) or "UNKNOWN",
        "primary_system": clean(ui.get("primary_detected")) or "UNKNOWN",
        "detected_systems": int(summary.get("detected_systems", 0) or 0),
        "fit_dimensions": int(summary.get("fit_dimensions", 0) or 0),
        "review_dimensions": int(summary.get("review_dimensions", 0) or 0),
        "evidence_incomplete_dimensions": int(summary.get("evidence_incomplete_dimensions", 0) or 0),
        "finding_count": int(summary.get("findings", 0) or 0),
        "record_valid": True,
        "validation_errors": [],
        "classification": CLASSIFICATION,
        "top_findings": [{"kind": clean(row.get("kind")), "subject": clean(row.get("subject")), "route": clean(row.get("route")), "state": clean(row.get("state"))} for row in findings[:6] if isinstance(row, dict)],
    }

def portfolio_summary(projects: list[dict[str, Any]]) -> dict[str, int]:
    rows = [row.get("design_advisor") for row in projects if isinstance(row.get("design_advisor"), dict)]
    return {
        "with_design_advisor": len(rows),
        "design_keep": sum(1 for row in rows if row.get("recommendation") == "KEEP"),
        "design_adapt": sum(1 for row in rows if row.get("recommendation") == "ADAPT"),
        "design_replace_candidate": sum(1 for row in rows if row.get("recommendation") == "REPLACE_CANDIDATE"),
        "design_evidence_incomplete": sum(1 for row in rows if row.get("recommendation") == "EVIDENCE_INCOMPLETE"),
    }

def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        graph = {"schema_version": 2, "graph_version": "2.0", "identity": {"repository": "owner/demo", "resolved_sha": "a"*40, "run_id": "123", "package_id": "com.example.demo"}, "root_nodes": {"build_artifact": "artifact:demo"}, "nodes": [{"id": "artifact:demo", "type": "BuildArtifact", "attributes": {"package_id": "com.example.demo", "apk_sha256": "b"*64, "version_name": "1.0", "version_code": "1"}}]}
        ids = ("hierarchy", "typography", "spacing", "density", "component_consistency", "feedback", "empty_loading_error_states", "interaction_affordances", "accessibility", "responsive", "dark_mode", "localization")
        record = {
            "schema_version": 1, "lab_version": LAB_VERSION, "record_type": RECORD_TYPE, "authority": AUTHORITY, "classification": CLASSIFICATION, "generated_at": "2026-10-11T00:00:00+00:00",
            "identity": graph_identity(graph),
            "product_context": {"category": "GENERAL_UTILITY", "interaction_style": "TASK_FOCUSED"},
            "ui_system": {"primary_detected": "FLUTTER_MATERIAL3"},
            "dimensions": [{"id": identifier, "state": "FIT", "rationale": "test", "evidence": []} for identifier in ids],
            "recommendation": {"decision": "KEEP", "rationale": "test", "replacement_is_not_default": True},
            "findings": [],
            "summary": {"detected_systems": 1, "fit_dimensions": 12, "review_dimensions": 0, "evidence_incomplete_dimensions": 0, "findings": 0},
            "guardrails": {"advisory_only": True, "no_release_verdict": True, "cannot_override_fast_full_certification": True, "no_numeric_aesthetic_score": True, "no_automatic_library_replacement": True, "different_library_is_not_automatically_better": True, "recommendations_require_observed_evidence": True, "missing_evidence_fails_closed": True, "source_evidence_remains_authoritative": True},
            "record_digest_sha256": "",
        }
        record["record_digest_sha256"] = record_digest(record)
        (root / "evidence-graph.json").write_text(json.dumps(graph), encoding="utf-8")
        (root / "design-system-advisor.json").write_text(json.dumps(record), encoding="utf-8")
        projected = project_from_directory(root)
        assert projected and projected["record_valid"] is True and projected["recommendation"] == "KEEP"
        record["identity"]["package_id"] = "other.package"
        record["record_digest_sha256"] = record_digest(record)
        (root / "design-system-advisor.json").write_text(json.dumps(record), encoding="utf-8")
        projected = project_from_directory(root)
        assert projected and projected["record_valid"] is False and projected["state"] == "EVIDENCE_INCOMPLETE"
    print("AppLab Studio Design Advisor self-test PASS")

if __name__ == "__main__":
    self_test()
