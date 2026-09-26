#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

LAB_RESULT_KEYS = {
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

def evaluate(plan: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    selected = plan.get("selected_labs", {}) if isinstance(plan.get("selected_labs"), dict) else {}
    skipped = [lab for lab, enabled in selected.items() if enabled is False and lab in LAB_RESULT_KEYS]
    observations = []
    false_negatives = []
    warning_misses = []
    for lab in skipped:
        observed = str(result.get(LAB_RESULT_KEYS[lab], "MISSING")).upper()
        observations.append({"lab": lab, "planned": "SKIP", "observed": observed})
        if observed in {"FAIL", "ERROR"}:
            false_negatives.append(lab)
        elif observed == "WARN":
            warning_misses.append(lab)
    return {
        "schema_version": 1,
        "shadow_full": bool(plan.get("shadow_full")),
        "skipped_labs_observed": observations,
        "false_negative_labs": false_negatives,
        "warning_miss_labs": warning_misses,
        "diverged": bool(false_negatives),
        "safe": not false_negatives,
    }

def self_test() -> None:
    plan = {"shadow_full": True, "selected_labs": {"network": False, "storage": True}}
    result = {"network_lab": "FAIL", "storage_lab": "PASS"}
    payload = evaluate(plan, result)
    assert payload["diverged"] and payload["false_negative_labs"] == ["network"]
    print("AppLab v0.9 Shadow Calibration self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan")
    parser.add_argument("--result")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.plan or not args.result or not args.output:
        raise SystemExit("--plan, --result and --output are required")
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    payload = evaluate(plan, result)
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
