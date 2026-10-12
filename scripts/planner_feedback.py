#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from planner_feedback_contract import (
    ENGINE_VERSION,
    GRAPH_SCHEMA_VERSION,
    GRAPH_VERSION,
    MAX_HINTS,
    MAX_RISK_BOOST,
    RECORD_TYPE,
    SCHEMA_VERSION,
    _analysis_truncated,
    _canonical_digest,
    _compatibility_errors,
    _lineage,
    _risk_hints,
    _safe,
    _source,
    _validate_structure,
    _valid_hints,
    read_json,
)

def build_feedback(
    graph: dict[str, Any], analysis_plan: dict[str, Any] | None = None
) -> dict[str, Any]:
    insights = graph.get("insights")
    insights = insights if isinstance(insights, dict) else {}
    impact = insights.get("impact")
    impact = impact if isinstance(impact, dict) else {}
    freshness = insights.get("freshness")
    freshness = freshness if isinstance(freshness, dict) else {}
    paths = impact.get("paths")
    paths = paths if isinstance(paths, list) else []
    invalidated = freshness.get("invalidated")
    invalidated = invalidated if isinstance(invalidated, list) else []
    source = _source(graph, analysis_plan)
    errors = _compatibility_errors(graph, source, analysis_plan, paths)
    hints = _risk_hints(paths, invalidated)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "record_type": RECORD_TYPE,
        "state": "AVAILABLE" if not errors else "EVIDENCE_INCOMPLETE",
        "source": source,
        "compatibility": {
            "source_analysis_truncated": _analysis_truncated(analysis_plan),
            "impact_path_cap_reached": len(paths) >= 128,
            "structural_errors": sorted(set(errors)),
        },
        "summary": {
            "risk_hint_files": len(hints),
            "impact_paths": len(paths),
            "invalidated_evidence": len(invalidated),
            "max_risk_boost": max((int(row["risk_boost"]) for row in hints), default=0),
        },
        "risk_hints": hints,
        "guardrails": {
            "advisory_input_only": True,
            "smart_test_plan_remains_single_authority": True,
            "cannot_reduce_coverage": True,
            "current_run_graph_cannot_retroactively_change_lane": True,
            "exact_baseline_sha_required": True,
            "lineage_compatibility_required_when_available": True,
            "missing_invalid_or_truncated_feedback_is_ignored": True,
        },
        "record_digest_sha256": "",
    }
    payload["record_digest_sha256"] = _canonical_digest(payload)
    return payload
def evaluate_feedback(
    payload: dict[str, Any] | None,
    *,
    repository: str,
    baseline_sha: str,
    source_ref: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "eligible": False,
            "state": "ABSENT",
            "reason": "NO_FEEDBACK",
            "risk_hints": [],
        }
    errors = _validate_structure(payload)
    source = payload.get("source")
    source = source if isinstance(source, dict) else {}
    feedback_repo = _safe(source.get("repository"))
    feedback_sha = _safe(source.get("resolved_sha")).lower()
    feedback_lineage = _lineage(source.get("lineage_ref"))
    expected_sha = _safe(baseline_sha).lower()
    expected_ref = _lineage(source_ref)
    if feedback_repo != _safe(repository):
        errors.append("REPOSITORY_MISMATCH")
    if not _SHA40.fullmatch(expected_sha) or feedback_sha != expected_sha:
        errors.append("BASELINE_SHA_MISMATCH")
    if expected_ref and not _SHA40.fullmatch(expected_ref.lower()) and feedback_lineage:
        if expected_ref != feedback_lineage:
            errors.append("LINEAGE_MISMATCH")
    compatibility = payload.get("compatibility")
    compatibility = compatibility if isinstance(compatibility, dict) else {}
    if compatibility.get("source_analysis_truncated") is True:
        errors.append("SOURCE_ANALYSIS_TRUNCATED")
    if compatibility.get("impact_path_cap_reached") is True:
        errors.append("IMPACT_PATH_CAP_REACHED")
    if payload.get("state") != "AVAILABLE":
        errors.append("FEEDBACK_NOT_AVAILABLE")
    eligible = not errors
    return {
        "eligible": eligible,
        "state": "ELIGIBLE" if eligible else "IGNORED",
        "reason": "COMPATIBLE_PRIOR_GRAPH" if eligible else ",".join(sorted(set(errors))),
        "source": {
            "repository": feedback_repo,
            "resolved_sha": feedback_sha,
            "lineage_ref": feedback_lineage,
            "graph_sha256": _safe(source.get("graph_sha256")),
        },
        "risk_hints": _valid_hints(payload) if eligible else [],
    }
