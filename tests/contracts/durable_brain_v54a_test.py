#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import durable_brain_v54a as brain  # noqa: E402


def assert_rejected(callback, contains: str) -> None:
    try:
        callback()
    except brain.ContractError as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected ContractError containing {contains!r}")


def main() -> int:
    contract = brain.load_contract()
    sha_a = "a" * 40
    sha_b = "b" * 40
    applab_sha = "c" * 40

    event = brain._event_fixture("evt_contract", "owner/app", "refs/heads/main", sha_b, "delivery")
    brain.validate_event(event, contract)

    bad_event = copy.deepcopy(event)
    bad_event["trust"]["signature_verified"] = False
    assert_rejected(
        lambda: brain.validate_event(bad_event, contract),
        "admitted event must satisfy all trust checks",
    )

    wrong_dedupe = copy.deepcopy(event)
    wrong_dedupe["dedupe_key"] = "sha256:" + "0" * 64
    assert_rejected(
        lambda: brain.validate_event(wrong_dedupe, contract),
        "event dedupe_key mismatch",
    )

    operation = brain._operation_fixture(
        "op_contract", "owner/app", "main", sha_b, applab_sha
    )
    brain.validate_operation(operation, contract)

    wrong_queue = copy.deepcopy(operation)
    wrong_queue["queue_key"] = "owner/other|main|VERIFICATION"
    assert_rejected(
        lambda: brain.validate_operation(wrong_queue, contract),
        "operation queue_key mismatch",
    )

    bad_cert = brain._operation_fixture(
        "op_bad_cert",
        "owner/app",
        "main",
        sha_b,
        applab_sha,
        operation_class="CERTIFICATION",
        analysis_mode="fast",
        priority=500,
    )
    assert_rejected(
        lambda: brain.validate_operation(bad_cert, contract),
        "CERTIFICATION operation must use certification analysis_mode",
    )

    scheduled = {
        "schema_version": 1,
        "record_type": "APPLAB_EVENT",
        "event_id": "evt_schedule",
        "correlation_id": "cor_schedule",
        "source": "github",
        "source_event_type": "reconciliation",
        "repository": "owner/app",
        "source_ref": "refs/heads/main",
        "resolved_sha": sha_b,
        "window_id": "window-1",
        "dedupe_key": "",
        "admission": "ADMITTED",
        "trust": {
            "signature_verified": True,
            "replay_window_valid": True,
            "source_authenticated": True,
        },
    }
    scheduled["dedupe_key"] = brain.event_dedupe_key(scheduled)
    scheduled_next = copy.deepcopy(scheduled)
    scheduled_next["event_id"] = "evt_schedule_next"
    scheduled_next["window_id"] = "window-2"
    scheduled_next["dedupe_key"] = brain.event_dedupe_key(scheduled_next)
    assert scheduled["dedupe_key"] != scheduled_next["dedupe_key"]
    brain.validate_event(scheduled, contract)
    brain.validate_event(scheduled_next, contract)

    deterministic_attempt = brain._attempt_fixture(
        "att_bad_retry",
        "op_contract",
        1,
        "FAILED",
        "APP_RUNTIME_FAILURE",
        True,
    )
    assert_rejected(
        lambda: brain.validate_attempt(deterministic_attempt, contract),
        "deterministic app/build failure cannot be marked retryable",
    )

    unfinished_attempt = brain._attempt_fixture(
        "att_running",
        "op_contract",
        1,
        "RUNNING",
        "INFRA_ERROR",
        True,
    )
    assert brain.retry_decision(unfinished_attempt, 2, contract) == {
        "retry": False,
        "reason": "ATTEMPT_NOT_FAILED",
    }

    assert_rejected(
        lambda: brain.validate_transition("SUCCEEDED", "RUNNING", contract),
        "illegal operation transition SUCCEEDED -> RUNNING",
    )

    created = brain._operation_fixture(
        "op_created_test", "owner/app", "main", sha_a, applab_sha, state="CREATED"
    )
    older = brain._operation_fixture(
        "op_old_test", "owner/app", "main", sha_a, applab_sha
    )
    newer = brain._operation_fixture(
        "op_new_test", "owner/app", "main", sha_b, applab_sha
    )
    allowed, reason = brain.can_supersede(
        older, newer, {sha_b: [sha_a]}, contract
    )
    assert allowed is True
    assert reason == "SAFE_PENDING_SUPERSESSION"

    allowed, reason = brain.can_supersede(
        created, newer, {sha_b: [sha_a]}, contract
    )
    assert allowed is False
    assert reason == "STATE_NOT_SUPERSEDEABLE"

    conflicting = copy.deepcopy(newer)
    conflicting["operation_id"] = older["operation_id"]
    assert_rejected(
        lambda: brain.simulate_queue([older, conflicting], {sha_b: [sha_a]}, contract),
        "operation_id reused with conflicting immutable identity",
    )

    independent = brain._operation_fixture(
        "op_other_test", "owner/other", "main", sha_b, applab_sha
    )
    allowed, reason = brain.can_supersede(
        older, independent, {sha_b: [sha_a]}, contract
    )
    assert allowed is False
    assert reason == "DIFFERENT_QUEUE"

    operational_workflows = [
        path for path in (ROOT / ".github" / "workflows").glob("*.yml")
        if path.name != "ci.yml"
    ]
    wired = [
        path.name
        for path in operational_workflows
        if "durable_brain_v54a.py" in path.read_text(encoding="utf-8")
    ]
    assert wired == [], f"v5.4A must remain offline; unexpected workflow wiring: {wired}"

    for forbidden in ("requests", "urllib.request", "socket", "psycopg", "conductor"):
        assert forbidden not in (ROOT / "scripts" / "durable_brain_v54a.py").read_text(encoding="utf-8")

    first = brain.replay_corpus(contract=contract)
    second = brain.replay_corpus(contract=contract)
    assert first == second
    assert first["passed"] is True
    assert first["case_count"] >= 10
    assert first["failures"] == []
    assert first["replay_digest_sha256"].startswith("sha256:")

    brain.self_test()
    print("AppLab v5.4A contract/replay test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
