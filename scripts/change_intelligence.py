#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ENGINE_VERSION = "2.4.0"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def feature_truth_index(report: dict[str, Any]) -> dict[str, str]:
    block = report.get("feature_truth")
    if not isinstance(block, dict):
        return {}
    rows = block.get("capabilities")
    if not isinstance(rows, list):
        return {}
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        capability = str(row.get("capability", "")).strip()
        truth = str(row.get("truth", "NOT_DETECTED")).strip() or "NOT_DETECTED"
        if capability:
            result[capability] = truth
    return result


def entity_names(report: dict[str, Any]) -> set[str]:
    block = report.get("deep_product_model")
    if not isinstance(block, dict):
        return set()
    rows = block.get("entities")
    if not isinstance(rows, list):
        return set()
    return {
        str(row.get("name", "")).strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("name", "")).strip()
    }


def surface_ids(report: dict[str, Any]) -> set[str]:
    flow = report.get("product_flow_graph")
    if not isinstance(flow, dict):
        return set()
    rows = flow.get("nodes")
    if not isinstance(rows, list):
        return set()
    return {
        str(row.get("id", "")).strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("id", "")).strip()
    }


def consistency_findings(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    block = report.get("product_consistency")
    if not isinstance(block, dict):
        return {}
    rows = block.get("findings")
    if not isinstance(rows, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        finding_id = str(row.get("id", "")).strip()
        if finding_id:
            result[finding_id] = row
    return result


def feature_changes(
    before: dict[str, str], after: dict[str, str]
) -> tuple[list[dict[str, str]], list[str], list[str]]:
    changed: list[dict[str, str]] = []
    added: list[str] = []
    removed: list[str] = []

    keys = sorted(set(before) | set(after))
    for capability in keys:
        old = before.get(capability, "NOT_DETECTED")
        new = after.get(capability, "NOT_DETECTED")
        if old == new:
            continue
        changed.append({
            "capability": capability,
            "before": old,
            "after": new,
        })
        if old == "NOT_DETECTED" and new != "NOT_DETECTED":
            added.append(capability)
        elif old != "NOT_DETECTED" and new == "NOT_DETECTED":
            removed.append(capability)

    return changed, added, removed


def finding_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id", "")),
        "domain": str(row.get("domain", "")),
        "kind": str(row.get("kind", "")),
        "severity": str(row.get("severity", "")),
        "confidence": str(row.get("confidence", "")),
        "subject": str(row.get("subject", "")),
        "message": str(row.get("message", "")),
        "evidence": (
            [str(item) for item in row.get("evidence", [])[:10]]
            if isinstance(row.get("evidence"), list)
            else []
        ),
    }


def build_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_features = feature_truth_index(before)
    after_features = feature_truth_index(after)
    truth_changed, capabilities_added, capabilities_removed = feature_changes(
        before_features, after_features
    )

    before_entities = entity_names(before)
    after_entities = entity_names(after)
    before_surfaces = surface_ids(before)
    after_surfaces = surface_ids(after)

    before_findings = consistency_findings(before)
    after_findings = consistency_findings(after)

    new_finding_ids = sorted(set(after_findings) - set(before_findings))
    resolved_finding_ids = sorted(set(before_findings) - set(after_findings))
    persistent_finding_ids = sorted(set(before_findings) & set(after_findings))

    new_findings = [finding_view(after_findings[key]) for key in new_finding_ids]
    resolved_findings = [
        finding_view(before_findings[key]) for key in resolved_finding_ids
    ]

    new_high = sum(
        1 for row in new_findings if row.get("severity") == "HIGH_REVIEW"
    )
    new_review = sum(
        1 for row in new_findings if row.get("severity") == "REVIEW"
    )

    entities_added = sorted(after_entities - before_entities)
    entities_removed = sorted(before_entities - after_entities)
    surfaces_added = sorted(after_surfaces - before_surfaces)
    surfaces_removed = sorted(before_surfaces - after_surfaces)

    changed = any(
        (
            truth_changed,
            entities_added,
            entities_removed,
            surfaces_added,
            surfaces_removed,
            new_findings,
            resolved_findings,
        )
    )
    if new_high:
        review_state = "HIGH_REVIEW"
    elif new_review:
        review_state = "REVIEW"
    elif changed:
        review_state = "CHANGED"
    else:
        review_state = "NO_MATERIAL_CHANGE"

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "baseline": {
            "root_name": str(before.get("root_name", "")),
            "lab_version": str(before.get("lab_version", "")),
            "scan_confidence": str(
                (before.get("scan") or {}).get("confidence", "UNKNOWN")
                if isinstance(before.get("scan"), dict)
                else "UNKNOWN"
            ),
        },
        "current": {
            "root_name": str(after.get("root_name", "")),
            "lab_version": str(after.get("lab_version", "")),
            "scan_confidence": str(
                (after.get("scan") or {}).get("confidence", "UNKNOWN")
                if isinstance(after.get("scan"), dict)
                else "UNKNOWN"
            ),
        },
        "review_state": review_state,
        "feature_truth": {
            "changed": truth_changed,
            "added": capabilities_added,
            "removed": capabilities_removed,
        },
        "domain_model": {
            "entities_added": entities_added,
            "entities_removed": entities_removed,
        },
        "product_flow": {
            "surfaces_added": surfaces_added,
            "surfaces_removed": surfaces_removed,
        },
        "consistency": {
            "new_findings": new_findings,
            "resolved_findings": resolved_findings,
            "persistent_finding_ids": persistent_finding_ids,
        },
        "summary": {
            "feature_truth_changes": len(truth_changed),
            "capabilities_added": len(capabilities_added),
            "capabilities_removed": len(capabilities_removed),
            "entities_added": len(entities_added),
            "entities_removed": len(entities_removed),
            "surfaces_added": len(surfaces_added),
            "surfaces_removed": len(surfaces_removed),
            "new_findings": len(new_findings),
            "new_high_review": new_high,
            "new_review": new_review,
            "resolved_findings": len(resolved_findings),
            "persistent_findings": len(persistent_finding_ids),
        },
        "guardrails": {
            "advisory_only": True,
            "no_generated_score": True,
            "no_runtime_verdict_override": True,
            "baseline_and_current_remain_authoritative": True,
        },
        "interpretation": (
            "Change Intelligence compares two App Intelligence evidence snapshots. "
            "It reports evidence movement, not causality or runtime correctness."
        ),
    }


def markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# AppLab Change Intelligence",
        "",
        f"- Engine version: **{report.get('engine_version', '')}**",
        f"- Review state: **{report.get('review_state', 'UNKNOWN')}**",
        f"- Baseline lab: **{(report.get('baseline') or {}).get('lab_version', '')}**",
        f"- Current lab: **{(report.get('current') or {}).get('lab_version', '')}**",
        "",
        "## Summary",
        "",
        f"- Feature truth changes: **{summary.get('feature_truth_changes', 0)}**",
        f"- Capabilities added: **{summary.get('capabilities_added', 0)}**",
        f"- Capabilities removed: **{summary.get('capabilities_removed', 0)}**",
        f"- Entities + / -: **{summary.get('entities_added', 0)} / {summary.get('entities_removed', 0)}**",
        f"- Surfaces + / -: **{summary.get('surfaces_added', 0)} / {summary.get('surfaces_removed', 0)}**",
        f"- New findings: **{summary.get('new_findings', 0)}**",
        f"- Resolved findings: **{summary.get('resolved_findings', 0)}**",
        "",
    ]

    feature = report.get("feature_truth") if isinstance(report.get("feature_truth"), dict) else {}
    changed = feature.get("changed") if isinstance(feature.get("changed"), list) else []
    if changed:
        lines.extend(["## Feature Truth Changes", ""])
        for row in changed[:40]:
            if isinstance(row, dict):
                lines.append(
                    f"- **{row.get('capability', '')}**: "
                    f"{row.get('before', '')} → {row.get('after', '')}"
                )
        lines.append("")

    consistency = (
        report.get("consistency")
        if isinstance(report.get("consistency"), dict)
        else {}
    )
    new_findings = (
        consistency.get("new_findings")
        if isinstance(consistency.get("new_findings"), list)
        else []
    )
    if new_findings:
        lines.extend(["## New Review Findings", ""])
        for row in new_findings[:30]:
            if isinstance(row, dict):
                subject = f" · {row.get('subject')}" if row.get("subject") else ""
                lines.append(
                    f"- **{row.get('severity', '')} / {row.get('domain', '')} / "
                    f"{row.get('kind', '')}**{subject}"
                )
        lines.append("")

    resolved = (
        consistency.get("resolved_findings")
        if isinstance(consistency.get("resolved_findings"), list)
        else []
    )
    if resolved:
        lines.extend(["## Resolved Review Findings", ""])
        for row in resolved[:30]:
            if isinstance(row, dict):
                lines.append(
                    f"- **{row.get('domain', '')} / {row.get('kind', '')}**"
                )
        lines.append("")

    lines.extend([
        "## Guardrails",
        "",
        "- Change Intelligence is advisory and produces no synthetic score.",
        "- New evidence does not automatically prove a regression.",
        "- Resolved static evidence does not automatically prove runtime correctness.",
        "- FAST/FULL/CERTIFICATION remain authoritative for runtime/release decisions.",
        "",
    ])
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "change-intelligence.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "change-intelligence.md").write_text(
        markdown(report),
        encoding="utf-8",
    )


