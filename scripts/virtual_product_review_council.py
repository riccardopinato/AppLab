#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import competitive_product_intelligence as competitive

SCHEMA_VERSION = 1
LAB_VERSION = "5.3.0"
RECORD_TYPE = "VIRTUAL_PRODUCT_REVIEW_COUNCIL"
AUTHORITY = "APPLAB_VIRTUAL_PRODUCT_REVIEW_COUNCIL_ADVISORY"
CLASSIFICATION = "VIRTUAL PRODUCT REVIEW COUNCIL"

REVIEWERS = ("QA", "UX", "ACCESSIBILITY", "PRODUCT", "DESIGN", "MARKET")
BUCKETS = ("FIX_NOW", "VERIFY_NEXT", "IMPROVE", "CONSIDER", "NO_ACTION")
ITEM_TYPES = {
    "TECHNICAL_DEFECT",
    "USABILITY_RISK",
    "ACCESSIBILITY_RISK",
    "PRODUCT_RISK",
    "DESIGN_FIT_QUESTION",
    "PRODUCT_OPPORTUNITY",
    "MARKET_OPPORTUNITY",
    "EVIDENCE_GAP",
}
UNCERTAINTY = {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}

SCOPES = {
    "QA": "Technical correctness, trusted runtime evidence, contradictions and release-assurance blockers.",
    "UX": "Observed/simulated usability friction, discoverability and journey risks without claiming real-user validation.",
    "ACCESSIBILITY": "Accessibility-specific UI evidence and missing semantic/accessibility coverage.",
    "PRODUCT": "Product-contract consistency, bounded product risks and product opportunities.",
    "DESIGN": "Design-system fit, component consistency and visual-system adaptation questions.",
    "MARKET": "Source-traceable competitive parity, differentiation and recurring market weakness opportunities.",
}

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

def evidence_identity(graph: dict[str, Any]) -> dict[str, str]:
    return competitive.evidence_identity(graph)

def norm_subject(value: object) -> str:
    text = clean(value).casefold()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "general"

def evidence_paths(value: object) -> list[str]:
    if isinstance(value, list):
        return sorted({clean(x) for x in value if clean(x)})[:12]
    if clean(value):
        return [clean(value)]
    return []

def identity_matches(record: dict[str, Any], identity: dict[str, str]) -> bool:
    raw = record.get("identity") if isinstance(record.get("identity"), dict) else {}
    if not raw:
        return True
    aliases = {
        "repository": "repository",
        "resolved_sha": "resolved_sha",
        "run_id": "run_id",
        "package_id": "package_id",
        "artifact_sha256": "artifact_sha256",
        "version_name": "version_name",
        "version_code": "version_code",
    }
    for source_key, identity_key in aliases.items():
        actual = clean(raw.get(source_key)).lower()
        expected = clean(identity.get(identity_key)).lower()
        if actual and actual != expected:
            return False
    return True

def item(
    reviewer: str,
    bucket: str,
    item_type: str,
    subject: object,
    message: object,
    source: str,
    evidence: object,
    uncertainty: str,
    basis: str,
) -> dict[str, Any]:
    if reviewer not in REVIEWERS:
        raise ValueError(f"invalid reviewer: {reviewer}")
    if bucket not in BUCKETS:
        raise ValueError(f"invalid bucket: {bucket}")
    if item_type not in ITEM_TYPES:
        raise ValueError(f"invalid item type: {item_type}")
    if uncertainty not in UNCERTAINTY:
        raise ValueError(f"invalid uncertainty: {uncertainty}")
    return {
        "reviewer": reviewer,
        "bucket": bucket,
        "item_type": item_type,
        "subject": clean(subject) or "general",
        "message": clean(message),
        "source": source,
        "evidence": evidence_paths(evidence),
        "uncertainty": uncertainty,
        "basis": basis,
    }

