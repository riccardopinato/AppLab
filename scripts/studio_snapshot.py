#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STUDIO_VERSION = "4.0.2"


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def present_capabilities(app: dict[str, Any]) -> list[str]:
    product = app.get("product") if isinstance(app.get("product"), dict) else {}
    rows = product.get("feature_signals") if isinstance(product.get("feature_signals"), list) else []
    result: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("status", "")).upper() != "PRESENT":
            continue
        label = str(row.get("label", "")).strip()
        if label:
            result.append(label)
    return sorted(set(result))


def count_findings(app: dict[str, Any], section: str) -> int:
    block = app.get(section) if isinstance(app.get(section), dict) else {}
    rows = block.get("findings") if isinstance(block.get("findings"), list) else []
    return sum(1 for row in rows if isinstance(row, dict))


def project_summary(project_id: str, project_dir: Path) -> dict[str, Any] | None:
    app = read_json(project_dir / "app-intelligence.json")
    market = read_json(project_dir / "market-intelligence.json")
    audit = read_json(project_dir / "audit-plan.json")
    change = read_json(project_dir / "change-intelligence.json")
    behavioral = read_json(project_dir / "behavioral-product.json")
    state_edge = read_json(project_dir / "state-edge-case.json")
    calibration = read_json(project_dir / "evidence-calibration.json")
    evidence_confidence = read_json(project_dir / "evidence-confidence.json")
    user_journey = read_json(project_dir / "user-journey.json")
    ux_friction = read_json(project_dir / "ux-friction.json")
    longitudinal = read_json(project_dir / "longitudinal-intelligence.json")
    experiment = read_json(project_dir / "experiment-plan.json")
    analyst = read_json(project_dir / "analyst-report.json")
    contract = read_json(project_dir / "product-contract-audit.json")
    brief = read_json(project_dir / "decision-brief.json")
    autonomous = read_json(project_dir / "autonomous-review.json")

    if all(
        item is None
        for item in (app, market, audit, change, behavioral, state_edge, calibration, evidence_confidence, user_journey, ux_friction, longitudinal, experiment, analyst, contract, brief, autonomous)
    ):
        return None

    row: dict[str, Any] = {
        "project_id": project_id,
        "product": None,
        "ux": None,
        "architecture": None,
        "market": None,
        "audit": None,
        "change": None,
        "evidence_confidence": None,
        "user_journey": None,
        "ux_friction": None,
        "longitudinal": None,
        "experiment_plan": None,
        "analyst": None,
        "autonomous_review": None,
    }

    if app:
        product = app.get("product") if isinstance(app.get("product"), dict) else {}
        stack = product.get("stack") if isinstance(product.get("stack"), dict) else {}
        scan = app.get("scan") if isinstance(app.get("scan"), dict) else {}
        architecture = (
            app.get("architecture_data")
            if isinstance(app.get("architecture_data"), dict)
            else {}
        )
        data = architecture.get("data") if isinstance(architecture.get("data"), dict) else {}
        truth = (
            app.get("feature_truth")
            if isinstance(app.get("feature_truth"), dict)
            else {}
        )
        truth_summary = (
            truth.get("summary") if isinstance(truth.get("summary"), dict) else {}
        )
        flow = (
            app.get("product_flow_graph")
            if isinstance(app.get("product_flow_graph"), dict)
            else {}
        )
        flow_summary = (
            flow.get("summary") if isinstance(flow.get("summary"), dict) else {}
        )
        deep = (
            app.get("deep_product_model")
            if isinstance(app.get("deep_product_model"), dict)
            else {}
        )
        deep_summary = (
            deep.get("summary") if isinstance(deep.get("summary"), dict) else {}
        )
        row["product"] = {
            "engine": str(stack.get("engine", "unknown")),
            "confidence": str(scan.get("confidence", "UNKNOWN")),
            "capabilities": present_capabilities(app),
            "screen_like_files": int(
                ((product.get("surface") or {}).get("screen_like_files", 0))
                if isinstance(product.get("surface"), dict)
                else 0
            ),
            "entity_count": int(deep.get("entity_count", 0) or 0),
            "surface_count": int(deep.get("surface_count", 0) or 0),
            "lifecycle_review_signals": int(
                deep_summary.get("lifecycle_review_signals", 0) or 0
            ),
            "documentation_drift_signals": int(
                deep_summary.get("documentation_drift_signals", 0) or 0
            ),
            "code_confirmed_capabilities": int(
                truth_summary.get("CODE_CONFIRMED", 0) or 0
            ),
            "doc_only_capabilities": int(
                truth_summary.get("DOC_ONLY_SIGNAL", 0) or 0
            ),
            "flow_nodes": int(flow.get("node_count", 0) or 0),
            "flow_edges": int(flow.get("edge_count", 0) or 0),
            "orphan_surface_candidates": int(
                flow_summary.get("orphan_surface_candidates", 0) or 0
            ),
        }
        row["ux"] = {
            "review_signals": count_findings(app, "ux_product"),
        }
        row["architecture"] = {
            "review_signals": count_findings(app, "architecture_data"),
            "local_first": str(data.get("local_first_assessment", "UNKNOWN")),
        }
        consistency = (
            app.get("product_consistency")
            if isinstance(app.get("product_consistency"), dict)
            else {}
        )
        consistency_summary = (
            consistency.get("summary")
            if isinstance(consistency.get("summary"), dict)
            else {}
        )
        consistency_findings = (
            consistency.get("findings")
            if isinstance(consistency.get("findings"), list)
            else []
        )
        row["consistency"] = {
            "total": int(consistency_summary.get("total", 0) or 0),
            "high_review": int(consistency_summary.get("high_review", 0) or 0),
            "review": int(consistency_summary.get("review", 0) or 0),
            "info": int(consistency_summary.get("info", 0) or 0),
            "by_domain": (
                consistency_summary.get("by_domain", {})
                if isinstance(consistency_summary.get("by_domain"), dict)
                else {}
            ),
            "top_findings": [
                {
                    "domain": str(item.get("domain", "")),
                    "kind": str(item.get("kind", "")),
                    "severity": str(item.get("severity", "")),
                    "subject": str(item.get("subject", "")),
                }
                for item in consistency_findings[:8]
                if isinstance(item, dict)
            ],
        }
        lifecycle = (
            app.get("lifecycle_integrity")
            if isinstance(app.get("lifecycle_integrity"), dict)
            else {}
        )
        lifecycle_summary = (
            lifecycle.get("summary")
            if isinstance(lifecycle.get("summary"), dict)
            else {}
        )
        row["lifecycle"] = {
            "entities_checked": int(lifecycle_summary.get("entities_checked", 0) or 0),
            "entities_with_review": int(
                lifecycle_summary.get("entities_with_review", 0) or 0
            ),
            "review_signals": int(lifecycle_summary.get("review_signals", 0) or 0),
            "by_kind": (
                lifecycle_summary.get("by_kind", {})
                if isinstance(lifecycle_summary.get("by_kind"), dict)
                else {}
            ),
        }

    if market:
        capabilities = market.get("capabilities") if isinstance(market.get("capabilities"), list) else []
        reviews = market.get("reviews") if isinstance(market.get("reviews"), dict) else {}
        recurring = (
            reviews.get("recurring_pain_signals")
            if isinstance(reviews.get("recurring_pain_signals"), list)
            else []
        )
        row["market"] = {
            "competitors": int(market.get("competitor_count", 0) or 0),
            "common_gap_reviews": sum(
                1
                for item in capabilities
                if isinstance(item, dict)
                and item.get("classification") == "COMMON_MARKET_GAP_REVIEW"
            ),
            "differentiator_signals": sum(
                1
                for item in capabilities
                if isinstance(item, dict)
                and item.get("classification") == "PROJECT_DIFFERENTIATOR_SIGNAL"
            ),
            "recurring_pain_signals": len(recurring),
        }

    if audit:
        selected = audit.get("selected_labs") if isinstance(audit.get("selected_labs"), list) else []
        row["audit"] = {
            "selected_lab_count": int(audit.get("selected_lab_count", len(selected)) or 0),
            "manual_review_required": bool(audit.get("manual_review_required", False)),
            "top_labs": [
                {
                    "lab": str(item.get("lab", "")),
                    "priority": str(item.get("priority", "")),
                }
                for item in selected[:8]
                if isinstance(item, dict)
            ],
        }

    if change:
        summary = change.get("summary") if isinstance(change.get("summary"), dict) else {}
        row["change"] = {
            "review_state": str(change.get("review_state", "UNKNOWN")),
            "feature_truth_changes": int(summary.get("feature_truth_changes", 0) or 0),
            "capabilities_added": int(summary.get("capabilities_added", 0) or 0),
            "capabilities_removed": int(summary.get("capabilities_removed", 0) or 0),
            "entities_added": int(summary.get("entities_added", 0) or 0),
            "entities_removed": int(summary.get("entities_removed", 0) or 0),
            "surfaces_added": int(summary.get("surfaces_added", 0) or 0),
            "surfaces_removed": int(summary.get("surfaces_removed", 0) or 0),
            "new_findings": int(summary.get("new_findings", 0) or 0),
            "resolved_findings": int(summary.get("resolved_findings", 0) or 0),
            "new_high_review": int(summary.get("new_high_review", 0) or 0),
            "new_review": int(summary.get("new_review", 0) or 0),
        }

    if ux_friction:
        ux_summary = (
            ux_friction.get("summary")
            if isinstance(ux_friction.get("summary"), dict)
            else {}
        )
        ux_findings = (
            ux_friction.get("findings")
            if isinstance(ux_friction.get("findings"), list)
            else []
        )
        row["ux_friction"] = {
            "runtime_transitions": int(ux_summary.get("runtime_transitions", 0) or 0),
            "no_change_actions": int(ux_summary.get("no_change_actions", 0) or 0),
            "no_change_share": float(ux_summary.get("no_change_share", 0.0) or 0.0),
            "review_signals": int(ux_summary.get("review_signals", 0) or 0),
            "info_signals": int(ux_summary.get("info_signals", 0) or 0),
            "by_category": (
                ux_summary.get("by_category", {})
                if isinstance(ux_summary.get("by_category"), dict)
                else {}
            ),
            "top_findings": [
                {
                    "category": str(item.get("category", "")),
                    "kind": str(item.get("kind", "")),
                    "severity": str(item.get("severity", "")),
                    "subject": str(item.get("subject", "")),
                }
                for item in ux_findings[:8]
                if isinstance(item, dict)
            ],
        }

    if longitudinal:
        longitudinal_summary = (
            longitudinal.get("summary")
            if isinstance(longitudinal.get("summary"), dict)
            else {}
        )
        longitudinal_baseline = (
            longitudinal.get("baseline")
            if isinstance(longitudinal.get("baseline"), dict)
            else {}
        )
        regression_rows = (
            longitudinal.get("regression_candidates")
            if isinstance(longitudinal.get("regression_candidates"), list)
            else []
        )
        row["longitudinal"] = {
            "state": str(longitudinal.get("state", "UNKNOWN")),
            "history_snapshots": int(longitudinal_summary.get("history_snapshots", 0) or 0),
            "baseline_available": bool(longitudinal_summary.get("baseline_available", False)),
            "baseline_sha": str(longitudinal_baseline.get("resolved_sha", "")),
            "new_findings": int(longitudinal_summary.get("new_findings", 0) or 0),
            "returned_findings": int(longitudinal_summary.get("returned_findings", 0) or 0),
            "persistent_findings": int(longitudinal_summary.get("persistent_findings", 0) or 0),
            "resolved_findings": int(longitudinal_summary.get("resolved_findings", 0) or 0),
            "severity_escalations": int(longitudinal_summary.get("severity_escalations", 0) or 0),
            "claim_status_changes": int(longitudinal_summary.get("claim_status_changes", 0) or 0),
            "regression_candidates": int(longitudinal_summary.get("regression_candidates", 0) or 0),
            "top_regressions": [
                {
                    "source": str(item.get("source", "")),
                    "kind": str(item.get("kind", "")),
                    "subject": str(item.get("subject", "")),
                    "reason": str(item.get("reason", "")),
                }
                for item in regression_rows[:8]
                if isinstance(item, dict)
            ],
        }

    if experiment:
        experiment_summary = (
            experiment.get("summary")
            if isinstance(experiment.get("summary"), dict)
            else {}
        )
        experiment_rows = (
            experiment.get("experiments")
            if isinstance(experiment.get("experiments"), list)
            else []
        )
        row["experiment_plan"] = {
            "state": str(experiment.get("state", "UNKNOWN")),
            "next_experiment_id": str(experiment.get("next_experiment_id", "") or ""),
            "experiments": int(experiment_summary.get("experiments", 0) or 0),
            "high_priority": int(experiment_summary.get("high_priority", 0) or 0),
            "normal_priority": int(experiment_summary.get("normal_priority", 0) or 0),
            "existing_lab_ready": int(experiment_summary.get("existing_lab_ready", 0) or 0),
            "bounded_review_only": int(experiment_summary.get("bounded_review_only", 0) or 0),
            "top_experiments": [
                {
                    "id": str(item.get("id", "")),
                    "priority": str(item.get("priority", "")),
                    "kind": str(item.get("kind", "")),
                    "subject": str(item.get("subject", "")),
                    "experiment_type": str(item.get("experiment_type", "")),
                    "labs": (
                        [str(value) for value in item.get("labs", [])[:4]]
                        if isinstance(item.get("labs"), list)
                        else []
                    ),
                }
                for item in experiment_rows[:8]
                if isinstance(item, dict)
            ],
        }

    if analyst:
        analyst_summary = (
            analyst.get("summary")
            if isinstance(analyst.get("summary"), dict)
            else {}
        )
        analyst_product = (
            analyst.get("product")
            if isinstance(analyst.get("product"), dict)
            else {}
        )
        analyst_evidence = (
            analyst.get("evidence_posture")
            if isinstance(analyst.get("evidence_posture"), dict)
            else {}
        )
        analyst_actions = (
            analyst.get("next_actions")
            if isinstance(analyst.get("next_actions"), list)
            else []
        )
        analyst_observations = (
            analyst.get("observations")
            if isinstance(analyst.get("observations"), list)
            else []
        )
        row["analyst"] = {
            "state": str(analyst.get("state", "UNKNOWN")),
            "headline": str(analyst.get("headline", "")),
            "engine": str(analyst_product.get("engine", "unknown")),
            "runtime_trust_state": str(analyst_evidence.get("runtime_trust_state", "NOT_PROVIDED")),
            "observations": int(analyst_summary.get("observations", 0) or 0),
            "high_priority_observations": int(analyst_summary.get("high_priority_observations", 0) or 0),
            "next_actions": int(analyst_summary.get("next_actions", 0) or 0),
            "high_priority_actions": int(analyst_summary.get("high_priority_actions", 0) or 0),
            "fix_now": int(analyst_summary.get("fix_now", 0) or 0),
            "verify_next": int(analyst_summary.get("verify_next", 0) or 0),
            "experiments": int(analyst_summary.get("experiments", 0) or 0),
            "contradictions": int(analyst_summary.get("contradictions", 0) or 0),
            "regression_candidates": int(analyst_summary.get("regression_candidates", 0) or 0),
            "top_observations": [
                {
                    "priority": str(item.get("priority", "")),
                    "category": str(item.get("category", "")),
                    "kind": str(item.get("kind", "")),
                    "subject": str(item.get("subject", "")),
                    "statement": str(item.get("statement", "")),
                }
                for item in analyst_observations[:8]
                if isinstance(item, dict)
            ],
            "top_actions": [
                {
                    "priority": str(item.get("priority", "")),
                    "action": str(item.get("action", "")),
                    "kind": str(item.get("kind", "")),
                    "subject": str(item.get("subject", "")),
                    "source_id": str(item.get("source_id", "") or ""),
                }
                for item in analyst_actions[:8]
                if isinstance(item, dict)
            ],
        }

    if user_journey:
        journey_summary = (
            user_journey.get("summary")
            if isinstance(user_journey.get("summary"), dict)
            else {}
        )
        journey_rows = (
            user_journey.get("journeys")
            if isinstance(user_journey.get("journeys"), list)
            else []
        )
        journey_findings = (
            user_journey.get("findings")
            if isinstance(user_journey.get("findings"), list)
            else []
        )
        row["user_journey"] = {
            "journeys_observed": int(journey_summary.get("journeys_observed", 0) or 0),
            "states_observed": int(journey_summary.get("states_observed", 0) or 0),
            "transitions_observed": int(journey_summary.get("transitions_observed", 0) or 0),
            "max_observed_depth": int(journey_summary.get("max_observed_depth", 0) or 0),
            "no_change_actions": int(journey_summary.get("no_change_actions", 0) or 0),
            "loop_candidates": int(journey_summary.get("loop_candidates", 0) or 0),
            "safe_dead_end_candidates": int(
                journey_summary.get("safe_dead_end_candidates", 0) or 0
            ),
            "review_signals": int(journey_summary.get("review_signals", 0) or 0),
            "sample_journeys": [
                {
                    "depth": int(item.get("depth", 0) or 0),
                    "steps": [
                        str(value)
                        for value in item.get("steps", [])[:5]
                    ] if isinstance(item.get("steps"), list) else [],
                }
                for item in journey_rows[:5]
                if isinstance(item, dict)
            ],
            "top_findings": [
                {
                    "kind": str(item.get("kind", "")),
                    "severity": str(item.get("severity", "")),
                    "subject": str(item.get("subject", "")),
                }
                for item in journey_findings[:6]
                if isinstance(item, dict)
            ],
        }

    if evidence_confidence:
        confidence_summary = (
            evidence_confidence.get("summary")
            if isinstance(evidence_confidence.get("summary"), dict)
            else {}
        )
        confidence_contradictions = (
            evidence_confidence.get("contradictions")
            if isinstance(evidence_confidence.get("contradictions"), list)
            else []
        )
        row["evidence_confidence"] = {
            "total_claims": int(confidence_summary.get("total_claims", 0) or 0),
            "confirmed": int(confidence_summary.get("confirmed", 0) or 0),
            "corroborated": int(confidence_summary.get("corroborated", 0) or 0),
            "contradicted": int(confidence_summary.get("contradicted", 0) or 0),
            "unverified": int(confidence_summary.get("unverified", 0) or 0),
            "stale": int(confidence_summary.get("stale", 0) or 0),
            "contradiction_count": int(
                confidence_summary.get("contradiction_count", 0) or 0
            ),
            "top_contradictions": [
                {
                    "domain": str(item.get("domain", "")),
                    "kind": str(item.get("kind", "")),
                    "subject": str(item.get("subject", "")),
                    "message": str(item.get("message", "")),
                }
                for item in confidence_contradictions[:8]
                if isinstance(item, dict)
            ],
        }

    if autonomous or behavioral or state_edge or calibration or contract or brief:
        review_summary = (
            autonomous.get("summary")
            if isinstance(autonomous, dict) and isinstance(autonomous.get("summary"), dict)
            else {}
        )
        decision_summary = (
            brief.get("summary")
            if isinstance(brief, dict) and isinstance(brief.get("summary"), dict)
            else {}
        )
        calibration_summary = (
            calibration.get("summary")
            if isinstance(calibration, dict) and isinstance(calibration.get("summary"), dict)
            else {}
        )
        contract_summary = (
            contract.get("summary")
            if isinstance(contract, dict) and isinstance(contract.get("summary"), dict)
            else {}
        )
        state_summary = (
            state_edge.get("summary")
            if isinstance(state_edge, dict) and isinstance(state_edge.get("summary"), dict)
            else {}
        )
        trust = (
            autonomous.get("runtime_evidence_trust")
            if isinstance(autonomous, dict)
            and isinstance(autonomous.get("runtime_evidence_trust"), dict)
            else {}
        )
        trust_binding = (
            trust.get("binding")
            if isinstance(trust.get("binding"), dict)
            else {}
        )
        brief_buckets = (
            brief.get("buckets")
            if isinstance(brief, dict) and isinstance(brief.get("buckets"), dict)
            else {}
        )
        top_actions: list[dict[str, Any]] = []
        for bucket_name in ("FIX_NOW", "VERIFY_NEXT", "IMPROVE"):
            bucket_rows = (
                brief_buckets.get(bucket_name)
                if isinstance(brief_buckets.get(bucket_name), list)
                else []
            )
            for item in bucket_rows:
                if not isinstance(item, dict):
                    continue
                top_actions.append(
                    {
                        "bucket": bucket_name,
                        "kind": str(item.get("kind", "")),
                        "subject": str(item.get("subject", "")),
                        "basis": str(item.get("basis", "")),
                        "evidence": (
                            [str(value) for value in item.get("evidence", [])[:3]]
                            if isinstance(item.get("evidence"), list)
                            else []
                        ),
                    }
                )
                if len(top_actions) >= 6:
                    break
            if len(top_actions) >= 6:
                break

        row["autonomous_review"] = {
            "review_state": str(
                autonomous.get("review_state", "EVIDENCE_INCOMPLETE")
                if isinstance(autonomous, dict)
                else "EVIDENCE_INCOMPLETE"
            ),
            "runtime_evidence_state": str(
                review_summary.get(
                    "runtime_evidence_state",
                    behavioral.get("runtime_evidence_state", "NOT_OBSERVED")
                    if isinstance(behavioral, dict)
                    else "NOT_OBSERVED",
                )
            ),
            "observed_states": int(
                review_summary.get(
                    "observed_states",
                    state_summary.get("observed", 0),
                )
                or 0
            ),
            "applicable_states": int(
                review_summary.get(
                    "applicable_states",
                    state_summary.get("applicable", 0),
                )
                or 0
            ),
            "fix_now": int(
                review_summary.get(
                    "fix_now",
                    decision_summary.get("fix_now", 0),
                )
                or 0
            ),
            "verify_next": int(
                review_summary.get(
                    "verify_next",
                    decision_summary.get("verify_next", 0),
                )
                or 0
            ),
            "runtime_confirmed": int(
                calibration_summary.get("runtime_confirmed", 0) or 0
            ),
            "runtime_contradicted": int(
                calibration_summary.get("runtime_contradicted", 0) or 0
            ),
            "contract_review_signals": int(
                review_summary.get(
                    "contract_review_signals",
                    contract_summary.get("review_signals", 0),
                )
                or 0
            ),
            "runtime_trust_state": str(trust.get("state", "NOT_PROVIDED")),
            "runtime_trusted": bool(trust.get("trusted", False)),
            "trusted_repository": str(trust_binding.get("repository", "")),
            "trusted_sha": str(trust_binding.get("resolved_sha", "")),
            "trusted_package_id": str(trust_binding.get("package_id", "")),
            "trusted_run_id": str(trust_binding.get("workflow_run_id", "")),
            "manifest_sha256": str(trust.get("manifest_sha256", "")),
            "top_actions": top_actions,
        }

    return row


