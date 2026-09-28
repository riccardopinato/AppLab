#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from product_review_common import load_json, write_report

SCHEMA_VERSION = 1
LAB_VERSION = "3.1.0"


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def evidence_set(row: dict[str, Any]) -> set[str]:
    values = row.get("evidence")
    if not isinstance(values, list):
        return set()
    return {str(item).strip() for item in values if str(item).strip()}


def strong_relation(static: dict[str, Any], runtime: dict[str, Any]) -> bool:
    static_subject = normalize(str(static.get("subject", "")))
    runtime_subject = normalize(str(runtime.get("subject", runtime.get("state", ""))))
    if static_subject and runtime_subject and static_subject == runtime_subject:
        return True

    static_key = str(static.get("relation_key", "")).strip()
    runtime_key = str(runtime.get("relation_key", "")).strip()
    if static_key and runtime_key and static_key == runtime_key:
        return True

    shared_evidence = evidence_set(static) & evidence_set(runtime)
    if shared_evidence:
        return True

    return False


def build_report(
    app: dict[str, Any],
    behavioral: dict[str, Any] | None,
    states: dict[str, Any] | None,
) -> dict[str, Any]:
    consistency = app.get("product_consistency") if isinstance(app.get("product_consistency"), dict) else {}
    static_findings = consistency.get("findings") if isinstance(consistency.get("findings"), list) else []
    behavioral = behavioral or {}
    states = states or {}

    matched_ids = {
        str(x.get("id", ""))
        for x in behavioral.get("runtime_matched_surfaces", [])
        if isinstance(x, dict)
    }
    runtime_findings = [
        x for x in behavioral.get("findings", []) if isinstance(x, dict)
    ]
    state_findings = [
        x for x in states.get("findings", []) if isinstance(x, dict)
    ]
    runtime_all = runtime_findings + state_findings

    calibrated: list[dict[str, Any]] = []
    for row in static_findings:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["evidence_class"] = "STATIC_HEURISTIC"
        item["runtime_relation"] = "NOT_OBSERVED"
        item["recommended_disposition"] = "VERIFY"

        subject = str(row.get("subject", ""))
        kind = str(row.get("kind", ""))

        if kind == "ORPHAN_SURFACE_CANDIDATE" and subject in matched_ids:
            item["evidence_class"] = "RUNTIME_CONTRADICTED"
            item["runtime_relation"] = "CONTRADICTED"
            item["recommended_disposition"] = "NO_ACTION"
        else:
            for runtime in runtime_all:
                if not strong_relation(row, runtime):
                    continue
                severity = str(runtime.get("severity", "")).upper()
                if severity == "HIGH_REVIEW":
                    item["evidence_class"] = "RUNTIME_CORROBORATED"
                    item["runtime_relation"] = "CORROBORATED"
                    item["recommended_disposition"] = "VERIFY_NEXT"
                    break
                if item["evidence_class"] == "STATIC_HEURISTIC":
                    item["evidence_class"] = "STATIC_CORROBORATED"
                    item["runtime_relation"] = "PARTIAL"
                    item["recommended_disposition"] = "VERIFY_NEXT"

        calibrated.append(item)

    for runtime in runtime_all:
        severity = str(runtime.get("severity", "")).upper()
        if severity not in {"HIGH_REVIEW", "REVIEW"}:
            continue
        evidence = runtime.get("evidence") if isinstance(runtime.get("evidence"), list) else []
        calibrated.append(
            {
                "id": f"runtime::{runtime.get('kind','runtime')}::{runtime.get('subject',runtime.get('state',''))}",
                "domain": "runtime",
                "kind": str(runtime.get("kind", "RUNTIME_REVIEW")),
                "severity": severity,
                "confidence": "HIGH" if severity == "HIGH_REVIEW" else str(runtime.get("confidence", "MEDIUM")),
                "subject": str(runtime.get("subject", runtime.get("state", ""))),
                "message": str(runtime.get("message", "Runtime evidence requires review.")),
                "evidence": evidence,
                "relation_key": str(runtime.get("relation_key", "")),
                "evidence_class": "RUNTIME_CONFIRMED",
                "runtime_relation": "DIRECT",
                "recommended_disposition": "FIX_OR_REPRODUCE" if severity == "HIGH_REVIEW" else "VERIFY_NEXT",
            }
        )

    order = {
        "RUNTIME_CONFIRMED": 0,
        "RUNTIME_CORROBORATED": 1,
        "STATIC_CORROBORATED": 2,
        "STATIC_HEURISTIC": 3,
        "RUNTIME_CONTRADICTED": 4,
    }
    calibrated.sort(
        key=lambda x: (
            order.get(str(x.get("evidence_class")), 9),
            str(x.get("severity", "")),
            str(x.get("domain", "")),
            str(x.get("kind", "")),
        )
    )
    counts: dict[str, int] = {}
    for row in calibrated:
        key = str(row.get("evidence_class", "UNKNOWN"))
        counts[key] = counts.get(key, 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "calibrated_findings": calibrated,
        "summary": {
            "total": len(calibrated),
            "by_evidence_class": dict(sorted(counts.items())),
            "runtime_confirmed": counts.get("RUNTIME_CONFIRMED", 0),
            "runtime_corroborated": counts.get("RUNTIME_CORROBORATED", 0),
            "runtime_contradicted": counts.get("RUNTIME_CONTRADICTED", 0),
            "static_only": counts.get("STATIC_HEURISTIC", 0),
        },
        "evidence_order": [
            "RUNTIME_CONFIRMED",
            "RUNTIME_CORROBORATED",
            "STATIC_CORROBORATED",
            "STATIC_HEURISTIC",
            "RUNTIME_CONTRADICTED",
        ],
        "guardrails": {
            "correlation_requires_strong_relation": True,
            "lexical_overlap_alone_is_insufficient": True,
            "runtime_does_not_auto_pass_static_findings": True,
            "contradicted_findings_are_suppressed_not_deleted": True,
            "no_numeric_quality_score": True,
            "no_certification_override": True,
        },
    }


