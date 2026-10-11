#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
SCHEMA_VERSION = 1
ENGINE_VERSION = "5.3.2"
RECORD_TYPE = "EVIDENCE_GRAPH_PLANNER_FEEDBACK"
GRAPH_SCHEMA_VERSION = 2
GRAPH_VERSION = "2.0"
MAX_HINTS = 128
MAX_RISK_BOOST = 20
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
def _safe(value: Any) -> str:
    return str(value).strip() if value is not None else ""
def _repo_path(value: Any) -> str:
    path = _safe(value).replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    if not path or path.startswith("/") or ".." in Path(path).parts:
        return ""
    return path
def _digest(payload: dict[str, Any], *, blank_record_digest: bool = False) -> str:
    normalized = dict(payload)
    if blank_record_digest:
        normalized["record_digest_sha256"] = ""
    raw = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
def _canonical_digest(payload: dict[str, Any]) -> str:
    return _digest(payload, blank_record_digest=True)
def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None
def _analysis_truncated(plan: dict[str, Any] | None) -> bool:
    if not isinstance(plan, dict):
        return True
    if any(key not in plan for key in ("analysis_truncated", "semantic_diff_truncated", "dependency_analysis")):
        return True
    dep = plan.get("dependency_analysis")
    dep = dep if isinstance(dep, dict) else {}
    return bool(
        plan.get("analysis_truncated")
        or plan.get("semantic_diff_truncated")
        or dep.get("dependency_scan_truncated")
        or dep.get("dependency_impact_cap_reached")
        or dep.get("dependency_import_truncated")
    )
