#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

NON_RUNTIME_LANES = {"NO_RUNTIME_CHANGE", "STATIC_ONLY"}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--resolved-sha", required=True)
    parser.add_argument("--history-key", required=True)
    parser.add_argument("--engine", required=True)
    args = parser.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    lane = str(plan.get("lane", ""))
    if lane not in NON_RUNTIME_LANES:
        raise SystemExit(f"preflight_result only supports non-runtime lanes, got {lane}")

    report = Path(args.report_dir)
    report.mkdir(parents=True, exist_ok=True)
    target_plan = report / "analysis-plan.json"
    target_plan.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    fingerprint = ""
    fingerprint_path = report / "domain-fingerprints.json"
    if fingerprint_path.is_file():
        try:
            fp_payload = json.loads(fingerprint_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            fp_payload = {}
        if isinstance(fp_payload, dict):
            fingerprint = str(fp_payload.get("selected", ""))

    reason = (
        "Runtime-affecting sources are unchanged; previous trusted runtime evidence remains applicable."
        if lane == "NO_RUNTIME_CHANGE"
        else "Only tests/static-analysis configuration changed; static verification passed and runtime APK is unchanged."
    )
    skipped = "SKIPPED"
    payload = {
        "schema_version": 1,
        "applab_version": "0.9.0",
        "result": "PASS",
        "reason": reason,
        "analysis_mode": str(plan.get("mode", "fast")),
        "analysis_lane": lane,
        "risk_score": plan.get("risk_score"),
        "risk_level": plan.get("risk_level"),
        "confidence": plan.get("confidence"),
        "analysis_domains": plan.get("domains", []),
        "selected_labs": plan.get("selected_labs", {}),
        "analysis_contract_fingerprint": fingerprint,
        "shadow_full": False,
        "runtime_changed": False,
        "runtime_evidence_sha": plan.get("baseline_sha", ""),
        "verification_scope": "SOURCE_ONLY" if lane == "NO_RUNTIME_CHANGE" else "STATIC_ONLY",
        "repository": args.repository,
        "requested_ref": args.ref,
        "resolved_sha": args.resolved_sha,
        "history_key": args.history_key,
        "engine": args.engine,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "apk": "",
        "package_id": "",
        "pid": "",
        "maestro": skipped,
        "visual_qa": skipped,
        "visual_regression": skipped,
        "visual_journey": skipped,
        "interaction_crawl": skipped,
        "system_lab": skipped,
        "network_lab": skipped,
        "persistence_lab": skipped,
        "configuration_lab": skipped,
        "resource_pressure_lab": skipped,
        "background_lab": skipped,
        "storage_lab": skipped,
        "upgrade_lab": skipped,
        "performance_lab": skipped,
        "evidence": {"analysis_plan": "analysis-plan.json", "telemetry": "telemetry.json"},
    }
    (report / "result.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (report / "summary.md").write_text(
        "# AppLab v0.9 adaptive verification\n\n"
        f"- Result: PASS\n"
        f"- Lane: {lane}\n"
        f"- Risk: {plan.get('risk_level')} ({plan.get('risk_score')}/100)\n"
        f"- Confidence: {plan.get('confidence')}\n"
        f"- Runtime changed: no\n"
        f"- Runtime evidence baseline: {plan.get('baseline_sha') or 'unavailable'}\n"
        f"- Reason: {reason}\n",
        encoding="utf-8",
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
