#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
LAB_VERSION = "5.3.0"
RECORD_TYPE = "VIRTUAL_PRODUCT_REVIEW_COUNCIL"
AUTHORITY = "APPLAB_VIRTUAL_PRODUCT_REVIEW_COUNCIL_ADVISORY"
CLASSIFICATION = "VIRTUAL PRODUCT REVIEW COUNCIL"
REVIEWERS = ("QA", "UX", "ACCESSIBILITY", "PRODUCT", "DESIGN", "MARKET")
BUCKETS = ("FIX_NOW", "VERIFY_NEXT", "IMPROVE", "CONSIDER", "NO_ACTION")
STATES = {"REVIEW_REQUIRED", "EVIDENCE_INCOMPLETE", "NO_STRONG_SIGNAL"}

def clean(value: object) -> str:
    return str(value or "").strip()

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
    out = {
        "repository": clean(identity.get("repository")),
        "resolved_sha": clean(identity.get("resolved_sha")).lower(),
        "run_id": clean(identity.get("run_id")),
        "package_id": clean(identity.get("package_id")),
        "artifact_sha256": clean(attrs.get("apk_sha256")).lower(),
        "version_name": clean(attrs.get("version_name")),
        "version_code": clean(attrs.get("version_code")),
    }
    if not out["repository"] or "/" not in out["repository"]:
        raise ValueError("repository identity")
    if len(out["resolved_sha"]) != 40:
        raise ValueError("resolved SHA")
    if not out["run_id"].isdigit():
        raise ValueError("run id")
    if not out["package_id"] or clean(attrs.get("package_id")) != out["package_id"]:
        raise ValueError("package identity")
    if len(out["artifact_sha256"]) != 64:
        raise ValueError("artifact SHA")
    if not out["version_name"] or not out["version_code"]:
        raise ValueError("artifact version")
    return out

def validation_errors(record: dict[str, Any], graph: dict[str, Any] | None) -> list[str]:
    errors: list[str] = []
    expected = {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "record_type": RECORD_TYPE,
        "authority": AUTHORITY,
        "classification": CLASSIFICATION,
    }
    for key, value in expected.items():
        if record.get(key) != value:
            errors.append(key)
    if clean(record.get("state")) not in STATES:
        errors.append("state")
    digest = clean(record.get("record_digest_sha256")).lower()
    if len(digest) != 64 or digest != record_digest(record):
        errors.append("record_digest_sha256")

    if not graph:
        errors.append("evidence_graph")
    else:
        try:
            identity = graph_identity(graph)
        except ValueError:
            errors.append("evidence_graph.identity")
        else:
            raw = record.get("identity") if isinstance(record.get("identity"), dict) else {}
            for key, value in identity.items():
                if clean(raw.get(key)).lower() != value.lower():
                    errors.append(f"identity.{key}")

    reviewers = record.get("reviewers")
    if not isinstance(reviewers, list):
        errors.append("reviewers")
    else:
        names = [clean(row.get("reviewer")) for row in reviewers if isinstance(row, dict)]
        if names != list(REVIEWERS):
            errors.append("reviewers.canonical_set")
        for row in reviewers:
            if not isinstance(row, dict):
                errors.append("reviewers.shape")
                continue
            if not clean(row.get("scope")) or clean(row.get("uncertainty")) not in {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}:
                errors.append("reviewers.scope_uncertainty")

    brief = record.get("product_review_brief") if isinstance(record.get("product_review_brief"), dict) else {}
    buckets = brief.get("buckets") if isinstance(brief.get("buckets"), dict) else {}
    if tuple(brief.get("priority_order", [])) != BUCKETS or set(buckets) != set(BUCKETS):
        errors.append("product_review_brief.buckets")
    else:
        for bucket, rows in buckets.items():
            if not isinstance(rows, list):
                errors.append(f"product_review_brief.{bucket}")
                continue
            for row in rows:
                if not isinstance(row, dict) or clean(row.get("bucket")) != bucket:
                    errors.append(f"product_review_brief.{bucket}.row")
                if bucket == "FIX_NOW" and isinstance(row, dict) and clean(row.get("reviewer")) != "QA":
                    errors.append("product_review_brief.fix_now_authority")

    guardrails = record.get("guardrails") if isinstance(record.get("guardrails"), dict) else {}
    for key in (
        "advisory_only",
        "no_release_verdict",
        "no_numeric_consensus_score",
        "preserve_reviewer_scope_and_uncertainty",
        "fix_now_only_from_existing_technical_runtime_evidence",
        "simulated_users_are_not_real_users",
        "physical_device_validation_remains_separate",
        "release_certification_remains_separate",
        "council_does_not_replace_product_ownership",
        "missing_evidence_fails_closed",
    ):
        if guardrails.get(key) is not True:
            errors.append(f"guardrails.{key}")
    return sorted(set(errors))

