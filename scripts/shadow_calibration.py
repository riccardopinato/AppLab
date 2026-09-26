#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

LAB_RESULT_FIELDS = {
    "system": "system_lab",
    "performance": "performance_lab",
    "network": "network_lab",
    "persistence": "persistence_lab",
    "configuration": "configuration_lab",
    "resource_pressure": "resource_pressure_lab",
    "background": "background_lab",
    "storage": "storage_lab",
    "upgrade": "upgrade_lab",
}
FAIL_STATES = {"FAIL", "ERROR"}

def evaluate(analysis_plan: Path, result_json: Path) -> dict[str, Any]:
    plan = json.loads(analysis_plan.read_text(encoding="utf-8"))
    result = json.loads(result_json.read_text(encoding="utf-8"))
    adaptive = plan.get("adaptive_impact", {})
    shadow = bool(adaptive.get("shadow_full"))
    predicted = adaptive.get("predicted_selected_labs", {})
    findings: list[dict[str, str]] = []
    false_negative = False
    skipped_prediction_count = 0
    checked_count = 0

    if shadow and isinstance(predicted, dict):
        for lab, field in LAB_RESULT_FIELDS.items():
            would_run = predicted.get(lab, True)
            actual = str(result.get(field, "UNKNOWN")).upper()
            if would_run is False:
                skipped_prediction_count += 1
                if actual not in {"SKIPPED", "NO_BASELINE", "UNKNOWN", ""}:
                    checked_count += 1
                if actual in FAIL_STATES:
                    false_negative = True
                    findings.append({
                        "lab": lab,
                        "predicted": "SKIP",
                        "actual": actual,
                        "severity": "CRITICAL",
                    })

    payload = {
        "schema_version": 1,
        "shadow_full": shadow,
        "predicted_skips": skipped_prediction_count,
        "verified_predicted_skips": checked_count,
        "false_negative": false_negative,
        "findings": findings,
        "status": "FAIL" if false_negative else ("PASS" if shadow else "NOT_APPLICABLE"),
    }
    return payload

def write(report_dir: Path, payload: dict[str, Any]) -> None:
    (report_dir / "shadow-calibration.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# AppLab FAST/FULL Shadow Calibration",
        "",
        f"- Shadow run: **{str(payload['shadow_full']).lower()}**",
        f"- Predicted FAST skips: **{payload['predicted_skips']}**",
        f"- Verified predicted skips in FULL: **{payload['verified_predicted_skips']}**",
        f"- False negative: **{str(payload['false_negative']).lower()}**",
        f"- Status: **{payload['status']}**",
    ]
    if payload["findings"]:
        lines += ["", "## Findings"]
        for item in payload["findings"]:
            lines.append(f"- {item['lab']}: predicted {item['predicted']}, actual {item['actual']}")
    (report_dir / "shadow-calibration.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        plan = root / "analysis-plan.json"
        result = root / "result.json"
        plan.write_text(json.dumps({
            "adaptive_impact": {
                "shadow_full": True,
                "predicted_selected_labs": {"network": False, "storage": True},
            }
        }), encoding="utf-8")
        result.write_text(json.dumps({"network_lab": "FAIL", "storage_lab": "PASS"}), encoding="utf-8")
        payload = evaluate(plan, result)
        assert payload["false_negative"]
        assert payload["status"] == "FAIL"
    print("AppLab shadow calibration self-test PASS")

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--report-dir")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.report_dir:
        raise SystemExit("--report-dir is required")
    root = Path(args.report_dir)
    payload = evaluate(root / "analysis-plan.json", root / "result.json")
    write(root, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 2 if payload["false_negative"] else 0

if __name__ == "__main__":
    raise SystemExit(main())
