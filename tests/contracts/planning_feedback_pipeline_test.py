#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import execution_acceleration  # noqa: E402
import history_learning  # noqa: E402
import planner_feedback  # noqa: E402
import smart_test_plan  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def compatible_source_plan() -> dict:
    return {
        "schema_version": 2,
        "planner_version": "1.1.0",
        "mode": "fast",
        "lane": "FAST_RUNTIME",
        "analysis_truncated": False,
        "semantic_diff_truncated": False,
        "dependency_analysis": {
            "dependency_scan_truncated": False,
            "dependency_impact_cap_reached": False,
            "dependency_import_truncated": False,
        },
        "diff_hunk_count": 1,
    }


def source_graph(sha: str) -> dict:
    return {
        "schema_version": 2,
        "engine_version": "4.6.0",
        "graph_version": "2.0",
        "identity": {
            "repository": "owner/app",
            "resolved_sha": sha,
            "lineage_ref": "main",
            "run_id": "101",
        },
        "insights": {
            "impact": {
                "paths": [
                    {
                        "origin_file": "lib/core/service.dart",
                        "terminal_evidence": "runtime:network",
                    }
                ]
            },
            "freshness": {"invalidated": []},
        },
    }


def current_fast_plan() -> dict:
    return {
        "schema_version": 2,
        "planner_version": "1.1.0",
        "requested_mode": "fast",
        "mode": "fast",
        "lane": "FAST_RUNTIME",
        "repository": "owner/app",
        "baseline_sha": "a" * 40,
        "changed_files": ["lib/core/service.dart"],
        "impacted_files": [],
        "changes": [
            {
                "path": "lib/core/service.dart",
                "status": "M",
                "additions": 2,
                "deletions": 1,
            }
        ],
        "risk_score": 68,
        "confidence": 0.9,
        "fallback_full": False,
        "run_static": True,
        "run_build": True,
        "run_runtime": True,
        "selected_labs": {lab: False for lab in smart_test_plan.LABS},
        "reasons": {lab: [] for lab in smart_test_plan.LABS},
    }


def main() -> int:
    baseline = "a" * 40
    feedback = planner_feedback.build_feedback(
        source_graph(baseline),
        compatible_source_plan(),
    )
    require(feedback["state"] == "AVAILABLE", "compatible feedback must be AVAILABLE")
    evaluation = planner_feedback.evaluate_feedback(
        feedback,
        repository="owner/app",
        baseline_sha=baseline,
        source_ref="main",
    )
    require(evaluation["eligible"] is True, "exact-baseline feedback must be eligible")

    applied = smart_test_plan.apply_graph_planner_feedback(
        current_fast_plan(),
        evaluation,
    )
    applied = history_learning.refresh_lane_telemetry(applied)
    require(applied["lane"] == "FULL_RUNTIME", "trusted risk feedback must promote the threshold-crossing FAST lane")
    require(applied["mode"] == "full", "promotion must update effective mode")
    require(applied["planner_feedback"]["coverage_reduced"] is False, "feedback must never reduce coverage")
    require(all(applied["selected_labs"].values()), "FULL promotion must select every specialist lab")
    require(applied["verification_budget_seconds"] == 1800, "lane telemetry must refresh after promotion")

    execution = execution_acceleration.build_execution_plan(
        analysis_plan=applied,
        repository="owner/app",
        resolved_sha="b" * 40,
        engine="flutter",
        history_key="contract-test",
        working_directory=".",
        build_command="flutter build apk --debug",
        apk_path="build/app.apk",
        contract_fingerprint="contract-v533",
        config_fingerprint="config-v1",
        toolchain=["flutter:3.47.5", "java:21"],
        build_inputs=[],
    )
    require(execution["run_runtime"] is True, "promoted plan must retain runtime execution")
    require(execution["run_build"] is True, "promoted plan must retain build execution")
    require(execution["lane"] == "FULL_RUNTIME", "execution identity must carry promoted lane")

    tampered = copy.deepcopy(feedback)
    tampered["risk_hints"][0]["risk_boost"] = 20
    tampered_eval = planner_feedback.evaluate_feedback(
        tampered,
        repository="owner/app",
        baseline_sha=baseline,
        source_ref="main",
    )
    require(tampered_eval["eligible"] is False, "digest-tampered feedback must fail closed")
    require("DIGEST_MISMATCH" in tampered_eval["reason"], "tampered feedback must expose digest mismatch")

    wrong_baseline = planner_feedback.evaluate_feedback(
        feedback,
        repository="owner/app",
        baseline_sha="c" * 40,
        source_ref="main",
    )
    require(wrong_baseline["eligible"] is False, "stale feedback must fail closed")
    require("BASELINE_SHA_MISMATCH" in wrong_baseline["reason"], "stale feedback must expose baseline mismatch")

    incomplete = compatible_source_plan()
    incomplete.pop("dependency_analysis")
    incomplete_feedback = planner_feedback.build_feedback(source_graph(baseline), incomplete)
    require(incomplete_feedback["state"] == "EVIDENCE_INCOMPLETE", "missing completeness metadata must fail closed")
    incomplete_eval = planner_feedback.evaluate_feedback(
        incomplete_feedback,
        repository="owner/app",
        baseline_sha=baseline,
        source_ref="main",
    )
    require(incomplete_eval["eligible"] is False, "incomplete source analysis must never influence planning")

    print("AppLab independent planning-feedback pipeline PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
