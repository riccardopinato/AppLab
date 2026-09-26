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
    parser.add_argument("--config-fingerprint", default="")
    parser.add_argument("--contract-fingerprint", default="")
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

    payload.update(
        {
            "repository": args.repository,
            "requested_ref": args.ref,
            "resolved_sha": args.resolved_sha,
            "history_key": args.history_key,
            "engine": args.engine,
            "config_fingerprint": args.config_fingerprint,
            "contract_fingerprint": args.contract_fingerprint,
            "pipeline_status": args.pipeline_status,
            "workflow_run_id": args.run_id,
            "analysis_mode": payload.get("analysis_mode") or args.analysis_mode,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    plan_path = report_dir / "analysis-plan.json"
    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            plan = {}
        if isinstance(plan, dict):
            payload.update(
                {
                    "analysis_requested_mode": plan.get("requested_mode", args.analysis_mode),
                    "analysis_lane": plan.get("lane", "FULL_RUNTIME"),
                    "analysis_risk": plan.get("risk", {}),
                    "analysis_confidence": plan.get("confidence", 0),
                    "analysis_shadow_full": bool(plan.get("shadow_full", False)),
                    "selected_labs": plan.get("selected_labs", {}),
                    "analysis_diff": plan.get("diff", {}),
                    "impacted_modules": plan.get("impacted_modules", []),
                    "planner_elapsed_ms": plan.get("planner_elapsed_ms"),
                }
            )

    timing_path = report_dir / "timings.json"
    if timing_path.is_file():
        try:
            timings = json.loads(timing_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            timings = {}
        if isinstance(timings, dict):
            payload["timings"] = timings

    calibration_path = report_dir / "shadow-calibration.json"
    if calibration_path.is_file():
        try:
            calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            calibration = {}
        if isinstance(calibration, dict):
            payload["shadow_calibration"] = calibration

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

    summary = summary_path.read_text(encoding="utf-8", errors="ignore")
    if "## Adaptive analysis" not in summary and payload.get("analysis_lane"):
        with summary_path.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n## Adaptive analysis\n\n"
                f"- Lane: **{payload.get('analysis_lane')}**\n"
                f"- Requested mode: **{payload.get('analysis_requested_mode', args.analysis_mode)}**\n"
                f"- Effective runtime mode: **{payload.get('analysis_mode', args.analysis_mode)}**\n"
                f"- Risk: **{payload.get('analysis_risk', {}).get('level', 'UNKNOWN')}**\n"
                f"- Confidence: **{payload.get('analysis_confidence', 0)}**\n"
                f"- Shadow FULL sample: **{payload.get('analysis_shadow_full', False)}**\n"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