def build_snapshot(evidence_root: Path) -> dict[str, Any]:
    if not evidence_root.is_dir():
        raise ValueError(f"Evidence root does not exist: {evidence_root}")

    projects: list[dict[str, Any]] = []
    for project_dir in sorted(path for path in evidence_root.iterdir() if path.is_dir()):
        row = project_summary(project_dir.name, project_dir)
        if row is not None:
            projects.append(row)

    portfolio_payload = read_json(evidence_root / "cross-app-intelligence.json") or {}
    portfolio = {
        "project_count": int(portfolio_payload.get("project_count", 0) or 0),
        "reusable_pattern_candidates": (
            portfolio_payload.get("reusable_pattern_candidates", [])
            if isinstance(portfolio_payload.get("reusable_pattern_candidates"), list)
            else []
        )[:30],
        "recurrent_review_signals": (
            portfolio_payload.get("recurrent_review_signals", [])
            if isinstance(portfolio_payload.get("recurrent_review_signals"), list)
            else []
        )[:30],
        "portfolio_profile": (
            portfolio_payload.get("portfolio_profile", {})
            if isinstance(portfolio_payload.get("portfolio_profile"), dict)
            else {}
        ),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "studio_version": STUDIO_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "projects": len(projects),
            "with_market": sum(1 for row in projects if row.get("market") is not None),
            "manual_review": sum(
                1
                for row in projects
                if isinstance(row.get("audit"), dict)
                and row["audit"].get("manual_review_required")
            ),
            "recurrent_patterns": len(portfolio["reusable_pattern_candidates"]),
            "with_change_intelligence": sum(
                1 for row in projects if row.get("change") is not None
            ),
            "with_longitudinal_intelligence": sum(
                1 for row in projects if row.get("longitudinal") is not None
            ),
            "with_experiment_plans": sum(
                1 for row in projects if row.get("experiment_plan") is not None
            ),
            "with_analyst_reports": sum(
                1 for row in projects if row.get("analyst") is not None
            ),
            "analyst_attention": sum(
                1
                for row in projects
                if isinstance(row.get("analyst"), dict)
                and row["analyst"].get("state")
                in {"CONFIRMED_ACTION", "VERIFICATION_REQUIRED", "EVIDENCE_INCOMPLETE"}
            ),
            "planned_experiments": sum(
                int((row.get("experiment_plan") or {}).get("experiments", 0) or 0)
                for row in projects
                if isinstance(row.get("experiment_plan"), dict)
            ),
            "high_priority_experiments": sum(
                int((row.get("experiment_plan") or {}).get("high_priority", 0) or 0)
                for row in projects
                if isinstance(row.get("experiment_plan"), dict)
            ),
            "longitudinal_attention": sum(
                1
                for row in projects
                if isinstance(row.get("longitudinal"), dict)
                and row["longitudinal"].get("state") == "REGRESSION_REVIEW"
            ),
            "change_attention": sum(
                1
                for row in projects
                if isinstance(row.get("change"), dict)
                and row["change"].get("review_state") in {"HIGH_REVIEW", "REVIEW"}
            ),
            "autonomous_reviews": sum(
                1 for row in projects if row.get("autonomous_review") is not None
            ),
            "autonomous_attention": sum(
                1
                for row in projects
                if isinstance(row.get("autonomous_review"), dict)
                and row["autonomous_review"].get("review_state")
                in {"ATTENTION_REQUIRED", "REVIEW_REQUIRED"}
            ),
            "runtime_observed": sum(
                1
                for row in projects
                if isinstance(row.get("autonomous_review"), dict)
                and str(row["autonomous_review"].get("runtime_evidence_state", ""))
                .startswith("OBSERVED")
            ),
            "trusted_runtime_reviews": sum(
                1
                for row in projects
                if isinstance(row.get("autonomous_review"), dict)
                and bool(row["autonomous_review"].get("runtime_trusted", False))
            ),
            "evidence_contradictions": sum(
                int((row.get("evidence_confidence") or {}).get("contradiction_count", 0) or 0)
                for row in projects
                if isinstance(row.get("evidence_confidence"), dict)
            ),
            "evidence_unverified": sum(
                int((row.get("evidence_confidence") or {}).get("unverified", 0) or 0)
                for row in projects
                if isinstance(row.get("evidence_confidence"), dict)
            ),
            "journeys_observed": sum(
                int((row.get("user_journey") or {}).get("journeys_observed", 0) or 0)
                for row in projects
                if isinstance(row.get("user_journey"), dict)
            ),
            "journey_review_signals": sum(
                int((row.get("user_journey") or {}).get("review_signals", 0) or 0)
                for row in projects
                if isinstance(row.get("user_journey"), dict)
            ),
            "ux_review_signals": sum(
                int((row.get("ux_friction") or {}).get("review_signals", 0) or 0)
                for row in projects
                if isinstance(row.get("ux_friction"), dict)
            ),
            "ux_no_change_actions": sum(
                int((row.get("ux_friction") or {}).get("no_change_actions", 0) or 0)
                for row in projects
                if isinstance(row.get("ux_friction"), dict)
            ),
        },
        "projects": projects,
        "portfolio": portfolio,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        project = root / "demo"
        project.mkdir()
        (project / "app-intelligence.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "scan": {"confidence": "HIGH"},
                    "product": {
                        "stack": {"engine": "flutter"},
                        "surface": {"screen_like_files": 4},
                        "feature_signals": [
                            {"label": "authentication", "status": "PRESENT"},
                            {"label": "ai_or_ml", "status": "NOT_DETECTED"},
                        ],
                    },
                    "deep_product_model": {
                        "entity_count": 3,
                        "surface_count": 5,
                        "summary": {
                            "lifecycle_review_signals": 1,
                            "documentation_drift_signals": 2,
                        },
                    },
                    "feature_truth": {
                        "summary": {
                            "CODE_CONFIRMED": 4,
                            "DOC_ONLY_SIGNAL": 1,
                        },
                    },
                    "product_flow_graph": {
                        "node_count": 5,
                        "edge_count": 6,
                        "summary": {"orphan_surface_candidates": 1},
                    },
                    "product_consistency": {
                        "summary": {
                            "total": 3,
                            "high_review": 1,
                            "review": 2,
                            "info": 0,
                            "by_domain": {"architecture": 1, "ux": 2},
                        },
                        "findings": [
                            {
                                "domain": "architecture",
                                "kind": "POSSIBLE_EMBEDDED_SECRET",
                                "severity": "HIGH_REVIEW",
                            }
                        ],
                    },
                    "lifecycle_integrity": {
                        "summary": {
                            "entities_checked": 4,
                            "entities_with_review": 2,
                            "review_signals": 3,
                            "by_kind": {"POSSIBLE_MEDIA_CLEANUP_GAP": 1},
                        }
                    },
                    "ux_product": {"findings": [{"kind": "A"}]},
                    "architecture_data": {
                        "findings": [],
                        "data": {"local_first_assessment": "SUPPORTED_BY_SIGNALS"},
                    },
                }
            ),
            encoding="utf-8",
        )
        (project / "market-intelligence.json").write_text(
            json.dumps(
                {
                    "competitor_count": 3,
                    "capabilities": [
                        {"classification": "COMMON_MARKET_GAP_REVIEW"},
                        {"classification": "PROJECT_DIFFERENTIATOR_SIGNAL"},
                    ],
                    "reviews": {"recurring_pain_signals": [{}, {}]},
                }
            ),
            encoding="utf-8",
        )
        (project / "autonomous-review.json").write_text(
            json.dumps(
                {
                    "platform_version": "3.1.0",
                    "review_state": "REVIEW_REQUIRED",
                    "runtime_evidence_trust": {
                        "state": "TRUSTED",
                        "trusted": True,
                        "manifest_sha256": "abc123",
                        "binding": {
                            "repository": "owner/demo",
                            "resolved_sha": "a" * 40,
                            "package_id": "com.example.demo",
                            "workflow_run_id": "123",
                        },
                    },
                    "summary": {
                        "runtime_evidence_state": "OBSERVED_PASS",
                        "observed_states": 5,
                        "applicable_states": 8,
                        "fix_now": 0,
                        "verify_next": 3,
                        "contract_review_signals": 2,
                    },
                }
            ),
            encoding="utf-8",
        )
        (project / "ux-friction.json").write_text(
            json.dumps(
                {
                    "summary": {
                        "runtime_transitions": 4,
                        "no_change_actions": 1,
                        "no_change_share": 0.25,
                        "review_signals": 2,
                        "info_signals": 1,
                        "by_category": {"feedback": 1, "discoverability": 2},
                    },
                    "findings": [
                        {
                            "category": "feedback",
                            "kind": "STABLE_SIGNATURE_AFTER_ACTION_CANDIDATE",
                            "severity": "REVIEW",
                            "subject": "Search",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (project / "user-journey.json").write_text(
            json.dumps(
                {
                    "summary": {
                        "journeys_observed": 2,
                        "states_observed": 3,
                        "transitions_observed": 2,
                        "max_observed_depth": 2,
                        "no_change_actions": 0,
                        "loop_candidates": 0,
                        "safe_dead_end_candidates": 1,
                        "review_signals": 1,
                    },
                    "journeys": [
                        {"depth": 1, "steps": ["Settings"]},
                        {"depth": 2, "steps": ["Settings", "Profile"]},
                    ],
                    "findings": [
                        {
                            "kind": "SAFE_JOURNEY_DEAD_END_CANDIDATE",
                            "severity": "INFO",
                            "subject": "profile",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (project / "evidence-confidence.json").write_text(
            json.dumps(
                {
                    "summary": {
                        "total_claims": 12,
                        "confirmed": 5,
                        "corroborated": 3,
                        "contradicted": 1,
                        "unverified": 3,
                        "stale": 0,
                        "contradiction_count": 2,
                    },
                    "contradictions": [
                        {
                            "domain": "capability",
                            "kind": "CONTRACT_IMPLEMENTATION_CONTRADICTION",
                            "subject": "cloud_or_sync",
                            "message": "Contract and implementation disagree.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (project / "evidence-calibration.json").write_text(
            json.dumps(
                {
                    "summary": {
                        "runtime_confirmed": 1,
                        "runtime_contradicted": 2,
                    }
                }
            ),
            encoding="utf-8",
        )
        (project / "change-intelligence.json").write_text(
            json.dumps(
                {
                    "review_state": "REVIEW",
                    "summary": {
                        "feature_truth_changes": 2,
                        "capabilities_added": 1,
                        "capabilities_removed": 0,
                        "entities_added": 1,
                        "entities_removed": 0,
                        "surfaces_added": 1,
                        "surfaces_removed": 0,
                        "new_findings": 2,
                        "resolved_findings": 1,
                        "new_high_review": 0,
                        "new_review": 2,
                    },
                }
            ),
            encoding="utf-8",
        )
        (project / "longitudinal-intelligence.json").write_text(
            json.dumps(
                {
                    "state": "REGRESSION_REVIEW",
                    "baseline": {"resolved_sha": "a" * 40},
                    "summary": {
                        "history_snapshots": 3,
                        "baseline_available": True,
                        "new_findings": 1,
                        "returned_findings": 1,
                        "persistent_findings": 2,
                        "resolved_findings": 1,
                        "severity_escalations": 1,
                        "claim_status_changes": 2,
                        "regression_candidates": 2,
                    },
                    "regression_candidates": [
                        {
                            "source": "ux_friction",
                            "kind": "NAVIGATION_LOOP_CANDIDATE",
                            "subject": "Open",
                            "reason": "finding returned",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (project / "experiment-plan.json").write_text(
            json.dumps(
                {
                    "state": "EXPERIMENTS_READY",
                    "next_experiment_id": "EXP-DEMO",
                    "summary": {
                        "experiments": 3,
                        "high_priority": 2,
                        "normal_priority": 1,
                        "existing_lab_ready": 2,
                        "bounded_review_only": 1,
                    },
                    "experiments": [
                        {
                            "id": "EXP-DEMO",
                            "priority": "HIGH",
                            "kind": "NAVIGATION_LOOP_CANDIDATE",
                            "subject": "Open",
                            "experiment_type": "TARGETED_JOURNEY",
                            "labs": ["safe-interaction-crawler", "visual-journey"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (project / "analyst-report.json").write_text(
            json.dumps(
                {
                    "state": "VERIFICATION_REQUIRED",
                    "headline": "Bounded verification required.",
                    "product": {"engine": "flutter"},
                    "evidence_posture": {"runtime_trust_state": "TRUSTED"},
                    "summary": {
                        "observations": 4,
                        "high_priority_observations": 2,
                        "next_actions": 3,
                        "high_priority_actions": 1,
                        "fix_now": 0,
                        "verify_next": 2,
                        "experiments": 3,
                        "contradictions": 1,
                        "regression_candidates": 1,
                    },
                    "observations": [
                        {
                            "priority": "HIGH",
                            "category": "REGRESSION_REVIEW",
                            "kind": "NAVIGATION_LOOP_CANDIDATE",
                            "subject": "Open",
                            "statement": "finding returned",
                        }
                    ],
                    "next_actions": [
                        {
                            "priority": "HIGH",
                            "action": "RUN_BOUNDED_EXPERIMENT",
                            "kind": "NAVIGATION_LOOP_CANDIDATE",
                            "subject": "Open",
                            "source_id": "EXP-DEMO",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (project / "audit-plan.json").write_text(
            json.dumps(
                {
                    "selected_lab_count": 4,
                    "manual_review_required": True,
                    "selected_labs": [
                        {"lab": "product-analysis", "priority": "MANDATORY"}
                    ],
                }
            ),
            encoding="utf-8",
        )
        (root / "cross-app-intelligence.json").write_text(
            json.dumps(
                {
                    "project_count": 2,
                    "reusable_pattern_candidates": [{"key": "authentication"}],
                    "recurrent_review_signals": [{"key": "accessibility"}],
                }
            ),
            encoding="utf-8",
        )

        snapshot = build_snapshot(root)
        assert snapshot["summary"]["projects"] == 1
        assert snapshot["summary"]["with_market"] == 1
        assert snapshot["summary"]["manual_review"] == 1
        assert snapshot["summary"]["recurrent_patterns"] == 1
        assert snapshot["projects"][0]["product"]["engine"] == "flutter"
        assert snapshot["projects"][0]["product"]["entity_count"] == 3
        assert snapshot["projects"][0]["product"]["lifecycle_review_signals"] == 1
        assert snapshot["projects"][0]["product"]["code_confirmed_capabilities"] == 4
        assert snapshot["projects"][0]["product"]["orphan_surface_candidates"] == 1
        assert snapshot["projects"][0]["consistency"]["total"] == 3
        assert snapshot["projects"][0]["consistency"]["high_review"] == 1
        assert snapshot["projects"][0]["lifecycle"]["entities_checked"] == 4
        assert snapshot["projects"][0]["lifecycle"]["review_signals"] == 3
        assert snapshot["projects"][0]["change"]["review_state"] == "REVIEW"
        assert snapshot["projects"][0]["change"]["new_findings"] == 2
        assert snapshot["projects"][0]["change"]["resolved_findings"] == 1
        assert snapshot["projects"][0]["longitudinal"]["state"] == "REGRESSION_REVIEW"
        assert snapshot["projects"][0]["longitudinal"]["history_snapshots"] == 3
        assert snapshot["projects"][0]["longitudinal"]["regression_candidates"] == 2
        assert snapshot["summary"]["with_longitudinal_intelligence"] == 1
        assert snapshot["summary"]["longitudinal_attention"] == 1
        assert snapshot["projects"][0]["experiment_plan"]["state"] == "EXPERIMENTS_READY"
        assert snapshot["projects"][0]["experiment_plan"]["experiments"] == 3
        assert snapshot["projects"][0]["experiment_plan"]["next_experiment_id"] == "EXP-DEMO"
        assert snapshot["summary"]["with_experiment_plans"] == 1
        assert snapshot["summary"]["planned_experiments"] == 3
        assert snapshot["summary"]["high_priority_experiments"] == 2
        assert snapshot["projects"][0]["analyst"]["state"] == "VERIFICATION_REQUIRED"
        assert snapshot["projects"][0]["analyst"]["observations"] == 4
        assert snapshot["projects"][0]["analyst"]["next_actions"] == 3
        assert snapshot["summary"]["with_analyst_reports"] == 1
        assert snapshot["summary"]["analyst_attention"] == 1
        assert snapshot["projects"][0]["autonomous_review"]["review_state"] == "REVIEW_REQUIRED"
        assert snapshot["projects"][0]["autonomous_review"]["runtime_confirmed"] == 1
        assert snapshot["summary"]["autonomous_reviews"] == 1
        assert snapshot["summary"]["runtime_observed"] == 1
        assert snapshot["projects"][0]["autonomous_review"]["runtime_trust_state"] == "TRUSTED"
        assert snapshot["projects"][0]["autonomous_review"]["trusted_package_id"] == "com.example.demo"
        assert snapshot["summary"]["trusted_runtime_reviews"] == 1
        assert snapshot["projects"][0]["evidence_confidence"]["confirmed"] == 5
        assert snapshot["projects"][0]["evidence_confidence"]["contradiction_count"] == 2
        assert snapshot["summary"]["evidence_contradictions"] == 2
        assert snapshot["summary"]["evidence_unverified"] == 3
        assert snapshot["projects"][0]["user_journey"]["journeys_observed"] == 2
        assert snapshot["projects"][0]["user_journey"]["max_observed_depth"] == 2
        assert snapshot["summary"]["journeys_observed"] == 2
        assert snapshot["summary"]["journey_review_signals"] == 1
        assert snapshot["projects"][0]["ux_friction"]["review_signals"] == 2
        assert snapshot["projects"][0]["ux_friction"]["no_change_share"] == 0.25
        assert snapshot["summary"]["ux_review_signals"] == 2
        assert snapshot["summary"]["ux_no_change_actions"] == 1
        assert snapshot["projects"][0]["market"]["competitors"] == 3
        assert snapshot["projects"][0]["audit"]["selected_lab_count"] == 4
        print("AppLab Studio snapshot self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.evidence_root or not args.output:
        raise SystemExit("--evidence-root and --output are required")

    snapshot = build_snapshot(Path(args.evidence_root))
    Path(args.output).write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"AppLab Studio snapshot: {snapshot['summary']['projects']} projects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
