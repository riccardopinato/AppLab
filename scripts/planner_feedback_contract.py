#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ENGINE_VERSION = "5.3.3"
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
