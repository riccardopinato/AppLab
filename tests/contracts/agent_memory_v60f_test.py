#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_memory_v60f as memory  # noqa: E402


def main() -> int:
    records = []
    for index in range(3):
        work = f"wrk_{index}"
        records.extend([
            {
                "record_type": "AUTONOMOUS_FAILURE_TRIAGE_V58A",
                "repository": "owner/app",
                "resolved_sha": chr(ord("a") + index) * 40,
                "classification": "BUILD_OR_QUALITY_FAILURE",
                "required_regression_evidence": ["test/client_test.dart"],
                "_source_ref": f"{work}/triage.json",
            },
            {
                "record_type": "CAUSAL_REPO_INVESTIGATION_V60B",
                "repository": "owner/app",
                "work_item_id": work,
                "resolved_sha": chr(ord("a") + index) * 40,
                "classification": "BUILD_OR_QUALITY_FAILURE",
                "ranked_candidate_files": [
                    {"path": "lib/client.dart"},
                    {"path": "test/client_test.dart"},
                ],
                "required_regression_targets": ["test/client_test.dart"],
                "_source_ref": f"{work}/investigation.json",
            },
            {
                "record_type": "BOUNDED_FIX_RESULT_V60C",
                "repository": "owner/app",
                "work_item_id": work,
                "resolved_sha": chr(ord("a") + index) * 40,
                "changed_files": ["lib/client.dart", "test/client_test.dart"],
                "_source_ref": f"{work}/repair.json",
            },
        ])

    # One verified repair and three independent STOP records to exercise
    # Pattern-3 observation without policy mutation.
    records.append({
        "record_type": "VERIFY_REPAIR_LOOP_DECISION_V60D",
        "repository": "owner/app",
        "root_work_item_id": "wrk_0",
        "root_resolved_sha": "a" * 40,
        "state": "COMPLETE",
        "reason_code": "VERIFIED_PASS",
        "attempt_signatures": [
            {
                "signature_sha256": "sha256:known",
                "classification": "BUILD_OR_QUALITY_FAILURE",
            }
        ],
        "_source_ref": "wrk_0/verdict.json",
    })
    for index in range(3):
        records.append({
            "record_type": "VERIFY_REPAIR_LOOP_DECISION_V60D",
            "repository": "owner/app",
            "root_work_item_id": f"stop_{index}",
            "root_resolved_sha": "f" * 40,
            "state": "STOPPED",
            "reason_code": "IDENTITY_NOT_PROVEN",
            "attempt_signatures": [],
            "_source_ref": f"stop_{index}/verdict.json",
        })

    derived = memory.build_memory(records)
    assert derived["guardrails"]["can_modify_policy"] is False
    assert derived["guardrails"]["can_modify_factory_core"] is False
    assert len(derived["successful_repairs"]) == 1
    assert derived["successful_repairs"][0]["files"] == [
        "lib/client.dart",
        "test/client_test.dart",
    ]
    pattern = next(
        row
        for row in derived["policy_observations"]
        if row["reason_code"] == "IDENTITY_NOT_PROVEN"
    )
    assert pattern["occurrences"] == 3
    assert pattern["classification"] == "PATTERN_3_REVIEW"
    assert pattern["automatic_policy_change"] is False

    ranking = memory.rank_strategies(
        derived,
        repository="owner/app",
        classification="BUILD_OR_QUALITY_FAILURE",
        failure_signature="sha256:known",
        candidate_files=["lib/client.dart"],
    )
    assert ranking["strategies"]
    top = ranking["strategies"][0]
    assert top["work_item_id"] == "wrk_0"
    assert "exact prior failure signature" in top["reasons"]
    assert "candidate-path overlap" in top["reasons"]
    assert ranking["automatic_code_change"] is False
    assert ranking["automatic_policy_change"] is False

    truncated = memory.build_memory(records, max_episodes=1)
    assert truncated["truncated"] is True
    assert truncated["episode_count"] == 1

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "good.json").write_text(
            json.dumps(records[0]),
            encoding="utf-8",
        )
        (root / "ignored.json").write_text(
            json.dumps({"record_type": "UNRELATED", "secret": "do-not-copy"}),
            encoding="utf-8",
        )
        (root / "bad.json").write_text("{not json", encoding="utf-8")
        scanned = memory._read_records(root)
        assert len(scanned) == 1
        assert "secret" not in scanned[0]

    memory.self_test()
    print("AppLab v6.0F episodic memory contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
