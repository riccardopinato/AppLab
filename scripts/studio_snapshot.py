#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STUDIO_VERSION = "2.0.0"


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def present_capabilities(app: dict[str, Any]) -> list[str]:
    product = app.get("product") if isinstance(app.get("product"), dict) else {}
    rows = product.get("feature_signals") if isinstance(product.get("feature_signals"), list) else []
    result: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("status", "")).upper() != "PRESENT":
            continue
        label = str(row.get("label", "")).strip()
        if label:
            result.append(label)
    return sorted(set(result))


def count_findings(app: dict[str, Any], section: str) -> int:
    block = app.get(section) if isinstance(app.get(section), dict) else {}
    rows = block.get("findings") if isinstance(block.get("findings"), list) else []
    return sum(1 for row in rows if isinstance(row, dict))


def project_summary(project_id: str, project_dir: Path) -> dict[str, Any] | None:
    app = read_json(project_dir / "app-intelligence.json")
    market = read_json(project_dir / "market-intelligence.json")
    audit = read_json(project_dir / "audit-plan.json")

    if app is None and market is None and audit is None:
        return None

    row: dict[str, Any] = {
        "project_id": project_id,
        "product": None,
        "ux": None,
        "architecture": None,
        "market": None,
        "audit": None,
    }

    if app:
        product = app.get("product") if isinstance(app.get("product"), dict) else {}
        stack = product.get("stack") if isinstance(product.get("stack"), dict) else {}
        scan = app.get("scan") if isinstance(app.get("scan"), dict) else {}
        architecture = (
            app.get("architecture_data")
            if isinstance(app.get("architecture_data"), dict)
            else {}
        )
        data = architecture.get("data") if isinstance(architecture.get("data"), dict) else {}
        row["product"] = {
            "engine": str(stack.get("engine", "unknown")),
            "confidence": str(scan.get("confidence", "UNKNOWN")),
            "capabilities": present_capabilities(app),
            "screen_like_files": int(
                ((product.get("surface") or {}).get("screen_like_files", 0))
                if isinstance(product.get("surface"), dict)
                else 0
            ),
        }
        row["ux"] = {
            "review_signals": count_findings(app, "ux_product"),
        }
        row["architecture"] = {
            "review_signals": count_findings(app, "architecture_data"),
            "local_first": str(data.get("local_first_assessment", "UNKNOWN")),
        }

    if market:
        capabilities = market.get("capabilities") if isinstance(market.get("capabilities"), list) else []
        reviews = market.get("reviews") if isinstance(market.get("reviews"), dict) else {}
        recurring = (
            reviews.get("recurring_pain_signals")
            if isinstance(reviews.get("recurring_pain_signals"), list)
            else []
        )
        row["market"] = {
            "competitors": int(market.get("competitor_count", 0) or 0),
            "common_gap_reviews": sum(
                1
                for item in capabilities
                if isinstance(item, dict)
                and item.get("classification") == "COMMON_MARKET_GAP_REVIEW"
            ),
            "differentiator_signals": sum(
                1
                for item in capabilities
                if isinstance(item, dict)
                and item.get("classification") == "PROJECT_DIFFERENTIATOR_SIGNAL"
            ),
            "recurring_pain_signals": len(recurring),
        }

    if audit:
        selected = audit.get("selected_labs") if isinstance(audit.get("selected_labs"), list) else []
        row["audit"] = {
            "selected_lab_count": int(audit.get("selected_lab_count", len(selected)) or 0),
            "manual_review_required": bool(audit.get("manual_review_required", False)),
            "top_labs": [
                {
                    "lab": str(item.get("lab", "")),
                    "priority": str(item.get("priority", "")),
                }
                for item in selected[:8]
                if isinstance(item, dict)
            ],
        }

    return row


