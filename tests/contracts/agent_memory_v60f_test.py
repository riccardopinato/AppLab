#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_memory_v60f as memory  # noqa: E402
import autonomous_failure_triage_v58a as triage_producer  # noqa: E402
import causal_repo_investigator_v60b as investigator  # noqa: E402
import verify_repair_loop_v60d as repair_loop  # noqa: E402


def repair_record(
    work_item_id: str,
    sha: str,
    attempt: int,
    changed_files: list[str],
    token: str,
    source_ref: str,
) -> dict:
    return {
        "schema_version": 1,
        "record_type": "BOUNDED_FIX_RESULT_V60C",
        "authority": "BRANCH_WORKSPACE_ONLY",
        "state": "READY_FOR_VERIFICATION",
        "repository": "owner/app",
        "resolved_sha": sha,
        "work_item_id": work_item_id,
        "attempt_number": attempt,
        "patch_sha256": token * 64,
        "result_patch_sha256": chr(ord(token) + 1) * 64,
        "changed_files": changed_files,
        "additions": 2,
        "deletions": 1,
        "changed_lines": 3,
        "_source_ref": source_ref,
    }


def main() -> int:
    root_work = "wrk_root"
    second_work = "wrk_second"
    first = repair_record(
        root_work,
        "a" * 40,
        1,
        ["lib/first.dart"],
        "1",
        "episodes/repair-1.json",
    )
    second = repair_record(
        second_work,
        "b" * 40,
        2,
        ["lib/final.dart", "test/final_test.dart"],
        "3",
        "episodes/repair-2.json",
    )
    final_identity = repair_loop.repair_identity(second)
    second_triage = triage_producer.build_triage(
        {
            "repository": "owner/app",
            "resolved_sha": "b" * 40,
            "result": "FAIL",
            "build_error": "unit test failed in lib/final.dart line 10",
        },
        {
            "repository": "owner/app",
            "head_sha": "b" * 40,
            "baseline_sha": "a" * 40,
            "lane": "FAST_RUNTIME",
        },
    )
    trigger_signature = second_triage["trigger_failure_signature"]["signature_sha256"]

    records = [
        {
            "record_type": "CAUSAL_REPO_INVESTIGATION_V60B",
            "repository": "owner/app",
            "resolved_sha": "a" * 40,
            "classification": "BUILD_OR_QUALITY_FAILURE",
            "ranked_candidate_files": [{"path": "lib/first.dart"}],
            "required_regression_targets": ["test/first_test.dart"],
            "_source_ref": "episodes/investigation-1.json",
        },
        first,
        second_triage,
        {
            "record_type": "CAUSAL_REPO_INVESTIGATION_V60B",
            "repository": "owner/app",
            "resolved_sha": "b" * 40,
            "classification": "BUILD_OR_QUALITY_FAILURE",
            "ranked_candidate_files": [{"path": "lib/final.dart"}],
            "required_regression_targets": ["test/final_test.dart"],
            "_source_ref": "episodes/investigation-2.json",
        },
        second,
        {
            "record_type": "VERIFY_REPAIR_LOOP_DECISION_V60D",
            "repository": "owner/app",
            "root_work_item_id": root_work,
            "root_resolved_sha": "a" * 40,
            "state": "COMPLETE",
            "reason_code": "VERIFIED_PASS",
            "repair_attempt_count": 2,
            "repair_identity_sha256": final_identity,
            "attempt_signatures": [],
            "_source_ref": "episodes/verdict.json",
        },
    ]

    derived = memory.build_memory(records)
    assert derived["guardrails"]["derived_rebuildable_noncanonical"] is True
    assert derived["guardrails"]["can_raise_autonomy_eligibility"] is False
    assert len(derived["successful_repairs"]) == 1
    success = derived["successful_repairs"][0]
    assert success["work_item_id"] == second_work
    assert success["repair_identity_sha256"] == final_identity
    assert success["files"] == ["lib/final.dart", "test/final_test.dart"]
    assert "lib/first.dart" not in success["files"]
    assert "test/final_test.dart" in success["required_regressions"]
    assert "BUILD_OR_QUALITY_FAILURE" in success["classifications"]
    assert trigger_signature in {
        row["signature_sha256"] for row in success["failure_signatures"]
    }

    ranking = memory.rank_strategies(
        derived,
        repository="owner/app",
        classification="BUILD_OR_QUALITY_FAILURE",
        failure_signature=trigger_signature,
        candidate_files=["lib/final.dart", "lib/not-authorized.dart"],
    )
    assert ranking["strategies"]
    top = ranking["strategies"][0]
    assert top["matched_current_candidates"] == ["lib/final.dart"]
    assert "lib/not-authorized.dart" not in top["matched_current_candidates"]
    assert ranking["guardrails"]["can_add_causal_candidate"] is False

    # A COMPLETE verdict without the exact final repair record is remembered as
    # incomplete provenance and never becomes a successful-repair hint.
    unbound = memory.build_memory(
        [row for row in records if row is not second]
    )
    assert unbound["successful_repairs"] == []
    root_episode = next(
        row for row in unbound["episodes"]
        if row["episode_key"] == root_work
    )
    assert root_episode["outcome"] == "VERIFIED_PASS"
    assert root_episode["repair_binding_state"] == "MISSING_FINAL_REPAIR"

    # Historical memory may add ranking points only after current evidence has
    # independently crossed the causal candidate threshold.
    with tempfile.TemporaryDirectory() as raw:
        repo = Path(raw)
        (repo / "lib/cache").mkdir(parents=True)
        candidate = repo / "lib/cache/state.dart"
        candidate.write_text("class State {}\n", encoding="utf-8")
        triage = {
            "repository": "owner/app",
            "resolved_sha": "c" * 40,
            "baseline_sha": "b" * 40,
            "classification": "BUILD_OR_QUALITY_FAILURE",
            "failed_labs": [],
            "likely_surfaces": ["cache state"],
            "root_cause_hypotheses": [],
            "required_regression_evidence": [],
        }
        weak_plan = {
            "repository": "owner/app",
            "head_sha": "c" * 40,
            "baseline_sha": "b" * 40,
            "changed_files": [],
            "impacted_files": [],
            "analysis_truncated": False,
        }
        historical = {
            "successful_repairs": [{"files": ["lib/cache/state.dart"]}]
        }
        weak = investigator.build_investigation(
            triage,
            weak_plan,
            repo,
            history=historical,
        )
        assert weak["ranked_candidate_files"] == []
        assert weak["edit_recommendation"] == "DENY_AUTONOMOUS_EDIT"

        strong = investigator.build_investigation(
            triage,
            {**weak_plan, "changed_files": ["lib/cache/state.dart"]},
            repo,
            history=historical,
        )
        row = strong["ranked_candidate_files"][0]
        assert row["path"] == "lib/cache/state.dart"
        assert row["historical_score_boost"] == 10
        assert row["current_evidence_score"] == row["score"] - 10
        assert row["current_evidence_score"] >= 25

    # Pattern-3 remains a review observation with no self-modifying authority.
    stopped = []
    for index in range(3):
        stopped.append(
            {
                "record_type": "VERIFY_REPAIR_LOOP_DECISION_V60D",
                "repository": "owner/app",
                "root_work_item_id": f"wrk_stop_{index}",
                "root_resolved_sha": chr(ord("d") + index) * 40,
                "state": "STOPPED",
                "reason_code": "IDENTITY_NOT_PROVEN",
                "attempt_signatures": [],
                "_source_ref": f"stop/{index}.json",
            }
        )
    patterns = memory.build_memory(stopped)
    pattern = next(
        row for row in patterns["policy_observations"]
        if row["reason_code"] == "IDENTITY_NOT_PROVEN"
    )
    assert pattern["occurrences"] == 3
    assert pattern["classification"] == "PATTERN_3_REVIEW"
    assert pattern["automatic_policy_change"] is False

    with tempfile.TemporaryDirectory() as raw:
        history = Path(raw)
        (history / "valid.json").write_text(
            json.dumps(records[0]),
            encoding="utf-8",
        )
        (history / "unrelated.json").write_text(
            json.dumps({"record_type": "UNRELATED", "secret": "never-copy"}),
            encoding="utf-8",
        )
        (history / "invalid-record-type.json").write_text(
            json.dumps({"record_type": [], "repository": "owner/app"}),
            encoding="utf-8",
        )
        (history / "malformed.json").write_text(
            json.dumps(
                {
                    "record_type": "CAUSAL_REPO_INVESTIGATION_V60B",
                    "repository": "not-a-repository",
                    "resolved_sha": "bad",
                    "secret": "never-copy",
                }
            ),
            encoding="utf-8",
        )
        scanned = memory._read_records(history)
        assert len(scanned) == 1
        assert "secret" not in scanned[0]

    memory.self_test()
    print("AppLab v6.0F episodic memory contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
