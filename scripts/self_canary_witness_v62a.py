#!/usr/bin/env python3
"""v6.2A: bind live GitHub canary admissions to durable v6 WorkItems.

This is intentionally *not* proof of an autonomous repair. A successful
verification job is not a successful bounded code-fix operation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHA40 = re.compile(r"^[0-9a-f]{40}$")
SELF_REPOSITORY = "riccardopinato/AppLab"


class WitnessError(ValueError):
    pass


def _read(path: str) -> dict[str, Any]:
    result = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise WitnessError("witness input must be a JSON object")
    return result


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise WitnessError(message)


def admission_witness(
    legacy: dict[str, Any],
    closed: dict[str, Any],
    *,
    run_id: int,
    run_attempt: int,
) -> dict[str, Any]:
    _require(isinstance(run_id, int) and run_id > 0, "positive real GitHub run ID required")
    _require(isinstance(run_attempt, int) and run_attempt > 0, "positive GitHub run attempt required")
    _require(legacy.get("record_type") == "APPLAB_V54G_ADMISSION", "wrong runner admission type")
    _require(closed.get("record_type") == "APPLAB_V61A_CLOSED_LOOP_ADMISSION", "wrong WorkItem admission type")
    _require(legacy.get("admitted") is True and legacy.get("live") is True
             and legacy.get("dispatch") is True, "runner must have actually dispatched")
    _require(closed.get("admitted") is True and closed.get("live_requested") is True,
             "v6.1 WorkItem must be admitted for the live event")
    _require(closed.get("dispatch") is False, "v6.1 must not create a competing dispatcher")
    _require(closed.get("repository") == legacy.get("repository") == SELF_REPOSITORY,
             "self-repository identity mismatch")
    _require(closed.get("source_ref") == legacy.get("source_ref") == "refs/heads/main",
             "self-canary must target main")
    sha = legacy.get("resolved_sha")
    _require(isinstance(sha, str) and SHA40.fullmatch(sha) is not None, "immutable SHA required")
    _require(closed.get("resolved_sha") == sha and closed.get("applab_sha") == sha
             and legacy.get("applab_sha") == sha, "immutable self source/AppLab identity mismatch")
    _require(closed.get("operation_id") == legacy.get("operation_id")
             and isinstance(legacy.get("operation_id"), str), "durable operation identity mismatch")
    _require(bool(closed.get("work_item_id")), "persisted WorkItem ID required")
    _require(closed.get("work_item_state") == "INVESTIGATING", "WorkItem investigation must be durable")
    _require(isinstance(closed.get("integrity"), dict) and
             closed["integrity"].get("ok") is True, "WorkItem integrity required")
    _require(legacy.get("source_delivery_id") == f"{run_id}:{run_attempt}",
             "GitHub run/delivery identity mismatch")
    _require(closed.get("effective_mutation_authorized") is True
             and closed.get("effective_draft_pr_authorized") is True,
             "bounded self-canary authority not admitted")

    evidence = {
        "schema_version": 1,
        "record_type": "APPLAB_V62A_SELF_CANARY_WITNESS",
        "authority": "NON_AUTHORITATIVE_OPERATIONAL_OBSERVATION",
        "repository": SELF_REPOSITORY,
        "source_ref": "refs/heads/main",
        "source_sha": sha,
        "applab_sha": sha,
        "github_run_id": run_id,
        "github_run_attempt": run_attempt,
        "operation_id": legacy["operation_id"],
        "work_item_id": closed["work_item_id"],
        "runner_dispatch_observed": True,
        "work_item_admission_observed": True,
        "verification_job_result": "NOT_VERIFIED",
        "observation_status": "LIVE_ADMISSION_OBSERVED",
        "bounded_repair_verified": False,
        "draft_pr_verified": False,
        "independent_review_verified": False,
        "promotion_counted": False,
        "promotion": "HOLD_SELF_CANARY",
    }
    evidence["source_receipt_sha256"] = hashlib.sha256(
        json.dumps({"legacy": legacy, "closed": closed},
                   sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return evidence


def finalize_witness(witness: dict[str, Any], final: dict[str, Any]) -> dict[str, Any]:
    _require(witness.get("record_type") == "APPLAB_V62A_SELF_CANARY_WITNESS",
             "invalid initial witness")
    _require(final.get("record_type") == "APPLAB_V54G_FINAL", "wrong runner final type")
    _require(final.get("operation_id") == witness.get("operation_id"),
             "runner final operation identity mismatch")
    _require(final.get("certification_authority_changed") is False,
             "runner must not change certification authority")
    _require(isinstance(final.get("queue_integrity"), dict)
             and final["queue_integrity"].get("ok") is True,
             "durable queue final integrity failure")
    outcome = final.get("verification_job_result")
    _require(outcome in {"success", "failure", "cancelled", "skipped"},
             "unexpected verification result")
    if outcome == "success":
        _require(final.get("operation_terminal_state") == "SUCCEEDED",
                 "success result conflicts with durable terminal state")
    else:
        _require(final.get("operation_terminal_state") == "FAILED",
                 "unsuccessful result conflicts with durable terminal state")
    result = dict(witness)
    result["verification_job_result"] = outcome.upper()
    result["observation_status"] = (
        "VERIFY_ONLY_RUNNER_SUCCEEDED" if outcome == "success"
        else "RUNNER_FAILED_OR_BLOCKED"
    )
    # v5.4G verifies an app/runtime, not an end-to-end autonomous repair.
    result["promotion_counted"] = False
    result["bounded_repair_verified"] = False
    result["draft_pr_verified"] = False
    result["promotion"] = "HOLD_SELF_CANARY"
    result["final_receipt_sha256"] = hashlib.sha256(
        json.dumps(final, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return result


def self_test() -> None:
    sha = "a" * 40
    legacy = {
        "record_type": "APPLAB_V54G_ADMISSION", "admitted": True, "live": True,
        "dispatch": True, "repository": SELF_REPOSITORY, "source_ref": "refs/heads/main",
        "resolved_sha": sha, "applab_sha": sha, "operation_id": "op-1",
        "source_delivery_id": "123:1",
    }
    closed = {
        "record_type": "APPLAB_V61A_CLOSED_LOOP_ADMISSION",
        "admitted": True, "live_requested": True, "dispatch": False,
        "repository": SELF_REPOSITORY, "source_ref": "refs/heads/main",
        "resolved_sha": sha, "applab_sha": sha, "operation_id": "op-1",
        "work_item_id": "wrk-1", "work_item_state": "INVESTIGATING",
        "effective_mutation_authorized": True, "effective_draft_pr_authorized": True,
        "integrity": {"ok": True},
    }
    receipt = admission_witness(legacy, closed, run_id=123, run_attempt=1)
    assert receipt["promotion_counted"] is False
    final = {
        "record_type": "APPLAB_V54G_FINAL", "operation_id": "op-1",
        "verification_job_result": "success", "operation_terminal_state": "SUCCEEDED",
        "certification_authority_changed": False, "queue_integrity": {"ok": True},
    }
    observation = finalize_witness(receipt, final)
    assert observation["observation_status"] == "VERIFY_ONLY_RUNNER_SUCCEEDED"
    assert observation["promotion_counted"] is False
    for first, second in [
        (legacy, {**closed, "applab_sha": "b" * 40}),
        ({**legacy, "source_delivery_id": "124:1"}, closed),
        (legacy, {**closed, "integrity": {"ok": False}}),
        (legacy, {**closed, "work_item_state": "CREATED"}),
        ({**legacy, "dispatch": False}, closed),
    ]:
        try:
            admission_witness(first, second, run_id=123, run_attempt=1)
        except WitnessError:
            pass
        else:
            raise AssertionError("unsafe admission accepted")
    try:
        finalize_witness(receipt, {**final, "operation_id": "other"})
    except WitnessError:
        pass
    else:
        raise AssertionError("mismatched final identity accepted")


def main() -> int:
    parser = argparse.ArgumentParser(description="v6.2A read-only live canary witness")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--admission")
    parser.add_argument("--closed-loop")
    parser.add_argument("--witness")
    parser.add_argument("--final")
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--run-attempt", type=int)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("AppLab v6.2A live canary witness self-test PASS")
        return 0
    if not args.output:
        parser.error("--output required")
    if args.final:
        if not args.witness:
            parser.error("--witness required when --final is set")
        report = finalize_witness(_read(args.witness), _read(args.final))
    else:
        if not args.admission or not args.closed_loop or not args.run_id or not args.run_attempt:
            parser.error("admission, closed-loop, run-id, and run-attempt required")
        report = admission_witness(
            _read(args.admission), _read(args.closed_loop),
            run_id=args.run_id, run_attempt=args.run_attempt,
        )
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