def markdown(r: dict[str, Any]) -> str:
    lines = [
        "# AppLab Evidence Calibration Engine",
        "",
        f"- Calibrated findings: **{r['summary']['total']}**",
        f"- Runtime confirmed: **{r['summary']['runtime_confirmed']}**",
        f"- Runtime corroborated: **{r['summary']['runtime_corroborated']}**",
        f"- Runtime contradicted: **{r['summary']['runtime_contradicted']}**",
        f"- Static-only: **{r['summary']['static_only']}**",
        "",
    ]
    for row in r["calibrated_findings"][:30]:
        lines.append(
            f"- **{row['evidence_class']} / {row.get('severity','')} / "
            f"{row.get('kind','')}** · {row.get('subject','')}"
        )
    return "\n".join(lines)


def self_test() -> None:
    app = {
        "product_consistency": {
            "findings": [
                {
                    "id": "a",
                    "domain": "product_flow",
                    "kind": "ORPHAN_SURFACE_CANDIDATE",
                    "severity": "REVIEW",
                    "subject": "lib/settings_screen.dart",
                    "message": "orphan",
                },
                {
                    "id": "b",
                    "domain": "ux",
                    "kind": "SAVE_FLOW_REVIEW",
                    "severity": "REVIEW",
                    "subject": "Save",
                    "message": "save review",
                },
            ]
        }
    }
    behavioral = {
        "runtime_matched_surfaces": [{"id": "lib/settings_screen.dart"}],
        "findings": [
            {
                "kind": "RUNTIME_INTERACTION_FAILURE",
                "severity": "HIGH_REVIEW",
                "subject": "Save",
                "message": "failure",
                "evidence": ["interaction-crawl.json"],
                "relation_key": "control:save",
            },
            {
                "kind": "RUNTIME_INTERACTION_FAILURE",
                "severity": "HIGH_REVIEW",
                "subject": "Unrelated",
                "message": "save word appears here but subject differs",
                "evidence": ["other.json"],
                "relation_key": "control:unrelated",
            },
        ],
    }
    r = build_report(app, behavioral, {"findings": []})
    by_id = {x.get("id"): x for x in r["calibrated_findings"] if x.get("id") in {"a", "b"}}
    assert by_id["a"]["evidence_class"] == "RUNTIME_CONTRADICTED"
    assert by_id["b"]["evidence_class"] == "RUNTIME_CORROBORATED"
    assert r["summary"]["runtime_confirmed"] == 2
    print("AppLab Evidence Calibration Engine self-test PASS")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--app-intelligence")
    p.add_argument("--behavioral")
    p.add_argument("--state-edge")
    p.add_argument("--output-dir", default="applab-evidence-calibration")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        self_test()
        return 0
    app = load_json(Path(a.app_intelligence)) if a.app_intelligence else None
    if app is None:
        raise SystemExit("--app-intelligence is required and must be valid")
    behavioral = load_json(Path(a.behavioral)) if a.behavioral else None
    states = load_json(Path(a.state_edge)) if a.state_edge else None
    r = build_report(app, behavioral, states)
    write_report(Path(a.output_dir), "evidence-calibration", r, markdown(r))
    print(json.dumps({"lab_version": LAB_VERSION, **r["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
