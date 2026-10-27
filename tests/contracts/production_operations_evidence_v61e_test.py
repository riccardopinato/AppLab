#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import production_operations_evidence_v61e as mod  # noqa: E402


def fixture(
    *,
    operation_id: str,
    repository: str = "riccardopinato/AppLab",
    source_sha: str = "a" * 40,
    applab_sha: str | None = None,
    stage: str = "SELF_CANARY",
    outcome: str = "SUCCESS",
    commit_to_green: float = 300,
    queue_wait: float = 15,
    orchestration: float = 30,
    github_execution: float = 220,
    repair_runtime: float = 100,
    event_observations: int = 3,
    reconciliation_recoveries: int = 0,
    fallback_batches: int = 1,
    covered_waits: int = 3,
    external_queries: int = 1,
    authority_breach: bool = False,
    false_repair: bool = False,
    recovery_failure: bool = False,
    identity_violation: bool = False,
    repeated_signature_stop: bool = False,
    rollback_attempted: bool = False,
    rollback_succeeded: bool = False,
) -> dict:
    return {
        "schema_version": 1,
        "record_type": "APPLAB_V61E_OPERATION_EVIDENCE",
        "operation_id": operation_id,
        "work_item_id": f"wrk_{operation_id}",
        "repository": repository,
        "source_ref": "refs/heads/main",
        "source_sha": source_sha,
        "applab_sha": applab_sha or source_sha,
        "stage": stage,
        "outcome": outcome,
        "durations": {
            "commit_to_green_seconds": commit_to_green,
            "queue_wait_seconds": queue_wait,
            "orchestration_overhead_seconds": orchestration,
            "github_execution_seconds": github_execution,
            "repair_runtime_seconds": repair_runtime,
        },
        "observations": {
            "event_observations": event_observations,
            "reconciliation_recoveries": reconciliation_recoveries,
            "fallback_observation_batches": fallback_batches,
            "covered_waits": covered_waits,
            "external_queries": external_queries,
        },
        "authority_breach": authority_breach,
        "false_repair": false_repair,
        "recovery_failure": recovery_failure,
        "exact_identity_violation": identity_violation,
        "repeated_signature_stop": repeated_signature_stop,
        "rollback": {
            "attempted": rollback_attempted,
            "succeeded": rollback_succeeded,
            "reason": "contract-test" if rollback_attempted else "",
        },
    }


def expect_error(callback, contains: str) -> None:
    try:
        callback()
    except mod.OperationsEvidenceError as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected OperationsEvidenceError containing {contains!r}")


