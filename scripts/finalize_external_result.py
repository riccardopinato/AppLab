#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path\n\nfrom contract_fingerprint import compute_selected


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

    plan: dict = {}
    plan_path = report_dir / "analysis-plan.json"
    if plan_path.is_file():
        try:
            loaded = json.loads(plan_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                plan = loaded
        except (json.JSONDecodeError, OSError):
            plan = {}

    if plan:
        payload["analysis_lane"] = plan.get("lane", payload.get("analysis_lane", ""))
        payload["risk"] = plan.get("risk", payload.get("risk", {}))
        payload["change_summary"] = plan.get("change_summary", payload.get("change_summary", {}))
        payload["dependency_graph"] = plan.get("dependency_graph", payload.get("dependency_graph", {}))
        payload["selected_labs"] = plan.get("selected_labs", payload.get("selected_labs", {}))
        payload["static_plan"] = plan.get("static_plan", payload.get("static_plan", {}))
        payload["shadow_full_recommended"] = bool(plan.get("shadow_full_recommended", False))
        payload["verification_contract_fingerprint"] = compute_selected(
            Path(__file__).resolve().parent.parent,
            plan.get("selected_labs", {}),
            certification=str(plan.get("mode", "")) == "certification",
        )[:16]

    shadow_path = report_dir / "shadow-calibration.json"
    if shadow_path.is_file():
        try:
            shadow = json.loads(shadow_path.read_text(encoding="utf-8"))
            if isinstance(shadow, dict):
                payload["shadow_calibration"] = shadow
        except (json.JSONDecodeError, OSError):
            pass

    timings_path = report_dir / "timings.json"
    if timings_path.is_file():
        try:
            timings = json.loads(timings_path.read_text(encoding="utf-8"))
            if isinstance(timings, dict):
                payload["timings"] = timings
        except (json.JSONDecodeError, OSError):
            pass

    payload.setdefault("verification_scope", "RUNTIME")

    payload.update(
        {
            "repository": args.repository,
            "requested_ref": args.ref,
            "resolved_sha": args.resolved_sha,
            "history_key": args.history_key,
            "engine": args.engine,
            "config_fingerprint": args.config_fingerprint,
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
