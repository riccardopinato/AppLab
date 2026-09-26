#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

LAB_FIELDS = {
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


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def compare(plan: dict[str, Any], fast: dict[str, Any], full: dict[str, Any]) -> dict[str, Any]:
    selected = plan.get("selected_labs", {})
    false_negative_labs: list[str] = []
    over_selected_labs: list[str] = []
    comparable = 0

    for lab, field in LAB_FIELDS.items():
        fast_selected = bool(selected.get(lab, False))
        full_state = str(full.get(field, "SKIPPED")).upper()
        if full_state in {"SKIPPED", "NO_BASELINE", ""}:
            continue
        comparable += 1
        if not fast_selected and full_state in {"FAIL", "ERROR"}:
            false_negative_labs.append(lab)
        if fast_selected and full_state == "PASS":
            over_selected_labs.append(lab)

    result = {
        "schema_version": 1,
        "performed": True,
        "comparable_labs": comparable,
        "false_negatives": len(false_negative_labs),
        "false_negative_labs": false_negative_labs,
        "over_selection": len(over_selected_labs),
        "over_selected_labs": over_selected_labs,
        "fast_result": fast.get("result", "UNKNOWN"),
        "shadow_full_result": full.get("result", "UNKNOWN"),
    }
    return result


def apply(main_result: Path, calibration: dict[str, Any]) -> None:
    payload = read_json(main_result)
    payload["shadow_calibration"] = calibration
    if calibration["false_negatives"]:
        payload["result"] = "FAIL"
        payload["reason"] = (
            "FAST shadow calibration discovered a specialist failure that the "
            "selected FAST plan would have skipped: "
            + ", ".join(calibration["false_negative_labs"])
        )
    main_result.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def self_test() -> None:
    plan = {"selected_labs": {lab: False for lab in LAB_FIELDS}}
    plan["selected_labs"]["configuration"] = True
    fast = {"result": "PASS", "configuration_lab": "PASS"}
    full = {
        "result": "FAIL",
        "configuration_lab": "PASS",
        "storage_lab": "FAIL",
    }
    result = compare(plan, fast, full)
    assert result["false_negatives"] == 1
    assert result["false_negative_labs"] == ["storage"]
    print("AppLab shadow calibration self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan")
    parser.add_argument("--fast-result")
    parser.add_argument("--full-result")
    parser.add_argument("--output")
    parser.add_argument("--apply-to", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.plan, args.fast_result, args.full_result, args.output)):
        raise SystemExit("--plan, --fast-result, --full-result and --output are required")
    calibration = compare(
        read_json(Path(args.plan)),
        read_json(Path(args.fast_result)),
        read_json(Path(args.full_result)),
    )
    Path(args.output).write_text(
        json.dumps(calibration, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.apply_to:
        apply(Path(args.apply_to), calibration)
    print(json.dumps(calibration, sort_keys=True))
    return 2 if calibration["false_negatives"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
