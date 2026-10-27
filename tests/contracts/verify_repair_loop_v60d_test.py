#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_repair_loop_v60d as mod  # noqa: E402


def main() -> int:
    item = mod._fixture_work_item()
    triage = {"classification": "BUILD_OR_QUALITY_FAILURE"}
    investigation = {
        "state": "LOCALIZED",
        "edit_recommendation": "ELIGIBLE_FOR_BOUNDED_REPAIR",
    }

    # Focused verify is mandatory and identity-bound.
    fix = mod._fix(1)
    focused_pending = {"attempt_number": 1, "fix_result": fix}
    pending = mod.evaluate(item, triage, investigation, [focused_pending])
    assert pending["state"] == "NEEDS_FOCUSED_VERIFY"

    wrong_focused = {
        "attempt_number": 1,
        "fix_result": fix,
        "focused_verification": {
            "result": "PASS",
            "repository": "owner/app",
            "resolved_sha": "b" * 40,
            "fix_result_identity_sha256": "sha256:" + "0" * 64,
        },
    }
    stopped = mod.evaluate(item, triage, investigation, [wrong_focused])
    assert stopped["reason_code"] == "IDENTITY_NOT_PROVEN"

    # A second different deterministic failure still exhausts the hard budget.
    first = mod._attempt(
        1,
        {"result": "FAIL", "build_error": "unit test failed expected alpha got beta"},
    )
    second = mod._attempt(
        2,
        {"result": "FAIL", "build_error": "lint failed unused import"},
    )
    exhausted = mod.evaluate(item, triage, investigation, [first, second])
    assert exhausted["reason_code"] == "BUDGET_EXHAUSTED"

    # Third repair history is invalid.
    third = mod._attempt(
        3,
        {"result": "FAIL", "build_error": "unit test failed again"},
    )
    try:
        mod.evaluate(item, triage, investigation, [first, second, third])
    except mod.LoopError as exc:
        assert "exceeds repair budget" in str(exc)
    else:
        raise AssertionError("third repair unexpectedly accepted")

    # Unknown is always terminal before mutation.
    unknown = mod.evaluate(
        item,
        {"classification": "UNKNOWN_FAILURE"},
        investigation,
        [],
    )
    assert unknown["state"] == "STOPPED"
    assert unknown["reason_code"] == "UNKNOWN_CLASSIFICATION"

    # Infrastructure classification waits instead of consuming a repair.
    infra = mod.evaluate(
        item,
        {"classification": "INFRA_ERROR"},
        investigation,
        [],
    )
    assert infra["state"] == "WAITING_EXTERNAL"

    # Canonical v6.0C result type is mandatory.
    bad = mod._attempt(1, {"result": "PASS"})
    bad["fix_result"] = copy.deepcopy(bad["fix_result"])
    bad["fix_result"]["record_type"] = "OLD_FIX_RESULT"
    try:
        mod.evaluate(item, triage, investigation, [bad])
    except mod.LoopError as exc:
        assert "canonical BOUNDED_FIX_RESULT_V60C" in str(exc)
    else:
        raise AssertionError("superseded v6.0C result unexpectedly accepted")

    mod.self_test()
    print("AppLab v6.0D canonical verify-repair contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
