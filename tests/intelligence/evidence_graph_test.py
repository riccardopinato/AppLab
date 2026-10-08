#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import evidence_graph as graph  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    sha_old = "a" * 40
    sha_new = "b" * 40
    inputs = {
        "app": {
            "feature_truth": {
                "capabilities": [
                    {"capability": "offline", "truth": "CODE_CONFIRMED"},
                    {"capability": "cloud_backup", "truth": "DOC_ONLY_SIGNAL"},
                ]
            },
            "product_flow_graph": {
                "nodes": [{"id": "home"}, {"id": "settings"}]
            },
            "product_consistency": {
                "findings": [
                    {
                        "id": "persist-gap",
                        "domain": "data",
                        "kind": "PERSISTENCE_GAP",
                        "subject": "draft",
                        "severity": "REVIEW",
                        "evidence": ["lib/store.dart"],
                    }
                ]
            },
        },
        "confidence": {
            "claims": [
                {
                    "id": "capability:offline",
                    "domain": "capability",
                    "subject": "offline",
                    "status": "CONFIRMED",
                    "evidence": ["lib/store.dart"],
                },
                {
                    "id": "capability:cloud_backup",
                    "domain": "capability",
                    "subject": "cloud_backup",
                    "status": "UNVERIFIED",
                    "evidence": ["README.md"],
                },
            ],
            "contradictions": [],
        },
        "journey": {
            "journeys": [{"depth": 1, "steps": ["home", "settings"]}],
            "findings": [
                {
                    "id": "persist-gap-journey",
                    "kind": "PERSISTENCE_GAP",
                    "subject": "draft",
                    "severity": "REVIEW",
                    "evidence": ["journey.json"],
                }
            ],
        },
        "ux": {"findings": []},
        "behavioral": {
            "findings": [
                {
                    "id": "behavioral-recurring",
                    "kind": "BEHAVIOR_GAP",
                    "subject": "resume",
                    "severity": "REVIEW",
                    "evidence": ["behavioral.json"],
                }
            ]
        },
        "longitudinal": {
            "state": "REGRESSION_REVIEW",
            "current": {
                "repository": "owner/app",
                "resolved_sha": sha_new,
                "run_id": "9",
                "lineage_ref": "main",
            },
            "baseline": {
                "available": True,
                "repository": "owner/app",
                "resolved_sha": sha_old,
                "run_id": "8",
            },
            "summary": {"history_snapshots": 3, "regression_candidates": 1},
            "findings": {
                "history": [
                    {
                        "key": "product_consistency|id:persist-gap",
                        "source": "product_consistency",
                        "id": "persist-gap",
                        "kind": "PERSISTENCE_GAP",
                        "subject": "draft",
                        "seen_count": 3,
                        "consecutive_seen": 2,
                        "first_seen_sha": sha_old,
                        "last_seen_sha": sha_new,
                    },
                    {
                        "key": "user_journey|id:persist-gap-journey",
                        "source": "user_journey",
                        "id": "persist-gap-journey",
                        "kind": "PERSISTENCE_GAP",
                        "subject": "draft",
                        "seen_count": 2,
                        "consecutive_seen": 2,
                        "first_seen_sha": sha_old,
                        "last_seen_sha": sha_new,
                    },
                    {
                        "key": "behavioral_product|id:behavioral-recurring",
                        "source": "behavioral_product",
                        "id": "behavioral-recurring",
                        "kind": "BEHAVIOR_GAP",
                        "subject": "resume",
                        "seen_count": 2,
                        "consecutive_seen": 2,
                        "first_seen_sha": sha_old,
                        "last_seen_sha": sha_new,
                    }
                ]
            },
            "regression_candidates": [
                {
                    "key": "user_journey|id:persist-gap-journey",
                    "source": "user_journey",
                    "kind": "PERSISTENCE_GAP",
                    "subject": "draft",
                    "reason": "returned after absence",
                }
            ],
        },
        "experiment": {
            "experiments": [
                {
                    "id": "EXP-PERSIST",
                    "priority": "HIGH",
                    "source": "LONGITUDINAL_REGRESSION",
                    "triggers": ["LONGITUDINAL_REGRESSION"],
                    "kind": "PERSISTENCE_GAP",
                    "subject": "draft",
                    "experiment_type": "SPECIALIST_RUNTIME",
                    "labs": ["persistence"],
                    "evidence": ["lib/store.dart"],
                }
            ]
        },
        "analyst": {
            "state": "VERIFICATION_REQUIRED",
            "headline": "Persistence requires verification",
            "summary": {"observations": 1, "next_actions": 1, "regression_candidates": 1},
        },
        "autonomous": {
            "runtime_evidence_trust": {
                "trusted": True,
                "binding": {
                    "repository": "owner/app",
                    "resolved_sha": sha_new,
                    "workflow_run_id": "9",
                    "package_id": "com.example.app",
                },
            }
        },
    }

    payload = graph.build_graph(inputs)
    nodes = payload["nodes"]
    edges = payload["edges"]
    node_ids = {row["id"] for row in nodes}

    require(all(row["from"] in node_ids and row["to"] in node_ids for row in edges), "dangling edge")
    require(payload["summary"]["nodes_by_type"]["Project"] == 1, "project node missing")
    require(payload["summary"]["nodes_by_type"]["Revision"] == 2, "revision lineage missing")
    require(payload["summary"]["nodes_by_type"]["Capability"] == 2, "capability nodes missing")
    require(payload["summary"]["nodes_by_type"]["Finding"] == 3, "source-namespaced finding identity mismatch")
    require(payload["summary"]["nodes_by_type"]["Experiment"] == 1, "experiment node missing")
    require(payload["summary"]["recurring_findings"] == 3, "recurrence not imported")
    require(payload["summary"]["unverified_capabilities"] == 1, "unverified capability not surfaced")

    history = graph.query_graph(payload, "history", "draft")
    require(len(history["results"]) == 2, "source-namespaced findings collapsed")
    require(all(row["first_observed_sha"] == sha_old for row in history["results"]), "first observed SHA mismatch")
    require(all("not proof" in row["caveat"] for row in history["results"]), "causal caveat missing")

    finding_nodes = {
        row["key"]: row
        for row in nodes
        if row.get("type") == "Finding"
    }
    require("behavioral_product|id:behavioral-recurring" in finding_nodes, "behavioral finding not imported")
    experiment_node = next(row for row in nodes if row.get("type") == "Experiment")
    experiment_edges = [
        row for row in edges
        if row.get("type") == "EXPERIMENT_TARGETS" and row.get("from") == experiment_node["id"]
    ]
    require(len(experiment_edges) == 1, "experiment target must be unambiguous")
    journey_target = finding_nodes["user_journey|id:persist-gap-journey"]["id"]
    require(experiment_edges[0]["to"] == journey_target, "experiment linked to wrong same-subject finding")

    journey_revision_edge = next(
        row for row in edges
        if row.get("type") == "REVISION_HAS_FINDING" and row.get("to") == journey_target
    )
    require(
        set(journey_revision_edge.get("provenance", []))
        == {"user-journey.json", "longitudinal-intelligence.json"},
        "edge provenance was overwritten instead of merged",
    )

    evidence = graph.query_graph(payload, "evidence", "cloud_backup")
    require(evidence["matched_nodes"], "subject matching failed")
    require(evidence["evidence"], "claim evidence relation missing")

    regression = graph.query_graph(payload, "regressions")
    require(len(regression["results"]) == 1, "regression query mismatch")

    print("Evidence Graph independent regression test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
