#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import controlled_closed_loop_expansion_v61d as expansion
import durable_brain_v54a as brain

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = (
    ROOT
    / "integration"
    / "orchestration"
    / "contracts"
    / "production-slo-operations-evidence-v1.json"
)
DEFAULT_POLICY = ROOT / "integration" / "orchestration" / "v61d-expansion.json"

OUTCOMES = {"SUCCESS", "FAILURE", "STOPPED"}
LATENCY_FIELDS = (
    "commit_to_green_seconds",
    "queue_wait_seconds",
    "orchestration_overhead_seconds",
    "github_execution_seconds",
    "repair_runtime_seconds",
)
PROMOTION_FIELDS = (
    "successful_closed_loop_operations",
    "failed_closed_loop_operations",
    "authority_breaches",
    "false_repairs",
    "recovery_failures",
    "exact_identity_violations",
)


class OperationsEvidenceError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise OperationsEvidenceError("unsupported v6.1E contract version")
    if payload.get("contract_name") != "APPLAB_PRODUCTION_SLO_OPERATIONS_EVIDENCE":
        raise OperationsEvidenceError("unexpected v6.1E contract")
    if payload.get("authority") != "READ_ONLY_OPERATIONS_EVIDENCE":
        raise OperationsEvidenceError("v6.1E authority drift")
    if payload.get("record_type") != "APPLAB_V61E_OPERATION_EVIDENCE":
        raise OperationsEvidenceError("unexpected v6.1E operation record type")
    if int(payload.get("minimum_latency_samples_per_repository", 0)) < 1:
        raise OperationsEvidenceError("minimum latency sample count must be positive")
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OperationsEvidenceError(
                f"invalid JSONL evidence at line {number}"
            ) from exc
        if not isinstance(value, dict):
            raise OperationsEvidenceError(
                f"operation evidence line {number} must be an object"
            )
        rows.append(value)
    return rows


