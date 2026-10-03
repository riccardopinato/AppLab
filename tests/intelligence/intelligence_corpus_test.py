#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import longitudinal_product_intelligence as longitudinal  # noqa: E402
import autonomous_experiment_planner as planner  # noqa: E402
import applab_analyst as analyst  # noqa: E402

CORPUS = ROOT / "integration/intelligence/intelligence-regression-corpus.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_cases() -> list[dict[str, Any]]:
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    require(isinstance(cases, list) and cases, "regression corpus must contain cases")
    return [row for row in cases if isinstance(row, dict)]


def run_case(case: dict[str, Any]) -> None:
    name = str(case.get("name", "unnamed"))
    history = case.get("history") if isinstance(case.get("history"), list) else []
    current = case.get("current") if isinstance(case.get("current"), dict) else {}
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    decision = case.get("decision") if isinstance(case.get("decision"), dict) else {}
    autonomous = case.get("autonomous") if isinstance(case.get("autonomous"), dict) else {}

    lineage_ref = ""
    repository = "owner/app"
    if history:
        last = history[-1]
        if isinstance(last, dict):
            lineage_ref = str(last.get("lineage_ref", ""))
            repository = str(last.get("repository", repository))

    current_sha = ("f" * 40) if name != "stable_product_no_action" else ("d" * 40)
    longitudinal_report = longitudinal.build_report(
        current,
        [row for row in history if isinstance(row, dict)],
        repository=repository,
        resolved_sha=current_sha,
        run_id="corpus",
        lineage_ref=lineage_ref or "main",
    )

    require(
        longitudinal_report.get("state") == expected.get("longitudinal_state"),
        f"{name}: longitudinal state mismatch: {longitudinal_report.get('state')}",
    )
    summary = longitudinal_report.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    require(
        int(summary.get("returned_findings", 0) or 0)
        == int(expected.get("returned_findings", 0) or 0),
        f"{name}: returned finding count mismatch",
    )
    require(
        int(summary.get("regression_candidates", 0) or 0)
        == int(expected.get("regression_candidates", 0) or 0),
        f"{name}: regression candidate count mismatch",
    )

    confidence = current.get("evidence_confidence")
    confidence = confidence if isinstance(confidence, dict) else {}
    experiment_report = planner.build_plan(
        {
            "decision": decision,
            "longitudinal": longitudinal_report,
            "confidence": confidence,
        }
    )
    require(
        experiment_report.get("state") == expected.get("planner_state"),
        f"{name}: planner state mismatch: {experiment_report.get('state')}",
    )

    min_high = int(expected.get("planner_high_priority_min", 0) or 0)
    exp_summary = experiment_report.get("summary")
    exp_summary = exp_summary if isinstance(exp_summary, dict) else {}
    require(
        int(exp_summary.get("high_priority", 0) or 0) >= min_high,
        f"{name}: planner high-priority coverage below corpus expectation",
    )

    expected_type = str(expected.get("loop_experiment_type", ""))
    if expected_type:
        experiments = experiment_report.get("experiments")
        experiments = experiments if isinstance(experiments, list) else []
        loop = next(
            (
                row
                for row in experiments
                if isinstance(row, dict)
                and row.get("kind") == "NAVIGATION_LOOP_CANDIDATE"
            ),
            None,
        )
        require(loop is not None, f"{name}: expected loop experiment missing")
        require(
            loop.get("experiment_type") == expected_type,
            f"{name}: loop experiment type mismatch: {loop.get('experiment_type')}",
        )

    analyst_report = analyst.build_report(
        {
            "app": {},
            "autonomous": autonomous,
            "decision": decision,
            "confidence": confidence,
            "longitudinal": longitudinal_report,
            "experiment": experiment_report,
        }
    )
    require(
        analyst_report.get("state") == expected.get("analyst_state"),
        f"{name}: analyst state mismatch: {analyst_report.get('state')}",
    )


def main() -> int:
    cases = load_cases()
    for case in cases:
        run_case(case)
    print(f"AppLab independent intelligence regression corpus PASS ({len(cases)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
