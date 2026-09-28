#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
LAB_VERSION = "1.6.0"


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def present_capabilities(report: dict[str, Any]) -> set[str]:
    product = report.get("product") if isinstance(report.get("product"), dict) else {}
    rows = product.get("feature_signals") if isinstance(product.get("feature_signals"), list) else []
    result: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("status", "")).upper() == "PRESENT":
            label = str(row.get("label", "")).strip()
            if label:
                result.add(label)
    return result


def finding_kinds(report: dict[str, Any], section: str) -> set[str]:
    block = report.get(section) if isinstance(report.get(section), dict) else {}
    findings = block.get("findings") if isinstance(block.get("findings"), list) else []
    return {
        str(row.get("kind", "")).strip()
        for row in findings
        if isinstance(row, dict) and str(row.get("kind", "")).strip()
    }


def add(plan: dict[str, dict[str, Any]], key: str, reason: str, priority: str = "NORMAL") -> None:
    order = {"LOW": 0, "NORMAL": 1, "HIGH": 2, "MANDATORY": 3}
    current = plan.get(key)
    if current is None:
        plan[key] = {"lab": key, "priority": priority, "reasons": [reason]}
        return
    if reason not in current["reasons"]:
        current["reasons"].append(reason)
    if order[priority] > order[current["priority"]]:
        current["priority"] = priority


def build_plan(app: dict[str, Any], *, has_market_evidence: bool = False) -> dict[str, Any]:
    confidence = str((app.get("scan") or {}).get("confidence", "LOW")).upper()
    product = app.get("product") if isinstance(app.get("product"), dict) else {}
    stack = product.get("stack") if isinstance(product.get("stack"), dict) else {}
    engine = str(stack.get("engine", "unknown"))
    capabilities = present_capabilities(app)
    ux_findings = finding_kinds(app, "ux_product")
    architecture_findings = finding_kinds(app, "architecture_data")
    local_first = str(
        ((app.get("architecture_data") or {}).get("data") or {}).get(
            "local_first_assessment", "UNKNOWN"
        )
    )

    labs: dict[str, dict[str, Any]] = {}
    add(labs, "product-analysis", "Canonical project understanding is always required.", "MANDATORY")
    add(labs, "ux-product", "UX/Product evidence is part of every product audit.", "MANDATORY")
    add(labs, "architecture-data", "Architecture/Data evidence is part of every product audit.", "MANDATORY")

    if confidence in {"LOW", "UNKNOWN"}:
        add(labs, "full-source-review", "App Intelligence confidence is low/unknown.", "HIGH")

    if "local_persistence" in capabilities or local_first != "UNKNOWN":
        add(labs, "storage-data-integrity", "Persistent local state was detected.", "HIGH")
        add(labs, "persistence-restart", "Persistent local state should survive restart.", "HIGH")
        add(labs, "upgrade-migration", "Persistent data creates migration risk.", "HIGH")

    if "network_api" in capabilities or "cloud_or_sync" in capabilities:
        add(labs, "network-offline", "Network/cloud capability was detected.", "HIGH")

    if "background_execution" in capabilities:
        add(labs, "background-doze-recovery", "Background execution capability was detected.", "HIGH")
        add(labs, "resource-pressure-process-death", "Background work increases process-recovery risk.", "NORMAL")

    if "notifications" in capabilities:
        add(labs, "permissions-notifications-system-ui", "Notification capability was detected.", "HIGH")

    if "maps_or_location" in capabilities:
        add(labs, "permissions-notifications-system-ui", "Location capability requires system-permission review.", "HIGH")
        add(labs, "visual-journey", "Map/location surfaces benefit from multi-screen visual verification.", "NORMAL")

    if "media_capture" in capabilities:
        add(labs, "permissions-notifications-system-ui", "Camera/audio/media capability requires permission review.", "HIGH")

    if "authentication" in capabilities:
        add(labs, "safe-interaction-crawler", "Authentication implies user-state transitions.", "NORMAL")

    if "monetization" in capabilities:
        add(labs, "monetization-review", "Monetization capability was detected.", "HIGH")

    if "ai_or_ml" in capabilities:
        add(labs, "ai-governance-review", "AI/ML capability was detected.", "HIGH")

    if "export_or_backup" in capabilities:
        add(labs, "data-lifecycle-review", "Export/backup capability creates data portability obligations.", "NORMAL")

    if ux_findings:
        add(labs, "ux-manual-review", f"{len(ux_findings)} UX/Product review signal(s) detected.", "HIGH")

    if architecture_findings:
        add(labs, "architecture-manual-review", f"{len(architecture_findings)} architecture review signal(s) detected.", "HIGH")

    if has_market_evidence:
        add(labs, "competitor-market", "Traceable market evidence was supplied.", "NORMAL")

    # Core runtime coverage is always retained when an Android-compatible runtime exists.
    if engine in {"flutter", "native_android"}:
        add(labs, "core-runtime", f"Android-compatible engine detected: {engine}.", "MANDATORY")
        add(labs, "visual-regression", "Runtime UI regression coverage is a core AppLab control.", "MANDATORY")
        add(labs, "configuration-lifecycle", "Lifecycle/configuration coverage is a core mobile risk.", "NORMAL")
        add(labs, "performance", "Performance baseline is useful for mobile runtime changes.", "NORMAL")

    ordered = sorted(
        labs.values(),
        key=lambda item: (
            {"MANDATORY": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}[item["priority"]],
            item["lab"],
        ),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "engine": engine,
        "scan_confidence": confidence,
        "capabilities": sorted(capabilities),
        "selected_labs": ordered,
        "selected_lab_count": len(ordered),
        "manual_review_required": any(
            item["lab"] in {"full-source-review", "ux-manual-review", "architecture-manual-review"}
            for item in ordered
        ),
        "market_evidence_supplied": has_market_evidence,
        "guardrails": {
            "advisory_plan": True,
            "cannot_skip_certification_requirements": True,
            "uncertainty_broadens_coverage": True,
            "no_hidden_feature_creation": True,
            "no_automatic_market_fetch": True,
            "principle": "The orchestrator may add coverage, but never weakens trusted certification requirements.",
        },
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AppLab Autonomous Audit Plan",
        "",
        f"- Orchestrator version: **{report['lab_version']}**",
        f"- Engine: **{report['engine']}**",
        f"- Source confidence: **{report['scan_confidence']}**",
        f"- Selected labs: **{report['selected_lab_count']}**",
        f"- Manual review required: **{report['manual_review_required']}**",
        "",
        "| Priority | Lab | Reason |",
        "|---|---|---|",
    ]
    for item in report["selected_labs"]:
        lines.append(
            f"| {item['priority']} | {item['lab']} | {'; '.join(item['reasons'])} |"
        )
    lines += [
        "",
        "## Guardrails",
        "",
        "- This is an audit plan, not a certification verdict.",
        "- Uncertainty can broaden coverage but cannot reduce mandatory coverage.",
        "- Market analysis runs only when explicit traceable market evidence is supplied.",
        "- The orchestrator does not create product features or modify the target.",
        "",
    ]
    return "\n".join(lines)


