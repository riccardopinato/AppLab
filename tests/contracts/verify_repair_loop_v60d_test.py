#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_repair_loop_v60d as mod  # noqa: E402


def main() -> int:
    work_item = mod._fixture_work_item()
    triage = {
        "classification": "BUILD_OR_QUALITY_FAILURE",
        "repository": "owner/app",
        "resolved_sha": "b" * 40,
    }
    investigation = {
        "state": "LOCALIZED",
        "edit_recommendation": "ELIGIBLE_FOR_BOUNDED_REPAIR",
    }

    # Focused verification must occur before AppLab verification.
    manifest = mod._manifest(1)
    focused_pending = {
        "attempt_number": 1,
        "repair_manifest": manifest,
    }
    focused = mod.evaluate_loop(
        work_item, triage, investigation, [focused_pending]
    )
    assert focused["state"] == "NEEDS_FOCUSED_VERIFY"
    assert focused["next_action"] == "RUN_FOCUSED_VERIFY"

    # Infrastructure uncertainty waits; it does not consume a new repair.
    infra = mod._attempt(
        1,
        {
            "result": "BLOCKED",
            "reason": "emulator connection reset",
            "pipeline_status": "failure",
        },
    )
    waiting = mod.evaluate_loop(work_item, triage, investigation, [infra])
    assert waiting["state"] == "WAITING_EXTERNAL"
    assert waiting["next_action"] == "WAIT_EXTERNAL"

    # Two materially different failures within the same broad class may consume
    # the bounded budget, but there is no third repair attempt.
    first = mod._attempt(
        1,
        {
            "result": "FAIL",
            "build_error": "unit test failed: expected alpha got beta",
        },
    )
    second = mod._attempt(
        2,
        {
            "result": "FAIL",
            "build_error": "lint failed: unused import in repaired file",
        },
    )
    exhausted = mod.evaluate_loop(
        work_item, triage, investigation, [first, second]
    )
    assert exhausted["state"] == "STOPPED"
    assert exhausted["reason_code"] == "BUDGET_EXHAUSTED"

    # A third attempt is rejected as invalid history, not silently ignored.
    third = mod._attempt(
        3,
        {
            "result": "FAIL",
            "build_error": "unit test failed again",
        },
    )
    try:
        mod.evaluate_loop(
            work_item, triage, investigation, [first, second, third]
        )
    except mod.RepairLoopError as exc:
        assert "exceeds repair budget" in str(exc)
    else:
        raise AssertionError("third repair attempt unexpectedly accepted")

    # PASS without exact repair identity is never enough.
    passed = mod._attempt(1, {"result": "PASS", "runtime_result": "PASS"})
    missing = copy.deepcopy(passed)
    missing["applab_verification"].pop("repair_identity_sha256")
    stopped = mod.evaluate_loop(
        work_item, triage, investigation, [missing]
    )
    assert stopped["state"] == "STOPPED"
    assert stopped["reason_code"] == "IDENTITY_NOT_PROVEN"

    # A non-localized deterministic failure re-enters investigation, not repair.
    deeper = mod.evaluate_loop(
        work_item,
        triage,
        {"state": "INSUFFICIENT_EVIDENCE", "edit_recommendation": "DENY_AUTONOMOUS_EDIT"},
        [],
    )
    assert deeper["state"] == "NEEDS_INVESTIGATION"
    assert deeper["next_action"] == "INVESTIGATE"

    mod.self_test()
    print("AppLab v6.0D verify-repair loop contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