def _non_negative_number(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise OperationsEvidenceError(f"{field} must be numeric")
    number = float(value)
    if number < 0:
        raise OperationsEvidenceError(f"{field} must be non-negative")
    return number


def _non_negative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise OperationsEvidenceError(f"{field} must be a non-negative integer")
    return int(value)


def validate_record(
    record: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    if record.get("schema_version") != 1:
        raise OperationsEvidenceError("operation evidence schema_version must be 1")
    if record.get("record_type") != contract["record_type"]:
        raise OperationsEvidenceError("unexpected operation evidence record_type")

    repository = brain._require_repository(record.get("repository"))
    source_ref = brain._require_non_empty_string(record.get("source_ref"), "source_ref")
    source_sha = brain._require_sha(record.get("source_sha"), "source_sha")
    applab_sha = brain._require_sha(record.get("applab_sha"), "applab_sha")
    operation_id = brain._require_non_empty_string(
        record.get("operation_id"), "operation_id"
    )
    work_item_id = brain._require_non_empty_string(
        record.get("work_item_id"), "work_item_id"
    )
    stage = str(record.get("stage") or "")
    if stage not in expansion.STAGES:
        raise OperationsEvidenceError("operation evidence stage is not a v6.1D stage")
    outcome = str(record.get("outcome") or "").upper()
    if outcome not in OUTCOMES:
        raise OperationsEvidenceError("unsupported operation evidence outcome")

    durations = record.get("durations")
    if not isinstance(durations, dict):
        raise OperationsEvidenceError("durations must be an object")
    normalized_durations = {
        field: _non_negative_number(durations.get(field, 0), f"durations.{field}")
        for field in LATENCY_FIELDS
    }

    observations = record.get("observations")
    if not isinstance(observations, dict):
        raise OperationsEvidenceError("observations must be an object")
    normalized_observations = {
        field: _non_negative_int(observations.get(field, 0), f"observations.{field}")
        for field in (
            "event_observations",
            "reconciliation_recoveries",
            "fallback_observation_batches",
            "covered_waits",
            "external_queries",
        )
    }
    if normalized_observations["external_queries"] > normalized_observations["covered_waits"]:
        raise OperationsEvidenceError(
            "external_queries cannot exceed covered_waits in coalesced evidence"
        )

    booleans: dict[str, bool] = {}
    for field in (
        "authority_breach",
        "false_repair",
        "recovery_failure",
        "exact_identity_violation",
        "repeated_signature_stop",
    ):
        value = record.get(field, False)
        if not isinstance(value, bool):
            raise OperationsEvidenceError(f"{field} must be boolean")
        booleans[field] = value

    rollback = record.get("rollback")
    if not isinstance(rollback, dict):
        raise OperationsEvidenceError("rollback must be an object")
    attempted = rollback.get("attempted", False)
    succeeded = rollback.get("succeeded", False)
    if not isinstance(attempted, bool) or not isinstance(succeeded, bool):
        raise OperationsEvidenceError("rollback attempted/succeeded must be boolean")
    if succeeded and not attempted:
        raise OperationsEvidenceError("rollback cannot succeed without being attempted")

    if repository == contract.get("self_repository", "riccardopinato/AppLab"):
        pass
    if repository == "riccardopinato/AppLab" and source_sha != applab_sha:
        raise OperationsEvidenceError("AppLab self evidence requires source SHA == AppLab SHA")

    return {
        **record,
        "repository": repository,
        "source_ref": source_ref,
        "source_sha": source_sha,
        "applab_sha": applab_sha,
        "operation_id": operation_id,
        "work_item_id": work_item_id,
        "stage": stage,
        "outcome": outcome,
        "durations": normalized_durations,
        "observations": normalized_observations,
        "rollback": {
            "attempted": attempted,
            "succeeded": succeeded,
            "reason": str(rollback.get("reason") or ""),
        },
        **booleans,
    }


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = (len(ordered) - 1) * p
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    fraction = rank - low
    value = ordered[low] + (ordered[high] - ordered[low]) * fraction
    return round(value, 3)


def _latency_summary(
    rows: list[dict[str, Any]],
    *,
    contract: dict[str, Any],
) -> dict[str, Any]:
    minimum = int(contract["minimum_latency_samples_per_repository"])
    targets = contract["latency_alert_targets"]
    metrics: dict[str, Any] = {}
    alerts: list[str] = []
    target_map = {
        "commit_to_green_seconds": "commit_to_green_p95_seconds",
        "queue_wait_seconds": "queue_wait_p95_seconds",
        "orchestration_overhead_seconds": "orchestration_overhead_p95_seconds",
        "github_execution_seconds": "github_execution_p95_seconds",
        "repair_runtime_seconds": "repair_runtime_p95_seconds",
    }
    for field in LATENCY_FIELDS:
        values = [float(row["durations"][field]) for row in rows]
        p50 = percentile(values, 0.50)
        p95 = percentile(values, 0.95)
        target = float(targets[target_map[field]])
        status = "INSUFFICIENT_SAMPLES" if len(values) < minimum else "OK"
        if len(values) >= minimum and p95 is not None and p95 > target:
            status = "ALERT"
            alerts.append(f"{field}:P95_ABOVE_TARGET")
        metrics[field] = {
            "samples": len(values),
            "p50_seconds": p50,
            "p95_seconds": p95,
            "alert_target_p95_seconds": target,
            "status": status,
        }
    return {"metrics": metrics, "alerts": alerts}


def _repository_summary(
    repository: str,
    rows: list[dict[str, Any]],
    *,
    contract: dict[str, Any],
) -> dict[str, Any]:
    success = sum(1 for row in rows if row["outcome"] == "SUCCESS")
    failure = sum(1 for row in rows if row["outcome"] == "FAILURE")
    repeated_stops = sum(1 for row in rows if row["repeated_signature_stop"])
    authority = sum(1 for row in rows if row["authority_breach"])
    false_repairs = sum(1 for row in rows if row["false_repair"])
    recovery = sum(1 for row in rows if row["recovery_failure"])
    identity = sum(1 for row in rows if row["exact_identity_violation"])
    rollback_attempts = sum(1 for row in rows if row["rollback"]["attempted"])
    rollback_successes = sum(1 for row in rows if row["rollback"]["succeeded"])

    observation_totals = {
        field: sum(int(row["observations"][field]) for row in rows)
        for field in (
            "event_observations",
            "reconciliation_recoveries",
            "fallback_observation_batches",
            "covered_waits",
            "external_queries",
        )
    }
    progression_total = (
        observation_totals["event_observations"]
        + observation_totals["reconciliation_recoveries"]
        + observation_totals["fallback_observation_batches"]
    )
    event_primary_ratio = (
        round(observation_totals["event_observations"] / progression_total, 4)
        if progression_total
        else None
    )
    fallback_queries_per_wait = (
        round(
            observation_totals["external_queries"]
            / observation_totals["covered_waits"],
            4,
        )
        if observation_totals["covered_waits"]
        else None
    )
    coalesced_wait_savings = max(
        0,
        observation_totals["covered_waits"]
        - observation_totals["external_queries"],
    )
    latency = _latency_summary(rows, contract=contract)

    return {
        "repository": repository,
        "operation_count": len(rows),
        "successful_closed_loop_operations": success,
        "failed_closed_loop_operations": failure,
        "stopped_operations": sum(1 for row in rows if row["outcome"] == "STOPPED"),
        "repeated_signature_stops": repeated_stops,
        "authority_breaches": authority,
        "false_repairs": false_repairs,
        "recovery_failures": recovery,
        "exact_identity_violations": identity,
        "rollback": {
            "attempts": rollback_attempts,
            "successes": rollback_successes,
            "failures": rollback_attempts - rollback_successes,
        },
        "latency": latency["metrics"],
        "latency_alerts": latency["alerts"],
        "observations": {
            **observation_totals,
            "event_primary_ratio": event_primary_ratio,
            "fallback_queries_per_wait": fallback_queries_per_wait,
            "coalesced_wait_savings": coalesced_wait_savings,
        },
    }


def _rollback_decision(
    *,
    active_stage: str,
    repositories: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    stage_index = expansion.STAGES.index(active_stage)
    target_stage = expansion.STAGES[max(0, stage_index - 1)]
    blockers: list[str] = []
    per_repository_kill_switches: list[str] = []
    global_kill_switch = False

    for repository, row in sorted(repositories.items()):
        if row["failed_closed_loop_operations"]:
            blockers.append(f"{repository}:FAILED_CLOSED_LOOP_OPERATION")
            per_repository_kill_switches.append(repository)
        if row["false_repairs"]:
            blockers.append(f"{repository}:FALSE_REPAIR")
            per_repository_kill_switches.append(repository)
        if row["recovery_failures"]:
            blockers.append(f"{repository}:RECOVERY_FAILURE")
            per_repository_kill_switches.append(repository)
        if row["authority_breaches"]:
            blockers.append(f"{repository}:AUTHORITY_BREACH")
            global_kill_switch = True
        if row["exact_identity_violations"]:
            blockers.append(f"{repository}:EXACT_IDENTITY_VIOLATION")
            global_kill_switch = True

    if not blockers:
        return {
            "decision": "NO_ROLLBACK_SIGNAL",
            "current_stage": active_stage,
            "recommended_stage": active_stage,
            "blockers": [],
            "recommend_global_kill_switch": False,
            "recommend_repository_kill_switches": [],
            "policy_changed": False,
        }

    return {
        "decision": (
            "HOLD_SELF_CANARY"
            if active_stage == "SELF_CANARY"
            else "ROLLBACK_RECOMMENDED"
        ),
        "current_stage": active_stage,
        "recommended_stage": target_stage,
        "blockers": blockers,
        "recommend_global_kill_switch": global_kill_switch,
        "recommend_repository_kill_switches": sorted(set(per_repository_kill_switches)),
        "policy_changed": False,
    }


def build_report(
    records: list[dict[str, Any]],
    *,
    policy_path: Path = DEFAULT_POLICY,
    contract_path: Path = DEFAULT_CONTRACT,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    policy = expansion.load_policy(policy_path)
    active_stage = str(policy["active_stage"])
    normalized = [validate_record(record, contract=contract) for record in records]

    allowed = set(policy["stages"]["PILOT_5"])
    for row in normalized:
        if row["repository"] not in allowed:
            raise OperationsEvidenceError(
                f"operation evidence repository is outside v6.1D PILOT_5: {row['repository']}"
            )
        if row["source_ref"] not in expansion.load_contract()["allowed_source_refs"]:
            raise OperationsEvidenceError("operation evidence source_ref is not allowed")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in normalized:
        grouped.setdefault(row["repository"], []).append(row)

    repositories = {
        repository: _repository_summary(repository, rows, contract=contract)
        for repository, rows in sorted(grouped.items())
    }
    promotion_evidence = {
        repository: {
            field: int(summary[field])
            for field in PROMOTION_FIELDS
        }
        for repository, summary in repositories.items()
    }
    promotion = expansion.promotion_decision(
        policy=policy,
        evidence=promotion_evidence,
        current_stage=active_stage,
    )
    rollback = _rollback_decision(
        active_stage=active_stage,
        repositories=repositories,
    )

    latency_alerts = sorted(
        {
            f"{repository}:{alert}"
            for repository, summary in repositories.items()
            for alert in summary["latency_alerts"]
        }
    )
    repeated_stops = sum(
        int(summary["repeated_signature_stops"])
        for summary in repositories.values()
    )
    observation_totals = {
        field: sum(
            int(summary["observations"][field])
            for summary in repositories.values()
        )
        for field in (
            "event_observations",
            "reconciliation_recoveries",
            "fallback_observation_batches",
            "covered_waits",
            "external_queries",
            "coalesced_wait_savings",
        )
    }

    if not normalized:
        production_status = "NO_EVIDENCE"
    elif rollback["decision"] != "NO_ROLLBACK_SIGNAL":
        production_status = "ROLLBACK_SIGNAL"
    elif latency_alerts:
        production_status = "SLO_ALERT"
    else:
        production_status = "MONITORING"

    return {
        "schema_version": 1,
        "record_type": contract["summary_record_type"],
        "authority": contract["authority"],
        "production_status": production_status,
        "active_stage": active_stage,
        "operation_count": len(normalized),
        "repository_count": len(repositories),
        "repositories": repositories,
        "promotion_evidence": promotion_evidence,
        "promotion": promotion,
        "rollback": rollback,
        "latency_alerts": latency_alerts,
        "repeated_signature_stops": repeated_stops,
        "observation_totals": observation_totals,
        "source_of_truth": "V61_CLOSED_LOOP_OPERATION_EVIDENCE",
        "latency_authority": "OPERATIONS_ALERT_ONLY",
        "policy_change_performed": False,
        "pass_or_certified_minted": False,
        "merge_authority": "NONE",
        "release_authority": "NONE",
        "verification_authority": "UNCHANGED",
        "certification_authority": "UNCHANGED",
    }


def _fixture(
    *,
    operation_id: str,
    source_sha: str,
    outcome: str = "SUCCESS",
    false_repair: bool = False,
    authority_breach: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "APPLAB_V61E_OPERATION_EVIDENCE",
        "operation_id": operation_id,
        "work_item_id": "wrk_" + operation_id,
        "repository": "riccardopinato/AppLab",
        "source_ref": "refs/heads/main",
        "source_sha": source_sha,
        "applab_sha": source_sha,
        "stage": "SELF_CANARY",
        "outcome": outcome,
        "durations": {
            "commit_to_green_seconds": 300,
            "queue_wait_seconds": 10,
            "orchestration_overhead_seconds": 20,
            "github_execution_seconds": 240,
            "repair_runtime_seconds": 120,
        },
        "observations": {
            "event_observations": 3,
            "reconciliation_recoveries": 1,
            "fallback_observation_batches": 1,
            "covered_waits": 3,
            "external_queries": 1,
        },
        "authority_breach": authority_breach,
        "false_repair": false_repair,
        "recovery_failure": False,
        "exact_identity_violation": False,
        "repeated_signature_stop": False,
        "rollback": {
            "attempted": false_repair,
            "succeeded": false_repair,
            "reason": "fixture" if false_repair else "",
        },
    }


def self_test() -> dict[str, Any]:
    empty = build_report([])
    assert empty["production_status"] == "NO_EVIDENCE"
    assert empty["promotion"]["decision"] == "HOLD"
    assert empty["policy_change_performed"] is False

    sha = "a" * 40
    healthy = build_report(
        [
            _fixture(operation_id="op1", source_sha=sha),
            _fixture(operation_id="op2", source_sha=sha),
            _fixture(operation_id="op3", source_sha=sha),
        ]
    )
    repo = healthy["repositories"]["riccardopinato/AppLab"]
    assert healthy["production_status"] == "MONITORING"
    assert healthy["promotion"]["decision"] == "ELIGIBLE_FOR_EXPLICIT_PROMOTION"
    assert healthy["promotion"]["next_stage"] == "PILOT_3"
    assert healthy["promotion"]["policy_changed"] is False
    assert repo["latency"]["commit_to_green_seconds"]["samples"] == 3
    assert repo["latency"]["commit_to_green_seconds"]["p95_seconds"] == 300.0
    assert repo["observations"]["coalesced_wait_savings"] == 6
    assert healthy["merge_authority"] == "NONE"

    unhealthy = build_report(
        [
            _fixture(
                operation_id="bad",
                source_sha=sha,
                outcome="FAILURE",
                false_repair=True,
            )
        ]
    )
    assert unhealthy["production_status"] == "ROLLBACK_SIGNAL"
    assert unhealthy["rollback"]["decision"] == "HOLD_SELF_CANARY"
    assert unhealthy["rollback"]["policy_changed"] is False
    assert unhealthy["promotion"]["decision"] == "HOLD"
    assert unhealthy["pass_or_certified_minted"] is False
    return healthy


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AppLab v6.1E production SLO, rollback and operations evidence"
    )
    parser.add_argument("--records", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("AppLab v6.1E production operations evidence self-test PASS")
        return 0

    records = read_jsonl(Path(args.records)) if args.records else []
    report = build_report(records, policy_path=Path(args.policy))
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
