#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_operations_studio_v60i as mod  # noqa: E402


def main() -> int:
    empty = mod.build_agent_operations([])
    assert empty["available"] is False
    assert empty["summary"]["work_items"] == 0
    assert empty["merge_authority"] == "NONE"
    assert empty["release_authority"] == "NONE"

    records = [
        {
            "record_type": "APPLAB_WORK_ITEM",
            "work_item_id": "wrk_a",
            "repository": "owner/app",
            "resolved_sha": "a" * 40,
            "state": "EXECUTING",
            "risk": "NORMAL",
            "budgets": {
                "max_repair_attempts": 2,
                "max_files": 5,
                "max_changed_lines": 250,
            },
            "authority_envelope": {
                "allowed_capabilities": ["ALLOW_CODE_EDIT"],
                "denied_capabilities": ["SELF_MERGE", "RELEASE"],
            },
        },
        {
            "record_type": "APPLAB_WORK_ACTION",
            "work_item_id": "wrk_a",
            "repository": "owner/app",
            "resolved_sha": "a" * 40,
        },
        {
            "record_type": "APPLAB_EVIDENCE_REF",
            "work_item_id": "wrk_a",
            "repository": "owner/app",
            "resolved_sha": "a" * 40,
        },
        {
            "record_type": "VERIFY_REPAIR_LOOP_DECISION_V60D",
            "root_work_item_id": "wrk_a",
            "root_resolved_sha": "a" * 40,
            "repository": "owner/app",
            "state": "STOPPED",
            "reason_code": "BUDGET_EXHAUSTED",
            "next_action": "NONE",
            "repair_attempt_count": 2,
        },
    ]
    records.extend(
        [
            {
                "record_type": "APPLAB_WORK_TRANSITION",
                "work_item_id": "wrk_a",
                "from_state": "EXECUTING",
                "to_state": "VERIFYING",
                "reason_code": "FIX_READY",
            },
            {
                "record_type": "VERIFY_REPAIR_LOOP_DECISION_V60D",
                "root_work_item_id": "wrk_root",
                "root_resolved_sha": "b" * 40,
                "repository": "owner/root",
                "state": "COMPLETE",
                "reason_code": "VERIFIED_PASS",
                "next_action": "OPEN_DRAFT_PR",
                "repair_attempt_count": 1,
            },
            {
                "record_type": "DRAFT_PR_MATERIALIZATION_V60E",
                "root_work_item_id": "wrk_root",
                "work_item_id": "wrk_repair",
                "repository": "owner/root",
                "state": "DRAFT_PR_CREATED",
                "pr_number": 321,
                "pr_url": "https://example.test/pr/321",
            },
        ]
    )

    snapshot = mod.build_agent_operations(records)
    assert snapshot["summary"]["stopped_or_blocked"] == 1
    assert snapshot["summary"]["complete"] == 1
    assert snapshot["summary"]["draft_prs"] == 1
    row = next(item for item in snapshot["work_items"] if item["work_item_id"] == "wrk_a")
    assert row["actions"] == 1
    assert row["evidence_count"] == 1
    assert row["stop_reason"] == "BUDGET_EXHAUSTED"
    assert row["budget"]["repair_attempts"] == {"used": 2, "max": 2}
    assert "SELF_MERGE" in row["authority_envelope"]["denied_capabilities"]
    root = next(item for item in snapshot["work_items"] if item["work_item_id"] == "wrk_root")
    assert root["resolved_sha"] == "b" * 40
    assert root["state"] == "COMPLETE"
    assert root["stop_reason"] == "VERIFIED_PASS"
    assert root["pr_number"] == 321
    assert root["pr_url"] == "https://example.test/pr/321"

    transition_only = mod.build_agent_operations(
        [
            {
                "record_type": "APPLAB_WORK_ITEM",
                "work_item_id": "wrk_transition",
                "state": "CREATED",
            },
            {
                "record_type": "APPLAB_WORK_TRANSITION",
                "work_item_id": "wrk_transition",
                "from_state": "CREATED",
                "to_state": "EXECUTING",
                "reason_code": "START",
            },
        ]
    )
    assert transition_only["work_items"][0]["state"] == "EXECUTING"

    mod.self_test()
    print("AppLab v6.0I agent operations studio contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
