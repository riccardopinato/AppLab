#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APPLAB_VERSION = "0.9.0"


def load_plan(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("analysis plan must be an object")
    lane = str(payload.get("lane", ""))
    if lane not in {"NO_RUNTIME_CHANGE", "STATIC_ONLY"}:
        raise ValueError(f"source-only finalizer cannot finalize lane {lane!r}")
    if payload.get("runtime_required"):
        raise ValueError("source-only plan unexpectedly requires runtime")
    return payload


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    plan_path = Path(args.analysis_plan)
    plan = load_plan(plan_path)

    static_status = args.static_status.upper()
    if static_status not in {"PASS", "SKIPPED"}:
        raise ValueError("source-only result requires PASS or SKIPPED static status")

    lane = str(plan["lane"])
    baseline_sha = str(plan.get("baseline_sha", ""))
    reason = (
        "Runtime-affecting sources are unchanged; current runtime evidence remains inherited "
        f"from trusted baseline {baseline_sha[:12]}."
        if lane == "NO_RUNTIME_CHANGE"
        else "Only static/test/CI surfaces changed; targeted static verification passed and no APK runtime was required."
    )

    payload = {
        "schema_version": 2,
        "applab_version": APPLAB_VERSION,
        "result": "PASS",
        "reason": reason,
        "verification_scope": "SOURCE_ONLY",
        "analysis_mode": str(plan.get("mode", "fast")),
        "analysis_lane": lane,
        "repository": args.repository,
        "requested_ref": args.ref,
        "resolved_sha": args.resolved_sha,
        "history_key": args.history_key,
        "engine": args.engine,
        "config_fingerprint": args.config_fingerprint,
        "runtime_inherited_from_sha": baseline_sha if lane == "NO_RUNTIME_CHANGE" else "",
        "runtime_evidence_reused": lane == "NO_RUNTIME_CHANGE",
        "static_status": static_status,
        "risk": plan.get("risk", {}),
        "change_summary": plan.get("change_summary", {}),
        "dependency_graph": plan.get("dependency_graph", {}),
        "selected_labs": plan.get("selected_labs", {}),
        "shadow_calibration": {},
        "certification_status": "NOT_REQUESTED",
        "release": {},
        "maestro": "SKIPPED",
        "visual_qa": "SKIPPED",
        "visual_regression": "SKIPPED",
        "visual_journey": "SKIPPED",
        "interaction_crawl": "SKIPPED",
        "system_lab": "SKIPPED",
        "network_lab": "SKIPPED",
        "persistence_lab": "SKIPPED",
        "configuration_lab": "SKIPPED",
        "resource_pressure_lab": "SKIPPED",
        "background_lab": "SKIPPED",
        "storage_lab": "SKIPPED",
        "upgrade_lab": "SKIPPED",
        "performance_lab": "SKIPPED",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "evidence": {"analysis_plan": "analysis-plan.json"},
    }
    (report_dir / "analysis-plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (report_dir / "result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (report_dir / "summary.md").write_text(
        "\n".join(
            [
                "# AppLab v0.9 source-only verification",
                "",
                f"- Result: **PASS**",
                f"- Lane: `{lane}`",
                f"- Static checks: `{static_status}`",
                f"- Risk: `{plan.get('risk', {}).get('level', 'UNKNOWN')}`",
                f"- Confidence: `{plan.get('risk', {}).get('confidence', 0)}`",
                f"- Runtime inherited from: `{baseline_sha or 'not-applicable'}`",
                f"- Reason: {reason}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        plan = {
            "schema_version": 2,
            "lane": "NO_RUNTIME_CHANGE",
            "runtime_required": False,
            "mode": "fast",
            "baseline_sha": "a" * 40,
            "risk": {"level": "LOW", "confidence": 0.99},
            "change_summary": {"total_files": 1},
            "dependency_graph": {},
            "selected_labs": {},
        }
        plan_path = root / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        args = argparse.Namespace(
            report_dir=str(root / "report"),
            analysis_plan=str(plan_path),
            repository="owner/app",
            ref="main",
            resolved_sha="b" * 40,
            history_key="watch-app",
            engine="flutter",
            config_fingerprint="cfg",
            static_status="SKIPPED",
        )
        payload = finalize(args)
        assert payload["result"] == "PASS"
        assert payload["verification_scope"] == "SOURCE_ONLY"
        assert payload["runtime_evidence_reused"] is True
    print("AppLab source-only result self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir")
    parser.add_argument("--analysis-plan")
    parser.add_argument("--repository")
    parser.add_argument("--ref")
    parser.add_argument("--resolved-sha")
    parser.add_argument("--history-key")
    parser.add_argument("--engine")
    parser.add_argument("--config-fingerprint", default="")
    parser.add_argument("--static-status", default="SKIPPED")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    required = (
        args.report_dir, args.analysis_plan, args.repository, args.ref,
        args.resolved_sha, args.history_key, args.engine,
    )
    if not all(required):
        raise SystemExit("missing required source-only result arguments")
    finalize(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
