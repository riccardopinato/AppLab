#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import change_intelligence
from product_review_common import write_report

SCHEMA_VERSION = 1
ENGINE_VERSION = "3.5.0"
MAX_HISTORY = 20

SEVERITY_RANK = {
    "": 0,
    "INFO": 1,
    "REVIEW": 2,
    "HIGH_REVIEW": 3,
}

FINDING_SOURCES = (
    ("product_consistency", ("app_intelligence", "product_consistency", "findings")),
    ("product_contract", ("product_contract", "findings")),
    ("behavioral_product", ("behavioral_product", "findings")),
    ("state_edge_case", ("state_edge_case", "findings")),
    ("user_journey", ("user_journey", "findings")),
    ("ux_friction", ("ux_friction", "findings")),
    ("evidence_contradiction", ("evidence_confidence", "contradictions")),
)

DETAILED_REPORTS = {
    "app_intelligence": "app-intelligence.json",
    "behavioral_product": "behavioral-product.json",
    "state_edge_case": "state-edge-case.json",
    "evidence_calibration": "evidence-calibration.json",
    "evidence_confidence": "evidence-confidence.json",
    "user_journey": "user-journey.json",
    "ux_friction": "ux-friction.json",
    "product_contract": "product-contract-audit.json",
    "decision_brief": "decision-brief.json",
}


