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


def _canonical_digest(payload: dict[str, Any]) -> str:
    normalized = dict(payload)
    normalized["record_digest_sha256"] = ""
    raw = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _graph_digest(graph: dict[str, Any]) -> str:
    raw = json.dumps(
        graph,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _analysis_digest(plan: dict[str, Any] | None) -> str:
    if not isinstance(plan, dict):
        return ""
    raw = json.dumps(
        plan,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _analysis_truncated(plan: dict[str, Any] | None) -> bool:
    if not isinstance(plan, dict):
        return False
    dependency = (
        plan.get("dependency_analysis")
        if isinstance(plan.get("dependency_analysis"), dict)
        else {}
    )
    return bool(
        plan.get("analysis_truncated")
        or plan.get("semantic_diff_truncated")
        or dependency.get("dependency_scan_truncated")
        or dependency.get("dependency_impact_cap_reached")
        or dependency.get("dependency_import_truncated")
    )


def _lineage(value: Any) -> str:
    ref = _safe(value)
    for prefix in ("refs/heads/", "origin/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
    return ref


def build_feedback(
    graph: dict[str, Any],
    analysis_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity = graph.get("identity") if isinstance(graph.get("identity"), dict) else {}
    repository = _safe(identity.get("repository"))
    resolved_sha = _safe(identity.get("resolved_sha")).lower()
    lineage_ref = _lineage(identity.get("lineage_ref"))
    run_id = _safe(identity.get("run_id"))

    structural_errors: list[str] = []
    if graph.get("schema_version") != GRAPH_SCHEMA_VERSION:
        structural_errors.append("GRAPH_SCHEMA_VERSION_MISMATCH")
    if _safe(graph.get("graph_version")) != GRAPH_VERSION:
        structural_errors.append("GRAPH_VERSION_MISMATCH")
    if not _REPOSITORY.fullmatch(repository):
        structural_errors.append("INVALID_REPOSITORY")
    if not _SHA40.fullmatch(resolved_sha):
        structural_errors.append("INVALID_RESOLVED_SHA")

    insights = graph.get("insights") if isinstance(graph.get("insights"), dict) else {}
    impact = insights.get("impact") if isinstance(insights.get("impact"), dict) else {}
    freshness = (
        insights.get("freshness")
        if isinstance(insights.get("freshness"), dict)
        else {}
    )
    paths = impact.get("paths") if isinstance(impact.get("paths"), list) else []
    invalidated = (
        freshness.get("invalidated")
        if isinstance(freshness.get("invalidated"), list)
        else []
    )

    source_analysis_truncated = _analysis_truncated(analysis_plan)
    impact_path_cap_reached = len(paths) >= 128
    if source_analysis_truncated:
        structural_errors.append("SOURCE_ANALYSIS_TRUNCATED")
    if impact_path_cap_reached:
        structural_errors.append("IMPACT_PATH_CAP_REACHED")

    per_file: dict[str, dict[str, Any]] = {}
    for row in paths:
        if not isinstance(row, dict):
            continue
        path = _repo_path(row.get("origin_file"))
        if not path:
            continue
        entry = per_file.setdefault(
            path,
            {
                "path": path,
                "impact_path_count": 0,
                "terminal_evidence": set(),
                "invalidated_evidence": 0,
                "reasons": set(),
            },
        )
        entry["impact_path_count"] += 1
        terminal = _safe(row.get("terminal_evidence"))
        if terminal:
            entry["terminal_evidence"].add(terminal)
        entry["reasons"].add("PRIOR_GRAPH_IMPACT_PATH")

    for row in invalidated:
        if not isinstance(row, dict):
            continue
        files = (
            row.get("invalidated_by_files")
            if isinstance(row.get("invalidated_by_files"), list)
            else []
        )
        for value in files:
            path = _repo_path(value)
            if not path:
                continue
            entry = per_file.setdefault(
                path,
                {
                    "path": path,
                    "impact_path_count": 0,
                    "terminal_evidence": set(),
                    "invalidated_evidence": 0,
                    "reasons": set(),
                },
            )
            entry["invalidated_evidence"] += 1
            entry["reasons"].add("PRIOR_GRAPH_INVALIDATED_EVIDENCE")

    hints: list[dict[str, Any]] = []
    for path, entry in per_file.items():
        path_count = int(entry["impact_path_count"])
        invalidated_count = int(entry["invalidated_evidence"])
        terminal_count = len(entry["terminal_evidence"])
        boost = min(
            MAX_RISK_BOOST,
            (12 if invalidated_count else 0)
            + min(6, path_count * 2)
            + min(2, terminal_count),
        )
        if boost <= 0:
            continue
        hints.append(
            {
                "path": path,
                "risk_boost": boost,
                "impact_path_count": path_count,
                "terminal_evidence_count": terminal_count,
                "invalidated_evidence_count": invalidated_count,
                "reasons": sorted(entry["reasons"]),
            }
        )

    hints.sort(key=lambda row: (-int(row["risk_boost"]), str(row["path"])))
    hints = hints[:MAX_HINTS]
    state = "AVAILABLE" if not structural_errors else "EVIDENCE_INCOMPLETE"

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "record_type": RECORD_TYPE,
        "state": state,
        "source": {
            "repository": repository,
            "resolved_sha": resolved_sha,
            "lineage_ref": lineage_ref,
            "run_id": run_id,
            "graph_schema_version": graph.get("schema_version"),
            "graph_version": _safe(graph.get("graph_version")),
            "graph_engine_version": _safe(graph.get("engine_version")),
            "graph_sha256": _graph_digest(graph),
            "analysis_plan_sha256": _analysis_digest(analysis_plan),
        },
        "compatibility": {
            "source_analysis_truncated": source_analysis_truncated,
            "impact_path_cap_reached": impact_path_cap_reached,
            "structural_errors": sorted(set(structural_errors)),
        },
        "summary": {
            "risk_hint_files": len(hints),
            "impact_paths": len(paths),
            "invalidated_evidence": len(invalidated),
            "max_risk_boost": max(
                (int(row["risk_boost"]) for row in hints),
                default=0,
            ),
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
        return {"eligible": False, "state": "ABSENT", "reason": "NO_FEEDBACK", "risk_hints": []}

    errors: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append("SCHEMA_VERSION_MISMATCH")
    if _safe(payload.get("record_type")) != RECORD_TYPE:
        errors.append("RECORD_TYPE_MISMATCH")
    digest = _safe(payload.get("record_digest_sha256")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or digest != _canonical_digest(payload):
        errors.append("DIGEST_MISMATCH")

    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
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

    guardrails = payload.get("guardrails") if isinstance(payload.get("guardrails"), dict) else {}
    required_guardrails = (
        "advisory_input_only",
        "smart_test_plan_remains_single_authority",
        "cannot_reduce_coverage",
        "current_run_graph_cannot_retroactively_change_lane",
        "exact_baseline_sha_required",
        "missing_invalid_or_truncated_feedback_is_ignored",
    )
    for key in required_guardrails:
        if guardrails.get(key) is not True:
            errors.append(f"GUARDRAIL_{key.upper()}")

    compatibility = (
        payload.get("compatibility")
        if isinstance(payload.get("compatibility"), dict)
        else {}
    )
    if compatibility.get("source_analysis_truncated") is True:
        errors.append("SOURCE_ANALYSIS_TRUNCATED")
    if compatibility.get("impact_path_cap_reached") is True:
        errors.append("IMPACT_PATH_CAP_REACHED")
    if payload.get("state") != "AVAILABLE":
        errors.append("FEEDBACK_NOT_AVAILABLE")

    hints = payload.get("risk_hints") if isinstance(payload.get("risk_hints"), list) else []
    valid_hints: list[dict[str, Any]] = []
    for row in hints[:MAX_HINTS]:
        if not isinstance(row, dict):
            continue
        path = _repo_path(row.get("path"))
        try:
            boost = int(row.get("risk_boost", 0))
        except (TypeError, ValueError):
            continue
        if not path or not 1 <= boost <= MAX_RISK_BOOST:
            continue
        valid_hints.append(
            {
                "path": path,
                "risk_boost": boost,
                "impact_path_count": int(row.get("impact_path_count", 0) or 0),
                "terminal_evidence_count": int(row.get("terminal_evidence_count", 0) or 0),
                "invalidated_evidence_count": int(row.get("invalidated_evidence_count", 0) or 0),
                "reasons": [
                    _safe(value)
                    for value in row.get("reasons", [])
                    if _safe(value)
                ][:8]
                if isinstance(row.get("reasons"), list)
                else [],
            }
        )

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
        "risk_hints": valid_hints if eligible else [],
    }


def markdown(payload: dict[str, Any]) -> str:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
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
    ]
    return "\n".join(lines) + "\n"


def write_outputs(payload: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "planner-feedback.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
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
                    {
                        "origin_file": "lib/auth.dart",
                        "terminal_evidence": "user-journey.json",
                    },
                    {
                        "origin_file": "lib/auth.dart",
                        "terminal_evidence": "ux-friction.json",
                    },
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

    eligible = evaluate_feedback(
        feedback,
        repository="owner/app",
        baseline_sha=sha,
        source_ref="main",
    )
    assert eligible["eligible"] is True
    assert eligible["risk_hints"]

    mismatch = evaluate_feedback(
        feedback,
        repository="owner/app",
        baseline_sha="2" * 40,
        source_ref="main",
    )
    assert mismatch["eligible"] is False

    truncated = build_feedback(graph, {**plan, "analysis_truncated": True})
    assert truncated["state"] == "EVIDENCE_INCOMPLETE"
    ignored = evaluate_feedback(
        truncated,
        repository="owner/app",
        baseline_sha=sha,
        source_ref="main",
    )
    assert ignored["eligible"] is False

    tampered = json.loads(json.dumps(feedback))
    tampered["risk_hints"][0]["risk_boost"] = 1
    assert evaluate_feedback(
        tampered,
        repository="owner/app",
        baseline_sha=sha,
        source_ref="main",
    )["eligible"] is False
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
