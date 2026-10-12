#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


def run_self_test(namespace: dict[str, Any]) -> None:
    # The production module passes its already-loaded globals. Keeping fixture
    # construction here prevents test data from consuming the production
    # module's maintainability budget without changing runtime behavior.
    globals().update(namespace)
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
        (project / "evidence-graph.json").write_text(
            json.dumps(studio_evidence_graph.self_test_payload()),
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
        assert snapshot["projects"][0]["evidence_graph"]["nodes"] == 24
        assert snapshot["projects"][0]["evidence_graph"]["edges"] == 38
        assert snapshot["projects"][0]["evidence_graph"]["unverified_capabilities"] == 1
        assert snapshot["projects"][0]["evidence_graph"]["recurring_findings"] == 1
        assert snapshot["summary"]["with_evidence_graph"] == 1
        assert snapshot["summary"]["evidence_graph_nodes"] == 24
        assert snapshot["summary"]["evidence_graph_edges"] == 38
        assert snapshot["summary"]["graph_unverified_capabilities"] == 1
        assert snapshot["summary"]["graph_recurring_findings"] == 1
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


