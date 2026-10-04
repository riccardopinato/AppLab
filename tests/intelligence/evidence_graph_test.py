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
        "journey": {"journeys": [{"depth": 1, "steps": ["home", "settings"]}], "findings": []},
        "ux": {"findings": []},
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
                        "id": "persist-gap",
                        "kind": "PERSISTENCE_GAP",
                        "subject": "draft",
                        "seen_count": 3,
                        "consecutive_seen": 2,
                        "first_seen_sha": sha_old,
                        "last_seen_sha": sha_new,
                    }
                ]
            },
            "regression_candidates": [
                {
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
    require(payload["summary"]["nodes_by_type"]["Experiment"] == 1, "experiment node missing")
    require(payload["summary"]["recurring_findings"] == 1, "recurrence not imported")
    require(payload["summary"]["unverified_capabilities"] == 1, "unverified capability not surfaced")

    history = graph.query_graph(payload, "history", "draft")
    require(history["results"], "history query returned no result")
    require(history["results"][0]["first_observed_sha"] == sha_old, "first observed SHA mismatch")
    require("not proof" in history["results"][0]["caveat"], "causal caveat missing")

    evidence = graph.query_graph(payload, "evidence", "cloud_backup")
    require(evidence["matched_nodes"], "subject matching failed")
    require(evidence["evidence"], "claim evidence relation missing")

    regression = graph.query_graph(payload, "regressions")
    require(len(regression["results"]) == 1, "regression query mismatch")

    print("Evidence Graph independent regression test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
