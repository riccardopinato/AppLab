#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--resolved-sha", default="")
    parser.add_argument("--history-key", required=True)
    parser.add_argument("--engine", default="flutter")
    parser.add_argument("--pipeline-status", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--analysis-mode", choices=("fast", "full", "certification"), default="full")
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    result_path = report_dir / "result.json"
    summary_path = report_dir / "summary.md"

    if result_path.exists():
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
    else:
        payload = {}

    if not payload:
        payload = {
            "schema_version": 1,
            "applab_version": "0.9.0",
            "result": "FAIL",
            "analysis_mode": args.analysis_mode,
            "reason": "Pipeline ended before the Android verifier produced a result.",
            "apk": "",
            "package_id": "",
            "pid": "",
            "maestro": "SKIPPED",
            "visual_qa": "SKIPPED",
            "visual_regression": "NO_BASELINE",
            "visual_journey": "SKIPPED",
            "interaction_crawl": "SKIPPED",
            "system_lab": "SKIPPED",
            "network_lab": "SKIPPED",
            "persistence_lab": "SKIPPED",
            "configuration_lab": "SKIPPED",
            "resource_pressure_lab": "SKIPPED",
            "background_lab": "SKIPPED",
            "storage_lab": "SKIPPED",
            "upgrade_lab": "NO_BASELINE",
            "performance_lab": "SKIPPED",
            "evidence": {},
        }

    plan_path = report_dir / "analysis-plan.json"
    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            plan = {}
        if isinstance(plan, dict):
            payload.update({
                "analysis_lane": plan.get("lane"),
                "risk_score": plan.get("risk_score"),
                "risk_level": plan.get("risk_level"),
                "confidence": plan.get("confidence"),
                "analysis_domains": plan.get("domains", []),
                "selected_labs": plan.get("selected_labs", {}),
                "shadow_full": bool(plan.get("shadow_full")),
                "runtime_changed": bool(plan.get("runtime_changed")),
                "planner_duration_ms": plan.get("planner_duration_ms"),
                "changed_file_count": len(plan.get("changed_files", [])) if isinstance(plan.get("changed_files"), list) else None,
                "churn": plan.get("churn"),
            })

    contract_copy = report_dir / "build-contract.json"
    if contract_copy.is_file():
        try:
            build_contract = json.loads(contract_copy.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            build_contract = {}
        if isinstance(build_contract, dict):
            payload["analysis_contract_fingerprint"] = build_contract.get("analysis_contract_fingerprint")

    shadow_path = report_dir / "shadow-calibration.json"
    if shadow_path.is_file():
        try:
            shadow = json.loads(shadow_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            shadow = {}
        if isinstance(shadow, dict):
            payload["shadow_calibration"] = shadow

    telemetry_path = report_dir / "telemetry.json"
    if telemetry_path.is_file():
        try:
            telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            telemetry = {}
        if isinstance(telemetry, dict):
            payload["telemetry"] = telemetry

    payload.update(
        {
            "repository": args.repository,
            "requested_ref": args.ref,
            "resolved_sha": args.resolved_sha,
            "history_key": args.history_key,
            "engine": args.engine,
            "pipeline_status": args.pipeline_status,
            "workflow_run_id": args.run_id,
            "analysis_mode": payload.get("analysis_mode") or args.analysis_mode,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    if args.pipeline_status != "success" and payload.get("result") == "PASS":
        payload["result"] = "FAIL"
        payload["reason"] = "A project-gate step failed after the Android verifier."

    result_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if not summary_path.exists():
        summary_path.write_text(
            "# AppLab report\n\n"
            f"- Result: {payload.get('result', 'FAIL')}\n"
            f"- Repository: {args.repository}\n"
            f"- Ref: {args.ref}\n"
            f"- Analysis mode: {payload.get('analysis_mode', args.analysis_mode)}\n"
            f"- Resolved SHA: {args.resolved_sha or 'unavailable'}\n"
            f"- Reason: {payload.get('reason') or 'See workflow logs.'}\n",
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