def self_test() -> None:
    baseline = {
        "root_name": "demo",
        "lab_version": "2.3.0",
        "scan": {"confidence": "HIGH"},
        "feature_truth": {
            "capabilities": [
                {"capability": "authentication", "truth": "DOC_ONLY_SIGNAL"},
                {"capability": "local_persistence", "truth": "CODE_CONFIRMED"},
            ]
        },
        "deep_product_model": {
            "entities": [{"name": "Note"}],
        },
        "product_flow_graph": {
            "nodes": [{"id": "lib/home_screen.dart"}],
        },
        "product_consistency": {
            "findings": [
                {
                    "id": "ux-error-state",
                    "domain": "ux",
                    "kind": "ERROR_STATE_EVIDENCE_GAP",
                    "severity": "REVIEW",
                }
            ]
        },
    }
    current = {
        "root_name": "demo",
        "lab_version": "2.4.0",
        "scan": {"confidence": "HIGH"},
        "feature_truth": {
            "capabilities": [
                {"capability": "authentication", "truth": "CODE_CONFIRMED"},
                {"capability": "local_persistence", "truth": "CODE_CONFIRMED"},
                {"capability": "notifications", "truth": "CODE_CONFIRMED"},
            ]
        },
        "deep_product_model": {
            "entities": [{"name": "Note"}, {"name": "Reminder"}],
        },
        "product_flow_graph": {
            "nodes": [
                {"id": "lib/home_screen.dart"},
                {"id": "lib/settings_screen.dart"},
            ],
        },
        "product_consistency": {
            "findings": [
                {
                    "id": "arch-secret",
                    "domain": "architecture",
                    "kind": "POSSIBLE_EMBEDDED_SECRET",
                    "severity": "HIGH_REVIEW",
                }
            ]
        },
    }
    report = build_diff(baseline, current)
    assert report["review_state"] == "HIGH_REVIEW"
    assert report["summary"]["feature_truth_changes"] == 2
    assert report["summary"]["capabilities_added"] == 1
    assert report["summary"]["entities_added"] == 1
    assert report["summary"]["surfaces_added"] == 1
    assert report["summary"]["new_findings"] == 1
    assert report["summary"]["resolved_findings"] == 1

    with tempfile.TemporaryDirectory() as raw:
        out = Path(raw)
        write_outputs(report, out)
        assert (out / "change-intelligence.json").is_file()
        assert (out / "change-intelligence.md").is_file()

    print("AppLab Change Intelligence self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline")
    parser.add_argument("--current")
    parser.add_argument("--output-dir", default="applab-change-intelligence")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.baseline or not args.current:
        raise SystemExit("--baseline and --current are required unless --self-test is used")

    baseline = read_json(Path(args.baseline))
    current = read_json(Path(args.current))
    report = build_diff(baseline, current)
    write_outputs(report, Path(args.output_dir))
    print(json.dumps({
        "engine_version": report["engine_version"],
        "review_state": report["review_state"],
        "new_findings": report["summary"]["new_findings"],
        "resolved_findings": report["summary"]["resolved_findings"],
        "output_dir": str(Path(args.output_dir)),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
