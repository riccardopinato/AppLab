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

    plan = {}
    metrics = {}
    shadow = {}
    build_contract = {}
    for name, target in (
        ("analysis-plan.json", "plan"),
        ("pipeline-metrics.json", "metrics"),
        ("shadow-calibration.json", "shadow"),
        ("build-contract.json", "build_contract"),
    ):
        path = report_dir / name
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            value = {}
        if target == "plan":
            plan = value
        elif target == "metrics":
            metrics = value
        elif target == "shadow":
            shadow = value
        else:
            build_contract = value

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
            "analysis_lane": plan.get("lane", payload.get("analysis_lane", "FULL_RUNTIME")),
            "risk_score": plan.get("risk_score", payload.get("risk_score")),
            "confidence": plan.get("confidence", payload.get("confidence")),
            "selected_labs": plan.get("selected_labs", payload.get("selected_labs", {})),
            "predicted_selected_labs": plan.get("predicted_selected_labs", payload.get("predicted_selected_labs", {})),
            "shadow_full": bool(plan.get("shadow_full", payload.get("shadow_full", False))),
            "pipeline_metrics": metrics or payload.get("pipeline_metrics", {}),
            "shadow_calibration": shadow or payload.get("shadow_calibration", {}),
            "domain_fingerprints": build_contract.get("domain_fingerprints", payload.get("domain_fingerprints", {})),
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
