#!/usr/bin/env python3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import self_canary_witness_v62a as mod  # noqa: E402
import live_canary_operations_v62c as bridge  # noqa: E402


def test_witness_self_test() -> None:
    mod.self_test()



def test_cancelled_witness_never_becomes_success() -> None:
    sha = "a" * 40
    legacy = {
        "record_type": "APPLAB_V54G_ADMISSION",
        "admitted": True, "live": True, "dispatch": True,
        "repository": "riccardopinato/AppLab", "source_ref": "refs/heads/main",
        "resolved_sha": sha, "applab_sha": sha, "operation_id": "op-cancelled",
        "source_delivery_id": "40660650650:1",
    }
    closed = {
        "record_type": "APPLAB_V61A_CLOSED_LOOP_ADMISSION",
        "admitted": True, "live_requested": True, "dispatch": False,
        "repository": "riccardopinato/AppLab", "source_ref": "refs/heads/main",
        "resolved_sha": sha, "applab_sha": sha, "operation_id": "op-cancelled",
        "work_item_id": "wrk-cancelled", "work_item_state": "INVESTIGATING",
        "effective_mutation_authorized": True,
        "effective_draft_pr_authorized": True,
        "integrity": {"ok": True},
    }
    receipt = mod.admission_witness(
        legacy, closed, run_id=40660650650, run_attempt=1,
    )
    final = {
        "record_type": "APPLAB_V54G_FINAL",
        "operation_id": "op-cancelled",
        "verification_job_result": "cancelled",
        "operation_terminal_state": "FAILED",
        "certification_authority_changed": False,
        "queue_integrity": {"ok": True},
    }
    observed = mod.finalize_witness(receipt, final)
    assert observed["verification_job_result"] == "CANCELLED"
    assert observed["observation_status"] == "RUNNER_FAILED_OR_BLOCKED"
    assert observed["promotion_counted"] is False
    assert observed["bounded_repair_verified"] is False
    assert observed["draft_pr_verified"] is False
    assert observed["promotion"] == "HOLD_SELF_CANARY"
    assert observed["operation_id"] == receipt["operation_id"]
    assert observed["source_sha"] == sha
    assert len(observed["source_receipt_sha256"]) == 64
    assert len(observed["final_receipt_sha256"]) == 64

    # Any conflicting terminal success must fail closed.
    for conflicting in (
        {**final, "verification_job_result": "success"},
        {**final, "operation_terminal_state": "SUCCEEDED"},
        {**final, "operation_id": "wrong-operation"},
    ):
        try:
            mod.finalize_witness(receipt, conflicting)
        except mod.WitnessError:
            pass
        else:
            raise AssertionError("contradictory cancelled evidence accepted")


def test_v62c_live_observation_fail_closed() -> None:
    bridge.self_test()


if __name__ == "__main__":
    test_witness_self_test()
    test_cancelled_witness_never_becomes_success()
    test_v62c_live_observation_fail_closed()
    print("v6.2A/v6.2B cancellation contract regression PASS")