def _lineage(value: Any) -> str:
    ref = _safe(value)
    for prefix in ("refs/heads/", "origin/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
    return ref
def _source(graph: dict[str, Any], plan: dict[str, Any] | None) -> dict[str, Any]:
    identity = graph.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    return {
        "repository": _safe(identity.get("repository")),
        "resolved_sha": _safe(identity.get("resolved_sha")).lower(),
        "lineage_ref": _lineage(identity.get("lineage_ref")),
        "run_id": _safe(identity.get("run_id")),
        "graph_schema_version": graph.get("schema_version"),
        "graph_version": _safe(graph.get("graph_version")),
        "graph_engine_version": _safe(graph.get("engine_version")),
        "graph_sha256": _digest(graph),
        "analysis_plan_sha256": _digest(plan) if isinstance(plan, dict) else "",
    }
def _compatibility_errors(
    graph: dict[str, Any],
    source: dict[str, Any],
    plan: dict[str, Any] | None,
    paths: list[Any],
) -> list[str]:
    errors: list[str] = []
    if graph.get("schema_version") != GRAPH_SCHEMA_VERSION:
        errors.append("GRAPH_SCHEMA_VERSION_MISMATCH")
    if _safe(graph.get("graph_version")) != GRAPH_VERSION:
        errors.append("GRAPH_VERSION_MISMATCH")
    if not _REPOSITORY.fullmatch(_safe(source.get("repository"))):
        errors.append("INVALID_REPOSITORY")
    if not _SHA40.fullmatch(_safe(source.get("resolved_sha"))):
        errors.append("INVALID_RESOLVED_SHA")
    if _analysis_truncated(plan):
        errors.append("SOURCE_ANALYSIS_TRUNCATED")
    if len(paths) >= 128:
        errors.append("IMPACT_PATH_CAP_REACHED")
    return errors
def _risk_hints(paths: list[Any], invalidated: list[Any]) -> list[dict[str, Any]]:
    per_file: dict[str, dict[str, Any]] = {}
    def entry(path: str) -> dict[str, Any]:
        return per_file.setdefault(
            path,
            {
                "impact_path_count": 0,
                "terminal_evidence": set(),
                "invalidated_evidence": 0,
                "reasons": set(),
            },
        )
    for row in paths:
        if not isinstance(row, dict):
            continue
        path = _repo_path(row.get("origin_file"))
        if not path:
            continue
        item = entry(path)
        item["impact_path_count"] += 1
        terminal = _safe(row.get("terminal_evidence"))
        if terminal:
            item["terminal_evidence"].add(terminal)
        item["reasons"].add("PRIOR_GRAPH_IMPACT_PATH")
    for row in invalidated:
        if not isinstance(row, dict):
            continue
        values = row.get("invalidated_by_files")
        values = values if isinstance(values, list) else []
        for value in values:
            path = _repo_path(value)
            if not path:
                continue
            item = entry(path)
            item["invalidated_evidence"] += 1
            item["reasons"].add("PRIOR_GRAPH_INVALIDATED_EVIDENCE")
    hints: list[dict[str, Any]] = []
    for path, item in per_file.items():
        path_count = int(item["impact_path_count"])
        invalidated_count = int(item["invalidated_evidence"])
        terminal_count = len(item["terminal_evidence"])
        boost = min(
            MAX_RISK_BOOST,
            (12 if invalidated_count else 0)
            + min(6, path_count * 2)
            + min(2, terminal_count),
        )
        if boost:
            hints.append(
                {
                    "path": path,
                    "risk_boost": boost,
                    "impact_path_count": path_count,
                    "terminal_evidence_count": terminal_count,
                    "invalidated_evidence_count": invalidated_count,
                    "reasons": sorted(item["reasons"]),
                }
            )
    return sorted(hints, key=lambda row: (-int(row["risk_boost"]), row["path"]))[:MAX_HINTS]
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
def _validate_structure(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append("SCHEMA_VERSION_MISMATCH")
    if _safe(payload.get("record_type")) != RECORD_TYPE:
        errors.append("RECORD_TYPE_MISMATCH")
    digest = _safe(payload.get("record_digest_sha256")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or digest != _canonical_digest(payload):
        errors.append("DIGEST_MISMATCH")
    guards = payload.get("guardrails")
    guards = guards if isinstance(guards, dict) else {}
    for key in (
        "advisory_input_only",
        "smart_test_plan_remains_single_authority",
        "cannot_reduce_coverage",
        "current_run_graph_cannot_retroactively_change_lane",
        "exact_baseline_sha_required",
        "missing_invalid_or_truncated_feedback_is_ignored",
    ):
        if guards.get(key) is not True:
            errors.append(f"GUARDRAIL_{key.upper()}")
    return errors
def _valid_hints(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("risk_hints")
    rows = rows if isinstance(rows, list) else []
    hints: list[dict[str, Any]] = []
    for row in rows[:MAX_HINTS]:
        if not isinstance(row, dict):
            continue
        path = _repo_path(row.get("path"))
        try:
            boost = int(row.get("risk_boost", 0))
        except (TypeError, ValueError):
            continue
        if not path or not 1 <= boost <= MAX_RISK_BOOST:
            continue
        try:
            impact_count = int(row.get("impact_path_count", 0) or 0)
            terminal_count = int(row.get("terminal_evidence_count", 0) or 0)
            invalidated_count = int(row.get("invalidated_evidence_count", 0) or 0)
        except (TypeError, ValueError):
            continue
        if min(impact_count, terminal_count, invalidated_count) < 0:
            continue
        hints.append(
            {
                "path": path,
                "risk_boost": boost,
                "impact_path_count": impact_count,
                "terminal_evidence_count": terminal_count,
                "invalidated_evidence_count": invalidated_count,
                "reasons": [
                    _safe(value)
                    for value in row.get("reasons", [])[:8]
                    if _safe(value)
                ]
                if isinstance(row.get("reasons"), list)
                else [],
            }
        )
    return hints
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
    assert evaluate_feedback(
        feedback, repository="owner/app", baseline_sha=sha, source_ref="main"
    )["eligible"]
    assert not evaluate_feedback(
        feedback, repository="owner/app", baseline_sha="2" * 40, source_ref="main"
    )["eligible"]
    truncated = build_feedback(graph, {**plan, "analysis_truncated": True})
    assert truncated["state"] == "EVIDENCE_INCOMPLETE"
    assert not evaluate_feedback(
        truncated, repository="owner/app", baseline_sha=sha, source_ref="main"
    )["eligible"]
    malformed = json.loads(json.dumps(feedback))
    malformed["risk_hints"][0]["impact_path_count"] = "unknown"
    malformed["record_digest_sha256"] = _canonical_digest(malformed)
    assert evaluate_feedback(
        malformed, repository="owner/app", baseline_sha=sha, source_ref="main"
    )["eligible"]
    assert evaluate_feedback(
        malformed, repository="owner/app", baseline_sha=sha, source_ref="main"
    )["risk_hints"] == []
    tampered = json.loads(json.dumps(feedback))
    tampered["risk_hints"][0]["risk_boost"] = 1
    assert not evaluate_feedback(
        tampered, repository="owner/app", baseline_sha=sha, source_ref="main"
    )["eligible"]
    incomplete_plan = {key: value for key, value in plan.items() if key != "dependency_analysis"}
    assert build_feedback(graph, incomplete_plan)["state"] == "EVIDENCE_INCOMPLETE"
    print("AppLab Graph-aware Planner Feedback v5.3.2 self-test PASS")
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
