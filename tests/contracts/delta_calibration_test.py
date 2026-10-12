#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import delta_calibration as calibration  # noqa: E402


def row(repository: str, category: str, actual: str = "PASS") -> dict:
    return {
        "repository": repository,
        "shadow_full": True,
        "playbook": {"category": category},
        "pipeline_metrics": {"shadow_full": True},
        "shadow_calibration": {
            "schema_version": 2,
            "shadow_full": True,
            "divergences": [
                {
                    "lab": "storage",
                    "actual": actual,
                    "kind": "predicted_skip_but_full_executed",
                }
            ],
            "false_negative_count": 1 if actual in {"FAIL", "ERROR"} else 0,
            "missed_warning_count": 1 if actual == "WARN" else 0,
            "missing_baseline_count": 1 if actual == "NO_BASELINE" else 0,
            "over_selection_count": 0,
        },
    }


def main() -> int:
    sparse = calibration.build_report([row("owner/a", "ui_change")])
    assert sparse["state"] == "COLLECTING"
    assert sparse["coverage_reduction_enabled"] is False
    assert sparse["guardrails"]["smart_test_plan_remains_single_authority"] is True

    rows = []
    categories = ("ui_change", "database_migration", "general_code_change")
    for repo_index in range(calibration.MIN_REPOSITORIES):
        repository = f"owner/app-{repo_index}"
        for run_index in range(5):
            rows.append(row(repository, categories[(repo_index + run_index) % len(categories)]))
    ready = calibration.build_report(rows)
    assert ready["state"] == "READY_FOR_EXPERIMENT"
    assert ready["coverage_reduction_enabled"] is False
    assert ready["lab_observations"]["storage"]["state"] == "EVIDENCE_CANDIDATE"

    unsafe = calibration.build_report(rows + [row("owner/app-0", "ui_change", "FAIL")])
    assert unsafe["state"] == "UNSAFE"
    assert unsafe["summary"]["false_negatives"] == 1
    assert unsafe["lab_observations"]["storage"]["state"] == "UNSAFE"

    missing = calibration.build_report(rows + [row("owner/app-0", "ui_change", "NO_BASELINE")])
    assert missing["state"] == "COLLECTING"
    assert missing["lab_observations"]["storage"]["state"] == "EVIDENCE_INCOMPLETE"

    legacy = row("owner/legacy", "ui_change", "WARN")
    del legacy["shadow_calibration"]["missed_warning_count"]
    legacy_report = calibration.build_report([legacy])
    assert legacy_report["summary"]["shadow_runs"] == 0
    assert legacy_report["state"] == "COLLECTING"

    casing_rows = []
    casing = ("Owner/App", "owner/app", "OWNER/APP", "oWnEr/aPp")
    for index in range(20):
        casing_rows.append(row(casing[index % len(casing)], categories[index % len(categories)]))
    casing_report = calibration.build_report(casing_rows)
    assert casing_report["summary"]["repositories"] == 1
    assert casing_report["summary"]["qualified_repositories"] == 1
    assert casing_report["state"] == "COLLECTING"

    planner = (ROOT / "scripts/smart_test_plan.py").read_text(encoding="utf-8")
    assert "import delta_calibration" not in planner
    assert "from delta_calibration" not in planner
    assert "coverage_reduction_enabled" not in planner

    registry = (ROOT / "scripts/evidence_contract_registry.py").read_text(encoding="utf-8")
    assert '"delta-calibration.json"' in registry

    print("AppLab independent delta calibration contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
