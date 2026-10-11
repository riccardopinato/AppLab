#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
LAB_VERSION = "5.2.0"
RECORD_TYPE = "COMPETITIVE_PRODUCT_INTELLIGENCE"
AUTHORITY = "APPLAB_COMPETITIVE_PRODUCT_INTELLIGENCE_ADVISORY"
CLASSIFICATION = "COMPETITIVE PRODUCT INTELLIGENCE"
ALLOWED_STATES = {"READY", "EVIDENCE_INCOMPLETE", "STALE_EVIDENCE"}
ALLOWED_ROUTES = {"REVIEW", "CONSIDER", "PROTECT_DIFFERENTIATOR", "NO_ACTION"}

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
    artifact = next(
        (
            row for row in nodes
            if isinstance(row, dict)
            and clean(row.get("id")) == artifact_id
            and clean(row.get("type")) == "BuildArtifact"
        ),
        None,
    )
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
        raise ValueError("Evidence Graph repository identity is missing")
    if len(out["resolved_sha"]) != 40 or any(ch not in "0123456789abcdef" for ch in out["resolved_sha"]):
        raise ValueError("Evidence Graph resolved SHA is invalid")
    if not out["run_id"].isdigit():
        raise ValueError("Evidence Graph trusted workflow run identity is invalid")
    if not out["package_id"] or clean(attrs.get("package_id")) != out["package_id"]:
        raise ValueError("Evidence Graph package identity is inconsistent")
    if len(out["artifact_sha256"]) != 64 or any(ch not in "0123456789abcdef" for ch in out["artifact_sha256"]):
        raise ValueError("Evidence Graph artifact SHA-256 is invalid")
    if not out["version_name"] or not out["version_code"]:
        raise ValueError("Evidence Graph artifact version identity is incomplete")
    return out

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
    if clean(record.get("state")) not in ALLOWED_STATES:
        errors.append("state")

    guardrails = record.get("guardrails") if isinstance(record.get("guardrails"), dict) else {}
    for key in (
        "advisory_only",
        "no_release_verdict",
        "no_auto_feature_addition",
        "no_competitor_feature_copying",
        "parity_requires_product_contract_and_target_user_context",
        "source_traceability_required",
        "freshness_required",
        "trusted_verifier_does_not_scrape_web",
    ):
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
            expected = graph_identity(graph)
        except ValueError:
            errors.append("evidence_graph.identity")
        else:
            for key, expected_value in expected.items():
                if clean(identity.get(key)).lower() != expected_value.lower():
                    errors.append(f"identity.{key}")

    competitor_set = record.get("competitor_set") if isinstance(record.get("competitor_set"), dict) else {}
    if not clean(competitor_set.get("id")):
        errors.append("competitor_set.id")
    try:
        competitors = int(competitor_set.get("competitor_count", 0) or 0)
    except (TypeError, ValueError):
        competitors = -1
    if competitors < 0:
        errors.append("competitor_set.competitor_count")

    findings = record.get("findings")
    if not isinstance(findings, list):
        errors.append("findings")
    else:
        for row in findings:
            if not isinstance(row, dict) or clean(row.get("route")) not in ALLOWED_ROUTES:
                errors.append("findings.route")

    parity = record.get("relevant_parity_reviews")
    if not isinstance(parity, list):
        errors.append("relevant_parity_reviews")
    else:
        for row in parity:
            if not isinstance(row, dict) or clean(row.get("route")) not in ALLOWED_ROUTES:
                errors.append("relevant_parity_reviews.route")
            if isinstance(row, dict) and clean(row.get("state")) == "RELEVANT_PARITY_REVIEW":
                if clean(row.get("contract_status")) not in {"PROMISED", "FUTURE", "MENTION_ONLY", "CONTRADICTORY"}:
                    errors.append("relevant_parity_reviews.contract_status")

    return sorted(set(errors))

def fail_closed(errors: list[str]) -> dict[str, Any]:
    return {
        "state": "EVIDENCE_INCOMPLETE",
        "competitor_set_id": "UNKNOWN",
        "category": "UNSPECIFIED",
        "competitors": 0,
        "freshness": "EVIDENCE_INCOMPLETE",
        "target_user_context": "EVIDENCE_INCOMPLETE",
        "common_expectations": 0,
        "relevant_parity_reviews": 0,
        "differentiation_opportunities": 0,
        "market_weakness_opportunities": 0,
        "stale": False,
        "record_valid": False,
        "validation_errors": errors or ["record_missing_or_invalid"],
        "classification": CLASSIFICATION,
        "top_findings": [],
    }