def main() -> int:
    contract = mod.load_contract()
    assert contract["authority"] == "READ_ONLY_OPERATIONS_EVIDENCE"
    assert contract["authority_boundaries"]["policy_change"] == "NONE"
    assert contract["authority_boundaries"]["certification"] == "UNCHANGED"

    empty = mod.build_report([])
    assert empty["production_status"] == "NO_EVIDENCE"
    assert empty["promotion"]["decision"] == "HOLD"
    assert empty["rollback"]["decision"] == "NO_ROLLBACK_SIGNAL"
    assert empty["policy_change_performed"] is False
    assert empty["pass_or_certified_minted"] is False

    healthy_records = [
        fixture(
            operation_id="op_a",
            commit_to_green=300,
            queue_wait=10,
            orchestration=25,
            github_execution=230,
            repair_runtime=120,
            event_observations=4,
            covered_waits=4,
            external_queries=1,
        ),
        fixture(
            operation_id="op_b",
            commit_to_green=360,
            queue_wait=20,
            orchestration=35,
            github_execution=260,
            repair_runtime=150,
            event_observations=3,
            reconciliation_recoveries=1,
            covered_waits=3,
            external_queries=1,
        ),
        fixture(
            operation_id="op_c",
            commit_to_green=420,
            queue_wait=30,
            orchestration=45,
            github_execution=290,
            repair_runtime=180,
            event_observations=2,
            fallback_batches=1,
            covered_waits=5,
            external_queries=1,
        ),
        fixture(
            operation_id="op_d",
            commit_to_green=390,
            queue_wait=25,
            orchestration=40,
            github_execution=270,
            repair_runtime=160,
            event_observations=4,
            covered_waits=4,
            external_queries=1,
        ),
    ]
    healthy = mod.build_report(healthy_records)
    repo = healthy["repositories"]["riccardopinato/AppLab"]

    assert repo["successful_closed_loop_operations"] == 4
    assert repo["failed_closed_loop_operations"] == 0
    assert repo["stopped_operations"] == 0
    assert repo["repeated_signature_stops"] == 0

    # Delivery replay is idempotent by immutable operation identity.
    replayed = mod.build_report([healthy_records[0], healthy_records[0], healthy_records[0]])
    replay_repo = replayed["repositories"]["riccardopinato/AppLab"]
    assert replayed["operation_count"] == 1
    assert replay_repo["successful_closed_loop_operations"] == 1
    assert replay_repo["observations"]["covered_waits"] == 4
    assert replay_repo["latency"]["commit_to_green_seconds"]["samples"] == 1
    assert replayed["promotion"]["decision"] == "HOLD"

    conflicting = json.loads(json.dumps(healthy_records[0]))
    conflicting["outcome"] = "FAILURE"
    expect_error(
        lambda: mod.build_report([healthy_records[0], conflicting]),
        "conflicting replay for immutable operation identity",
    )

    # Non-finite latency measurements fail closed before aggregation.\n    for invalid_latency in (float("nan"), float("inf"), float("-inf"), 1e309):\n        non_finite = fixture(operation_id="non-finite")\n        non_finite["durations"]["commit_to_green_seconds"] = invalid_latency\n        expect_error(\n            lambda row=non_finite: mod.build_report([row]),\n            "finite non-negative number",\n        )\n\n    # Missing latency measurements stay missing and never become zero samples.
    partial_records = [
        fixture(operation_id="partial1"),
        fixture(operation_id="partial2"),
        fixture(operation_id="partial3"),
    ]
    partial_records[0]["durations"] = {"commit_to_green_seconds": 400}
    partial_records[1]["durations"] = {}
    partial_records[2]["durations"] = {}
    partial = mod.build_report(partial_records)
    partial_latency = partial["repositories"]["riccardopinato/AppLab"]["latency"]
    assert partial_latency["commit_to_green_seconds"]["samples"] == 1
    assert partial_latency["commit_to_green_seconds"]["p50_seconds"] == 400.0
    assert partial_latency["commit_to_green_seconds"]["status"] == "INSUFFICIENT_SAMPLES"
    assert partial_latency["queue_wait_seconds"]["samples"] == 0
    assert partial_latency["queue_wait_seconds"]["p50_seconds"] is None
    assert partial_latency["queue_wait_seconds"]["status"] == "INSUFFICIENT_SAMPLES"

    # Real successes satisfy v6.1D evidence, but 6.1E never changes policy.
    assert healthy["promotion"]["decision"] == "ELIGIBLE_FOR_EXPLICIT_PROMOTION"
    assert healthy["promotion"]["next_stage"] == "PILOT_3"
    assert healthy["promotion"]["policy_changed"] is False
    assert healthy["operations_gate"]["decision"] == "ELIGIBLE_FOR_EXPLICIT_PROMOTION"
    assert healthy["policy_change_performed"] is False

    # GitHub runtime and AppLab overhead stay separately inspectable.
    assert repo["latency"]["github_execution_seconds"]["p95_seconds"] is not None
    assert repo["latency"]["orchestration_overhead_seconds"]["p95_seconds"] is not None
    assert (
        repo["latency"]["github_execution_seconds"]["p95_seconds"]
        > repo["latency"]["orchestration_overhead_seconds"]["p95_seconds"]
    )

    # Coalescing evidence is explicit: 16 waits covered by four external queries.
    assert repo["observations"]["covered_waits"] == 16
    assert repo["observations"]["external_queries"] == 4
    assert repo["observations"]["coalesced_wait_savings"] == 12
    assert repo["observations"]["fallback_queries_per_wait"] == 0.25
    assert healthy["repeated_signature_stops"] == 0

    safety_stop = mod.build_report(
        [
            fixture(operation_id="safe1"),
            fixture(operation_id="safe2"),
            fixture(operation_id="safe3"),
            fixture(
                operation_id="safe-stop",
                outcome="STOPPED",
                repeated_signature_stop=True,
            ),
        ]
    )
    assert safety_stop["promotion"]["decision"] == "ELIGIBLE_FOR_EXPLICIT_PROMOTION"
    assert safety_stop["operations_gate"]["decision"] == "HOLD"
    assert any(
        "REPEATED_FAILURE_SIGNATURE_STOP" in blocker
        for blocker in safety_stop["operations_gate"]["blockers"]
    )

    # Operational latency alerts are read-only and do not mint verification truth.
    slow = mod.build_report(
        [
            fixture(operation_id="slow1", commit_to_green=1000),
            fixture(operation_id="slow2", commit_to_green=1100),
            fixture(operation_id="slow3", commit_to_green=1200),
        ]
    )
    assert slow["production_status"] == "SLO_ALERT"
    assert any("commit_to_green_seconds" in item for item in slow["latency_alerts"])
    assert slow["pass_or_certified_minted"] is False
    assert slow["certification_authority"] == "UNCHANGED"

    false_repair = mod.build_report(
        [
            fixture(
                operation_id="bad",
                outcome="FAILURE",
                false_repair=True,
                rollback_attempted=True,
                rollback_succeeded=True,
            )
        ]
    )
    assert false_repair["production_status"] == "ROLLBACK_SIGNAL"
    assert false_repair["rollback"]["decision"] == "HOLD_SELF_CANARY"
    assert "riccardopinato/AppLab" in false_repair["rollback"][
        "recommend_repository_kill_switches"
    ]
    assert false_repair["rollback"]["policy_changed"] is False
    assert false_repair["promotion"]["decision"] == "HOLD"
    assert false_repair["operations_gate"]["decision"] == "HOLD"

    authority = mod.build_report(
        [
            fixture(
                operation_id="authority",
                outcome="FAILURE",
                authority_breach=True,
            )
        ]
    )
    assert authority["rollback"]["recommend_global_kill_switch"] is True
    assert authority["policy_change_performed"] is False

    expect_error(
        lambda: mod.build_report(
            [
                fixture(
                    operation_id="identity",
                    source_sha="a" * 40,
                    applab_sha="b" * 40,
                )
            ]
        ),
        "requires source SHA == AppLab SHA",
    )
    bad_queries = fixture(operation_id="bad-query")
    bad_queries["observations"]["covered_waits"] = 1
    bad_queries["observations"]["external_queries"] = 2
    expect_error(
        lambda: mod.build_report([bad_queries]),
        "external_queries cannot exceed covered_waits",
    )

    downstream = fixture(
        operation_id="downstream",
        repository="riccardopinato/CamperBoss",
        source_sha="c" * 40,
        applab_sha="d" * 40,
        stage="PILOT_3",
    )
    normalized = mod.validate_record(downstream)
    assert normalized["source_sha"] != normalized["applab_sha"]

    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "evidence.jsonl"
        path.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in healthy_records) + "\n",
            encoding="utf-8",
        )
        loaded = mod.read_jsonl(path)
        assert len(loaded) == len(healthy_records)

    self_report = mod.self_test()
    assert self_report["promotion"]["policy_changed"] is False
    print("AppLab v6.1E production SLO operations evidence contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
