#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from product_review_common import load_json, write_report

SCHEMA_VERSION = 1
LAB_VERSION = "3.2.0"

STATUSES = ("CONFIRMED", "CORROBORATED", "CONTRADICTED", "UNVERIFIED", "STALE")


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9_.:/-]+", "-", value.lower()).strip("-")


def observed(value: str) -> bool:
    return value.startswith("OBSERVED")


def evidence_paths(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= 12:
            break
    return result


def provenance_paths(capability: dict[str, Any]) -> dict[str, list[str]]:
    provenance = capability.get("provenance")
    if not isinstance(provenance, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, rows in provenance.items():
        paths = evidence_paths(rows)
        if paths:
            result[str(key)] = paths
    return result


def claim(
    *,
    claim_id: str,
    subject: str,
    proposition: str,
    status: str,
    sources: list[str],
    evidence: list[str],
    rationale: str,
    domain: str,
    source_sha: str = "",
    current_sha: str = "",
) -> dict[str, Any]:
    final_status = status if status in STATUSES else "UNVERIFIED"
    stale = bool(source_sha and current_sha and source_sha.lower() != current_sha.lower())
    if stale:
        final_status = "STALE"
    return {
        "id": claim_id,
        "domain": domain,
        "subject": subject,
        "proposition": proposition,
        "status": final_status,
        "sources": sorted(set(sources)),
        "evidence": evidence[:12],
        "rationale": rationale,
        "source_sha": source_sha,
        "current_sha": current_sha,
    }


def feature_claims(
    app: dict[str, Any],
    contract: dict[str, Any],
    states: dict[str, Any],
    trust: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    truth = app.get("feature_truth") if isinstance(app.get("feature_truth"), dict) else {}
    truth_rows = truth.get("capabilities") if isinstance(truth.get("capabilities"), list) else []
    contract_rows = contract.get("capabilities") if isinstance(contract.get("capabilities"), list) else []
    contract_by_cap = {
        str(row.get("capability", "")): row
        for row in contract_rows
        if isinstance(row, dict) and str(row.get("capability", ""))
    }
    state_map = states.get("states") if isinstance(states.get("states"), dict) else {}
    binding = trust.get("binding") if isinstance(trust.get("binding"), dict) else {}
    current_sha = str(binding.get("resolved_sha", ""))

    claims: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []

    for row in truth_rows:
        if not isinstance(row, dict):
            continue
        capability = str(row.get("capability", "")).strip()
        if not capability:
            continue
        implementation = str(row.get("truth", "NOT_DETECTED"))
        contract_row = contract_by_cap.get(capability, {})
        contract_status = str(contract_row.get("contract_status", "UNMENTIONED"))
        verified = str(contract_row.get("runtime_verified", "NOT_OBSERVED"))
        provenance = provenance_paths(row)
        sources: list[str] = []
        evidence: list[str] = []
        for source, paths in provenance.items():
            sources.append(source)
            evidence.extend(paths)
        evidence.extend(evidence_paths(contract_row.get("contract_evidence")))
        if observed(verified):
            sources.append("TRUSTED_RUNTIME")

        if contract_status == "PROMISED" and implementation == "NOT_DETECTED":
            status = "CONTRADICTED"
            rationale = "The product contract promises the capability but bounded implementation evidence is absent."
        elif contract_status == "EXCLUDED" and implementation == "CODE_CONFIRMED":
            status = "CONTRADICTED"
            rationale = "The product contract excludes the capability while bounded code evidence confirms implementation."
        elif implementation == "CODE_CONFIRMED" and observed(verified):
            status = "CONFIRMED"
            rationale = "Implementation evidence and trusted runtime observation agree."
        elif contract_status == "PROMISED" and implementation in {"CODE_CONFIRMED", "CONFIG_SIGNAL"}:
            status = "CORROBORATED"
            rationale = "Product-contract and implementation evidence agree, but matching runtime verification is incomplete."
        elif implementation == "CODE_CONFIRMED":
            status = "CORROBORATED"
            rationale = "Bounded code evidence supports the capability; independent runtime/product-contract confirmation is incomplete."
        elif implementation in {"CONFIG_SIGNAL", "TEST_ONLY_SIGNAL", "DOC_ONLY_SIGNAL"}:
            status = "UNVERIFIED"
            rationale = "Only weaker bounded evidence exists for the capability."
        else:
            status = "UNVERIFIED"
            rationale = "No strong bounded evidence confirms the capability."

        item = claim(
            claim_id=f"capability:{norm(capability)}",
            subject=capability,
            proposition="capability-present",
            status=status,
            sources=sources,
            evidence=evidence,
            rationale=rationale,
            domain="capability",
            current_sha=current_sha,
        )
        claims.append(item)
        if item["status"] == "CONTRADICTED":
            contradictions.append(
                {
                    "id": f"contradiction:{item['id']}",
                    "domain": "capability",
                    "subject": capability,
                    "kind": (
                        "CONTRACT_IMPLEMENTATION_CONTRADICTION"
                        if contract_status in {"PROMISED", "EXCLUDED"}
                        else "EVIDENCE_CONTRADICTION"
                    ),
                    "message": rationale,
                    "evidence": item["evidence"],
                    "sources": item["sources"],
                }
            )

    return claims, contradictions


def surface_claims(
    app: dict[str, Any],
    behavioral: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    flow = app.get("product_flow_graph") if isinstance(app.get("product_flow_graph"), dict) else {}
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), list) else []
    matched = {
        str(row.get("id", ""))
        for row in behavioral.get("runtime_matched_surfaces", [])
        if isinstance(row, dict)
    }
    consistency = app.get("product_consistency") if isinstance(app.get("product_consistency"), dict) else {}
    findings = consistency.get("findings") if isinstance(consistency.get("findings"), list) else []
    orphan_ids = {
        str(row.get("subject", ""))
        for row in findings
        if isinstance(row, dict) and str(row.get("kind", "")) == "ORPHAN_SURFACE_CANDIDATE"
    }

    claims: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        surface = str(node.get("id", "")).strip()
        if not surface:
            continue
        if surface in matched:
            status = "CONFIRMED"
            rationale = "Static surface evidence is confirmed by observed trusted UI hierarchy."
            sources = ["STATIC_FLOW", "TRUSTED_RUNTIME_UI"]
        else:
            status = "UNVERIFIED"
            rationale = "The static surface was not matched in bounded trusted runtime exploration."
            sources = ["STATIC_FLOW"]
        item = claim(
            claim_id=f"surface:{norm(surface)}",
            subject=surface,
            proposition="surface-reachable",
            status=status,
            sources=sources,
            evidence=[surface],
            rationale=rationale,
            domain="surface",
        )
        claims.append(item)
        if surface in orphan_ids and surface in matched:
            contradictions.append(
                {
                    "id": f"contradiction:orphan:{norm(surface)}",
                    "domain": "surface",
                    "subject": surface,
                    "kind": "STATIC_ORPHAN_CONTRADICTED_BY_RUNTIME",
                    "message": "A static orphan candidate was directly observed in trusted runtime UI evidence.",
                    "evidence": [surface],
                    "sources": ["STATIC_FLOW", "TRUSTED_RUNTIME_UI"],
                }
            )
    return claims, contradictions


def state_claims(states: dict[str, Any]) -> list[dict[str, Any]]:
    state_map = states.get("states") if isinstance(states.get("states"), dict) else {}
    result: list[dict[str, Any]] = []
    for state, row in sorted(state_map.items()):
        if not isinstance(row, dict):
            continue
        if str(row.get("applicability", "APPLICABLE")) == "NOT_APPLICABLE":
            continue
        raw = str(row.get("status", "NOT_OBSERVED"))
        evidence: list[str] = []
        source = row.get("source")
        if isinstance(source, str) and source:
            evidence.append(source)
        elif isinstance(source, list):
            evidence.extend(evidence_paths(source))
        if raw in {"OBSERVED_PASS", "OBSERVED"}:
            status = "CONFIRMED"
            rationale = "Trusted runtime evidence directly observed this applicable state."
        elif raw == "OBSERVED_FAIL":
            status = "CONFIRMED"
            rationale = "Trusted runtime evidence directly observed a failure in this applicable state."
        else:
            status = "UNVERIFIED"
            rationale = "No trusted runtime observation confirms this applicable state."
        result.append(
            claim(
                claim_id=f"state:{norm(state)}",
                subject=state,
                proposition=f"state-{raw.lower()}",
                status=status,
                sources=[str(row.get("source_kind", "RUNTIME"))],
                evidence=evidence,
                rationale=rationale,
                domain="state",
            )
        )
    return result


def calibrated_claims(
    calibration: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = calibration.get("calibrated_findings") if isinstance(calibration.get("calibrated_findings"), list) else []
    result: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    mapping = {
        "RUNTIME_CONFIRMED": "CONFIRMED",
        "RUNTIME_CORROBORATED": "CORROBORATED",
        "STATIC_CORROBORATED": "CORROBORATED",
        "STATIC_HEURISTIC": "UNVERIFIED",
        "RUNTIME_CONTRADICTED": "CONTRADICTED",
    }
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        evidence_class = str(row.get("evidence_class", "STATIC_HEURISTIC"))
        subject = str(row.get("subject", "")).strip() or str(row.get("kind", "finding"))
        item = claim(
            claim_id=f"finding:{norm(str(row.get('id', index)))}",
            subject=subject,
            proposition=str(row.get("kind", "finding")).lower(),
            status=mapping.get(evidence_class, "UNVERIFIED"),
            sources=[evidence_class],
            evidence=evidence_paths(row.get("evidence")),
            rationale=str(row.get("message", "")) or f"Calibrated evidence class: {evidence_class}.",
            domain=str(row.get("domain", "finding")),
        )
        result.append(item)
        if item["status"] == "CONTRADICTED":
            contradictions.append(
                {
                    "id": f"contradiction:{item['id']}",
                    "domain": item["domain"],
                    "subject": item["subject"],
                    "kind": "CALIBRATED_FINDING_CONTRADICTED",
                    "message": item["rationale"],
                    "evidence": item["evidence"],
                    "sources": item["sources"],
                }
            )
    return result, contradictions


def build_report(
    app: dict[str, Any],
    behavioral: dict[str, Any],
    states: dict[str, Any],
    calibration: dict[str, Any],
    contract: dict[str, Any],
    trust: dict[str, Any],
) -> dict[str, Any]:
    claims: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []

    feature_rows, feature_contradictions = feature_claims(app, contract, states, trust)
    surface_rows, surface_contradictions = surface_claims(app, behavioral)
    finding_rows, finding_contradictions = calibrated_claims(calibration)

    claims.extend(feature_rows)
    claims.extend(surface_rows)
    claims.extend(state_claims(states))
    claims.extend(finding_rows)
    contradictions.extend(feature_contradictions)
    contradictions.extend(surface_contradictions)
    contradictions.extend(finding_contradictions)

    binding = trust.get("binding") if isinstance(trust.get("binding"), dict) else {}
    current_sha = str(binding.get("resolved_sha", ""))
    for item in claims:
        source_sha = str(item.get("source_sha", ""))
        if source_sha and current_sha and source_sha.lower() != current_sha.lower():
            item["status"] = "STALE"
            item["rationale"] = "Evidence is bound to a different source SHA."

    counts = Counter(str(item.get("status", "UNVERIFIED")) for item in claims)
    by_domain: dict[str, dict[str, int]] = {}
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for item in claims:
        grouped[str(item.get("domain", "unknown"))][str(item.get("status", "UNVERIFIED"))] += 1
    for domain, domain_counts in sorted(grouped.items()):
        by_domain[domain] = dict(sorted(domain_counts.items()))

    order = {"CONTRADICTED": 0, "STALE": 1, "UNVERIFIED": 2, "CORROBORATED": 3, "CONFIRMED": 4}
    claims.sort(key=lambda row: (order.get(str(row.get("status")), 9), str(row.get("domain")), str(row.get("subject"))))
    contradictions.sort(key=lambda row: (str(row.get("domain")), str(row.get("kind")), str(row.get("subject"))))

    return {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "claims": claims,
        "contradictions": contradictions,
        "summary": {
            "total_claims": len(claims),
            "confirmed": counts.get("CONFIRMED", 0),
            "corroborated": counts.get("CORROBORATED", 0),
            "contradicted": counts.get("CONTRADICTED", 0),
            "unverified": counts.get("UNVERIFIED", 0),
            "stale": counts.get("STALE", 0),
            "contradiction_count": len(contradictions),
            "by_domain": by_domain,
        },
        "status_semantics": {
            "CONFIRMED": "Independent strong evidence, or direct trusted runtime observation, supports the claim.",
            "CORROBORATED": "Multiple compatible bounded sources support the claim but direct runtime confirmation is incomplete.",
            "CONTRADICTED": "Strong bounded evidence sources disagree about the same product subject.",
            "UNVERIFIED": "Evidence is missing, weak or incomplete; absence is not a defect verdict.",
            "STALE": "Evidence is explicitly bound to a different source revision.",
        },
        "guardrails": {
            "no_numeric_confidence_score": True,
            "missing_evidence_never_becomes_pass": True,
            "contradiction_preserves_all_sources": True,
            "trusted_runtime_has_highest_direct_authority": True,
            "certification_authority_unchanged": True,
        },
    }


def markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# AppLab Evidence Confidence & Contradiction Engine",
        "",
        f"- Claims: **{summary['total_claims']}**",
        f"- Confirmed: **{summary['confirmed']}**",
        f"- Corroborated: **{summary['corroborated']}**",
        f"- Contradicted: **{summary['contradicted']}**",
        f"- Unverified: **{summary['unverified']}**",
        f"- Stale: **{summary['stale']}**",
        f"- Explicit contradictions: **{summary['contradiction_count']}**",
        "",
    ]
    if report["contradictions"]:
        lines.extend(["## Contradictions", ""])
        for row in report["contradictions"][:30]:
            lines.append(
                f"- **{row['kind']}** · {row.get('subject','')} — {row.get('message','')}"
            )
        lines.append("")
    lines.extend(["## Claims requiring attention", ""])
    for row in report["claims"]:
        if row["status"] not in {"CONTRADICTED", "STALE", "UNVERIFIED"}:
            continue
        lines.append(
            f"- **{row['status']} / {row['domain']}** · {row['subject']} — {row['rationale']}"
        )
        if sum(1 for x in lines if x.startswith("- **")) >= 40:
            break
    return "\n".join(lines)


def self_test() -> None:
    app = {
        "feature_truth": {
            "capabilities": [
                {
                    "capability": "authentication",
                    "truth": "CODE_CONFIRMED",
                    "provenance": {"CODE": ["auth.dart"]},
                },
                {
                    "capability": "cloud_or_sync",
                    "truth": "NOT_DETECTED",
                    "provenance": {"DOCUMENTATION": ["README.md"]},
                },
            ]
        },
        "product_flow_graph": {
            "nodes": [
                {"id": "lib/home_screen.dart"},
                {"id": "lib/settings_screen.dart"},
            ]
        },
        "product_consistency": {
            "findings": [
                {
                    "id": "orphan-settings",
                    "domain": "product_flow",
                    "kind": "ORPHAN_SURFACE_CANDIDATE",
                    "subject": "lib/settings_screen.dart",
                    "message": "candidate",
                }
            ]
        },
    }
    behavioral = {
        "runtime_matched_surfaces": [{"id": "lib/settings_screen.dart"}],
        "findings": [],
    }
    states = {
        "states": {
            "auth": {
                "status": "OBSERVED",
                "applicability": "APPLICABLE",
                "source": ["ui.xml"],
                "source_kind": "UI_HIERARCHY",
            }
        }
    }
    calibration = {
        "calibrated_findings": [
            {
                "id": "orphan-settings",
                "domain": "product_flow",
                "kind": "ORPHAN_SURFACE_CANDIDATE",
                "subject": "lib/settings_screen.dart",
                "message": "runtime disproved orphan",
                "evidence_class": "RUNTIME_CONTRADICTED",
                "evidence": ["ui.xml"],
            }
        ]
    }
    contract = {
        "capabilities": [
            {
                "capability": "authentication",
                "contract_status": "PROMISED",
                "runtime_verified": "OBSERVED",
                "contract_evidence": ["README.md:2"],
            },
            {
                "capability": "cloud_or_sync",
                "contract_status": "PROMISED",
                "runtime_verified": "NOT_OBSERVED",
                "contract_evidence": ["README.md:3"],
            },
        ]
    }
    trust = {
        "trusted": True,
        "binding": {"resolved_sha": "a" * 40},
    }
    report = build_report(app, behavioral, states, calibration, contract, trust)
    by_id = {row["id"]: row for row in report["claims"]}
    assert by_id["capability:authentication"]["status"] == "CONFIRMED"
    assert by_id["capability:cloud_or_sync"]["status"] == "CONTRADICTED"
    assert by_id["surface:lib/settings_screen.dart"]["status"] == "CONFIRMED"
    assert any(
        row["kind"] == "STATIC_ORPHAN_CONTRADICTED_BY_RUNTIME"
        for row in report["contradictions"]
    )
    assert report["summary"]["contradiction_count"] >= 2
    print("AppLab Evidence Confidence & Contradiction Engine self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-intelligence")
    parser.add_argument("--behavioral")
    parser.add_argument("--state-edge")
    parser.add_argument("--calibration")
    parser.add_argument("--product-contract")
    parser.add_argument("--runtime-trust")
    parser.add_argument("--output-dir", default="applab-evidence-confidence")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    paths = {
        "app": args.app_intelligence,
        "behavioral": args.behavioral,
        "states": args.state_edge,
        "calibration": args.calibration,
        "contract": args.product_contract,
    }
    loaded: dict[str, dict[str, Any]] = {}
    for key, value in paths.items():
        payload = load_json(Path(value)) if value else None
        if payload is None:
            raise SystemExit(f"--{key} evidence is required and must be valid")
        loaded[key] = payload
    trust = load_json(Path(args.runtime_trust)) if args.runtime_trust else {}
    report = build_report(
        loaded["app"],
        loaded["behavioral"],
        loaded["states"],
        loaded["calibration"],
        loaded["contract"],
        trust or {},
    )
    write_report(Path(args.output_dir), "evidence-confidence", report, markdown(report))
    print(json.dumps({"lab_version": LAB_VERSION, **report["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
