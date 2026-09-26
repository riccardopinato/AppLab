#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

LAB_FIELDS = (
    "system_lab", "network_lab", "persistence_lab", "configuration_lab",
    "resource_pressure_lab", "background_lab", "storage_lab",
    "upgrade_lab", "performance_lab",
)

def load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("analysis plan must be an object")
    return payload

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--resolved-sha", required=True)
    parser.add_argument("--history-key", required=True)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--config-fingerprint", default="")
    parser.add_argument("--contract-fingerprint", default="")
    parser.add_argument("--static-status", choices=("PASS", "FAIL", "SKIPPED"), default="SKIPPED")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()

    plan = load(Path(args.plan))
    lane = str(plan.get("lane", "FULL_RUNTIME"))
    if lane not in {"NO_RUNTIME_CHANGE", "STATIC_ONLY"}:
        raise SystemExit(f"preflight result is only valid for short-circuit lanes, got {lane}")

    static_status = args.static_status
    if lane == "NO_RUNTIME_CHANGE":
        static_status = "SKIPPED"
    result = "PASS" if static_status != "FAIL" else "FAIL"
    reason = args.reason.strip()
    if not reason:
        reason = (
            "Runtime-affecting source is unchanged; previous trusted runtime evidence remains applicable."
            if lane == "NO_RUNTIME_CHANGE"
            else "Static-only change verified without rebuilding or launching the APK."
        )

    payload = {
        "schema_version": 2,
        "applab_version": "0.9.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "result": result,
        "reason": reason,
        "repository": args.repository,
        "requested_ref": args.ref,
        "resolved_sha": args.resolved_sha,
        "history_key": args.history_key,
        "engine": args.engine,
        "config_fingerprint": args.config_fingerprint,
        "contract_fingerprint": args.contract_fingerprint,
        "workflow_run_id": args.run_id,
        "analysis_mode": str(plan.get("mode", "fast")),
        "analysis_lane": lane,
        "risk": plan.get("risk", {}),
        "confidence": plan.get("confidence", 0),
        "shadow_full": bool(plan.get("shadow_full", False)),
        "selected_labs": plan.get("selected_labs", {}),
        "analysis_diff": plan.get("diff", {}),
        "impacted_modules": plan.get("impacted_modules", []),
        "planner_elapsed_ms": plan.get("planner_elapsed_ms"),
        "runtime_evidence_inherited_from": str(plan.get("baseline_sha", "")) if lane == "NO_RUNTIME_CHANGE" else "",
        "static_analysis": static_status,
        "apk": "",
        "package_id": "",
        "pid": "",
        "maestro": "SKIPPED",
        "visual_qa": "SKIPPED",
        "visual_regression": "SKIPPED",
        "visual_journey": "SKIPPED",
        "interaction_crawl": "SKIPPED",
        **{field: "SKIPPED" for field in LAB_FIELDS},
        "certification_status": "NOT_REQUESTED",
        "evidence": {"analysis_plan": "analysis-plan.json"},
    }

    report = Path(args.report_dir)
    report.mkdir(parents=True, exist_ok=True)
    (report / "analysis-plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (report / "result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (report / "summary.md").write_text(
        "# AppLab v0.9 Adaptive Verification\n\n"
        f"- Result: **{result}**\n"
        f"- Lane: **{lane}**\n"
        f"- Risk: **{plan.get('risk', {}).get('level', 'UNKNOWN')}**\n"
        f"- Confidence: **{plan.get('confidence', 0)}**\n"
        f"- Static analysis: **{static_status}**\n"
        f"- Runtime build: **SKIPPED**\n"
        f"- Runtime verification: **SKIPPED**\n"
        f"- Reason: {reason}\n",
        encoding="utf-8",
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
