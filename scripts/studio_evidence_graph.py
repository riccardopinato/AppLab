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
    }


def self_test_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "engine_version": "4.2.0",
        "graph_version": "1.0",
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
    print("AppLab Studio Evidence Graph projection self-test PASS")


if __name__ == "__main__":
    self_test()