def _nested(value: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _safe_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _finding_subject(row: dict[str, Any]) -> str:
    return _safe_text(row.get("subject")) or _safe_text(row.get("capability"))


def finding_key(source: str, row: dict[str, Any]) -> str:
    explicit = _safe_text(row.get("id"))
    if explicit:
        return f"{source}|id:{explicit}"
    parts = (
        source,
        _safe_text(row.get("domain")).lower(),
        _safe_text(row.get("category")).lower(),
        _safe_text(row.get("kind")).lower(),
        _finding_subject(row).lower(),
    )
    return "|".join(parts)


def finding_view(source: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": finding_key(source, row),
        "source": source,
        "domain": _safe_text(row.get("domain")),
        "category": _safe_text(row.get("category")),
        "kind": _safe_text(row.get("kind")),
        "severity": _safe_text(row.get("severity")),
        "confidence": _safe_text(row.get("confidence")),
        "subject": _finding_subject(row),
        "message": _safe_text(row.get("message")),
        "evidence": (
            [str(value) for value in row.get("evidence", [])[:6]]
            if isinstance(row.get("evidence"), list)
            else []
        ),
    }


def findings_index(review: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for source, path in FINDING_SOURCES:
        rows = _nested(review, path)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            view = finding_view(source, row)
            key = view["key"]
            if key in result:
                before = SEVERITY_RANK.get(_safe_text(result[key].get("severity")).upper(), 0)
                after = SEVERITY_RANK.get(_safe_text(view.get("severity")).upper(), 0)
                if after > before:
                    result[key] = view
            else:
                result[key] = view
    return result


def claim_key(row: dict[str, Any]) -> str:
    explicit = _safe_text(row.get("id"))
    if explicit:
        return explicit
    return "|".join(
        (
            _safe_text(row.get("domain")).lower(),
            _safe_text(row.get("kind")).lower(),
            _safe_text(row.get("subject")).lower(),
        )
    )


def claims_index(review: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = _nested(review, ("evidence_confidence", "claims"))
    if not isinstance(rows, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = claim_key(row)
        if not key:
            continue
        result[key] = {
            "key": key,
            "domain": _safe_text(row.get("domain")),
            "kind": _safe_text(row.get("kind")),
            "subject": _safe_text(row.get("subject")),
            "status": _safe_text(row.get("status")),
            "rationale": _safe_text(row.get("rationale")),
            "source_sha": _safe_text(row.get("source_sha")),
        }
    return result


def _metadata_from_review(review: dict[str, Any]) -> dict[str, str]:
    trust = review.get("runtime_evidence_trust")
    trust = trust if isinstance(trust, dict) else {}
    binding = trust.get("binding")
    binding = binding if isinstance(binding, dict) else {}
    return {
        "repository": _safe_text(binding.get("repository")),
        "resolved_sha": _safe_text(binding.get("resolved_sha")),
        "run_id": _safe_text(binding.get("run_id")),
    }


def make_snapshot(
    review: dict[str, Any],
    *,
    repository: str = "",
    resolved_sha: str = "",
    run_id: str = "",
    recorded_at: str = "",
) -> dict[str, Any]:
    inferred = _metadata_from_review(review)
    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "recorded_at": recorded_at or datetime.now(timezone.utc).isoformat(),
        "repository": repository or inferred["repository"],
        "resolved_sha": resolved_sha or inferred["resolved_sha"],
        "run_id": run_id or inferred["run_id"],
        "review": review,
    }


def load_composed_review(current_path: Path | None, current_dir: Path | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if current_path is not None:
        try:
            raw = json.loads(current_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to read current autonomous review: {current_path}") from exc
        if not isinstance(raw, dict):
            raise ValueError("current autonomous review must be a JSON object")
        payload.update(raw)

    if current_dir is not None:
        if not current_dir.is_dir():
            raise ValueError(f"current evidence directory does not exist: {current_dir}")
        if not payload:
            slim = current_dir / "autonomous-review.json"
            if slim.is_file():
                try:
                    raw = json.loads(slim.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ValueError(f"Unable to read current autonomous review: {slim}") from exc
                if isinstance(raw, dict):
                    payload.update(raw)
        for key, filename in DETAILED_REPORTS.items():
            file_path = current_dir / filename
            if not file_path.is_file():
                continue
            try:
                detail = json.loads(file_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(detail, dict):
                payload[key] = detail

    if not payload:
        raise ValueError("no current autonomous review evidence was loaded")
    return payload


def _read_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("review"), dict):
        snapshot = dict(payload)
    elif "app_intelligence" in payload:
        snapshot = make_snapshot(payload)
    else:
        return None
    snapshot["_path"] = str(path)
    return snapshot


def load_history(
    history_dir: Path | None,
    *,
    repository: str = "",
    current_sha: str = "",
    limit: int = MAX_HISTORY,
) -> list[dict[str, Any]]:
    if history_dir is None or not history_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in history_dir.glob("*.json"):
        row = _read_snapshot(path)
        if row is None:
            continue
        row_repo = _safe_text(row.get("repository"))
        row_sha = _safe_text(row.get("resolved_sha"))
        if repository and row_repo and row_repo != repository:
            continue
        if current_sha and row_sha and row_sha == current_sha:
            continue
        rows.append(row)

    rows.sort(key=lambda row: (_safe_text(row.get("recorded_at")), _safe_text(row.get("_path"))))
    deduped: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for row in rows:
        sha = _safe_text(row.get("resolved_sha"))
        if sha:
            deduped[sha] = row
        else:
            anonymous.append(row)
    merged = anonymous + list(deduped.values())
    merged.sort(key=lambda row: (_safe_text(row.get("recorded_at")), _safe_text(row.get("_path"))))
    return merged[-max(1, limit):]


def _transition_view(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": after.get("key") or before.get("key"),
        "source": after.get("source") or before.get("source"),
        "kind": after.get("kind") or before.get("kind"),
        "subject": after.get("subject") or before.get("subject"),
        "before_severity": _safe_text(before.get("severity")),
        "after_severity": _safe_text(after.get("severity")),
    }


def _claim_transition(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": after.get("key") or before.get("key"),
        "domain": after.get("domain") or before.get("domain"),
        "kind": after.get("kind") or before.get("kind"),
        "subject": after.get("subject") or before.get("subject"),
        "before_status": _safe_text(before.get("status")),
        "after_status": _safe_text(after.get("status")),
    }


def _history_presence(
    key: str,
    historical_indexes: list[dict[str, dict[str, Any]]],
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    seen_positions = [
        index
        for index, values in enumerate(historical_indexes)
        if key in values
    ]
    if not seen_positions:
        return {
            "seen_count": 0,
            "consecutive_seen": 0,
            "first_seen_sha": "",
            "last_seen_sha": "",
        }
    consecutive = 0
    for values in reversed(historical_indexes):
        if key in values:
            consecutive += 1
        else:
            break
    first = snapshots[seen_positions[0]]
    last = snapshots[seen_positions[-1]]
    return {
        "seen_count": len(seen_positions),
        "consecutive_seen": consecutive,
        "first_seen_sha": _safe_text(first.get("resolved_sha")),
        "last_seen_sha": _safe_text(last.get("resolved_sha")),
    }


def _scan_comparable(before_app: dict[str, Any], after_app: dict[str, Any]) -> tuple[bool, str]:
    before = before_app.get("scan") if isinstance(before_app.get("scan"), dict) else {}
    after = after_app.get("scan") if isinstance(after_app.get("scan"), dict) else {}
    before_max = int(before.get("max_files", 0) or 0)
    after_max = int(after.get("max_files", 0) or 0)
    before_scanned = int(before.get("scanned_files", 0) or 0)
    after_scanned = int(after.get("scanned_files", 0) or 0)
    before_truncated = bool(before.get("truncated", False))
    after_truncated = bool(after.get("truncated", False))

    if after_truncated and not before_truncated:
        return False, "current scan is truncated while baseline scan was complete"
    if before_max and after_max and after_max < before_max and after_truncated:
        return False, "current max_files bound is lower than baseline and current scan is truncated"
    if before_scanned and after_scanned < before_scanned and after_truncated:
        return False, "current scan covers fewer files than baseline and is truncated"
    return True, ""


def build_report(
    current_review: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    repository: str = "",
    resolved_sha: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    current_snapshot = make_snapshot(
        current_review,
        repository=repository,
        resolved_sha=resolved_sha,
        run_id=run_id,
    )
    current_findings = findings_index(current_review)
    current_claims = claims_index(current_review)

    historical_reviews = [
        row.get("review")
        for row in history
        if isinstance(row.get("review"), dict)
    ]
    historical_indexes = [findings_index(row) for row in historical_reviews]
    previous_snapshot = history[-1] if history else None
    previous_review = (
        previous_snapshot.get("review")
        if isinstance(previous_snapshot, dict)
        and isinstance(previous_snapshot.get("review"), dict)
        else None
    )
    previous_findings = findings_index(previous_review) if previous_review else {}
    previous_claims = claims_index(previous_review) if previous_review else {}

    current_keys = set(current_findings)
    previous_keys = set(previous_findings)
    older_keys = (
        set().union(*(set(values) for values in historical_indexes[:-1]))
        if len(historical_indexes) > 1
        else set()
    )

    new_keys = sorted(current_keys - previous_keys)
    persistent_keys = sorted(current_keys & previous_keys)
    resolved_keys = sorted(previous_keys - current_keys)
    returned_keys = sorted(key for key in new_keys if key in older_keys)
    first_seen_keys = sorted(key for key in new_keys if key not in older_keys)

    severity_changes: list[dict[str, Any]] = []
    severity_escalations: list[dict[str, Any]] = []
    severity_deescalations: list[dict[str, Any]] = []
    for key in persistent_keys:
        before = previous_findings[key]
        after = current_findings[key]
        before_rank = SEVERITY_RANK.get(_safe_text(before.get("severity")).upper(), 0)
        after_rank = SEVERITY_RANK.get(_safe_text(after.get("severity")).upper(), 0)
        if before_rank == after_rank:
            continue
        view = _transition_view(before, after)
        severity_changes.append(view)
        if after_rank > before_rank:
            severity_escalations.append(view)
        elif after_rank < before_rank:
            severity_deescalations.append(view)

    claim_status_changes = [
        _claim_transition(previous_claims[key], current_claims[key])
        for key in sorted(set(previous_claims) & set(current_claims))
        if _safe_text(previous_claims[key].get("status"))
        != _safe_text(current_claims[key].get("status"))
    ]

    product_change: dict[str, Any] | None = None
    comparison_compatible = True
    comparison_suppressed_reason = ""
    if previous_review:
        before_app = previous_review.get("app_intelligence")
        after_app = current_review.get("app_intelligence")
        if isinstance(before_app, dict) and isinstance(after_app, dict):
            comparison_compatible, comparison_suppressed_reason = _scan_comparable(before_app, after_app)
            if comparison_compatible:
                product_change = change_intelligence.build_diff(before_app, after_app)

    capability_removed = (
        list((product_change.get("feature_truth") or {}).get("removed", []))
        if isinstance(product_change, dict)
        and isinstance(product_change.get("feature_truth"), dict)
        else []
    )
    regression_candidates: list[dict[str, Any]] = []
    for key in returned_keys:
        row = dict(current_findings[key])
        row["reason"] = "finding returned after being absent from the immediately previous snapshot"
        regression_candidates.append(row)
    for row in severity_escalations:
        regression_candidates.append({**row, "reason": "persistent finding severity increased"})
    for capability in capability_removed:
        regression_candidates.append({
            "source": "feature_truth",
            "kind": "CAPABILITY_EVIDENCE_REMOVED",
            "subject": capability,
            "reason": "capability evidence disappeared relative to the previous snapshot",
        })

    finding_history = []
    for key in sorted(current_findings):
        history_view = _history_presence(
            key,
            historical_indexes + [current_findings],
            history + [current_snapshot],
        )
        finding_history.append({
            **current_findings[key],
            **history_view,
        })

    if not previous_review:
        state = "INSUFFICIENT_HISTORY"
    elif regression_candidates:
        state = "REGRESSION_REVIEW"
    elif (
        first_seen_keys
        or resolved_keys
        or severity_changes
        or claim_status_changes
        or (
            isinstance(product_change, dict)
            and product_change.get("review_state") != "NO_MATERIAL_CHANGE"
        )
    ):
        state = "CHANGED"
    else:
        state = "STABLE"

    baseline = {
        "available": bool(previous_review),
        "repository": _safe_text(previous_snapshot.get("repository")) if previous_snapshot else "",
        "resolved_sha": _safe_text(previous_snapshot.get("resolved_sha")) if previous_snapshot else "",
        "run_id": _safe_text(previous_snapshot.get("run_id")) if previous_snapshot else "",
        "recorded_at": _safe_text(previous_snapshot.get("recorded_at")) if previous_snapshot else "",
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "state": state,
        "current": {
            "repository": current_snapshot["repository"],
            "resolved_sha": current_snapshot["resolved_sha"],
            "run_id": current_snapshot["run_id"],
            "review_state": _safe_text(current_review.get("review_state")),
        },
        "baseline": baseline,
        "summary": {
            "history_snapshots": len(history),
            "baseline_available": bool(previous_review),
            "current_findings": len(current_findings),
            "new_findings": len(first_seen_keys),
            "returned_findings": len(returned_keys),
            "persistent_findings": len(persistent_keys),
            "resolved_findings": len(resolved_keys),
            "severity_changes": len(severity_changes),
            "severity_escalations": len(severity_escalations),
            "severity_deescalations": len(severity_deescalations),
            "claim_status_changes": len(claim_status_changes),
            "regression_candidates": len(regression_candidates),
            "product_change_state": (
                _safe_text(product_change.get("review_state"))
                if isinstance(product_change, dict)
                else ("SUPPRESSED_INCOMPATIBLE_SCAN" if previous_review and not comparison_compatible else "NO_BASELINE")
            ),
            "comparison_compatible": comparison_compatible,
            "comparison_suppressed_reason": comparison_suppressed_reason,
        },
        "findings": {
            "new": [current_findings[key] for key in first_seen_keys],
            "returned": [current_findings[key] for key in returned_keys],
            "persistent": [current_findings[key] for key in persistent_keys],
            "resolved": [previous_findings[key] for key in resolved_keys],
            "severity_changes": severity_changes,
            "severity_escalations": severity_escalations,
            "severity_deescalations": severity_deescalations,
            "history": finding_history,
        },
        "claims": {
            "status_changes": claim_status_changes,
        },
        "product_change": product_change,
        "regression_candidates": regression_candidates,
        "guardrails": {
            "no_numeric_product_score": True,
            "longitudinal_state_is_advisory": True,
            "regression_candidates_require_review": True,
            "resolved_finding_is_not_proof_of_runtime_fix": True,
            "capability_removal_is_not_automatically_a_defect": True,
            "historical_evidence_never_overrides_current_trusted_evidence": True,
            "release_verdict_unchanged": True,
            "certification_unchanged": True,
        },
    }


def markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# AppLab v3.5 — Longitudinal Product Intelligence",
        "",
        f"- State: **{report.get('state', 'UNKNOWN')}**",
        f"- History snapshots: **{summary['history_snapshots']}**",
        f"- Baseline available: **{summary['baseline_available']}**",
        f"- Current findings: **{summary['current_findings']}**",
        f"- New: **{summary['new_findings']}**",
        f"- Returned: **{summary['returned_findings']}**",
        f"- Persistent: **{summary['persistent_findings']}**",
        f"- Resolved: **{summary['resolved_findings']}**",
        f"- Severity escalations: **{summary['severity_escalations']}**",
        f"- Claim-status changes: **{summary['claim_status_changes']}**",
        f"- Regression candidates: **{summary['regression_candidates']}**",
        "",
    ]
    if not summary["baseline_available"]:
        lines.append(
            "No prior trusted product-review snapshot is available yet; "
            "this run establishes the longitudinal baseline."
        )
        return "\n".join(lines)

    if report["regression_candidates"]:
        lines.extend(["## Regression candidates", ""])
        for row in report["regression_candidates"][:20]:
            lines.append(
                f"- **{row.get('kind', '')}** · {row.get('subject', '')} — "
                f"{row.get('reason', '')}"
            )
        lines.append("")

    changes = report["findings"]["severity_changes"]
    if changes:
        lines.extend(["## Severity transitions", ""])
        for row in changes[:20]:
            lines.append(
                f"- {row.get('kind', '')} · {row.get('subject', '')}: "
                f"{row.get('before_severity', '')} → {row.get('after_severity', '')}"
            )
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    write_report(output_dir, "longitudinal-intelligence", report, markdown(report))


def prune_history(history_dir: Path, limit: int = MAX_HISTORY) -> None:
    if not history_dir.is_dir():
        return
    rows: list[tuple[str, str, Path]] = []
    for path in history_dir.glob("*.json"):
        snapshot = _read_snapshot(path)
        if snapshot is None:
            continue
        rows.append((
            _safe_text(snapshot.get("recorded_at")),
            _safe_text(snapshot.get("resolved_sha")),
            path,
        ))
    rows.sort(key=lambda item: (item[0], item[2].name))

    latest_by_sha: dict[str, tuple[str, str, Path]] = {}
    anonymous: list[tuple[str, str, Path]] = []
    for row in rows:
        sha = row[1]
        if sha:
            previous = latest_by_sha.get(sha)
            if previous is not None:
                previous[2].unlink(missing_ok=True)
            latest_by_sha[sha] = row
        else:
            anonymous.append(row)

    distinct = anonymous + list(latest_by_sha.values())
    distinct.sort(key=lambda item: (item[0], item[2].name))
    for _, _, path in distinct[:-max(1, limit)]:
        path.unlink(missing_ok=True)


def self_test() -> None:
    import tempfile

    def review(
        findings: list[dict[str, Any]],
        claims: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "review_state": "REVIEW_REQUIRED",
            "app_intelligence": {
                "scan": {
                    "max_files": 3500,
                    "scanned_files": 10,
                    "truncated": False,
                    "confidence": "HIGH",
                },
                "feature_truth": {"capabilities": []},
                "product_consistency": {"findings": []},
                "deep_product_model": {"entities": []},
                "product_flow_graph": {"nodes": []},
            },
            "product_contract": {"findings": []},
            "behavioral_product": {"findings": []},
            "state_edge_case": {"findings": []},
            "user_journey": {"findings": []},
            "ux_friction": {"findings": findings},
            "evidence_confidence": {"claims": claims or [], "contradictions": []},
        }

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        older = make_snapshot(
            review([
                {"kind": "A", "subject": "alpha", "severity": "REVIEW"},
                {"kind": "D", "subject": "delta", "severity": "REVIEW"},
            ]),
            repository="owner/app",
            resolved_sha="1" * 40,
            recorded_at="2026-01-01T00:00:00+00:00",
        )
        previous = make_snapshot(
            review([
                {"kind": "B", "subject": "beta", "severity": "INFO"},
                {"kind": "D", "subject": "delta", "severity": "REVIEW"},
            ], [{"id": "claim-1", "subject": "beta", "status": "UNVERIFIED"}]),
            repository="owner/app",
            resolved_sha="2" * 40,
            recorded_at="2026-01-02T00:00:00+00:00",
        )
        (root / "older.json").write_text(json.dumps(older), encoding="utf-8")
        (root / "previous.json").write_text(json.dumps(previous), encoding="utf-8")

        current = review([
            {"kind": "A", "subject": "alpha", "severity": "REVIEW"},
            {"kind": "B", "subject": "beta", "severity": "REVIEW"},
            {"kind": "C", "subject": "gamma", "severity": "INFO"},
        ], [{"id": "claim-1", "subject": "beta", "status": "CONFIRMED"}])
        history = load_history(root, repository="owner/app", current_sha="3" * 40)
        report = build_report(
            current,
            history,
            repository="owner/app",
            resolved_sha="3" * 40,
            run_id="123",
        )
        assert report["state"] == "REGRESSION_REVIEW"
        assert report["summary"]["history_snapshots"] == 2
        assert report["summary"]["new_findings"] == 1
        assert report["summary"]["returned_findings"] == 1
        assert report["summary"]["persistent_findings"] == 1
        assert report["summary"]["resolved_findings"] == 1
        assert report["summary"]["severity_escalations"] == 1
        assert report["summary"]["claim_status_changes"] == 1
        assert report["summary"]["regression_candidates"] == 2
        assert report["findings"]["history"]

        baseline_only = build_report(
            current,
            [],
            repository="owner/app",
            resolved_sha="3" * 40,
        )
        assert baseline_only["state"] == "INSUFFICIENT_HISTORY"

        contract = review([])
        contract["product_contract"]["findings"] = [
            {
                "kind": "PROMISED_WITHOUT_IMPLEMENTATION_EVIDENCE",
                "severity": "REVIEW",
                "capability": "authentication",
            },
            {
                "kind": "PROMISED_WITHOUT_IMPLEMENTATION_EVIDENCE",
                "severity": "REVIEW",
                "capability": "backup",
            },
        ]
        contract_findings = findings_index(contract)
        assert len(contract_findings) == 2
        assert {row["subject"] for row in contract_findings.values()} == {"authentication", "backup"}

        runtime_review = review([])
        runtime_review["behavioral_product"]["findings"] = [
            {"kind": "RUNTIME_INTERACTION_FAILURE", "subject": "save", "severity": "HIGH_REVIEW"}
        ]
        runtime_review["state_edge_case"]["findings"] = [
            {"kind": "EDGE_STATE_RUNTIME_FAILURE", "subject": "offline", "severity": "HIGH_REVIEW"}
        ]
        runtime_sources = {row["source"] for row in findings_index(runtime_review).values()}
        assert {"behavioral_product", "state_edge_case"} <= runtime_sources

        baseline_scan = review([])
        baseline_scan["app_intelligence"]["feature_truth"]["capabilities"] = [
            {"capability": "authentication", "truth": "CODE_CONFIRMED"}
        ]
        lower_scan = review([])
        lower_scan["app_intelligence"]["scan"] = {
            "max_files": 100,
            "scanned_files": 100,
            "truncated": True,
            "confidence": "MEDIUM",
        }
        incompatible = build_report(
            lower_scan,
            [
                make_snapshot(
                    baseline_scan,
                    repository="owner/app",
                    resolved_sha="4" * 40,
                    recorded_at="2026-01-03T00:00:00+00:00",
                )
            ],
            repository="owner/app",
            resolved_sha="5" * 40,
        )
        assert incompatible["summary"]["comparison_compatible"] is False
        assert incompatible["summary"]["product_change_state"] == "SUPPRESSED_INCOMPATIBLE_SCAN"
        assert not any(
            row.get("kind") == "CAPABILITY_EVIDENCE_REMOVED"
            for row in incompatible["regression_candidates"]
        )

        evidence_dir = root / "composed"
        evidence_dir.mkdir()
        (evidence_dir / "autonomous-review.json").write_text(
            json.dumps({"review_state": "READY_FOR_HUMAN_REVIEW"}),
            encoding="utf-8",
        )
        (evidence_dir / "app-intelligence.json").write_text(
            json.dumps({"scan": {"max_files": 3500}, "feature_truth": {"capabilities": []}}),
            encoding="utf-8",
        )
        composed = load_composed_review(None, evidence_dir)
        assert composed["review_state"] == "READY_FOR_HUMAN_REVIEW"
        assert composed["app_intelligence"]["scan"]["max_files"] == 3500

        prune_root = root / "prune"
        prune_root.mkdir()
        duplicate_old = make_snapshot(
            review([]),
            repository="owner/app",
            resolved_sha="6" * 40,
            recorded_at="2026-01-01T00:00:00+00:00",
        )
        duplicate_new = make_snapshot(
            review([]),
            repository="owner/app",
            resolved_sha="6" * 40,
            recorded_at="2026-01-04T00:00:00+00:00",
        )
        distinct = make_snapshot(
            review([]),
            repository="owner/app",
            resolved_sha="7" * 40,
            recorded_at="2026-01-05T00:00:00+00:00",
        )
        (prune_root / "dup-old.json").write_text(json.dumps(duplicate_old), encoding="utf-8")
        (prune_root / "dup-new.json").write_text(json.dumps(duplicate_new), encoding="utf-8")
        (prune_root / "distinct.json").write_text(json.dumps(distinct), encoding="utf-8")
        prune_history(prune_root, 2)
        remaining = [
            _read_snapshot(path)
            for path in prune_root.glob("*.json")
        ]
        remaining_shas = [
            _safe_text(row.get("resolved_sha"))
            for row in remaining
            if isinstance(row, dict)
        ]
        assert remaining_shas.count("6" * 40) == 1
        assert set(remaining_shas) == {"6" * 40, "7" * 40}

        print("AppLab Longitudinal Product Intelligence self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current")
    parser.add_argument("--current-dir", default="")
    parser.add_argument("--history-dir", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--resolved-sha", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output-dir", default="applab-longitudinal")
    parser.add_argument("--snapshot-output", default="")
    parser.add_argument("--history-limit", type=int, default=MAX_HISTORY)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.current and not args.current_dir:
        raise SystemExit("--current or --current-dir is required")

    try:
        current = load_composed_review(
            Path(args.current) if args.current else None,
            Path(args.current_dir) if args.current_dir else None,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    history_dir = Path(args.history_dir) if args.history_dir else None
    history = load_history(
        history_dir,
        repository=args.repository,
        current_sha=args.resolved_sha,
        limit=max(1, args.history_limit),
    )
    report = build_report(
        current,
        history,
        repository=args.repository,
        resolved_sha=args.resolved_sha,
        run_id=args.run_id,
    )
    write_outputs(report, Path(args.output_dir))

    if args.snapshot_output:
        snapshot_path = Path(args.snapshot_output)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            json.dumps(
                make_snapshot(
                    current,
                    repository=args.repository,
                    resolved_sha=args.resolved_sha,
                    run_id=args.run_id,
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        prune_history(snapshot_path.parent, max(1, args.history_limit))

    print(
        json.dumps(
            {
                "engine_version": ENGINE_VERSION,
                "state": report["state"],
                **report["summary"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
