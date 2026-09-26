#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import impact_engine
import smart_test_plan

RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

def synthetic_records(files: list[str]) -> list[dict]:
    return [
        {
            "status": "M",
            "path": path,
            "previous_path": "",
            "additions": 5,
            "deletions": 2,
        }
        for path in files
    ]

def run_case(case: dict) -> None:
    files = list(case.get("files", []))
    count = int(case.get("generated_count", 0) or 0)
    pattern = str(case.get("generated_pattern", "file_{i}.txt"))
    if count:
        files.extend(pattern.format(i=i) for i in range(count))
    records = synthetic_records(files)
    imports = list(case.get("imports", []))
    score, _ = impact_engine.risk_score(records, imports, 0)
    risk = impact_engine.risk_label(score)
    modules = impact_engine.impacted_modules(records, str(case.get("engine", "flutter")))
    conf = impact_engine.confidence(records, "ok", modules)
    lane, mode, _ = impact_engine.choose_lane("fast", records, "ok", risk, conf)
    if len(records) > impact_engine.MAX_CHANGED_FILES:
        lane, mode = "FULL_RUNTIME", "full"

    expected_lane = str(case["expected_lane"])
    if lane != expected_lane:
        raise AssertionError(f"{case['name']}: expected lane {expected_lane}, got {lane} (risk={risk}, confidence={conf})")

    max_risk = case.get("max_risk")
    if max_risk and RISK_ORDER[risk] > RISK_ORDER[str(max_risk)]:
        raise AssertionError(f"{case['name']}: risk {risk} exceeds {max_risk}")

    plan = smart_test_plan.classify(files, mode, "a" * 40)
    selected = plan["selected_labs"]
    for lab in case.get("required_labs", []):
        if not selected.get(lab, False):
            raise AssertionError(f"{case['name']}: required lab {lab} was not selected")

def run_corpus(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported corpus schema")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("corpus must contain cases")
    for case in cases:
        run_case(case)
    print(f"AppLab impact regression corpus PASS ({len(cases)} cases)")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="tests/impact-planner-corpus.json")
    args = parser.parse_args()
    run_corpus(Path(args.corpus))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
