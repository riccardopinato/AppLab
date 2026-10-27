#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_repair_loop_v60d as loop  # noqa: E402


def expect_error(callback, contains: str) -> None:
    try:
        callback()
    except loop.RepairLoopError as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected RepairLoopError containing {contains!r}")


def main() -> int:
    root = loop._fixture_work_item(
        work_item_id="wrk_contract_1",
        resolved_sha="b" * 40,
    )
    triage = {
        "classification": "BUILD_OR_QUALITY_FAILURE",
        "repository": "owner/app",
        "resolved_sha": root["resolved_sha"],
    }
    initial = loop._investigation(root)

    start = loop.evaluate_loop(root, triage, initial, [])
    assert start["state"] == "NEEDS_REPAIR"
    assert start["next_source_sha"] == root["resolved_sha"]

    # Focused verification is mandatory and repair-identity bound.
    repair = loop._repair(root, 1)
    pending = {
        "chain_attempt_number": 1,
        "work_item": root,
        "investigation": initial,
        "repair_result": repair,
    }
    focused = loop.evaluate_loop(root, triage, initial, [pending])
    assert focused["state"] == "NEEDS_FOCUSED_VERIFY"

    wrong_focus = copy.deepcopy(pending)
    wrong_focus["focused_verification"] = {
        "status": "PASS",
        "repair_identity_sha256": "sha256:" + "0" * 64,
    }
    expect_error(
        lambda: loop.evaluate_loop(root, triage, initial, [wrong_focus]),
        "focused verification repair identity mismatch",
    )

    # A focused PASS must be materialized to a real descendant SHA before
    # trusted AppLab verification can occur.
    focus_ok = copy.deepcopy(pending)
    focus_ok["focused_verification"] = {
        "status": "PASS",
        "repair_identity_sha256": loop.repair_identity(repair),
    }
    materialize = loop.evaluate_loop(root, triage, initial, [focus_ok])
    assert materialize["state"] == "NEEDS_MATERIALIZATION"
    assert materialize["next_action"] == "MATERIALIZE_DRAFT_BRANCH"

    attempt1 = loop._attempt(
        root,
        1,
        "d" * 40,
        {"result": "PASS", "runtime_result": "PASS"},
    )
    verified = loop.evaluate_loop(root, triage, initial, [attempt1])
    assert verified["state"] == "COMPLETE"
    assert verified["reason_code"] == "VERIFIED_PASS"
    assert verified["trusted_evidence_producer"] == "trusted-apk-verifier"

    # The result string alone is never sufficient.
    fake = copy.deepcopy(attempt1)
    fake["trusted_evidence"]["manifest_sha256"] = ""
    not_trusted = loop.evaluate_loop(root, triage, initial, [fake])
    assert not_trusted["state"] == "STOPPED"
    assert not_trusted["reason_code"] == "VERIFICATION_NOT_TRUSTED"

    # A deterministic failed first repair requests a new investigation rooted
    # at the exact materialized repaired SHA.
    first_fail = loop._attempt(
        root,
        1,
        "d" * 40,
        {
            "result": "FAIL",
            "build_error": "unit test failed in lib/fix.dart line 10",
        },
    )
    retry = loop.evaluate_loop(root, triage, initial, [first_fail])
    assert retry["state"] == "NEEDS_INVESTIGATION"
    assert retry["next_source_sha"] == "d" * 40
    assert retry["next_attempt_number"] == 2

    # Attempt two must use a fresh WorkItem for the exact prior repaired SHA.
    stale_second = loop._attempt(
        root,
        2,
        "e" * 40,
        {
            "result": "FAIL",
            "build_error": "unit test failed in lib/fix.dart line 99",
        },
    )
    expect_error(
        lambda: loop.evaluate_loop(root, triage, initial, [first_fail, stale_second]),
        "repair chain attempt source does not match prior repaired SHA",
    )

    second_work = loop._fixture_work_item(
        work_item_id="wrk_contract_2",
        resolved_sha="d" * 40,
    )
    second_same = loop._attempt(
        second_work,
        2,
        "e" * 40,
        {
            "result": "FAIL",
            "build_error": "unit test failed in lib/fix.dart line 99",
        },
    )
    repeated = loop.evaluate_loop(
        root,
        triage,
        initial,
        [first_fail, second_same],
    )
    assert repeated["state"] == "STOPPED"
    assert repeated["reason_code"] == "REPEATED_FAILURE_SIGNATURE"

    different_same_class = loop._attempt(
        second_work,
        2,
        "e" * 40,
        {
            "result": "FAIL",
            "build_error": "lint failed: unused import after repair",
        },
    )
    exhausted = loop.evaluate_loop(
        root,
        triage,
        initial,
        [first_fail, different_same_class],
    )
    assert exhausted["state"] == "STOPPED"
    assert exhausted["reason_code"] == "BUDGET_EXHAUSTED"

    mutation = loop._attempt(
        second_work,
        2,
        "e" * 40,
        {
            "result": "FAIL",
            "network_lab": "FAIL",
            "reason": "network request failed",
        },
    )
    changed_class = loop.evaluate_loop(
        root,
        triage,
        initial,
        [first_fail, mutation],
    )
    assert changed_class["reason_code"] == "UNEXPLAINED_FAILURE_MUTATION"

    # UNKNOWN and infrastructure uncertainty never become another code edit.
    unknown = loop.evaluate_loop(
        root,
        {**triage, "classification": "UNKNOWN_FAILURE"},
        initial,
        [],
    )
    assert unknown["reason_code"] == "UNKNOWN_CLASSIFICATION"

    infra = loop.evaluate_loop(
        root,
        {**triage, "classification": "INFRA_ERROR"},
        initial,
        [],
    )
    assert infra["state"] == "WAITING_EXTERNAL"

    loop.self_test()
    print("AppLab v6.0D trusted verify-repair contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
