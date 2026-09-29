#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from product_review_common import find_json, load_json, result_state, write_report

SCHEMA_VERSION = 1
LAB_VERSION = "3.1.0"

STOP_TOKENS = {
    "screen", "page", "view", "activity", "fragment", "route", "lib", "src",
    "main", "dart", "java", "kotlin", "kt",
}


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
        tokens.update(
            x
            for x in re.findall(r"[a-z0-9]{3,}", value.lower())
            if x not in STOP_TOKENS
        )
    return tokens


def hierarchy_text(path: Path) -> str:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return ""
    values: list[str] = []
    for node in root.iter():
        for key in ("text", "content-desc", "resource-id", "class"):
            value = str(node.attrib.get(key, "")).strip()
            if value:
                values.append(value)
    return " ".join(values).lower()


def runtime_observations(
    actions: list[dict[str, Any]],
    runtime_root: Path | None,
) -> tuple[str, list[dict[str, Any]]]:
    texts: list[str] = []
    observations: list[dict[str, Any]] = []
    for row in actions:
        label = str(row.get("label", "")).strip()
        hierarchy = str(row.get("ui_hierarchy", "") or "").strip()
        hierarchy_path: Path | None = None
        text = ""
        if runtime_root is not None and hierarchy:
            candidate = runtime_root / hierarchy
            try:
                candidate.relative_to(runtime_root)
            except ValueError:
                candidate = Path()
            if candidate.is_file():
                hierarchy_path = candidate
                text = hierarchy_text(candidate)
                if text:
                    texts.append(text)
        observations.append(
            {
                "label": label,
                "status": str(row.get("status", "")),
                "state_changed": bool(row.get("state_changed", False)),
                "screenshot": row.get("screenshot"),
                "ui_hierarchy": hierarchy,
                "hierarchy_observed": hierarchy_path is not None,
                "hierarchy_text_tokens": len(re.findall(r"[a-z0-9]{3,}", text)),
            }
        )
    return " ".join(texts), observations


def build_report(
    app: dict[str, Any],
    crawl: dict[str, Any] | None,
    crawl_path: str | None = None,
    runtime_root: Path | None = None,
) -> dict[str, Any]:
    surfaces = static_surfaces(app)
    actions = (
        [row for row in crawl.get("actions", []) if isinstance(row, dict)]
        if isinstance(crawl, dict) and isinstance(crawl.get("actions"), list)
        else []
    )
    hierarchy_corpus, observations = runtime_observations(actions, runtime_root)

    observed_surfaces: list[dict[str, Any]] = []
    unobserved_surfaces: list[dict[str, Any]] = []
    for row in surfaces:
        tokens = surface_tokens(row)
        matched = sorted(token for token in tokens if token in hierarchy_corpus)
        item = {
            "id": str(row.get("id", "")),
            "label": str(row.get("label", "")),
            "roles": row.get("roles", []),
            "matched_tokens": matched,
            "match_source": "UI_HIERARCHY" if matched else "NOT_OBSERVED",
        }
        (observed_surfaces if matched else unobserved_surfaces).append(item)

    findings: list[dict[str, Any]] = []
    for row in actions:
        status = str(row.get("status", "")).upper()
        label = str(row.get("label", "")).strip()
        evidence = [crawl_path] if crawl_path else []
        hierarchy = str(row.get("ui_hierarchy", "") or "").strip()
        if hierarchy:
            evidence.append(hierarchy)
        if status == "FAIL":
            findings.append(
                {
                    "kind": "RUNTIME_INTERACTION_FAILURE",
                    "severity": "HIGH_REVIEW",
                    "confidence": "HIGH",
                    "subject": label,
                    "message": "A conservative runtime interaction produced a crawler failure.",
                    "evidence": evidence,
                    "relation_key": f"control:{label.lower()}",
                }
            )
        elif status == "NO_CHANGE":
            findings.append(
                {
                    "kind": "RUNTIME_ACTION_NO_STATE_CHANGE",
                    "severity": "REVIEW",
                    "confidence": "MEDIUM",
                    "subject": label,
                    "message": "A safe runtime control was activated without an observed UI-state change.",
                    "evidence": evidence,
                    "relation_key": f"control:{label.lower()}",
                }
            )

    if crawl is not None:
        for row in unobserved_surfaces[:30]:
            findings.append(
                {
                    "kind": "STATIC_SURFACE_NOT_RUNTIME_OBSERVED",
                    "severity": "INFO",
                    "confidence": "LOW",
                    "subject": row["id"],
                    "message": "The static product model contains this surface, but no matching bounded UI hierarchy was observed.",
                    "evidence": [row["id"]],
                    "relation_key": f"surface:{row['id']}",
                }
            )

    runtime_state = result_state(crawl)
    hierarchy_count = sum(1 for row in observations if row["hierarchy_observed"])
    return {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "runtime_evidence_state": runtime_state,
        "crawler_result": str(crawl.get("result", "NOT_OBSERVED")) if crawl else "NOT_OBSERVED",
        "actions_observed": len(actions),
        "hierarchies_observed": hierarchy_count,
        "state_changes_observed": sum(1 for row in actions if bool(row.get("state_changed"))),
        "static_surface_count": len(surfaces),
        "runtime_matched_surfaces": observed_surfaces,
        "runtime_unobserved_surfaces": unobserved_surfaces,
        "runtime_controls": observations,
        "findings": findings,
        "guardrails": {
            "safe_actions_only": True,
            "surface_matching_uses_ui_hierarchy": True,
            "control_label_is_not_surface_proof": True,
            "unobserved_does_not_mean_unreachable": True,
            "runtime_failure_requires_source_evidence": True,
            "no_runtime_verdict_override": True,
        },
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AppLab Behavioral Product Lab",
        "",
        f"- Runtime evidence: **{report['runtime_evidence_state']}**",
        f"- Safe actions observed: **{report['actions_observed']}**",
        f"- UI hierarchies observed: **{report['hierarchies_observed']}**",
        f"- State changes observed: **{report['state_changes_observed']}**",
        f"- Static surfaces: **{report['static_surface_count']}**",
        f"- Runtime-matched surfaces: **{len(report['runtime_matched_surfaces'])}**",
        "",
    ]
    for row in report["findings"][:25]:
        lines.append(f"- **{row['severity']} / {row['kind']}** · {row.get('subject','')}")
    return "\n".join(lines)


