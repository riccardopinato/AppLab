#!/usr/bin/env python3
"""v6.2C read-only live-canary observation from v5.4G/v6.1A/v6.2A receipts.

A verify-only success NEVER becomes a successful autonomous repair. Existing
v6.1E remains the sole operations-evidence authority for real repairs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import production_operations_evidence_v61e as operations
import self_canary_witness_v62a as witness


class LiveObservationError(ValueError):
    pass


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LiveObservationError("receipt must be a JSON object")
    return value


def build_observation(
    legacy: dict[str, Any],
    closed: dict[str, Any],
    runner_final: dict[str, Any],
    observed_admission: dict[str, Any],
    observed_final: dict[str, Any],
    *,
    run_id: int,
    run_attempt: int,
    run_sha: str,
    event_name: str,
) -> dict[str, Any]:
    if event_name not in {"push", "workflow_dispatch"}:
        raise LiveObservationError("live observation requires a real main event")
    admission = witness.admission_witness(
        legacy, closed, run_id=run_id, run_attempt=run_attempt
    )
    if observed_admission != admission:
        raise LiveObservationError("admission witness does not match source receipts")
    final = witness.finalize_witness(admission, runner_final)
    if observed_final != final:
        raise LiveObservationError("final witness does not match trusted runner final")
    if run_sha != admission["source_sha"] or run_sha != admission["applab_sha"]:
        raise LiveObservationError("GitHub event SHA and receipt SHA differ")
    if final["promotion_counted"] is not False or final["bounded_repair_verified"] is not False:
        raise LiveObservationError("verify-only evidence cannot grant repair authority")
    if final["draft_pr_verified"] is not False or final["independent_review_verified"] is not False:
        raise LiveObservationError("verify-only receipt cannot grant PR/review authority")
    if final["observation_status"] not in {
        "VERIFY_ONLY_RUNNER_SUCCEEDED", "RUNNER_FAILED_OR_BLOCKED"
    }:
        raise LiveObservationError("unsupported verification observation")

    # No independently verified causal repair receipt exists in this lane.
    # Passing a synthetic SUCCESS operation to v6.1E would be false promotion.
    v61e_report = operations.build_report([])
    studio = operations.studio_projection([v61e_report])
    latency = {
        key: {"sample_count": 0, "p50": None, "p95": None}
        for key in operations.LATENCY_FIELDS
    }
    return {
        "schema_version": 1,
        "record_type": "APPLAB_V62C_LIVE_CANARY_OBSERVATION",
        "authority": "READ_ONLY_NON_AUTHORITATIVE",
        "active_stage": "SELF_CANARY",
        "repository": admission["repository"],
        "source_ref": admission["source_ref"],
        "source_sha": admission["source_sha"],
        "applab_sha": admission["applab_sha"],
        "github_run_id": run_id,
        "github_run_attempt": run_attempt,
        "event_name": event_name,
        "operation_id": admission["operation_id"],
        "work_item_id": admission["work_item_id"],
        "verification_job_result": final["verification_job_result"],
        "observation_status": final["observation_status"],
        "receipt_sha256": {
            "legacy": _digest(legacy),
            "closed_loop": _digest(closed),
            "runner_final": _digest(runner_final),
            "admission_witness": _digest(observed_admission),
            "final_witness": _digest(observed_final),
        },
        "trusted_verify_only_observations": 1,
        "real_closed_loop_repair_receipts": 0,
        "repair_promotion_counted": False,
        "repair_success_threshold": 3,
        "latency": latency,
        "unmeasured_latency_is_zero": False,
        "unmeasured_fallback_cost_is_zero": False,
        "latency_coverage": "NOT_MEASURED_FOR_CAUSAL_REPAIR",
        "v61e_operations_report": v61e_report,
        "studio_projection": studio,
        "v61e_source_of_truth_unchanged": True,
        "recommendation": "HOLD_SELF_CANARY",
        "external_merge_authority": "UNCHANGED",
        "automatic_promotion": False,
    }


def self_test() -> None:
    sha = "a" * 40
    legacy = {
        "record_type": "APPLAB_V54G_ADMISSION", "admitted": True, "live": True,
        "dispatch": True, "repository": "riccardopinato/AppLab",
        "source_ref": "refs/heads/main", "resolved_sha": sha,
        "applab_sha": sha, "operation_id": "op-test",
        "source_delivery_id": "123:1",
    }
    closed = {
        "record_type": "APPLAB_V61A_CLOSED_LOOP_ADMISSION",
        "admitted": True, "live_requested": True, "dispatch": False,
        "repository": "riccardopinato/AppLab", "source_ref": "refs/heads/main",
        "resolved_sha": sha, "applab_sha": sha, "operation_id": "op-test",
        "work_item_id": "wrk-test", "work_item_state": "INVESTIGATING",
        "effective_mutation_authorized": True,
        "effective_draft_pr_authorized": True, "integrity": {"ok": True},
    }
    admission = witness.admission_witness(legacy, closed, run_id=123, run_attempt=1)
    for outcome, terminal in (("success", "SUCCEEDED"), ("cancelled", "FAILED")):
        runner = {
            "record_type": "APPLAB_V54G_FINAL", "operation_id": "op-test",
            "verification_job_result": outcome, "operation_terminal_state": terminal,
            "certification_authority_changed": False, "queue_integrity": {"ok": True},
        }
        final = witness.finalize_witness(admission, runner)
        kw = {
            "run_id": 123, "run_attempt": 1, "run_sha": sha, "event_name": "push",
        }
        result = build_observation(legacy, closed, runner, admission, final, **kw)
        assert result["real_closed_loop_repair_receipts"] == 0
        assert result["repair_promotion_counted"] is False
        assert result["v61e_operations_report"]["operation_count"] == 0
        assert result["studio_projection"]["available"] is False
        assert result["recommendation"] == "HOLD_SELF_CANARY"
        assert all(row["p50"] is None and row["sample_count"] == 0
                   for row in result["latency"].values())
        for edits in (
            {"run_sha": "b" * 40},
            {"event_name": "pull_request"},
        ):
            try:
                build_observation(legacy, closed, runner, admission, final, **{**kw, **edits})
            except LiveObservationError:
                pass
            else:
                raise AssertionError("untrusted GitHub event accepted")
        try:
            build_observation(legacy, closed, runner, admission,
                              {**final, "promotion_counted": True}, **kw)
        except LiveObservationError:
            pass
        else:
            raise AssertionError("forged promotion accepted")
        try:
            build_observation(legacy, closed, runner,
                              {**admission, "work_item_id": "forged"}, final, **kw)
        except LiveObservationError:
            pass
        else:
            raise AssertionError("forged work item accepted")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only verified canary projection")
    for key in ("legacy", "closed_loop", "runner_final", "admission_witness",
                "final_witness", "run_sha", "event_name", "output"):
        parser.add_argument("--" + key.replace("_", "-"), required=False)
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--run-attempt", type=int)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("AppLab v6.2C read-only live operations bridge PASS")
        return 0
    required = ("legacy", "closed_loop", "runner_final", "admission_witness",
                "final_witness", "run_sha", "event_name", "output",
                "run_id", "run_attempt")
    if any(not getattr(args, key) for key in required):
        parser.error("all receipt paths, GitHub run identity and output are required")
    report = build_observation(
        _read(Path(args.legacy)), _read(Path(args.closed_loop)),
        _read(Path(args.runner_final)), _read(Path(args.admission_witness)),
        _read(Path(args.final_witness)),
        run_id=args.run_id, run_attempt=args.run_attempt,
        run_sha=args.run_sha, event_name=args.event_name,
    )
    Path(args.output).write_text(json.dumps(report, sort_keys=True, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps({
        "status": report["observation_status"],
        "repair_promotion_counted": False,
        "recommendation": report["recommendation"],
        "source_sha": report["source_sha"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
