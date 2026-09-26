#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

LAB_FIELD = {
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

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        import tempfile
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan = {
                "shadow_full": True,
                "selected_labs": {"network": False, "storage": True},
            }
            result = {"network_lab": "FAIL", "storage_lab": "PASS"}
            (root / "plan.json").write_text(json.dumps(plan))
            (root / "result.json").write_text(json.dumps(result))
            outcome = evaluate(plan, result)
            assert outcome["false_negative_count"] == 1
            assert outcome["status"] == "DIVERGED"
        print("AppLab shadow calibration self-test PASS")
        return 0

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    payload = evaluate(plan, result)
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0

def evaluate(plan: dict, result: dict) -> dict:
    if not bool(plan.get("shadow_full")):
        return {"schema_version": 1, "status": "NOT_SAMPLED", "false_negative_count": 0, "false_negatives": []}
    selected = plan.get("selected_labs", {})
    false_negatives = []
    over_selected = []
    for lab, field in LAB_FIELD.items():
        actual = str(result.get(field, "SKIPPED")).upper()
        predicted = bool(selected.get(lab, True))
        if not predicted and actual in {"FAIL", "ERROR"}:
            false_negatives.append({"lab": lab, "actual": actual})
        if predicted and actual == "SKIPPED":
            over_selected.append({"lab": lab, "actual": actual})
    return {
        "schema_version": 1,
        "status": "DIVERGED" if false_negatives else "MATCH",
        "false_negative_count": len(false_negatives),
        "false_negatives": false_negatives,
        "over_selected_count": len(over_selected),
        "over_selected": over_selected,
    }

if __name__ == "__main__":
    raise SystemExit(main())
