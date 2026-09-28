#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from product_review_common import find_json, load_json, result_state, write_report

SCHEMA_VERSION = 1
LAB_VERSION = "2.7.0"


def static_surfaces(app: dict[str, Any]) -> list[dict[str, Any]]:
    flow = app.get("product_flow_graph") if isinstance(app.get("product_flow_graph"), dict) else {}
    rows = flow.get("nodes") if isinstance(flow.get("nodes"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def surface_tokens(row: dict[str, Any]) -> set[str]:
    values = [
        str(row.get("id", "")),
        str(row.get("label", "")),
        " ".join(str(x) for x in row.get("roles", []) if isinstance(x, str)),
    ]
    tokens: set[str] = set()
    for value in values:
        tokens.update(x for x in re.findall(r"[a-z0-9]{3,}", value.lower()) if x not in {"screen","page","view","activity","fragment","route","lib","src","main"})
    return tokens


def build_report(app: dict[str, Any], crawl: dict[str, Any] | None, crawl_path: str | None = None) -> dict[str, Any]:
    surfaces = static_surfaces(app)
    actions = crawl.get("actions", []) if isinstance(crawl, dict) and isinstance(crawl.get("actions"), list) else []
    runtime_labels = [
        str(row.get("label", "")).strip()
        for row in actions if isinstance(row, dict) and str(row.get("label", "")).strip()
    ]
    label_text = " ".join(runtime_labels).lower()

    observed_surfaces: list[dict[str, Any]] = []
    unobserved_surfaces: list[dict[str, Any]] = []
    for row in surfaces:
        tokens = surface_tokens(row)
        matched = sorted(token for token in tokens if token in label_text)
        item = {
            "id": str(row.get("id", "")),
            "label": str(row.get("label", "")),
            "roles": row.get("roles", []),
            "matched_tokens": matched,
        }
        (observed_surfaces if matched else unobserved_surfaces).append(item)

    findings: list[dict[str, Any]] = []
    for row in actions:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status", "")).upper()
        label = str(row.get("label", "")).strip()
        if status == "FAIL":
            findings.append({
                "kind": "RUNTIME_INTERACTION_FAILURE",
                "severity": "HIGH_REVIEW",
                "confidence": "HIGH",
                "subject": label,
                "message": "A conservative runtime interaction produced a crawler failure.",
                "evidence": [crawl_path] if crawl_path else [],
            })
        elif status == "NO_CHANGE":
            findings.append({
                "kind": "RUNTIME_ACTION_NO_STATE_CHANGE",
                "severity": "REVIEW",
                "confidence": "MEDIUM",
                "subject": label,
                "message": "A safe runtime control was activated without an observed UI-state change.",
                "evidence": [crawl_path] if crawl_path else [],
            })

    if crawl is not None:
        for row in unobserved_surfaces[:30]:
            findings.append({
                "kind": "STATIC_SURFACE_NOT_RUNTIME_OBSERVED",
                "severity": "INFO",
                "confidence": "LOW",
                "subject": row["id"],
                "message": "The static product model contains this surface, but the bounded safe crawler did not observe a matching runtime control.",
                "evidence": [row["id"]],
            })

    runtime_state = result_state(crawl)
    return {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "runtime_evidence_state": runtime_state,
        "crawler_result": str(crawl.get("result", "NOT_OBSERVED")) if crawl else "NOT_OBSERVED",
        "actions_observed": len(actions),
        "state_changes_observed": sum(1 for row in actions if isinstance(row, dict) and bool(row.get("state_changed"))),
        "static_surface_count": len(surfaces),
        "runtime_matched_surfaces": observed_surfaces,
        "runtime_unobserved_surfaces": unobserved_surfaces,
        "runtime_controls": [
            {
                "label": str(row.get("label", "")),
                "status": str(row.get("status", "")),
                "state_changed": bool(row.get("state_changed", False)),
                "screenshot": row.get("screenshot"),
                "ui_hierarchy": row.get("ui_hierarchy"),
            }
            for row in actions if isinstance(row, dict)
        ],
        "findings": findings,
        "guardrails": {
            "safe_actions_only": True,
            "unobserved_does_not_mean_unreachable": True,
            "runtime_failure_requires_source_evidence": True,
            "no_runtime_verdict_override": True,
        },
    }


def markdown(report: dict[str, Any]) -> str:
    lines=[
        "# AppLab Behavioral Product Lab","",
        f"- Runtime evidence: **{report['runtime_evidence_state']}**",
        f"- Safe actions observed: **{report['actions_observed']}**",
        f"- State changes observed: **{report['state_changes_observed']}**",
        f"- Static surfaces: **{report['static_surface_count']}**",
        f"- Runtime-matched surfaces: **{len(report['runtime_matched_surfaces'])}**","",
    ]
    for row in report["findings"][:25]:
        lines.append(f"- **{row['severity']} / {row['kind']}** · {row.get('subject','')}")
    return "\n".join(lines)


def self_test() -> None:
    app={"product_flow_graph":{"nodes":[{"id":"lib/home_screen.dart","label":"home","roles":["home"]},{"id":"lib/settings_screen.dart","label":"settings","roles":["settings"]}]}}
    crawl={"result":"PASS","actions":[{"label":"Settings","status":"CHANGED","state_changed":True},{"label":"Profile","status":"NO_CHANGE","state_changed":False}]}
    report=build_report(app,crawl,"interaction-crawl.json")
    assert report["runtime_evidence_state"]=="OBSERVED_PASS"
    assert len(report["runtime_matched_surfaces"])==1
    assert any(x["kind"]=="RUNTIME_ACTION_NO_STATE_CHANGE" for x in report["findings"])
    print("AppLab Behavioral Product Lab self-test PASS")


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--app-intelligence")
    p.add_argument("--runtime-evidence-dir")
    p.add_argument("--interaction-crawl")
    p.add_argument("--output-dir",default="applab-behavioral-product")
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:
        self_test(); return 0
    if not args.app_intelligence:
        raise SystemExit("--app-intelligence is required")
    app=load_json(Path(args.app_intelligence))
    if app is None:
        raise SystemExit("invalid app intelligence")
    crawl_path=None; crawl=None
    if args.interaction_crawl:
        cp=Path(args.interaction_crawl); crawl=load_json(cp); crawl_path=str(cp)
    elif args.runtime_evidence_dir:
        cp,crawl=find_json(Path(args.runtime_evidence_dir),["interaction-crawl.json"])
        crawl_path=str(cp) if cp else None
    report=build_report(app,crawl,crawl_path)
    write_report(Path(args.output_dir),"behavioral-product",report,markdown(report))
    print(json.dumps({"lab_version":LAB_VERSION,"runtime_evidence":report["runtime_evidence_state"],"findings":len(report["findings"])}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