def project_from_directory(project_dir: Path) -> dict[str, Any] | None:
    path = project_dir / "competitive-product-intelligence.json"
    if not path.is_file():
        return None
    record = read_json(path)
    graph = read_json(project_dir / "evidence-graph.json")
    if not record:
        return fail_closed(["record_json"])
    errors = validation_errors(record, graph)
    if errors:
        return fail_closed(errors)

    competitor_set = record.get("competitor_set") if isinstance(record.get("competitor_set"), dict) else {}
    target = record.get("target_user_context") if isinstance(record.get("target_user_context"), dict) else {}
    freshness = record.get("freshness") if isinstance(record.get("freshness"), dict) else {}
    summary = record.get("summary") if isinstance(record.get("summary"), dict) else {}
    findings = record.get("findings") if isinstance(record.get("findings"), list) else []
    return {
        "state": clean(record.get("state")) or "EVIDENCE_INCOMPLETE",
        "competitor_set_id": clean(competitor_set.get("id")) or "UNKNOWN",
        "category": clean(competitor_set.get("category")) or "UNSPECIFIED",
        "competitors": int(summary.get("competitors", competitor_set.get("competitor_count", 0)) or 0),
        "freshness": clean(freshness.get("state")) or "EVIDENCE_INCOMPLETE",
        "target_user_context": clean(target.get("state")) or "EVIDENCE_INCOMPLETE",
        "common_expectations": int(summary.get("common_expectations", 0) or 0),
        "relevant_parity_reviews": int(summary.get("relevant_parity_reviews", 0) or 0),
        "differentiation_opportunities": int(summary.get("differentiation_opportunities", 0) or 0),
        "market_weakness_opportunities": int(summary.get("market_weakness_opportunities", 0) or 0),
        "stale": bool(summary.get("stale", False)),
        "record_valid": True,
        "validation_errors": [],
        "classification": CLASSIFICATION,
        "top_findings": [
            {
                "kind": clean(row.get("kind")),
                "subject": clean(row.get("subject")),
                "route": clean(row.get("route")),
            }
            for row in findings[:6]
            if isinstance(row, dict)
        ],
    }

def portfolio_summary(projects: list[dict[str, Any]]) -> dict[str, int]:
    rows = [row.get("competitive_product") for row in projects if isinstance(row.get("competitive_product"), dict)]
    return {
        "with_competitive_product": len(rows),
        "competitive_ready": sum(1 for row in rows if row.get("state") == "READY"),
        "competitive_evidence_incomplete": sum(1 for row in rows if row.get("state") == "EVIDENCE_INCOMPLETE"),
        "competitive_stale": sum(1 for row in rows if row.get("state") == "STALE_EVIDENCE" or row.get("stale")),
        "competitive_parity_reviews": sum(int(row.get("relevant_parity_reviews", 0) or 0) for row in rows),
        "competitive_differentiators": sum(int(row.get("differentiation_opportunities", 0) or 0) for row in rows),
        "competitive_weakness_opportunities": sum(int(row.get("market_weakness_opportunities", 0) or 0) for row in rows),
    }

def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        graph = {
            "schema_version": 2,
            "graph_version": "2.0",
            "identity": {"repository": "owner/demo", "resolved_sha": "a"*40, "run_id": "123", "package_id": "com.example.demo"},
            "root_nodes": {"build_artifact": "artifact:demo"},
            "nodes": [{"id": "artifact:demo", "type": "BuildArtifact", "attributes": {"package_id": "com.example.demo", "apk_sha256": "b"*64, "version_name": "1.0", "version_code": "1"}}],
        }
        record = {
            "schema_version": 1,
            "lab_version": LAB_VERSION,
            "record_type": RECORD_TYPE,
            "authority": AUTHORITY,
            "classification": CLASSIFICATION,
            "generated_at": "2026-10-11T00:00:00+00:00",
            "identity": graph_identity(graph),
            "state": "READY",
            "competitor_set": {"id": "notes_core", "category": "notes", "competitor_count": 2, "competitors": [], "source_urls": []},
            "target_user_context": {"state": "DECLARED"},
            "freshness": {"state": "FRESH"},
            "comparison": {},
            "common_market_expectations": [],
            "relevant_parity_reviews": [{"key": "export", "state": "RELEVANT_PARITY_REVIEW", "route": "REVIEW", "contract_status": "PROMISED"}],
            "differentiation_opportunities": [],
            "market_weakness_opportunities": [],
            "findings": [{"kind": "RELEVANT_MARKET_PARITY_REVIEW", "subject": "export", "route": "REVIEW"}],
            "summary": {"competitors": 2, "common_expectations": 1, "relevant_parity_reviews": 1, "differentiation_opportunities": 0, "market_weakness_opportunities": 0, "stale": False},
            "guardrails": {
                "advisory_only": True,
                "no_release_verdict": True,
                "no_auto_feature_addition": True,
                "no_competitor_feature_copying": True,
                "parity_requires_product_contract_and_target_user_context": True,
                "source_traceability_required": True,
                "freshness_required": True,
                "trusted_verifier_does_not_scrape_web": True,
            },
            "record_digest_sha256": "",
        }
        record["record_digest_sha256"] = record_digest(record)
        (root / "evidence-graph.json").write_text(json.dumps(graph), encoding="utf-8")
        (root / "competitive-product-intelligence.json").write_text(json.dumps(record), encoding="utf-8")
        projected = project_from_directory(root)
        assert projected and projected["record_valid"] is True
        assert projected["relevant_parity_reviews"] == 1
        record["identity"]["package_id"] = "other.package"
        record["record_digest_sha256"] = record_digest(record)
        (root / "competitive-product-intelligence.json").write_text(json.dumps(record), encoding="utf-8")
        projected = project_from_directory(root)
        assert projected and projected["record_valid"] is False and projected["state"] == "EVIDENCE_INCOMPLETE"
    print("AppLab Studio Competitive Product v5.2 self-test PASS")

if __name__ == "__main__":
    self_test()
