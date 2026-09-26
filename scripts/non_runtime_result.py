#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

LAB_FIELDS = (
    "system_lab",
    "network_lab",
    "persistence_lab",
    "configuration_lab",
    "resource_pressure_lab",
    "background_lab",
    "storage_lab",
    "upgrade_lab",
    "performance_lab",
)

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
    parser.add_argument("--static-status", default="PASS")
    args = parser.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    lane = str(plan.get("lane", ""))
    if lane not in {"no_runtime", "static_only"}:
        raise SystemExit(f"non-runtime result cannot finalize lane {lane!r}")

    static_status = args.static_status.strip().upper()
    result = "PASS" if static_status == "PASS" else "FAIL"
    reason = (
        "Runtime-affecting files were not changed; previous verified runtime evidence remains applicable."
        if lane == "no_runtime"
        else "Static-only change completed targeted static verification without rebuilding the APK."
    )
    if result != "PASS":
        reason = "Targeted static verification failed."

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "applab_version": "0.9.0",
        "result": result,
        "reason": reason,
        "repository": args.repository,
        "requested_ref": args.ref,
        "resolved_sha": args.resolved_sha,
        "history_key": args.history_key,
        "engine": args.engine,
        "pipeline_status": "success" if result == "PASS" else "failure",
        "workflow_run_id": args.run_id,
        "analysis_mode": "fast",
        "analysis_lane": lane,
        "risk": plan.get("risk", {}),
        "confidence": plan.get("confidence", {}),
        "runtime_required": False,
        "runtime_evidence_reused_from": str(plan.get("baseline_sha", "")),
        "changed_files": plan.get("changed_files", []),
        "adaptive_plan": plan,
        "maestro": "SKIPPED",
        "visual_qa": "SKIPPED",
        "visual_regression": "SKIPPED",
        "visual_journey": "SKIPPED",
        "interaction_crawl": "SKIPPED",
        **{field: "SKIPPED" for field in LAB_FIELDS},
        "certification_status": "NOT_REQUESTED",
        "release": {},
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
        "# AppLab v0.9 Adaptive Analysis\n\n"
        f"- Result: {result}\n"
        f"- Lane: {lane}\n"
        f"- Risk: {plan.get('risk', {}).get('level', 'unknown')} "
        f"({plan.get('risk', {}).get('score', '?')}/100)\n"
        f"- Confidence: {plan.get('confidence', {}).get('score', '?')}\n"
        f"- Runtime executed: no\n"
        f"- Runtime evidence baseline: {plan.get('baseline_sha') or 'none'}\n"
        f"- Reason: {reason}\n",
        encoding="utf-8",
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