def fail_closed(errors: list[str]) -> dict[str, Any]:
    return {
        "state": "EVIDENCE_INCOMPLETE",
        "reviewers": 0,
        "reviewers_with_findings": 0,
        "reviewers_with_missing_evidence": 6,
        "agreements": 0,
        "contradictions": 0,
        "fix_now": 0,
        "verify_next": 0,
        "improve": 0,
        "consider": 0,
        "no_action": 0,
        "record_valid": False,
        "validation_errors": errors or ["record_missing_or_invalid"],
        "classification": CLASSIFICATION,
        "top_items": [],
        "evidence_classes": {},
    }

def project_from_directory(project_dir: Path) -> dict[str, Any] | None:
    path = project_dir / "virtual-product-review-council.json"
    if not path.is_file():
        return None
    record = read_json(path)
    graph = read_json(project_dir / "evidence-graph.json")
    if not record:
        return fail_closed(["record_json"])
    errors = validation_errors(record, graph)
    if errors:
        return fail_closed(errors)

    summary = record.get("summary") if isinstance(record.get("summary"), dict) else {}
    brief = record.get("product_review_brief") if isinstance(record.get("product_review_brief"), dict) else {}
    buckets = brief.get("buckets") if isinstance(brief.get("buckets"), dict) else {}
    top_items = []
    for bucket in BUCKETS:
        for row in buckets.get(bucket, [])[:3]:
            if isinstance(row, dict):
                top_items.append({
                    "bucket": bucket,
                    "reviewer": clean(row.get("reviewer")),
                    "item_type": clean(row.get("item_type")),
                    "subject": clean(row.get("subject")),
                    "uncertainty": clean(row.get("uncertainty")),
                })
        if len(top_items) >= 8:
            break
    return {
        "state": clean(record.get("state")) or "EVIDENCE_INCOMPLETE",
        "reviewers": int(summary.get("reviewers", 0) or 0),
        "reviewers_with_findings": int(summary.get("reviewers_with_findings", 0) or 0),
        "reviewers_with_missing_evidence": int(summary.get("reviewers_with_missing_evidence", 0) or 0),
        "agreements": int(summary.get("agreements", 0) or 0),
        "contradictions": int(summary.get("contradictions", 0) or 0),
        "fix_now": int(summary.get("fix_now", 0) or 0),
        "verify_next": int(summary.get("verify_next", 0) or 0),
        "improve": int(summary.get("improve", 0) or 0),
        "consider": int(summary.get("consider", 0) or 0),
        "no_action": int(summary.get("no_action", 0) or 0),
        "record_valid": True,
        "validation_errors": [],
        "classification": CLASSIFICATION,
        "top_items": top_items,
        "evidence_classes": record.get("evidence_classes") if isinstance(record.get("evidence_classes"), dict) else {},
    }

