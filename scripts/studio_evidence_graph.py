#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


def project_summary(evidence_graph: dict[str, Any]) -> dict[str, Any]:
    summary = (
        evidence_graph.get("summary")
        if isinstance(evidence_graph.get("summary"), dict)
        else {}
    )
    insights = (
        evidence_graph.get("insights")
        if isinstance(evidence_graph.get("insights"), dict)
        else {}
    )
    nodes_by_type = (
        summary.get("nodes_by_type")
        if isinstance(summary.get("nodes_by_type"), dict)
        else {}
    )
    relations_by_type = (
        summary.get("relations_by_type")
        if isinstance(summary.get("relations_by_type"), dict)
        else {}
    )
    unverified = (
        insights.get("unverified_capabilities")
        if isinstance(insights.get("unverified_capabilities"), list)
        else []
    )
    recurring = (
        insights.get("recurring_findings")
        if isinstance(insights.get("recurring_findings"), list)
        else []
    )
    impact = insights.get("impact") if isinstance(insights.get("impact"), dict) else {}
    freshness = insights.get("freshness") if isinstance(insights.get("freshness"), dict) else {}
    lifecycle = (
        insights.get("finding_lifecycle")
        if isinstance(insights.get("finding_lifecycle"), dict)
        else {}
    )
    invalidated = (
        freshness.get("invalidated")
        if isinstance(freshness.get("invalidated"), list)
        else []
    )
    impact_paths = impact.get("paths") if isinstance(impact.get("paths"), list) else []

    return {
        "nodes": int(summary.get("nodes", 0) or 0),
        "edges": int(summary.get("edges", 0) or 0),
        "nodes_by_type": nodes_by_type,
        "relations_by_type": relations_by_type,
        "unverified_capabilities": int(
            summary.get("unverified_capabilities", 0) or 0
        ),
        "recurring_findings": int(summary.get("recurring_findings", 0) or 0),
        "regression_candidates": int(
            summary.get("regression_candidates", 0) or 0
        ),
        "changed_files": int(summary.get("changed_files", 0) or 0),
        "dependency_impacted_files": int(
            summary.get("dependency_impacted_files", 0) or 0
        ),
        "impact_paths": int(summary.get("impact_paths", 0) or 0),
        "invalidated_evidence": int(summary.get("invalidated_evidence", 0) or 0),
        "stale_or_historical_evidence": int(
            summary.get("stale_or_historical_evidence", 0) or 0
        ),
        "finding_lifecycle": {
            str(key): int(value or 0)
            for key, value in sorted(lifecycle.items())
        },
        "top_unverified_capabilities": [
            {
                "capability": str(item.get("capability", "")),
                "status": str(item.get("status", "")),
                "claim_id": str(item.get("claim_id", "")),
            }
            for item in unverified[:8]
            if isinstance(item, dict)
        ],
        "top_recurring_findings": [
            {
                "kind": str(item.get("kind", "")),
                "subject": str(item.get("subject", "")),
                "seen_count": int(item.get("seen_count", 0) or 0),
                "first_observed_sha": str(item.get("first_observed_sha", "")),
                "last_observed_sha": str(item.get("last_observed_sha", "")),
            }
            for item in recurring[:8]
            if isinstance(item, dict)
        ],
        "top_invalidated_evidence": [
            {
                "evidence_id": str(item.get("evidence_id", "")),
                "label": str(item.get("label", "")),
                "invalidated_by_files": [
                    str(value)
                    for value in item.get("invalidated_by_files", [])[:8]
                ] if isinstance(item.get("invalidated_by_files"), list) else [],
            }
            for item in invalidated[:8]
            if isinstance(item, dict)
        ],
        "top_impact_paths": [
            {
                "origin_file": str(item.get("origin_file", "")),
                "relations": [
                    str(value) for value in item.get("relations", [])[:8]
                ] if isinstance(item.get("relations"), list) else [],
                "terminal_evidence": str(item.get("terminal_evidence", "")),
            }
            for item in impact_paths[:8]
            if isinstance(item, dict)
        ],
    }


def self_test_payload() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "engine_version": "4.6.0",
        "graph_version": "2.0",
        "summary": {
            "nodes": 24,
            "edges": 38,
            "nodes_by_type": {
                "Project": 1,
                "Revision": 2,
                "BuildArtifact": 1,
                "Capability": 6,
                "Surface": 2,
                "Journey": 2,
                "Finding": 3,
                "Claim": 3,
                "Evidence": 2,
                "Experiment": 1,
                "Result": 1,
            },
            "relations_by_type": {
                "PROJECT_HAS_REVISION": 2,
                "CLAIM_SUPPORTED_BY": 3,
            },
            "unverified_capabilities": 1,
            "recurring_findings": 1,
            "regression_candidates": 1,
            "changed_files": 2,
            "dependency_impacted_files": 1,
            "impact_paths": 1,
            "invalidated_evidence": 1,
            "stale_or_historical_evidence": 2,
        },
        "insights": {
            "unverified_capabilities": [
                {
                    "claim_id": "capability:backup",
                    "capability": "backup",
                    "status": "UNVERIFIED",
                }
            ],
            "recurring_findings": [
                {
                    "kind": "NAVIGATION_LOOP_CANDIDATE",
                    "subject": "Open",
                    "seen_count": 3,
                    "first_observed_sha": "a" * 40,
                    "last_observed_sha": "b" * 40,
                }
            ],
            "finding_lifecycle": {
                "RETURNED": 1,
                "RESOLVED": 1,
            },
            "freshness": {
                "invalidated_count": 1,
                "invalidated": [
                    {
                        "evidence_id": "Evidence:1",
                        "label": "lib/legacy.dart",
                        "invalidated_by_files": ["lib/legacy.dart"],
                    }
                ],
            },
            "impact": {
                "paths": [
                    {
                        "origin_file": "lib/settings.dart",
                        "relations": [
                            "FILE_IN_COMPONENT",
                            "COMPONENT_SUPPORTS_CAPABILITY",
                            "CAPABILITY_OBSERVED_ON_SURFACE",
                            "SURFACE_IN_JOURNEY",
                            "DERIVED_FROM",
                        ],
                        "terminal_evidence": "user-journey.json",
                    }
                ]
            },
        },
    }


def self_test() -> None:
    row = project_summary(self_test_payload())
    assert row["nodes"] == 24
    assert row["edges"] == 38
    assert row["unverified_capabilities"] == 1
    assert row["recurring_findings"] == 1
    assert row["top_unverified_capabilities"][0]["capability"] == "backup"
    assert row["top_recurring_findings"][0]["seen_count"] == 3
    assert row["impact_paths"] == 1
    assert row["invalidated_evidence"] == 1
    assert row["finding_lifecycle"]["RESOLVED"] == 1
    assert row["top_invalidated_evidence"][0]["label"] == "lib/legacy.dart"
    assert "SURFACE_IN_JOURNEY" in row["top_impact_paths"][0]["relations"]
    print("AppLab Studio Evidence Graph projection self-test PASS")


if __name__ == "__main__":
    self_test()
