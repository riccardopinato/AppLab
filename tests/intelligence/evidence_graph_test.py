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
                    {"capability": "settings", "truth": "CODE_CONFIRMED"},
                ]
            },
            "product_flow_graph": {
                "nodes": [
                    {"id": "home", "roles": ["home", "entry"]},
                    {"id": "settings", "roles": ["settings"]}
                ]
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
                    },
                    {
                        "id": "persist-gap-secondary",
                        "domain": "data",
                        "kind": "PERSISTENCE_GAP",
                        "subject": "draft",
                        "severity": "REVIEW",
                        "evidence": ["lib/store-secondary.dart"],
                    },
                    {
                        "id": "orphan-settings",
                        "domain": "product_flow",
                        "kind": "ORPHAN_SURFACE_CANDIDATE",
                        "subject": "settings",
                        "severity": "REVIEW",
                        "evidence": ["ui/settings.dart"],
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
                {
                    "id": "surface:settings",
                    "domain": "surface",
                    "subject": "settings",
                    "status": "CONFIRMED",
                    "evidence": ["ui/settings.dart"],
                },
                {
                    "id": "localized:設定",
                    "domain": "state",
                    "subject": "設定",
                    "status": "UNVERIFIED",
                    "evidence": ["localized-state.json"],
                },
                {
                    "id": "state:offline",
                    "domain": "state",
                    "subject": "offline",
                    "status": "CONFIRMED",
                    "evidence": ["state-offline.json"],
                },
                {
                    "id": "finding:orphan-settings",
                    "domain": "product_flow",
                    "subject": "settings",
                    "status": "UNVERIFIED",
                    "evidence": ["ui/settings.dart"],
                },
            ],
            "contradictions": [],
        },
        "states": {
            "findings": [
                {
                    "id": "offline-state-settings",
                    "domain": "state",
                    "kind": "OFFLINE_STATE_FAILURE",
                    "subject": "settings",
                    "severity": "REVIEW",
                    "evidence": ["state-settings.json"],
                }
            ]
        },
        "journey": {
            "journeys": [
                {"state_id": "state-settings-a", "depth": 1, "steps": ["home", "settings"]},
                {"state_id": "state-settings-b", "depth": 1, "steps": ["home", "settings"]}
            ],
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
        "contract": {
            "findings": [
                {
                    "kind": "PROMISED_WITHOUT_IMPLEMENTATION",
                    "capability": "cloud_backup",
                    "severity": "REVIEW",
                    "message": "Cloud backup is promised without strong implementation evidence.",
                    "evidence": ["README.md"],
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
                        "key": "product_consistency|id:persist-gap-secondary",
                        "source": "product_consistency",
                        "id": "persist-gap-secondary",
                        "kind": "PERSISTENCE_GAP",
                        "subject": "draft",
                        "seen_count": 2,
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
                    },
                    {
                        "key": "product_contract|||promised_without_implementation|cloud_backup",
                        "source": "product_contract",
                        "kind": "PROMISED_WITHOUT_IMPLEMENTATION",
                        "subject": "cloud_backup",
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
        "trusted_result": {
            "schema_version": 1,
            "result": "PASS",
            "pipeline_status": "success",
            "analysis_mode": "full",
            "analysis_lane": "FULL_RUNTIME",
            "reason": "Trusted runtime verification passed.",
            "repository": "owner/app",
            "resolved_sha": sha_new,
            "workflow_run_id": "9",
            "package_id": "com.example.app",
            "engine": "native_android",
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
    require(payload["summary"]["nodes_by_type"]["Capability"] == 3, "capability nodes missing")
    require(payload["summary"]["nodes_by_type"]["Surface"] == 2, "surface nodes missing")
    require(payload["summary"]["nodes_by_type"]["Journey"] == 2, "state-distinct journeys collapsed")
    require(payload["summary"]["nodes_by_type"]["Finding"] == 7, "canonical finding identity mismatch")
    require(payload["summary"]["nodes_by_type"]["Claim"] == 6, "claim nodes missing")
    require(payload["summary"]["nodes_by_type"]["Experiment"] == 1, "experiment node missing")
    require(payload["summary"]["nodes_by_type"]["Result"] == 3, "trusted runtime result missing")
    require(payload["summary"]["recurring_findings"] == 5, "recurrence not imported")
    require(payload["summary"]["unverified_capabilities"] == 1, "unverified capability not surfaced")

    history = graph.query_graph(payload, "history", "draft")
    require(len(history["results"]) == 3, "canonical same-subject findings collapsed")
    require(all(row["first_observed_sha"] == sha_old for row in history["results"]), "first observed SHA mismatch")
    require(all("not proof" in row["caveat"] for row in history["results"]), "causal caveat missing")

    surface_nodes = {
        row["key"]: row
        for row in nodes
        if row.get("type") == "Surface"
    }
    require(
        surface_nodes["home"]["attributes"].get("roles") == ["home", "entry"],
        "surface roles array was not preserved",
    )
    journey_nodes = [row for row in nodes if row.get("type") == "Journey"]
    require(
        {row["key"] for row in journey_nodes} == {"state-settings-a", "state-settings-b"},
        "journey state_id was not used as canonical key",
    )

    finding_nodes = {
        row["key"]: row
        for row in nodes
        if row.get("type") == "Finding"
    }
    require("behavioral_product|id:behavioral-recurring" in finding_nodes, "behavioral finding not imported")
    require(
        "product_consistency|id:persist-gap" in finding_nodes
        and "product_consistency|id:persist-gap-secondary" in finding_nodes,
        "distinct canonical finding IDs collapsed",
    )
    surface_settings = surface_nodes["settings"]
    capability_settings = next(
        row for row in nodes
        if row.get("type") == "Capability" and row.get("key") == "settings"
    )
    surface_claim = next(
        row for row in nodes
        if row.get("type") == "Claim" and row.get("key") == "surface:settings"
    )
    surface_claim_edges = [
        row for row in edges
        if row.get("type") == "CLAIM_ABOUT" and row.get("from") == surface_claim["id"]
    ]
    require(len(surface_claim_edges) == 1, "surface claim target missing")
    require(
        surface_claim_edges[0]["to"] == surface_settings["id"]
        and surface_claim_edges[0]["to"] != capability_settings["id"],
        "surface claim linked to colliding capability",
    )

    orphan_finding = finding_nodes["product_consistency|id:orphan-settings"]
    orphan_edges = [
        row for row in edges
        if row.get("type") == "FINDING_ABOUT" and row.get("from") == orphan_finding["id"]
    ]
    require(len(orphan_edges) == 1, "surface finding target missing")
    require(
        orphan_edges[0]["to"] == surface_settings["id"]
        and orphan_edges[0]["to"] != capability_settings["id"],
        "surface finding linked to colliding capability",
    )

    calibrated_claim = next(
        row for row in nodes
        if row.get("type") == "Claim" and row.get("key") == "finding:orphan-settings"
    )
    calibrated_edges = [
        row for row in edges
        if row.get("type") == "CLAIM_ABOUT" and row.get("from") == calibrated_claim["id"]
    ]
    require(len(calibrated_edges) == 1, "calibrated finding claim target missing")
    require(
        calibrated_edges[0]["to"] == orphan_finding["id"],
        "calibrated finding claim linked to wrong colliding subject",
    )

    state_claim = next(
        row for row in nodes
        if row.get("type") == "Claim" and row.get("key") == "state:offline"
    )
    require(
        not any(
            row.get("type") == "CLAIM_ABOUT" and row.get("from") == state_claim["id"]
            for row in edges
        ),
        "state claim manufactured a false semantic target",
    )

    offline_history = graph.query_graph(payload, "history", "offline")
    require(
        offline_history["results"] == [],
        "subject query matched finding kind instead of finding subject",
    )

    localized = graph.query_graph(payload, "evidence", "設定")
    require(localized["matched_nodes"], "Unicode subject did not normalize for query")
    require(localized["evidence"], "Unicode subject evidence was not reachable")

    trusted_result = next(
        row for row in nodes
        if row.get("type") == "Result" and row.get("key") == "trusted_runtime"
    )
    require(
        trusted_result["attributes"].get("result") == "PASS"
        and trusted_result["attributes"].get("pipeline_status") == "success",
        "trusted runtime result attributes missing",
    )
    require(
        any(
            row.get("type") == "REVISION_HAS_RESULT"
            and row.get("to") == trusted_result["id"]
            for row in edges
        ),
        "trusted runtime result is not revision-linked",
    )

    contract_key = "product_contract|||promised_without_implementation|cloud_backup"
    require(contract_key in finding_nodes, "contract finding did not match longitudinal identity")
    require(
        finding_nodes[contract_key]["attributes"].get("capability") == "cloud_backup",
        "contract capability attribute was not preserved",
    )
    cloud_capability = next(
        row for row in nodes
        if row.get("type") == "Capability" and row.get("key") == "cloud_backup"
    )
    require(
        any(
            row.get("type") == "FINDING_ABOUT"
            and row.get("from") == finding_nodes[contract_key]["id"]
            and row.get("to") == cloud_capability["id"]
            for row in edges
        ),
        "contract finding was not linked to its capability",
    )
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

    fallback_inputs = dict(inputs)
    fallback_inputs.pop("autonomous", None)
    fallback_inputs.pop("trusted_result", None)
    fallback_inputs["build_contract"] = {
        "repository": "owner/app",
        "resolved_sha": sha_new,
        "apk": {
            "package_id": "com.example.contract",
            "sha256": "c" * 64,
            "size_bytes": 1234,
        },
    }
    fallback_graph = graph.build_graph(fallback_inputs)
    require(
        fallback_graph["identity"].get("package_id") == "com.example.contract",
        "build contract package identity fallback missing",
    )

    print("Evidence Graph independent regression test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