def portfolio_summary(projects: list[dict[str, Any]]) -> dict[str, int]:
    rows = [row.get("review_council") for row in projects if isinstance(row.get("review_council"), dict)]
    return {
        "with_review_council": len(rows),
        "council_review_required": sum(1 for row in rows if row.get("state") == "REVIEW_REQUIRED"),
        "council_evidence_incomplete": sum(1 for row in rows if row.get("state") == "EVIDENCE_INCOMPLETE"),
        "council_no_strong_signal": sum(1 for row in rows if row.get("state") == "NO_STRONG_SIGNAL"),
        "council_fix_now": sum(int(row.get("fix_now", 0) or 0) for row in rows),
        "council_verify_next": sum(int(row.get("verify_next", 0) or 0) for row in rows),
        "council_improve": sum(int(row.get("improve", 0) or 0) for row in rows),
        "council_consider": sum(int(row.get("consider", 0) or 0) for row in rows),
        "council_contradictions": sum(int(row.get("contradictions", 0) or 0) for row in rows),
    }

def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        graph = {
            "schema_version": 2, "graph_version": "2.0",
            "identity": {"repository":"owner/demo","resolved_sha":"a"*40,"run_id":"123","package_id":"com.example.demo"},
            "root_nodes":{"build_artifact":"artifact:demo"},
            "nodes":[{"id":"artifact:demo","type":"BuildArtifact","attributes":{"package_id":"com.example.demo","apk_sha256":"b"*64,"version_name":"1.0","version_code":"1"}}],
        }
        identity = graph_identity(graph)
        reviewers = [{"reviewer": name, "scope": "scope", "source_records": {}, "missing_or_invalid_sources": [], "uncertainty": "MEDIUM", "findings": [], "summary": {}} for name in REVIEWERS]
        record = {
            "schema_version": 1, "lab_version": LAB_VERSION, "record_type": RECORD_TYPE,
            "authority": AUTHORITY, "classification": CLASSIFICATION,
            "generated_at": "2026-10-11T00:00:00+00:00", "identity": identity,
            "state": "REVIEW_REQUIRED", "reviewers": reviewers,
            "cross_review": {"agreements": [], "contradictions": [], "missing_evidence_reviewers": []},
            "product_review_brief": {"priority_order": list(BUCKETS), "buckets": {key: [] for key in BUCKETS}},
            "evidence_classes": {},
            "summary": {"reviewers":6,"reviewers_with_findings":0,"reviewers_with_missing_evidence":0,"agreements":0,"contradictions":0,"fix_now":0,"verify_next":0,"improve":0,"consider":0,"no_action":0},
            "guardrails": {
                "advisory_only": True, "no_release_verdict": True, "no_numeric_consensus_score": True,
                "preserve_reviewer_scope_and_uncertainty": True,
                "fix_now_only_from_existing_technical_runtime_evidence": True,
                "simulated_users_are_not_real_users": True,
                "physical_device_validation_remains_separate": True,
                "release_certification_remains_separate": True,
                "council_does_not_replace_product_ownership": True,
                "missing_evidence_fails_closed": True,
            },
            "record_digest_sha256": "",
        }
        record["record_digest_sha256"] = record_digest(record)
        (root/"evidence-graph.json").write_text(json.dumps(graph), encoding="utf-8")
        (root/"virtual-product-review-council.json").write_text(json.dumps(record), encoding="utf-8")
        projected = project_from_directory(root)
        assert projected and projected["record_valid"] is True and projected["reviewers"] == 6

        record["identity"]["package_id"] = "other.package"
        record["record_digest_sha256"] = record_digest(record)
        (root/"virtual-product-review-council.json").write_text(json.dumps(record), encoding="utf-8")
        projected = project_from_directory(root)
        assert projected and projected["record_valid"] is False and projected["state"] == "EVIDENCE_INCOMPLETE"
    print("AppLab Studio Virtual Product Review Council v5.3 self-test PASS")

if __name__ == "__main__":
    self_test()
