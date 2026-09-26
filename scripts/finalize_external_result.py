#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
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
    parser.add_argument("--verification-fingerprint", default="")
    parser.add_argument("--cache-domains", default="core")
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

    analysis_plan_path = report_dir / "analysis-plan.json"
    if analysis_plan_path.is_file():
        try:
            analysis_plan = json.loads(analysis_plan_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            analysis_plan = {}
        adaptive = analysis_plan.get("adaptive_impact", {}) if isinstance(analysis_plan, dict) else {}
        if isinstance(adaptive, dict):
            payload["verification_lane"] = adaptive.get("lane", payload.get("verification_lane", ""))
            payload["risk"] = adaptive.get("risk", payload.get("risk", {}))
            payload["confidence"] = adaptive.get("confidence", payload.get("confidence"))
            payload["shadow_full"] = bool(adaptive.get("shadow_full", payload.get("shadow_full", False)))
            payload["cache_domains"] = adaptive.get("cache_domains", payload.get("cache_domains", []))
            payload["historical_failure_count"] = adaptive.get(
                "historical_failure_count", payload.get("historical_failure_count", 0)
            )
            payload["impacted_modules"] = adaptive.get("impacted_modules", [])
            payload["targeted"] = adaptive.get("targeted", {})
            payload["telemetry"] = adaptive.get("telemetry", payload.get("telemetry", {}))
            if isinstance(payload["telemetry"], dict):
                generated_ms = payload["telemetry"].get("plan_generated_unix_ms")
                if isinstance(generated_ms, (int, float)) and generated_ms > 0:
                    payload["telemetry"]["pipeline_after_plan_ms"] = max(
                        0, int(time.time() * 1000 - generated_ms)
                    )
            payload["calibration_from_lane"] = adaptive.get("calibration_from_lane", "")

    calibration_path = report_dir / "shadow-calibration.json"
    if calibration_path.is_file():
        try:
            payload["shadow_calibration"] = json.loads(calibration_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

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
            "verification_fingerprint": args.verification_fingerprint or payload.get("verification_fingerprint", ""),
            "cache_domains": payload.get("cache_domains") or [x for x in args.cache_domains.split("-") if x],
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