def self_test() -> None:
    app = {
        "product_flow_graph": {
            "nodes": [
                {"id": "lib/home_screen.dart", "label": "home", "roles": ["home"]},
                {"id": "lib/settings_screen.dart", "label": "settings", "roles": ["settings"]},
            ]
        }
    }
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        crawl_dir = root / "interaction-crawl"
        crawl_dir.mkdir()
        hierarchy = crawl_dir / "01-after.xml"
        hierarchy.write_text(
            '<hierarchy><node text="Settings" content-desc="Account settings"/></hierarchy>',
            encoding="utf-8",
        )
        crawl = {
            "result": "PASS",
            "actions": [
                {
                    "label": "Open",
                    "status": "CHANGED",
                    "state_changed": True,
                    "ui_hierarchy": "interaction-crawl/01-after.xml",
                },
                {"label": "Profile", "status": "NO_CHANGE", "state_changed": False},
            ],
        }
        report = build_report(app, crawl, "interaction-crawl.json", root)
        assert report["runtime_evidence_state"] == "OBSERVED_PASS"
        assert report["hierarchies_observed"] == 1
        assert len(report["runtime_matched_surfaces"]) == 1
        assert report["runtime_matched_surfaces"][0]["id"] == "lib/settings_screen.dart"
        assert any(x["kind"] == "RUNTIME_ACTION_NO_STATE_CHANGE" for x in report["findings"])
    print("AppLab Behavioral Product Lab self-test PASS")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--app-intelligence")
    p.add_argument("--runtime-evidence-dir")
    p.add_argument("--interaction-crawl")
    p.add_argument("--output-dir", default="applab-behavioral-product")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.app_intelligence:
        raise SystemExit("--app-intelligence is required")
    app = load_json(Path(args.app_intelligence))
    if app is None:
        raise SystemExit("invalid app intelligence")
    runtime_root = Path(args.runtime_evidence_dir) if args.runtime_evidence_dir else None
    crawl_path = None
    crawl = None
    if args.interaction_crawl:
        cp = Path(args.interaction_crawl)
        crawl = load_json(cp)
        crawl_path = str(cp)
    elif runtime_root:
        cp, crawl = find_json(runtime_root, ["interaction-crawl.json"])
        crawl_path = str(cp) if cp else None
    report = build_report(app, crawl, crawl_path, runtime_root)
    write_report(Path(args.output_dir), "behavioral-product", report, markdown(report))
    print(
        json.dumps(
            {
                "lab_version": LAB_VERSION,
                "runtime_evidence": report["runtime_evidence_state"],
                "findings": len(report["findings"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