def source_state(path: Path, identity: dict[str, str]) -> tuple[dict[str, Any] | None, str]:
    payload = read_json(path)
    if payload is None:
        return None, "MISSING"
    return payload, "AVAILABLE" if identity_matches(payload, identity) else "IDENTITY_MISMATCH"

def qa_review(root: Path, identity: dict[str, str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    sources: dict[str, str] = {}
    brief, sources["decision-brief.json"] = source_state(root / "decision-brief.json", identity)
    confidence, sources["evidence-confidence.json"] = source_state(root / "evidence-confidence.json", identity)
    assurance, sources["release-assurance.json"] = source_state(root / "release-assurance.json", identity)

    if brief and sources["decision-brief.json"] == "AVAILABLE":
        buckets = brief.get("buckets") if isinstance(brief.get("buckets"), dict) else {}
        for bucket in ("FIX_NOW", "VERIFY_NEXT", "NO_ACTION"):
            for row in buckets.get(bucket, []):
                if not isinstance(row, dict):
                    continue
                mapped_type = "TECHNICAL_DEFECT" if bucket == "FIX_NOW" else "PRODUCT_RISK"
                rows.append(item(
                    "QA", bucket, mapped_type, row.get("subject") or row.get("kind"),
                    row.get("message"), "decision-brief.json", row.get("evidence"),
                    "LOW" if bucket == "FIX_NOW" else "MEDIUM", clean(row.get("basis")) or "DECISION_BRIEF",
                ))
    if confidence and sources["evidence-confidence.json"] == "AVAILABLE":
        for row in confidence.get("contradictions", []):
            if not isinstance(row, dict):
                continue
            rows.append(item(
                "QA", "VERIFY_NEXT", "TECHNICAL_DEFECT", row.get("subject") or row.get("kind"),
                row.get("message") or "Evidence sources contradict each other.",
                "evidence-confidence.json", row.get("evidence"), "MEDIUM", "EVIDENCE_CONTRADICTION",
            ))
    if assurance and sources["release-assurance.json"] == "AVAILABLE":
        for row in assurance.get("failures", []):
            if isinstance(row, dict):
                rows.append(item(
                    "QA", "VERIFY_NEXT", "EVIDENCE_GAP", row.get("key") or "release_assurance",
                    row.get("message") or "Required release-assurance stage failed; keep the release authority separate and investigate the failed stage.",
                    "release-assurance.json", row.get("evidence"), "LOW", "RELEASE_ASSURANCE_FAILURE",
                ))
        for row in assurance.get("blockers", []):
            if isinstance(row, dict):
                rows.append(item(
                    "QA", "VERIFY_NEXT", "EVIDENCE_GAP", row.get("key") or "release_assurance",
                    row.get("message") or "Required release-assurance stage is blocked or not verified.",
                    "release-assurance.json", row.get("evidence"), "MEDIUM", "RELEASE_ASSURANCE_BLOCKER",
                ))
    return reviewer_record("QA", sources, rows)

def ux_review(root: Path, identity: dict[str, str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    sources: dict[str, str] = {}
    simulated, sources["simulated-human-qa.json"] = source_state(root / "simulated-human-qa.json", identity)
    friction, sources["ux-friction.json"] = source_state(root / "ux-friction.json", identity)

    if simulated and sources["simulated-human-qa.json"] == "AVAILABLE":
        for row in simulated.get("actions", []):
            if not isinstance(row, dict):
                continue
            route = clean(row.get("route")).upper()
            bucket = route if route in {"VERIFY_NEXT", "IMPROVE"} else "IMPROVE"
            rows.append(item(
                "UX", bucket, "USABILITY_RISK", row.get("subject") or row.get("kind"),
                row.get("message"), "simulated-human-qa.json", row.get("evidence"),
                "HIGH", "SIMULATED_USER_REVIEW",
            ))
    if friction and sources["ux-friction.json"] == "AVAILABLE":
        for row in friction.get("findings", []):
            if not isinstance(row, dict):
                continue
            severity = clean(row.get("severity")).upper()
            rows.append(item(
                "UX", "VERIFY_NEXT" if severity in {"HIGH_REVIEW", "REVIEW"} else "IMPROVE",
                "USABILITY_RISK", row.get("subject") or row.get("kind"), row.get("message"),
                "ux-friction.json", row.get("evidence"), "MEDIUM",
                "RUNTIME_UX_REVIEW" if evidence_paths(row.get("evidence")) else "UX_REVIEW_CANDIDATE",
            ))
    return reviewer_record("UX", sources, rows)

def accessibility_review(root: Path, identity: dict[str, str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    sources: dict[str, str] = {}
    design, sources["design-system-advisor.json"] = source_state(root / "design-system-advisor.json", identity)
    if design and sources["design-system-advisor.json"] == "AVAILABLE":
        dimensions = design.get("dimensions") if isinstance(design.get("dimensions"), list) else []
        access = next((row for row in dimensions if isinstance(row, dict) and clean(row.get("id")) == "accessibility"), None)
        if access:
            state = clean(access.get("state")).upper()
            if state == "REVIEW":
                rows.append(item(
                    "ACCESSIBILITY", "IMPROVE", "ACCESSIBILITY_RISK", "accessibility",
                    access.get("rationale"), "design-system-advisor.json", access.get("evidence"),
                    "MEDIUM", "DESIGN_ACCESSIBILITY_REVIEW",
                ))
            elif state == "EVIDENCE_INCOMPLETE":
                rows.append(item(
                    "ACCESSIBILITY", "VERIFY_NEXT", "EVIDENCE_GAP", "accessibility",
                    access.get("rationale"), "design-system-advisor.json", access.get("evidence"),
                    "HIGH", "ACCESSIBILITY_EVIDENCE_INCOMPLETE",
                ))
            elif state == "FIT":
                rows.append(item(
                    "ACCESSIBILITY", "NO_ACTION", "ACCESSIBILITY_RISK", "accessibility",
                    access.get("rationale"), "design-system-advisor.json", access.get("evidence"),
                    "MEDIUM", "BOUNDED_ACCESSIBILITY_FIT_SIGNAL",
                ))
    return reviewer_record("ACCESSIBILITY", sources, rows)

def product_review(root: Path, identity: dict[str, str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    sources: dict[str, str] = {}
    contract, sources["product-contract-audit.json"] = source_state(root / "product-contract-audit.json", identity)
    brief, sources["decision-brief.json"] = source_state(root / "decision-brief.json", identity)
    if contract and sources["product-contract-audit.json"] == "AVAILABLE":
        for row in contract.get("findings", []):
            if not isinstance(row, dict):
                continue
            severity = clean(row.get("severity")).upper()
            rows.append(item(
                "PRODUCT", "VERIFY_NEXT" if severity in {"HIGH_REVIEW", "REVIEW"} else "IMPROVE",
                "PRODUCT_RISK", row.get("capability") or row.get("kind"), row.get("message"),
                "product-contract-audit.json", row.get("evidence"),
                "MEDIUM", "PRODUCT_CONTRACT",
            ))
    if brief and sources["decision-brief.json"] == "AVAILABLE":
        buckets = brief.get("buckets") if isinstance(brief.get("buckets"), dict) else {}
        for row in buckets.get("IMPROVE", []):
            if not isinstance(row, dict):
                continue
            rows.append(item(
                "PRODUCT", "IMPROVE", "PRODUCT_OPPORTUNITY", row.get("subject") or row.get("kind"),
                row.get("message"), "decision-brief.json", row.get("evidence"), "MEDIUM",
                clean(row.get("basis")) or "DECISION_BRIEF",
            ))
    return reviewer_record("PRODUCT", sources, rows)

def design_review(root: Path, identity: dict[str, str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    sources: dict[str, str] = {}
    design, sources["design-system-advisor.json"] = source_state(root / "design-system-advisor.json", identity)
    if design and sources["design-system-advisor.json"] == "AVAILABLE":
        rec = design.get("recommendation") if isinstance(design.get("recommendation"), dict) else {}
        decision = clean(rec.get("decision")).upper()
        mapping = {
            "KEEP": ("NO_ACTION", "MEDIUM"),
            "ADAPT": ("IMPROVE", "MEDIUM"),
            "REPLACE_CANDIDATE": ("CONSIDER", "HIGH"),
            "EVIDENCE_INCOMPLETE": ("VERIFY_NEXT", "HIGH"),
        }
        if decision in mapping:
            bucket, uncertainty = mapping[decision]
            rows.append(item(
                "DESIGN", bucket, "DESIGN_FIT_QUESTION", "design_system",
                rec.get("rationale"), "design-system-advisor.json", [],
                uncertainty, f"DESIGN_RECOMMENDATION_{decision}",
            ))
        for row in design.get("findings", []):
            if not isinstance(row, dict) or clean(row.get("subject")) == "accessibility":
                continue
            route = clean(row.get("route")).upper()
            bucket = "VERIFY_NEXT" if route == "VERIFY_NEXT" else "IMPROVE"
            rows.append(item(
                "DESIGN", bucket, "DESIGN_FIT_QUESTION", row.get("subject") or row.get("kind"),
                row.get("message"), "design-system-advisor.json", row.get("evidence"),
                "MEDIUM" if bucket == "IMPROVE" else "HIGH", clean(row.get("kind")) or "DESIGN_REVIEW",
            ))
    return reviewer_record("DESIGN", sources, rows)

def market_review(root: Path, identity: dict[str, str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    sources: dict[str, str] = {}
    market, sources["competitive-product-intelligence.json"] = source_state(root / "competitive-product-intelligence.json", identity)
    if market and sources["competitive-product-intelligence.json"] == "AVAILABLE":
        state = clean(market.get("state")).upper()
        if state in {"EVIDENCE_INCOMPLETE", "STALE_EVIDENCE"}:
            rows.append(item(
                "MARKET", "VERIFY_NEXT", "EVIDENCE_GAP", "market_evidence",
                f"Competitive product evidence state is {state}.",
                "competitive-product-intelligence.json", [], "HIGH", state,
            ))
        for row in market.get("findings", []):
            if not isinstance(row, dict):
                continue
            kind = clean(row.get("kind"))
            if kind == "MARKET_EVIDENCE_FRESHNESS_REVIEW":
                bucket, item_type = "VERIFY_NEXT", "EVIDENCE_GAP"
            else:
                bucket, item_type = "CONSIDER", "MARKET_OPPORTUNITY"
            rows.append(item(
                "MARKET", bucket, item_type, row.get("subject") or kind,
                row.get("message"), "competitive-product-intelligence.json", row.get("evidence"),
                "HIGH" if bucket == "CONSIDER" else "MEDIUM", kind or "MARKET_REVIEW",
            ))
        for row in market.get("differentiation_opportunities", []):
            if isinstance(row, dict):
                rows.append(item(
                    "MARKET", "CONSIDER", "PRODUCT_OPPORTUNITY", row.get("key"),
                    "Protect and validate this bounded project differentiator before commoditizing it.",
                    "competitive-product-intelligence.json", row.get("source_urls"),
                    "HIGH", "PROTECT_DIFFERENTIATOR",
                ))
    return reviewer_record("MARKET", sources, rows)

def reviewer_record(name: str, sources: dict[str, str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    dedup: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["bucket"], row["item_type"], norm_subject(row["subject"]), row["message"])
        dedup[key] = row
    findings = list(dedup.values())[:40]
    missing = sorted(key for key, state in sources.items() if state != "AVAILABLE")
    uncertainty = "HIGH" if not findings or missing else ("MEDIUM" if any(row["uncertainty"] in {"MEDIUM", "HIGH"} for row in findings) else "LOW")
    return {
        "reviewer": name,
        "scope": SCOPES[name],
        "source_records": sources,
        "missing_or_invalid_sources": missing,
        "uncertainty": uncertainty,
        "findings": findings,
        "summary": dict(Counter(row["bucket"] for row in findings)),
    }

def cross_review(reviewers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for reviewer in reviewers:
        for row in reviewer["findings"]:
            by_subject[norm_subject(row["subject"])].append(row)

    agreements: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    action = {"FIX_NOW", "VERIFY_NEXT", "IMPROVE", "CONSIDER"}
    for subject, rows in sorted(by_subject.items()):
        reviewer_ids = sorted({row["reviewer"] for row in rows})
        if len(reviewer_ids) < 2:
            continue
        actionable = [row for row in rows if row["bucket"] in action]
        no_action = [row for row in rows if row["bucket"] == "NO_ACTION"]
        if actionable and no_action:
            contradictions.append({
                "subject_key": subject,
                "reviewers": reviewer_ids,
                "kind": "CROSS_REVIEW_ACTION_CONTRADICTION",
                "positions": [{"reviewer": row["reviewer"], "bucket": row["bucket"], "basis": row["basis"]} for row in rows],
                "evidence": sorted({ev for row in rows for ev in row["evidence"]})[:16],
            })
        elif len({row["reviewer"] for row in actionable}) >= 2:
            agreements.append({
                "subject_key": subject,
                "reviewers": sorted({row["reviewer"] for row in actionable}),
                "kind": "CROSS_REVIEW_AGREEMENT",
                "buckets": sorted({row["bucket"] for row in actionable}),
                "evidence": sorted({ev for row in actionable for ev in row["evidence"]})[:16],
            })
    return agreements, contradictions

def prioritized_brief(reviewers: list[dict[str, Any]], contradictions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {key: [] for key in BUCKETS}
    seen: set[tuple[str, str, str, str]] = set()
    contradicted = {row["subject_key"] for row in contradictions}
    for reviewer in reviewers:
        for row in reviewer["findings"]:
            bucket = row["bucket"]
            if bucket == "FIX_NOW" and reviewer["reviewer"] != "QA":
                bucket = "VERIFY_NEXT"
            if norm_subject(row["subject"]) in contradicted and bucket in {"FIX_NOW", "IMPROVE", "CONSIDER"}:
                bucket = "VERIFY_NEXT"
            key = (bucket, row["item_type"], norm_subject(row["subject"]), row["message"])
            if key in seen:
                continue
            seen.add(key)
            buckets[bucket].append({**row, "bucket": bucket})
    limits = {"FIX_NOW": 10, "VERIFY_NEXT": 16, "IMPROVE": 12, "CONSIDER": 12, "NO_ACTION": 10}
    return {key: buckets[key][:limits[key]] for key in BUCKETS}

def evidence_classes(root: Path) -> dict[str, Any]:
    physical = read_json(root / "physical-evidence.json")
    release = read_json(root / "release-reality.json")
    certification = read_json(root / "certification.json")
    return {
        "real_user_validation": {
            "class": "REAL_USER_VALIDATION",
            "state": "NOT_PROVIDED",
            "note": "Simulated Human QA is not real-user validation.",
        },
        "physical_device_validation": {
            "class": "PHYSICAL_DEVICE_VALIDATION",
            "state": clean((physical or {}).get("state") or (physical or {}).get("status")) or "NOT_PROVIDED",
            "source": "physical-evidence.json" if physical else "",
        },
        "release_certification": {
            "class": "RELEASE_CERTIFICATION",
            "state": clean((certification or {}).get("status") or (release or {}).get("certification_status")) or "NOT_VERIFIED",
            "source": "certification.json" if certification else ("release-reality.json" if release else ""),
        },
    }

def build_report(evidence_dir: Path) -> dict[str, Any]:
    graph = read_json(evidence_dir / "evidence-graph.json")
    if not graph:
        raise ValueError("evidence-graph.json is required for Virtual Product Review Council")
    identity = evidence_identity(graph)
    reviewers = [
        qa_review(evidence_dir, identity),
        ux_review(evidence_dir, identity),
        accessibility_review(evidence_dir, identity),
        product_review(evidence_dir, identity),
        design_review(evidence_dir, identity),
        market_review(evidence_dir, identity),
    ]
    agreements, contradictions = cross_review(reviewers)
    brief = prioritized_brief(reviewers, contradictions)
    missing_reviewers = [row["reviewer"] for row in reviewers if not row["findings"] and row["missing_or_invalid_sources"]]
    actionable = any(brief[key] for key in ("FIX_NOW", "VERIFY_NEXT", "IMPROVE", "CONSIDER"))
    if actionable:
        state = "REVIEW_REQUIRED"
    elif missing_reviewers:
        state = "EVIDENCE_INCOMPLETE"
    else:
        state = "NO_STRONG_SIGNAL"
    summary = {
        "reviewers": len(reviewers),
        "reviewers_with_findings": sum(bool(row["findings"]) for row in reviewers),
        "reviewers_with_missing_evidence": sum(bool(row["missing_or_invalid_sources"]) for row in reviewers),
        "agreements": len(agreements),
        "contradictions": len(contradictions),
        **{key.lower(): len(brief[key]) for key in BUCKETS},
    }
    record = {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "record_type": RECORD_TYPE,
        "authority": AUTHORITY,
        "classification": CLASSIFICATION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "state": state,
        "reviewers": reviewers,
        "cross_review": {
            "agreements": agreements,
            "contradictions": contradictions,
            "missing_evidence_reviewers": missing_reviewers,
        },
        "product_review_brief": {
            "priority_order": list(BUCKETS),
            "buckets": brief,
        },
        "evidence_classes": evidence_classes(evidence_dir),
        "summary": summary,
        "guardrails": {
            "advisory_only": True,
            "no_release_verdict": True,
            "no_numeric_consensus_score": True,
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
    return record

def markdown(record: dict[str, Any]) -> str:
    s = record["summary"]
    lines = [
        "# AppLab v5.3 — Virtual Product Review Council", "",
        f"- Classification: **{CLASSIFICATION}**",
        f"- State: **{record['state']}**",
        f"- Project: **{record['identity']['repository']}@{record['identity']['resolved_sha']}**",
        f"- Reviewers: **{s['reviewers']}** · with findings **{s['reviewers_with_findings']}**",
        f"- Cross-review agreements: **{s['agreements']}**",
        f"- Cross-review contradictions: **{s['contradictions']}**", "",
        "## Reviewer table", "",
        "| Reviewer | Uncertainty | Findings | Missing/invalid sources |",
        "|---|---|---:|---:|",
    ]
    lines.extend(
        f"| {row['reviewer']} | {row['uncertainty']} | {len(row['findings'])} | {len(row['missing_or_invalid_sources'])} |"
        for row in record["reviewers"]
    )
    for bucket in BUCKETS:
        lines.extend(["", f"## {bucket}", ""])
        rows = record["product_review_brief"]["buckets"][bucket]
        lines.extend(
            f"- **{row['reviewer']} / {row['item_type']} / {row['subject']}** — {row['message']} [{row['basis']}]"
            for row in rows
        )
        if not rows:
            lines.append("- None.")
    lines.extend(["", "## Authority separation", ""])
    for key, row in record["evidence_classes"].items():
        lines.append(f"- **{key}** — {row['state']}")
    lines.extend([
        "",
        "- The Council reduces manual triage; it does not replace final product ownership.",
        "- Simulated users remain separate from real-user validation.",
        "- Physical-device evidence and release certification remain independent authorities.",
        "- Advisory design/market/product evidence cannot create a technical FIX_NOW item.",
        "",
    ])
    return "\n".join(lines)

def write_report(output_dir: Path, record: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "virtual-product-review-council.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "virtual-product-review-council.md").write_text(markdown(record), encoding="utf-8")

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
        (root / "evidence-graph.json").write_text(json.dumps(graph), encoding="utf-8")
        (root / "decision-brief.json").write_text(json.dumps({
            "buckets": {
                "FIX_NOW": [{"kind":"CRASH","subject":"save","message":"Save crashes","evidence":["runtime.json"],"basis":"RUNTIME_CONFIRMED"}],
                "VERIFY_NEXT": [], "IMPROVE": [], "NO_ACTION": []
            }
        }), encoding="utf-8")
        (root / "evidence-confidence.json").write_text(json.dumps({"contradictions":[]}), encoding="utf-8")
        (root / "release-assurance.json").write_text(json.dumps({"identity": evidence_identity(graph), "failures":[], "blockers":[]}), encoding="utf-8")
        (root / "ux-friction.json").write_text(json.dumps({"findings":[{"kind":"DISCOVERABILITY","severity":"REVIEW","subject":"save","message":"Save is hard to find","evidence":["journey.json"]}]}), encoding="utf-8")
        (root / "simulated-human-qa.json").write_text(json.dumps({"identity": evidence_identity(graph), "actions":[]}), encoding="utf-8")
        (root / "design-system-advisor.json").write_text(json.dumps({
            "identity": evidence_identity(graph),
            "dimensions":[{"id":"accessibility","state":"REVIEW","rationale":"Semantics incomplete","evidence":["ui.dart"]}],
            "recommendation":{"decision":"ADAPT","rationale":"Targeted adaptation."},
            "findings":[],
        }), encoding="utf-8")
        (root / "product-contract-audit.json").write_text(json.dumps({"findings":[]}), encoding="utf-8")
        (root / "competitive-product-intelligence.json").write_text(json.dumps({
            "identity": evidence_identity(graph), "state":"READY", "findings":[],
            "differentiation_opportunities":[{"key":"offline","source_urls":["https://example.com"]}],
        }), encoding="utf-8")

        report = build_report(root)
        assert [row["reviewer"] for row in report["reviewers"]] == list(REVIEWERS)
        assert report["state"] == "REVIEW_REQUIRED"
        assert len(report["product_review_brief"]["buckets"]["FIX_NOW"]) == 1
        assert report["product_review_brief"]["buckets"]["FIX_NOW"][0]["reviewer"] == "QA"
        assert any(row["subject_key"] == "save" for row in report["cross_review"]["agreements"])
        assert report["evidence_classes"]["real_user_validation"]["state"] == "NOT_PROVIDED"
        assert report["guardrails"]["council_does_not_replace_product_ownership"] is True
        assert report["record_digest_sha256"] == record_digest(report)

        stale = json.loads((root / "design-system-advisor.json").read_text())
        stale["identity"]["package_id"] = "other.package"
        (root / "design-system-advisor.json").write_text(json.dumps(stale), encoding="utf-8")
        report = build_report(root)
        design_reviewer = next(row for row in report["reviewers"] if row["reviewer"] == "DESIGN")
        assert "design-system-advisor.json" in design_reviewer["missing_or_invalid_sources"]
    print("AppLab Virtual Product Review Council v5.3 self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.evidence_dir:
        parser.error("--evidence-dir is required unless --self-test is used")
    output = Path(args.output_dir) if args.output_dir else Path(args.evidence_dir)
    record = build_report(Path(args.evidence_dir))
    write_report(output, record)
    print(json.dumps({"lab_version": LAB_VERSION, "state": record["state"], **record["summary"]}, sort_keys=True))
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, AssertionError) as exc:
        raise SystemExit(f"AppLab Virtual Product Review Council failed: {exc}") from exc
