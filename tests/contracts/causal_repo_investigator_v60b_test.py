#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import causal_repo_investigator_v60b as mod  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        for path in (
            "lib/data/sync_client.dart",
            "lib/data/sync_repository.dart",
            "test/data/sync_client_test.dart",
            ".github/workflows/ci.yml",
        ):
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("// fixture\n", encoding="utf-8")

        base_triage = {
            "repository": "owner/app",
            "resolved_sha": "b" * 40,
            "baseline_sha": "a" * 40,
            "classification": "APP_RUNTIME_FAILURE",
            "failed_labs": ["network"],
            "likely_surfaces": ["network client", "sync/connectivity"],
            "required_regression_evidence": ["focused regression for network"],
        }
        plan = {
            "repository": "owner/app",
            "head_sha": "b" * 40,
            "baseline_sha": "a" * 40,
            "changed_files": [
                "lib/data/sync_client.dart",
                "lib/data/sync_repository.dart",
            ],
            "impacted_files": [],
            "analysis_truncated": False,
        }

        localized = mod.build_investigation(
            {
                **base_triage,
                "root_cause_hypotheses": [
                    "lib/data/sync_client.dart:71 request retries after reconnect"
                ],
            },
            plan,
            root,
        )
        assert localized["state"] == "LOCALIZED"
        assert localized["ranked_candidate_files"][0]["path"] == "lib/data/sync_client.dart"
        assert localized["edit_recommendation"] == "ELIGIBLE_FOR_BOUNDED_REPAIR"
        assert "test/data/sync_client_test.dart" in localized["required_regression_targets"]

        # Two changed sync files with no explicit diagnostic path remain
        # deliberately ambiguous rather than manufacturing certainty.
        ambiguous = mod.build_investigation(
            {
                **base_triage,
                "root_cause_hypotheses": ["network sync failed after reconnect"],
            },
            plan,
            root,
        )
        assert ambiguous["state"] == "LOCALIZED"
        assert "top causal candidates are closely scored" in ambiguous["unresolved_uncertainty"]
        assert "diagnostics contain no explicit repository path" in ambiguous["unresolved_uncertainty"]
        assert ambiguous["edit_recommendation"] == "HUMAN_OR_DEEPER_INVESTIGATION_REQUIRED"


        stale_graph = {
            "identity": {
                "repository": "owner/other",
                "resolved_sha": "b" * 40,
            },
            "nodes": [
                {
                    "type": "File",
                    "key": "lib/data/sync_client.dart",
                    "attributes": {
                        "path": "lib/data/sync_client.dart",
                        "changed": True,
                    },
                }
            ],
        }
        stale = mod.build_investigation(
            {
                **base_triage,
                "root_cause_hypotheses": [
                    "lib/data/sync_client.dart:71 request retries after reconnect"
                ],
            },
            plan,
            root,
            evidence_graph=stale_graph,
        )
        assert stale["evidence_summary"]["graph_accepted"] is False
        assert "evidence graph ignored: GRAPH_REPOSITORY_MISMATCH" in stale["unresolved_uncertainty"]

        bounded_contract = dict(mod.load_contract())
        bounded_contract["max_repository_files"] = 1
        truncated_inventory = mod.build_investigation(
            {
                **base_triage,
                "root_cause_hypotheses": [
                    "lib/data/sync_client.dart:71 request retries after reconnect"
                ],
            },
            plan,
            root,
            contract=bounded_contract,
        )
        assert truncated_inventory["evidence_summary"]["inventory_truncated"] is True
        assert truncated_inventory["edit_recommendation"] == "HUMAN_OR_DEEPER_INVESTIGATION_REQUIRED"

        # Workflow localization is allowed as evidence, but the investigator
        # must not declare it eligible for autonomous bounded repair.
        protected = mod.build_investigation(
            {
                **base_triage,
                "classification": "BUILD_OR_QUALITY_FAILURE",
                "failed_labs": [],
                "likely_surfaces": ["build workflow"],
                "root_cause_hypotheses": [".github/workflows/ci.yml: invalid action input"],
            },
            {
                **plan,
                "changed_files": [".github/workflows/ci.yml"],
                "impacted_files": [],
            },
            root,
        )
        assert protected["ranked_candidate_files"][0]["kind"] == "PROTECTED"
        assert protected["edit_recommendation"] == "HUMAN_OR_DEEPER_INVESTIGATION_REQUIRED"
        assert "top candidate is protected by the repair authority boundary" in protected["unresolved_uncertainty"]

        for failure_class in ("UNKNOWN_FAILURE", "INFRA_ERROR", "FLAKY_SUSPECT"):
            report = mod.build_investigation(
                {**base_triage, "classification": failure_class},
                plan,
                root,
            )
            assert report["state"] == "NON_CODE_FAILURE"
            assert report["edit_recommendation"] == "DENY_AUTONOMOUS_EDIT"
            assert report["ranked_candidate_files"] == []

    mod.self_test()
    print("AppLab v6.0B causal investigator contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