def build_snapshot(evidence_root: Path) -> dict[str, Any]:
    if not evidence_root.is_dir():
        raise ValueError(f"Evidence root does not exist: {evidence_root}")

    projects: list[dict[str, Any]] = []
    for project_dir in sorted(path for path in evidence_root.iterdir() if path.is_dir()):
        row = project_summary(project_dir.name, project_dir)
        if row is not None:
            projects.append(row)

    portfolio_payload = read_json(evidence_root / "cross-app-intelligence.json") or {}
    portfolio = {
        "project_count": int(portfolio_payload.get("project_count", 0) or 0),
        "reusable_pattern_candidates": (
            portfolio_payload.get("reusable_pattern_candidates", [])
            if isinstance(portfolio_payload.get("reusable_pattern_candidates"), list)
            else []
        )[:30],
        "recurrent_review_signals": (
            portfolio_payload.get("recurrent_review_signals", [])
            if isinstance(portfolio_payload.get("recurrent_review_signals"), list)
            else []
        )[:30],
        "portfolio_profile": (
            portfolio_payload.get("portfolio_profile", {})
            if isinstance(portfolio_payload.get("portfolio_profile"), dict)
            else {}
        ),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "studio_version": STUDIO_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "projects": len(projects),
            "with_market": sum(1 for row in projects if row.get("market") is not None),
            "manual_review": sum(
                1
                for row in projects
                if isinstance(row.get("audit"), dict)
                and row["audit"].get("manual_review_required")
            ),
            "recurrent_patterns": len(portfolio["reusable_pattern_candidates"]),
        },
        "projects": projects,
        "portfolio": portfolio,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        project = root / "demo"
        project.mkdir()
        (project / "app-intelligence.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "scan": {"confidence": "HIGH"},
                    "product": {
                        "stack": {"engine": "flutter"},
                        "surface": {"screen_like_files": 4},
                        "feature_signals": [
                            {"label": "authentication", "status": "PRESENT"},
                            {"label": "ai_or_ml", "status": "NOT_DETECTED"},
                        ],
                    },
                    "ux_product": {"findings": [{"kind": "A"}]},
                    "architecture_data": {
                        "findings": [],
                        "data": {"local_first_assessment": "SUPPORTED_BY_SIGNALS"},
                    },
                }
            ),
            encoding="utf-8",
        )
        (project / "market-intelligence.json").write_text(
            json.dumps(
                {
                    "competitor_count": 3,
                    "capabilities": [
                        {"classification": "COMMON_MARKET_GAP_REVIEW"},
                        {"classification": "PROJECT_DIFFERENTIATOR_SIGNAL"},
                    ],
                    "reviews": {"recurring_pain_signals": [{}, {}]},
                }
            ),
            encoding="utf-8",
        )
        (project / "audit-plan.json").write_text(
            json.dumps(
                {
                    "selected_lab_count": 4,
                    "manual_review_required": True,
                    "selected_labs": [
                        {"lab": "product-analysis", "priority": "MANDATORY"}
                    ],
                }
            ),
            encoding="utf-8",
        )
        (root / "cross-app-intelligence.json").write_text(
            json.dumps(
                {
                    "project_count": 2,
                    "reusable_pattern_candidates": [{"key": "authentication"}],
                    "recurrent_review_signals": [{"key": "accessibility"}],
                }
            ),
            encoding="utf-8",
        )

        snapshot = build_snapshot(root)
        assert snapshot["summary"]["projects"] == 1
        assert snapshot["summary"]["with_market"] == 1
        assert snapshot["summary"]["manual_review"] == 1
        assert snapshot["summary"]["recurrent_patterns"] == 1
        assert snapshot["projects"][0]["product"]["engine"] == "flutter"
        assert snapshot["projects"][0]["market"]["competitors"] == 3
        assert snapshot["projects"][0]["audit"]["selected_lab_count"] == 4
        print("AppLab Studio snapshot self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.evidence_root or not args.output:
        raise SystemExit("--evidence-root and --output are required")

    snapshot = build_snapshot(Path(args.evidence_root))
    Path(args.output).write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"AppLab Studio snapshot: {snapshot['summary']['projects']} projects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
