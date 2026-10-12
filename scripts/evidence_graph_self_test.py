#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from typing import Any


def run_self_test(namespace: dict[str, Any]) -> None:
    # The production module passes its already-loaded globals. Keeping fixture
    # construction here prevents test data from consuming the production
    # module's maintainability budget without changing runtime behavior.
    globals().update(namespace)
    sha1 = "1" * 40
    sha2 = "2" * 40
    evidence = {
        "app": {
            "schema_version": 1,
            "feature_truth": {
                "capabilities": [
                    {"capability": "auth", "truth": "CODE_CONFIRMED", "provenance": {"code": ["lib/auth.dart"]}},
                    {"capability": "backup", "truth": "DOC_ONLY_SIGNAL", "provenance": {"docs": ["README.md"]}},
                ]
            },
            "product_flow_graph": {
                "nodes": [
                    {"id": "home", "path": "lib/auth.dart", "role": "home"},
                    {"id": "settings", "path": "lib/settings.dart", "role": "settings"},
                ]
            },
            "product_consistency": {
                "findings": [
                    {
                        "id": "finding-save",
                        "domain": "data",
                        "kind": "SAVE_FAILURE",
                        "severity": "REVIEW",
                        "subject": "save",
                        "message": "Save may fail",
                        "evidence": ["lib/save.dart"],
                    }
                ]
            },
        },
        "confidence": {
            "schema_version": 1,
            "claims": [
                {
                    "id": "capability:auth",
                    "domain": "capability",
                    "subject": "auth",
                    "proposition": "capability-present",
                    "status": "CONFIRMED",
                    "evidence": ["lib/auth.dart"],
                    "rationale": "runtime and code agree",
                },
                {
                    "id": "capability:backup",
                    "domain": "capability",
                    "subject": "backup",
                    "proposition": "capability-present",
                    "status": "UNVERIFIED",
                    "evidence": ["README.md"],
                    "rationale": "docs only",
                },
                {
                    "id": "state:legacy-doc",
                    "domain": "state",
                    "subject": "legacy-doc",
                    "proposition": "historical-reference",
                    "status": "STALE",
                    "source_sha": sha1,
                    "current_sha": sha2,
                    "evidence": ["docs/old.md"],
                    "rationale": "historical evidence outside current impact set",
                },
            ],
            "contradictions": [],
        },
        "journey": {
            "schema_version": 1,
            "journeys": [{"depth": 2, "steps": ["home", "settings"]}],
            "findings": [],
        },
        "ux": {"schema_version": 1, "findings": []},
        "longitudinal": {
            "schema_version": 1,
            "state": "REGRESSION_REVIEW",
            "current": {"repository": "owner/app", "resolved_sha": sha2, "run_id": "42", "lineage_ref": "main"},
            "baseline": {"available": True, "repository": "owner/app", "resolved_sha": sha1, "run_id": "41"},
            "summary": {"history_snapshots": 2, "regression_candidates": 1},
            "findings": {
                "new": [],
                "returned": [
                    {
                        "key": "product_consistency|id:finding-save",
                        "source": "product_consistency",
                        "id": "finding-save",
                        "kind": "SAVE_FAILURE",
                        "subject": "save",
                    }
                ],
                "persistent": [],
                "resolved": [],
                "resolved_history": [
                    {
                        "key": "product_consistency|id:old-gap",
                        "source": "product_consistency",
                        "id": "old-gap",
                        "kind": "LEGACY_GAP",
                        "subject": "legacy",
                        "severity": "REVIEW",
                        "evidence": ["lib/legacy.dart"],
                        "last_seen_sha": sha1,
                        "resolution_observed_sha": sha1,
                    }
                ],
                "suppressed_resolved": [],
                "history": [
                    {
                        "key": "product_consistency|id:finding-save",
                        "source": "product_consistency",
                        "id": "finding-save",
                        "kind": "SAVE_FAILURE",
                        "subject": "save",
                        "seen_count": 2,
                        "consecutive_seen": 2,
                        "first_seen_sha": sha1,
                        "last_seen_sha": sha2,
                    }
                ]
            },
            "regression_candidates": [
                {
                    "key": "product_consistency|id:finding-save",
                    "kind": "SAVE_FAILURE",
                    "subject": "save",
                    "reason": "returned",
                    "source": "product_consistency",
                }
            ],
        },
        "experiment": {
            "schema_version": 1,
            "experiments": [
                {
                    "id": "EXP-1",
                    "priority": "HIGH",
                    "kind": "SAVE_FAILURE",
                    "subject": "save",
                    "experiment_type": "SPECIALIST_RUNTIME",
                    "labs": ["persistence"],
                    "evidence": ["lib/save.dart"],
                }
            ],
        },
        "analyst": {
            "schema_version": 1,
            "state": "VERIFICATION_REQUIRED",
            "headline": "Verify save regression",
            "summary": {"observations": 1, "next_actions": 1, "regression_candidates": 1},
        },
        "autonomous": {
            "schema_version": 1,
            "runtime_evidence_trust": {
                "trusted": True,
                "manifest_sha256": "a" * 64,
                "binding": {
                    "repository": "owner/app",
                    "resolved_sha": sha2,
                    "workflow_run_id": "42",
                    "package_id": "com.example.app",
                },
            },
        },
        "build_contract": {
            "schema_version": 1,
            "repository": "owner/app",
            "resolved_sha": sha2,
            "trusted_applab_sha": "3" * 40,
            "apk": {
                "package_id": "com.example.app",
                "sha256": "b" * 64,
                "size_bytes": 1234,
                "version_name": "1.0",
                "version_code": "1",
                "build_variant": "debug",
            },
        },
        "analysis_plan": {
            "schema_version": 1,
            "mode": "fast",
            "lane": "FAST_RUNTIME",
            "changed_files": ["lib/auth.dart", "lib/legacy.dart"],
            "changes": [
                {"path": "lib/auth.dart", "status": "M"},
                {"path": "lib/legacy.dart", "status": "M"},
            ],
            "impacted_files": ["lib/settings.dart"],
        },
    }

    graph = build_graph(evidence)
    counts = graph["summary"]["nodes_by_type"]
    for node_type in NODE_TYPES:
        assert node_type in counts
    assert counts["Project"] == 1
    assert counts["Revision"] == 2
    assert counts["BuildArtifact"] == 1
    assert counts["Capability"] == 2
    assert counts["Finding"] == 2
    assert counts["Claim"] == 3
    assert counts["Experiment"] == 1
    assert graph["summary"]["unverified_capabilities"] == 1
    assert graph["summary"]["recurring_findings"] == 1
    assert graph["summary"]["regression_candidates"] == 1
    assert counts["File"] >= 4
    assert counts["Component"] >= 2
    file_keys = {row.get("key") for row in graph["nodes"] if row.get("type") == "File"}
    assert FILES["app"] not in file_keys
    assert "docs/old.md" not in file_keys
    assert graph["summary"]["finding_lifecycle"]["RETURNED"] == 1
    assert graph["summary"]["finding_lifecycle"]["RESOLVED"] == 1
    assert graph["summary"]["invalidated_evidence"] == 1
    assert graph["summary"]["impact_paths"] >= 1

    recurring = query_graph(graph, "recurring-findings")
    assert recurring["results"][0]["first_observed_sha"] == sha1
    unverified = query_graph(graph, "unverified-capabilities")
    assert unverified["results"][0]["capability"] == "backup"
    history = query_graph(graph, "history", "save")
    assert len(history["results"]) == 1
    assert history["results"][0]["seen_count"] == 2
    evidence_query = query_graph(graph, "evidence", "backup")
    assert any(row.get("type") == "Evidence" for row in evidence_query["evidence"])

    lifecycle_query = query_graph(graph, "lifecycle")
    assert lifecycle_query["results"]["RETURNED"] == 1
    stale_query = query_graph(graph, "stale-evidence")
    stale_by_label = {
        row["label"]: (row.get("attributes") or {}).get("freshness")
        for row in stale_query["results"]
    }
    assert stale_by_label["lib/legacy.dart"] == "INVALIDATED"
    assert stale_by_label["docs/old.md"] == "STALE"
    assert stale_query["summary"]["invalidated_count"] == 1
    current_auth = [
        row for row in graph["nodes"]
        if row.get("type") == "Evidence"
        and row.get("label") == "lib/auth.dart"
        and (row.get("attributes") or {}).get("observation_scope") == "CURRENT"
    ]
    assert current_auth
    assert all((row.get("attributes") or {}).get("freshness") == "CURRENT" for row in current_auth)
    assert all(not (row.get("attributes") or {}).get("invalidated_by_files") for row in current_auth)
    impact_query = query_graph(graph, "impact")
    relations = [relation for row in impact_query["results"]["paths"] for relation in row["relations"]]
    assert "FILE_IN_COMPONENT" in relations
    assert "COMPONENT_SUPPORTS_CAPABILITY" in relations
    assert "CAPABILITY_OBSERVED_ON_SURFACE" in relations
    assert "SURFACE_IN_JOURNEY" in relations
    subject_query = query_graph(graph, "subject", "legacy")
    assert subject_query["history"][0]["lifecycle_state"] == "RESOLVED"

    optional_inputs = dict(evidence)
    optional_inputs.pop("autonomous", None)
    optional_inputs.pop("build_contract", None)
    optional_graph = build_graph(optional_inputs)
    optional_nodes = optional_graph["nodes"]
    optional_revision = next(
        row
        for row in optional_nodes
        if row.get("type") == "Revision"
        and (row.get("attributes") or {}).get("resolved_sha") == sha2
    )
    assert FILES["autonomous"] not in optional_revision["provenance"]
    assert not any(row.get("type") == "BuildArtifact" for row in optional_nodes)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        write_outputs(graph, out)
        assert (out / "evidence-graph.json").is_file()
        assert (out / "evidence-graph.md").is_file()
    print("AppLab Evidence Graph v4.6 self-test PASS")