def write(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "audit-plan.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "audit-plan.md").write_text(markdown(report), encoding="utf-8")


def self_test() -> None:
    app = {
        "scan": {"confidence": "HIGH"},
        "product": {
            "stack": {"engine": "flutter"},
            "feature_signals": [
                {"label": "local_persistence", "status": "PRESENT"},
                {"label": "cloud_or_sync", "status": "PRESENT"},
                {"label": "notifications", "status": "PRESENT"},
            ],
        },
        "ux_product": {"findings": [{"kind": "ACCESSIBILITY_EVIDENCE_GAP"}]},
        "architecture_data": {
            "data": {"local_first_assessment": "SUPPORTED_BY_SIGNALS"},
            "findings": [],
        },
    }
    report = build_plan(app, has_market_evidence=True)
    selected = {item["lab"] for item in report["selected_labs"]}
    assert "product-analysis" in selected
    assert "storage-data-integrity" in selected
    assert "network-offline" in selected
    assert "permissions-notifications-system-ui" in selected
    assert "competitor-market" in selected
    assert "core-runtime" in selected
    assert report["manual_review_required"] is True
    with tempfile.TemporaryDirectory() as raw:
        write(report, Path(raw))
        assert (Path(raw) / "audit-plan.json").is_file()
        assert (Path(raw) / "audit-plan.md").is_file()
    print("AppLab Autonomous Audit Orchestrator self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-intelligence")
    parser.add_argument("--market-evidence")
    parser.add_argument("--output-dir", default="applab-audit-plan")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.app_intelligence:
        raise SystemExit("--app-intelligence is required unless --self-test is used")

    app = load_json(Path(args.app_intelligence))
    market_supplied = bool(args.market_evidence)
    if market_supplied:
        load_json(Path(args.market_evidence))

    report = build_plan(app, has_market_evidence=market_supplied)
    write(report, Path(args.output_dir))
    print(json.dumps({
        "lab_version": report["lab_version"],
        "selected_labs": report["selected_lab_count"],
        "manual_review_required": report["manual_review_required"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
