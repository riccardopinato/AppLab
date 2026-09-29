#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from product_review_common import write_report

SCHEMA_VERSION = 1
ENGINE_VERSION = "4.0.0"

FILES = {
    "app": "app-intelligence.json",
    "autonomous": "autonomous-review.json",
    "behavioral": "behavioral-product.json",
    "states": "state-edge-case.json",
    "calibration": "evidence-calibration.json",
    "confidence": "evidence-confidence.json",
    "journey": "user-journey.json",
    "ux": "ux-friction.json",
    "contract": "product-contract-audit.json",
    "decision": "decision-brief.json",
    "longitudinal": "longitudinal-intelligence.json",
    "experiment": "experiment-plan.json",
    "audit": "audit-plan.json",
    "market": "market-intelligence.json",
}


def _safe(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def load_evidence(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key, filename in FILES.items():
        payload = read_json(root / filename)
        if payload is not None:
            result[key] = payload
    return result


def _version(payload: dict[str, Any]) -> str:
    for key in ("platform_version", "engine_version", "lab_version", "studio_version"):
        value = _safe(payload.get(key))
        if value:
            return value
    return ""


def provenance(evidence: dict[str, dict[str, Any]]) -> dict[str, Any]:
    inputs = {}
    for key, payload in sorted(evidence.items()):
        inputs[key] = {
            "file": FILES.get(key, ""),
            "schema_version": payload.get("schema_version"),
            "version": _version(payload),
        }
    return {
        "derivation_type": "DETERMINISTIC_EVIDENCE_SYNTHESIS",
        "engine": "applab_analyst.py",
        "engine_version": ENGINE_VERSION,
        "inputs": inputs,
        "input_count": len(inputs),
        "model_provider": None,
        "model_version": None,
    }


def _present_capabilities(app: dict[str, Any]) -> list[str]:
    product = app.get("product") if isinstance(app.get("product"), dict) else {}
    rows = product.get("feature_signals") if isinstance(product.get("feature_signals"), list) else []
    return sorted(
        {
            _safe(row.get("label"))
            for row in rows
            if isinstance(row, dict)
            and _safe(row.get("label"))
            and _safe(row.get("status")).upper() == "PRESENT"
        }
    )


def product_snapshot(app: dict[str, Any]) -> dict[str, Any]:
    product = app.get("product") if isinstance(app.get("product"), dict) else {}
    stack = product.get("stack") if isinstance(product.get("stack"), dict) else {}
    scan = app.get("scan") if isinstance(app.get("scan"), dict) else {}
    deep = app.get("deep_product_model") if isinstance(app.get("deep_product_model"), dict) else {}
    flow = app.get("product_flow_graph") if isinstance(app.get("product_flow_graph"), dict) else {}
    architecture = app.get("architecture_data") if isinstance(app.get("architecture_data"), dict) else {}
    data = architecture.get("data") if isinstance(architecture.get("data"), dict) else {}
    entities = deep.get("entities") if isinstance(deep.get("entities"), list) else []
    surfaces = flow.get("nodes") if isinstance(flow.get("nodes"), list) else []
    return {
        "engine": _safe(stack.get("engine")) or "unknown",
        "scan_confidence": _safe(scan.get("confidence")) or "UNKNOWN",
        "scan_truncated": bool(scan.get("truncated", False)),
        "scanned_files": int(scan.get("scanned_files", 0) or 0),
        "capabilities": _present_capabilities(app),
        "entity_count": len(entities) or int(deep.get("entity_count", 0) or 0),
        "surface_count": len(surfaces) or int(deep.get("surface_count", 0) or 0),
        "local_first": _safe(data.get("local_first_assessment")) or "UNKNOWN",
    }


def _bucket(decision: dict[str, Any], name: str) -> list[dict[str, Any]]:
    buckets = decision.get("buckets") if isinstance(decision.get("buckets"), dict) else {}
    rows = buckets.get(name) if isinstance(buckets.get(name), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _evidence_list(row: dict[str, Any]) -> list[str]:
    values = row.get("evidence") if isinstance(row.get("evidence"), list) else []
    return [str(value) for value in values[:8]]


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(parts).encode("utf-8")
    return prefix + "-" + hashlib.sha256(raw).hexdigest()[:12].upper()


def observation(
    *,
    category: str,
    priority: str,
    kind: str,
    subject: str,
    statement: str,
    basis: list[str],
    evidence_state: str,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": _stable_id("OBS", category, kind, subject),
        "category": category,
        "priority": priority,
        "kind": kind,
        "subject": subject,
        "statement": statement,
        "basis": list(dict.fromkeys(basis)),
        "evidence_state": evidence_state,
        "evidence": list(dict.fromkeys(evidence or []))[:8],
    }


def build_observations(evidence: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    decision = evidence.get("decision", {})
    longitudinal = evidence.get("longitudinal", {})
    confidence = evidence.get("confidence", {})
    experiment = evidence.get("experiment", {})

    rows: list[dict[str, Any]] = []

    for item in _bucket(decision, "FIX_NOW"):
        kind = _safe(item.get("kind"))
        subject = _safe(item.get("subject"))
        rows.append(
            observation(
                category="CONFIRMED_ACTION",
                priority="HIGH",
                kind=kind,
                subject=subject,
                statement=_safe(item.get("message")) or f"{kind} is supported by the Decision Brief FIX_NOW policy.",
                basis=["decision-brief.json", "evidence-calibration.json"],
                evidence_state=_safe(item.get("basis")) or "RUNTIME_CONFIRMED",
                evidence=_evidence_list(item),
            )
        )

    regressions = (
        longitudinal.get("regression_candidates")
        if isinstance(longitudinal.get("regression_candidates"), list)
        else []
    )
    for item in regressions:
        if not isinstance(item, dict):
            continue
        kind = _safe(item.get("kind"))
        subject = _safe(item.get("subject"))
        rows.append(
            observation(
                category="REGRESSION_REVIEW",
                priority="HIGH",
                kind=kind,
                subject=subject,
                statement=_safe(item.get("reason")) or "Longitudinal evidence marks this as a regression candidate.",
                basis=["longitudinal-intelligence.json"],
                evidence_state="LONGITUDINAL_CANDIDATE",
                evidence=_evidence_list(item),
            )
        )

    contradictions = (
        confidence.get("contradictions")
        if isinstance(confidence.get("contradictions"), list)
        else []
    )
    for item in contradictions:
        if not isinstance(item, dict):
            continue
        kind = _safe(item.get("kind")) or "EVIDENCE_CONTRADICTION"
        subject = _safe(item.get("subject"))
        rows.append(
            observation(
                category="EVIDENCE_CONTRADICTION",
                priority="HIGH",
                kind=kind,
                subject=subject,
                statement=_safe(item.get("message")) or "Bounded evidence sources disagree for the same product subject.",
                basis=["evidence-confidence.json"],
                evidence_state="CONTRADICTED",
                evidence=_evidence_list(item),
            )
        )

    for item in _bucket(decision, "VERIFY_NEXT"):
        kind = _safe(item.get("kind"))
        subject = _safe(item.get("subject"))
        rows.append(
            observation(
                category="VERIFICATION_GAP",
                priority="NORMAL",
                kind=kind,
                subject=subject,
                statement=_safe(item.get("message")) or "Current evidence requires bounded verification.",
                basis=["decision-brief.json"],
                evidence_state=_safe(item.get("basis")) or "VERIFY_NEXT",
                evidence=_evidence_list(item),
            )
        )

    exp_rows = experiment.get("experiments") if isinstance(experiment.get("experiments"), list) else []
    if exp_rows:
        top = exp_rows[0] if isinstance(exp_rows[0], dict) else {}
        if top:
            rows.append(
                observation(
                    category="NEXT_EXPERIMENT",
                    priority=_safe(top.get("priority")) or "NORMAL",
                    kind=_safe(top.get("kind")) or "EXPERIMENT",
                    subject=_safe(top.get("subject")),
                    statement=(
                        f"Next bounded experiment is {_safe(top.get('id'))}: "
                        f"{_safe(top.get('experiment_type'))} using "
                        f"{', '.join(str(x) for x in top.get('labs', []) if isinstance(x, str)) or 'bounded review'}."
                    ),
                    basis=["experiment-plan.json"],
                    evidence_state="PLANNED",
                    evidence=[str(x) for x in top.get("evidence", [])[:8]] if isinstance(top.get("evidence"), list) else [],
                )
            )

    priority_rank = {"HIGH": 0, "NORMAL": 1, "LOW": 2}
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = "|".join((_safe(row.get("category")), _safe(row.get("kind")), _safe(row.get("subject"))))
        if key not in unique:
            unique[key] = row
    result = list(unique.values())
    result.sort(
        key=lambda row: (
            priority_rank.get(_safe(row.get("priority")), 9),
            _safe(row.get("category")),
            _safe(row.get("kind")),
            _safe(row.get("subject")),
        )
    )
    return result[:30]


def build_actions(evidence: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    decision = evidence.get("decision", {})
    experiment = evidence.get("experiment", {})
    actions: list[dict[str, Any]] = []

    for item in _bucket(decision, "FIX_NOW"):
        kind = _safe(item.get("kind"))
        subject = _safe(item.get("subject"))
        actions.append(
            {
                "id": _stable_id("ACT", "FIX", kind, subject),
                "priority": "HIGH",
                "action": "FIX_CONFIRMED_ISSUE",
                "kind": kind,
                "subject": subject,
                "rationale": _safe(item.get("message")),
                "basis": ["decision-brief.json", "evidence-calibration.json"],
                "source_id": None,
            }
        )

    exp_rows = experiment.get("experiments") if isinstance(experiment.get("experiments"), list) else []
    for item in exp_rows:
        if not isinstance(item, dict):
            continue
        exp_type = _safe(item.get("experiment_type"))
        action_type = "VERIFY_AFTER_FIX" if exp_type == "POST_FIX_VERIFICATION" else "RUN_BOUNDED_EXPERIMENT"
        actions.append(
            {
                "id": _stable_id("ACT", action_type, _safe(item.get("id"))),
                "priority": _safe(item.get("priority")) or "NORMAL",
                "action": action_type,
                "kind": _safe(item.get("kind")),
                "subject": _safe(item.get("subject")),
                "rationale": _safe(item.get("reason")) or _safe(item.get("hypothesis")),
                "basis": ["experiment-plan.json"],
                "source_id": _safe(item.get("id")) or None,
                "labs": [str(x) for x in item.get("labs", []) if isinstance(x, str)][:6],
            }
        )

    for item in _bucket(decision, "IMPROVE"):
        kind = _safe(item.get("kind"))
        subject = _safe(item.get("subject"))
        actions.append(
            {
                "id": _stable_id("ACT", "IMPROVE", kind, subject),
                "priority": "LOW",
                "action": "CONSIDER_EVIDENCE_BACKED_IMPROVEMENT",
                "kind": kind,
                "subject": subject,
                "rationale": _safe(item.get("message")),
                "basis": ["decision-brief.json"],
                "source_id": None,
            }
        )

    rank = {"HIGH": 0, "NORMAL": 1, "LOW": 2}
    action_rank = {
        "FIX_CONFIRMED_ISSUE": 0,
        "VERIFY_AFTER_FIX": 1,
        "RUN_BOUNDED_EXPERIMENT": 2,
        "CONSIDER_EVIDENCE_BACKED_IMPROVEMENT": 3,
    }
    deduped: dict[str, dict[str, Any]] = {}
    for row in actions:
        key = "|".join((_safe(row.get("action")), _safe(row.get("kind")), _safe(row.get("subject")), _safe(row.get("source_id"))))
        deduped.setdefault(key, row)
    result = list(deduped.values())
    result.sort(
        key=lambda row: (
            rank.get(_safe(row.get("priority")), 9),
            action_rank.get(_safe(row.get("action")), 9),
            _safe(row.get("kind")),
            _safe(row.get("subject")),
        )
    )
    return result[:20]


def market_context(market: dict[str, Any]) -> dict[str, Any] | None:
    if not market:
        return None
    competitors = market.get("competitors") if isinstance(market.get("competitors"), list) else []
    summary = market.get("summary") if isinstance(market.get("summary"), dict) else {}
    return {
        "available": True,
        "competitors": len(competitors) or int(summary.get("competitors", 0) or 0),
        "common_gap_reviews": int(summary.get("common_gap_reviews", 0) or 0),
        "differentiator_signals": int(summary.get("differentiator_signals", 0) or 0),
        "recurring_pain_signals": int(summary.get("recurring_pain_signals", 0) or 0),
        "interpretation": "Descriptive market evidence only; no competitor ranking or feature invention.",
    }


def analyst_state(evidence: dict[str, dict[str, Any]]) -> str:
    decision = evidence.get("decision", {})
    autonomous = evidence.get("autonomous", {})
    longitudinal = evidence.get("longitudinal", {})
    confidence = evidence.get("confidence", {})
    experiment = evidence.get("experiment", {})

    if _bucket(decision, "FIX_NOW"):
        return "CONFIRMED_ACTION"

    trust = autonomous.get("runtime_evidence_trust") if isinstance(autonomous.get("runtime_evidence_trust"), dict) else {}
    runtime_trusted = bool(trust.get("trusted", (autonomous.get("summary") or {}).get("runtime_evidence_trusted", False)))
    if not runtime_trusted or _safe(autonomous.get("review_state")) == "EVIDENCE_INCOMPLETE":
        return "EVIDENCE_INCOMPLETE"

    contradictions = confidence.get("contradictions") if isinstance(confidence.get("contradictions"), list) else []
    exp_summary = experiment.get("summary") if isinstance(experiment.get("summary"), dict) else {}
    if (
        contradictions
        or _bucket(decision, "VERIFY_NEXT")
        or int(exp_summary.get("high_priority", 0) or 0) > 0
        or _safe(longitudinal.get("state")) == "REGRESSION_REVIEW"
    ):
        return "VERIFICATION_REQUIRED"

    if _safe(longitudinal.get("state")) == "CHANGED":
        return "CHANGE_REVIEW"

    return "NO_IMMEDIATE_ACTION"


def build_report(evidence: dict[str, dict[str, Any]]) -> dict[str, Any]:
    app = evidence.get("app", {})
    autonomous = evidence.get("autonomous", {})
    decision = evidence.get("decision", {})
    confidence = evidence.get("confidence", {})
    longitudinal = evidence.get("longitudinal", {})
    experiment = evidence.get("experiment", {})
    journey = evidence.get("journey", {})
    ux = evidence.get("ux", {})

    fix_now = _bucket(decision, "FIX_NOW")
    verify_next = _bucket(decision, "VERIFY_NEXT")
    improve = _bucket(decision, "IMPROVE")
    contradictions = confidence.get("contradictions") if isinstance(confidence.get("contradictions"), list) else []
    confidence_summary = confidence.get("summary") if isinstance(confidence.get("summary"), dict) else {}
    longitudinal_summary = longitudinal.get("summary") if isinstance(longitudinal.get("summary"), dict) else {}
    experiment_summary = experiment.get("summary") if isinstance(experiment.get("summary"), dict) else {}
    journey_summary = journey.get("summary") if isinstance(journey.get("summary"), dict) else {}
    ux_summary = ux.get("summary") if isinstance(ux.get("summary"), dict) else {}
    trust = autonomous.get("runtime_evidence_trust") if isinstance(autonomous.get("runtime_evidence_trust"), dict) else {}

    state = analyst_state(evidence)
    observations = build_observations(evidence)
    actions = build_actions(evidence)

    if state == "CONFIRMED_ACTION":
        headline = f"{len(fix_now)} evidence-backed issue(s) meet FIX_NOW criteria; preserve the original trusted path for post-fix verification."
    elif state == "EVIDENCE_INCOMPLETE":
        headline = "Current evidence is incomplete; AppLab should gather missing trusted evidence before stronger product conclusions."
    elif state == "VERIFICATION_REQUIRED":
        headline = f"Current evidence requires bounded verification: {len(contradictions)} contradiction(s), {len(verify_next)} VERIFY_NEXT item(s), {int(experiment_summary.get('high_priority', 0) or 0)} high-priority experiment(s)."
    elif state == "CHANGE_REVIEW":
        headline = "Longitudinal evidence changed without a current regression candidate; review the evidence delta before changing product conclusions."
    else:
        headline = "Current bounded evidence contains no immediate FIX_NOW or high-priority verification requirement."

    briefing = [
        {
            "statement": headline,
            "basis": ["decision-brief.json", "evidence-confidence.json", "longitudinal-intelligence.json", "experiment-plan.json"],
        },
        {
            "statement": (
                f"Runtime evidence trust is {_safe(trust.get('state')) or ('TRUSTED' if trust.get('trusted') else 'NOT_PROVIDED')} "
                f"and Autonomous Review state is {_safe(autonomous.get('review_state')) or 'UNKNOWN'}."
            ),
            "basis": ["autonomous-review.json"],
        },
        {
            "statement": (
                f"Longitudinal state is {_safe(longitudinal.get('state')) or 'NOT_AVAILABLE'} across "
                f"{int(longitudinal_summary.get('history_snapshots', 0) or 0)} prior snapshot(s)."
            ),
            "basis": ["longitudinal-intelligence.json"],
        },
        {
            "statement": (
                f"Experiment Planner exposes {int(experiment_summary.get('experiments', 0) or 0)} experiment(s), "
                f"with {int(experiment_summary.get('high_priority', 0) or 0)} high-priority."
            ),
            "basis": ["experiment-plan.json"],
        },
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "state": state,
        "headline": headline,
        "product": product_snapshot(app),
        "evidence_posture": {
            "autonomous_review_state": _safe(autonomous.get("review_state")) or "UNKNOWN",
            "runtime_trust_state": _safe(trust.get("state")) or ("TRUSTED" if trust.get("trusted") else "NOT_PROVIDED"),
            "runtime_trusted": bool(trust.get("trusted", False)),
            "claims": int(confidence_summary.get("total_claims", 0) or 0),
            "confirmed": int(confidence_summary.get("confirmed", 0) or 0),
            "corroborated": int(confidence_summary.get("corroborated", 0) or 0),
            "contradicted": int(confidence_summary.get("contradicted", 0) or 0),
            "unverified": int(confidence_summary.get("unverified", 0) or 0),
            "contradiction_count": len(contradictions),
            "journeys_observed": int(journey_summary.get("journeys_observed", 0) or 0),
            "journey_review_signals": int(journey_summary.get("review_signals", 0) or 0),
            "ux_review_signals": int(ux_summary.get("review_signals", 0) or 0),
        },
        "change_context": {
            "longitudinal_state": _safe(longitudinal.get("state")) or "NOT_AVAILABLE",
            "history_snapshots": int(longitudinal_summary.get("history_snapshots", 0) or 0),
            "new_findings": int(longitudinal_summary.get("new_findings", 0) or 0),
            "returned_findings": int(longitudinal_summary.get("returned_findings", 0) or 0),
            "persistent_findings": int(longitudinal_summary.get("persistent_findings", 0) or 0),
            "resolved_findings": int(longitudinal_summary.get("resolved_findings", 0) or 0),
            "regression_candidates": int(longitudinal_summary.get("regression_candidates", 0) or 0),
        },
        "experiment_context": {
            "state": _safe(experiment.get("state")) or "NOT_AVAILABLE",
            "next_experiment_id": _safe(experiment.get("next_experiment_id")) or None,
            "experiments": int(experiment_summary.get("experiments", 0) or 0),
            "high_priority": int(experiment_summary.get("high_priority", 0) or 0),
            "existing_lab_ready": int(experiment_summary.get("existing_lab_ready", 0) or 0),
            "bounded_review_only": int(experiment_summary.get("bounded_review_only", 0) or 0),
        },
        "decision_context": {
            "fix_now": len(fix_now),
            "verify_next": len(verify_next),
            "improve": len(improve),
            "no_action": len(_bucket(decision, "NO_ACTION")),
        },
        "market": market_context(evidence.get("market", {})),
        "briefing": briefing,
        "observations": observations,
        "next_actions": actions,
        "summary": {
            "observations": len(observations),
            "high_priority_observations": sum(1 for row in observations if row.get("priority") == "HIGH"),
            "next_actions": len(actions),
            "high_priority_actions": sum(1 for row in actions if row.get("priority") == "HIGH"),
            "fix_now": len(fix_now),
            "verify_next": len(verify_next),
            "experiments": int(experiment_summary.get("experiments", 0) or 0),
            "contradictions": len(contradictions),
            "regression_candidates": int(longitudinal_summary.get("regression_candidates", 0) or 0),
        },
        "do_not_conclude": [
            "A regression candidate is not automatically a product defect.",
            "A resolved finding is not proof that runtime behavior was fixed.",
            "Missing or unobserved evidence is not PASS.",
            "Static heuristics do not override stronger trusted runtime evidence.",
            "Market evidence does not alter technical verification or certification.",
            "The Analyst state is not a release or certification verdict.",
        ],
        "provenance": provenance(evidence),
        "guardrails": {
            "deterministic_synthesis": True,
            "no_required_llm": True,
            "no_numeric_quality_score": True,
            "no_feature_invention": True,
            "no_automatic_product_mutation": True,
            "all_actionable_observations_have_basis": True,
            "current_trusted_evidence_remains_authoritative": True,
            "fast_full_certification_remain_independent": True,
        },
    }


def markdown(report: dict[str, Any]) -> str:
    product = report["product"]
    evidence = report["evidence_posture"]
    change = report["change_context"]
    experiments = report["experiment_context"]
    decisions = report["decision_context"]

    lines = [
        "# AppLab v4.0 — Analyst Report",
        "",
        f"- Analyst state: **{report['state']}**",
        f"- Headline: {report['headline']}",
        "",
        "## Product context",
        "",
        f"- Engine: **{product['engine']}**",
        f"- Scan confidence: **{product['scan_confidence']}**",
        f"- Capabilities: **{len(product['capabilities'])}**",
        f"- Entities / surfaces: **{product['entity_count']} / {product['surface_count']}**",
        f"- Local-first: **{product['local_first']}**",
        "",
        "## Evidence posture",
        "",
        f"- Autonomous review: **{evidence['autonomous_review_state']}**",
        f"- Runtime trust: **{evidence['runtime_trust_state']}**",
        f"- Claims confirmed/corroborated/contradicted/unverified: **{evidence['confirmed']} / {evidence['corroborated']} / {evidence['contradicted']} / {evidence['unverified']}**",
        f"- Contradictions: **{evidence['contradiction_count']}**",
        f"- Journeys observed: **{evidence['journeys_observed']}**",
        "",
        "## Change and experiments",
        "",
        f"- Longitudinal state: **{change['longitudinal_state']}**",
        f"- History snapshots: **{change['history_snapshots']}**",
        f"- Regression candidates: **{change['regression_candidates']}**",
        f"- Experiment state: **{experiments['state']}**",
        f"- Planned experiments: **{experiments['experiments']}**",
        f"- Next experiment: **{experiments['next_experiment_id'] or '—'}**",
        "",
        "## Decision context",
        "",
        f"- FIX_NOW: **{decisions['fix_now']}**",
        f"- VERIFY_NEXT: **{decisions['verify_next']}**",
        f"- IMPROVE: **{decisions['improve']}**",
        "",
    ]

    if report["observations"]:
        lines.extend(["## Evidence-backed observations", ""])
        for row in report["observations"][:20]:
            lines.append(
                f"- **{row['priority']} · {row['category']} · {row['kind']}**"
                f"{' · ' + row['subject'] if row['subject'] else ''}: {row['statement']} "
                f"(basis: {', '.join(row['basis'])})"
            )
        lines.append("")

    if report["next_actions"]:
        lines.extend(["## Next actions", ""])
        for row in report["next_actions"][:16]:
            lines.append(
                f"- **{row['priority']} · {row['action']}**"
                f"{' · ' + row['subject'] if row['subject'] else ''}: {row['rationale']} "
                f"(basis: {', '.join(row['basis'])})"
            )
        lines.append("")

    lines.extend(["## Do not conclude", ""])
    lines.extend(f"- {value}" for value in report["do_not_conclude"])
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    write_report(output_dir, "analyst-report", report, markdown(report))


def self_test() -> None:
    evidence = {
        "app": {
            "schema_version": 1,
            "lab_version": "2.5.0",
            "scan": {"confidence": "HIGH", "scanned_files": 50, "truncated": False},
            "product": {
                "stack": {"engine": "flutter"},
                "feature_signals": [
                    {"label": "authentication", "status": "PRESENT"},
                    {"label": "cloud_or_sync", "status": "PRESENT"},
                ],
            },
            "deep_product_model": {"entities": [{"name": "User"}]},
            "product_flow_graph": {"nodes": [{"id": "home"}, {"id": "login"}]},
            "architecture_data": {"data": {"local_first_assessment": "PARTIAL"}},
        },
        "autonomous": {
            "schema_version": 2,
            "platform_version": "4.0.0",
            "review_state": "ATTENTION_REQUIRED",
            "runtime_evidence_trust": {"trusted": True, "state": "TRUSTED"},
        },
        "decision": {
            "lab_version": "3.4.0",
            "buckets": {
                "FIX_NOW": [
                    {
                        "kind": "RUNTIME_INTERACTION_FAILURE",
                        "subject": "Save",
                        "message": "Save failed in trusted runtime.",
                        "basis": "RUNTIME_CONFIRMED",
                        "evidence": ["interaction-crawl.json"],
                    }
                ],
                "VERIFY_NEXT": [
                    {
                        "kind": "EDGE_STATE_NOT_OBSERVED",
                        "subject": "offline",
                        "message": "Offline state not observed.",
                        "basis": "STATIC_HEURISTIC",
                        "evidence": [],
                    }
                ],
                "IMPROVE": [],
                "NO_ACTION": [],
            },
        },
        "confidence": {
            "summary": {
                "total_claims": 5,
                "confirmed": 2,
                "corroborated": 1,
                "contradicted": 1,
                "unverified": 1,
            },
            "contradictions": [
                {
                    "kind": "CONTRACT_RUNTIME_CONTRADICTION",
                    "subject": "authentication",
                    "message": "Contract and runtime disagree.",
                    "evidence": ["README.md", "ui.xml"],
                }
            ],
        },
        "longitudinal": {
            "state": "REGRESSION_REVIEW",
            "summary": {
                "history_snapshots": 4,
                "new_findings": 1,
                "returned_findings": 1,
                "persistent_findings": 2,
                "resolved_findings": 1,
                "regression_candidates": 1,
            },
            "regression_candidates": [
                {
                    "kind": "NAVIGATION_LOOP_CANDIDATE",
                    "subject": "Search",
                    "reason": "finding returned",
                }
            ],
        },
        "experiment": {
            "state": "EXPERIMENTS_READY",
            "next_experiment_id": "EXP-ONE",
            "summary": {
                "experiments": 2,
                "high_priority": 1,
                "existing_lab_ready": 2,
                "bounded_review_only": 0,
            },
            "experiments": [
                {
                    "id": "EXP-ONE",
                    "priority": "HIGH",
                    "kind": "NAVIGATION_LOOP_CANDIDATE",
                    "subject": "Search",
                    "experiment_type": "TARGETED_JOURNEY",
                    "labs": ["safe-interaction-crawler", "visual-journey"],
                    "reason": "finding returned",
                    "evidence": ["journey-crawl.json"],
                }
            ],
        },
        "journey": {"summary": {"journeys_observed": 3, "review_signals": 1}},
        "ux": {"summary": {"review_signals": 2}},
    }

    report = build_report(evidence)
    assert report["state"] == "CONFIRMED_ACTION"
    assert report["product"]["engine"] == "flutter"
    assert report["product"]["capabilities"] == ["authentication", "cloud_or_sync"]
    assert report["summary"]["fix_now"] == 1
    assert report["summary"]["contradictions"] == 1
    assert report["next_actions"][0]["action"] == "FIX_CONFIRMED_ISSUE"
    assert report["provenance"]["input_count"] >= 7
    assert report["guardrails"]["no_numeric_quality_score"] is True
    assert all(row["basis"] for row in report["observations"])
    assert "score" not in report["summary"]

    incomplete = build_report(
        {
            "autonomous": {
                "review_state": "EVIDENCE_INCOMPLETE",
                "runtime_evidence_trust": {"trusted": False, "state": "NOT_PROVIDED"},
            },
            "decision": {"buckets": {}},
        }
    )
    assert incomplete["state"] == "EVIDENCE_INCOMPLETE"

    stable = build_report(
        {
            "autonomous": {
                "review_state": "READY_FOR_HUMAN_REVIEW",
                "runtime_evidence_trust": {"trusted": True, "state": "TRUSTED"},
            },
            "decision": {"buckets": {}},
            "longitudinal": {"state": "STABLE", "summary": {}},
            "confidence": {"summary": {}, "contradictions": []},
            "experiment": {"state": "NO_EXPERIMENTS_REQUIRED", "summary": {}},
        }
    )
    assert stable["state"] == "NO_IMMEDIATE_ACTION"
    print("AppLab Analyst v4.0 self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir")
    parser.add_argument("--output-dir", default="applab-autonomous-review")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.evidence_dir:
        raise SystemExit("--evidence-dir is required")

    root = Path(args.evidence_dir)
    if not root.is_dir():
        raise SystemExit("evidence directory does not exist")

    report = build_report(load_evidence(root))
    write_outputs(report, Path(args.output_dir))
    print(json.dumps({"engine_version": ENGINE_VERSION, "state": report["state"], **report["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