def markdown(payload: dict[str, Any]) -> str:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return "\n".join(
        (
            "# AppLab Graph-aware Planner Feedback",
            "",
            f"- State: **{payload.get('state', 'UNKNOWN')}**",
            f"- Repository: **{source.get('repository') or 'unknown'}**",
            f"- Source revision: **{source.get('resolved_sha') or 'unknown'}**",
            f"- Lineage: **{source.get('lineage_ref') or 'unknown'}**",
            f"- Risk-hint files: **{summary.get('risk_hint_files', 0)}**",
            f"- Prior impact paths: **{summary.get('impact_paths', 0)}**",
            f"- Prior invalidated evidence: **{summary.get('invalidated_evidence', 0)}**",
            "",
            "Feedback is escalation-only. Smart Test Plan remains the sole FAST/FULL selection authority.",
            "",
        )
    )
def write_outputs(payload: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "planner-feedback.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "planner-feedback.md").write_text(markdown(payload), encoding="utf-8")
def self_test() -> None:
    sha = "1" * 40
    graph = {
        "schema_version": 2,
        "engine_version": "4.6.0",
        "graph_version": "2.0",
        "identity": {
            "repository": "owner/app",
            "resolved_sha": sha,
            "run_id": "42",
            "lineage_ref": "main",
        },
        "insights": {
            "impact": {
                "paths": [
                    {"origin_file": "lib/auth.dart", "terminal_evidence": "user-journey.json"},
                    {"origin_file": "lib/auth.dart", "terminal_evidence": "ux-friction.json"},
                ]
            },
            "freshness": {
                "invalidated": [
                    {
                        "evidence_id": "Evidence:x",
                        "label": "lib/auth.dart",
                        "invalidated_by_files": ["lib/auth.dart"],
                    }
                ]
            },
        },
    }
    plan = {
        "schema_version": 2,
        "analysis_truncated": False,
        "semantic_diff_truncated": False,
        "dependency_analysis": {},
    }
    feedback = build_feedback(graph, plan)
    assert feedback["state"] == "AVAILABLE"
    assert feedback["risk_hints"][0]["path"] == "lib/auth.dart"
    assert feedback["risk_hints"][0]["risk_boost"] > 0
    assert evaluate_feedback(feedback, repository="owner/app", baseline_sha=sha, source_ref="main")["eligible"]
    assert not evaluate_feedback(feedback, repository="owner/app", baseline_sha="2" * 40, source_ref="main")["eligible"]
    truncated = build_feedback(graph, {**plan, "analysis_truncated": True})
    assert truncated["state"] == "EVIDENCE_INCOMPLETE"
    assert not evaluate_feedback(truncated, repository="owner/app", baseline_sha=sha, source_ref="main")["eligible"]
    malformed = json.loads(json.dumps(feedback))
    malformed["risk_hints"][0]["impact_path_count"] = "unknown"
    malformed["record_digest_sha256"] = _canonical_digest(malformed)
    malformed_eval = evaluate_feedback(malformed, repository="owner/app", baseline_sha=sha, source_ref="main")
    assert malformed_eval["eligible"] and malformed_eval["risk_hints"] == []
    tampered = json.loads(json.dumps(feedback))
    tampered["risk_hints"][0]["risk_boost"] = 1
    assert not evaluate_feedback(tampered, repository="owner/app", baseline_sha=sha, source_ref="main")["eligible"]
    incomplete_plan = {key: value for key, value in plan.items() if key != "dependency_analysis"}
    assert build_feedback(graph, incomplete_plan)["state"] == "EVIDENCE_INCOMPLETE"
    print("AppLab Graph-aware Planner Feedback v5.3.3 self-test PASS")
def main() -> int:
    parser = argparse.ArgumentParser(description="Build AppLab graph-aware planner feedback")
    parser.add_argument("--graph", default="")
    parser.add_argument("--analysis-plan", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.graph or not args.output_dir:
        raise SystemExit("--graph and --output-dir are required")
    graph = read_json(Path(args.graph))
    if graph is None:
        raise SystemExit("Evidence Graph is missing or invalid")
    plan = read_json(Path(args.analysis_plan)) if args.analysis_plan else None
    payload = build_feedback(graph, plan)
    write_outputs(payload, Path(args.output_dir))
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
