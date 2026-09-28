#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from product_review_common import load_json, write_report

SCHEMA_VERSION = 1
LAB_VERSION = "3.1.0"


def build_report(
    calibration: dict[str, Any] | None,
    contract: dict[str, Any] | None,
    app: dict[str, Any] | None,
) -> dict[str, Any]:
    calibration = calibration or {}
    contract = contract or {}
    app = app or {}
    buckets = {"FIX_NOW": [], "VERIFY_NEXT": [], "IMPROVE": [], "NO_ACTION": []}
    seen: set[tuple[str, str, str, str]] = set()

    def add(
        bucket: str,
        source: str,
        kind: str,
        subject: str,
        message: str,
        evidence: list[Any],
        basis: str,
    ) -> None:
        key = (bucket, kind, subject, message)
        if key in seen:
            return
        seen.add(key)
        buckets[bucket].append(
            {
                "source": source,
                "kind": kind,
                "subject": subject,
                "message": message,
                "evidence": evidence[:8],
                "basis": basis,
            }
        )

    for row in calibration.get("calibrated_findings", []):
        if not isinstance(row, dict):
            continue
        evidence_class = str(row.get("evidence_class", ""))
        severity = str(row.get("severity", "")).upper()
        confidence = str(row.get("confidence", "")).upper()
        evidence = row.get("evidence") if isinstance(row.get("evidence"), list) else []

        if evidence_class == "RUNTIME_CONTRADICTED":
            bucket = "NO_ACTION"
        elif (
            evidence_class == "RUNTIME_CONFIRMED"
            and severity == "HIGH_REVIEW"
            and confidence == "HIGH"
            and bool(evidence)
        ):
            bucket = "FIX_NOW"
        elif evidence_class in {
            "RUNTIME_CONFIRMED",
            "RUNTIME_CORROBORATED",
            "STATIC_CORROBORATED",
            "STATIC_HEURISTIC",
        }:
            bucket = "VERIFY_NEXT"
        else:
            bucket = "IMPROVE"

        add(
            bucket,
            "evidence-calibration",
            str(row.get("kind", "")),
            str(row.get("subject", "")),
            str(row.get("message", "")),
            evidence,
            evidence_class,
        )

    for row in contract.get("findings", []):
        if not isinstance(row, dict):
            continue
        severity = str(row.get("severity", "")).upper()
        bucket = "VERIFY_NEXT" if severity in {"HIGH_REVIEW", "REVIEW"} else "IMPROVE"
        add(
            bucket,
            "product-contract",
            str(row.get("kind", "")),
            str(row.get("capability", "")),
            str(row.get("message", "")),
            row.get("evidence", []) if isinstance(row.get("evidence"), list) else [],
            "PRODUCT_CONTRACT",
        )

    lifecycle = app.get("lifecycle_integrity") if isinstance(app.get("lifecycle_integrity"), dict) else {}
    lifecycle_findings = (
        lifecycle.get("findings") if isinstance(lifecycle.get("findings"), list) else []
    )
    for row in lifecycle_findings:
        if not isinstance(row, dict):
            continue
        add(
            "VERIFY_NEXT",
            "lifecycle-integrity",
            str(row.get("kind", "")),
            str(row.get("entity", "")),
            str(row.get("message", "")),
            row.get("evidence", []) if isinstance(row.get("evidence"), list) else [],
            "STATIC_LIFECYCLE",
        )

    limits = {"FIX_NOW": 8, "VERIFY_NEXT": 12, "IMPROVE": 8, "NO_ACTION": 8}
    for key in buckets:
        buckets[key] = buckets[key][: limits[key]]

    return {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "buckets": buckets,
        "summary": {key.lower(): len(value) for key, value in buckets.items()},
        "priority_order": ["FIX_NOW", "VERIFY_NEXT", "IMPROVE", "NO_ACTION"],
        "guardrails": {
            "fix_now_requires_high_confidence_runtime_evidence": True,
            "product_contract_findings_never_auto_fix": True,
            "no_feature_generation": True,
            "no_numeric_score": True,
            "no_action_items_without_evidence_basis": True,
            "no_release_verdict": True,
        },
    }


def markdown(r: dict[str, Any]) -> str:
    lines = ["# AppLab Decision & Opportunity Brief", ""]
    for bucket in r["priority_order"]:
        lines.extend([f"## {bucket.replace('_', ' ').title()}", ""])
        rows = r["buckets"][bucket]
        if not rows:
            lines.append("- None.")
        for row in rows:
            subject = f" · {row['subject']}" if row.get("subject") else ""
            lines.append(
                f"- **{row['kind']}**{subject} — {row['message']} [{row['basis']}]"
            )
        lines.append("")
    return "\n".join(lines)


def self_test() -> None:
    calibration = {
        "calibrated_findings": [
            {
                "kind": "A",
                "severity": "HIGH_REVIEW",
                "confidence": "HIGH",
                "evidence_class": "RUNTIME_CONFIRMED",
                "subject": "Save",
                "message": "failed",
                "evidence": ["interaction-crawl.json"],
            },
            {
                "kind": "B",
                "severity": "HIGH_REVIEW",
                "confidence": "HIGH",
                "evidence_class": "RUNTIME_CORROBORATED",
                "subject": "Delete",
                "message": "corroborated",
                "evidence": ["x"],
            },
            {
                "kind": "C",
                "severity": "REVIEW",
                "confidence": "LOW",
                "evidence_class": "RUNTIME_CONTRADICTED",
                "subject": "Settings",
                "message": "orphan",
                "evidence": [],
            },
        ]
    }
    contract = {
        "findings": [
            {
                "kind": "PROMISED_WITHOUT_IMPLEMENTATION_EVIDENCE",
                "severity": "HIGH_REVIEW",
                "capability": "sync",
                "message": "contract mismatch",
                "evidence": ["README.md:4"],
            }
        ]
    }
    r = build_report(calibration, contract, {"lifecycle_integrity": {"findings": []}})
    assert len(r["buckets"]["FIX_NOW"]) == 1
    assert len(r["buckets"]["VERIFY_NEXT"]) == 2
    assert len(r["buckets"]["NO_ACTION"]) == 1
    print("AppLab Decision & Opportunity Brief self-test PASS")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--calibration")
    p.add_argument("--product-contract")
    p.add_argument("--app-intelligence")
    p.add_argument("--output-dir", default="applab-decision-brief")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        self_test()
        return 0
    r = build_report(
        load_json(Path(a.calibration)) if a.calibration else None,
        load_json(Path(a.product_contract)) if a.product_contract else None,
        load_json(Path(a.app_intelligence)) if a.app_intelligence else None,
    )
    write_report(Path(a.output_dir), "decision-brief", r, markdown(r))
    print(json.dumps({"lab_version": LAB_VERSION, **r["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
