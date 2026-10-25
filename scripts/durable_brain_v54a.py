#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = ROOT / "integration" / "orchestration" / "contracts" / "durable-brain-contract-v1.json"
DEFAULT_CORPUS = ROOT / "integration" / "orchestration" / "v54a-replay-corpus.json"

HEX40 = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[a-z]{2,4}_[A-Za-z0-9._:-]+$")
REPOSITORY_RE = re.compile(r"^[^/\s]+/[^/\s]+$")


class ContractError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ContractError("unsupported durable brain contract version")
    if payload.get("contract_name") != "APPLAB_DURABLE_BRAIN_CONTROL_PLANE":
        raise ContractError("unexpected durable brain contract name")
    return payload


def _require_dict(payload: Any, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ContractError(f"{label} must be an object")
    return payload


def _require_fields(payload: dict[str, Any], fields: list[str], label: str) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise ContractError(f"{label} missing required fields: {', '.join(missing)}")


def _require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value


def _require_sha(value: Any, label: str) -> str:
    text = _require_non_empty_string(value, label)
    if not HEX40.fullmatch(text):
        raise ContractError(f"{label} must be a lowercase 40-hex SHA")
    return text


def _require_id(value: Any, label: str) -> str:
    text = _require_non_empty_string(value, label)
    if not ID_RE.fullmatch(text):
        raise ContractError(f"{label} has invalid durable id syntax")
    return text


def _require_repository(value: Any) -> str:
    text = _require_non_empty_string(value, "repository")
    if not REPOSITORY_RE.fullmatch(text):
        raise ContractError("repository must be owner/name")
    return text


def event_dedupe_key(event: dict[str, Any]) -> str:
    source = _require_non_empty_string(event.get("source"), "event.source")
    event_type = _require_non_empty_string(event.get("source_event_type"), "event.source_event_type")
    repository = _require_repository(event.get("repository"))
    source_ref = _require_non_empty_string(event.get("source_ref"), "event.source_ref")
    resolved_sha = _require_sha(event.get("resolved_sha"), "event.resolved_sha")
    delivery = str(event.get("source_delivery_id") or "")
    normalized = {
        "source": source,
        "source_event_type": event_type,
        "repository": repository,
        "source_ref": source_ref,
        "resolved_sha": resolved_sha,
    }
    if event_type in {"manual", "manual_request"} and delivery:
        normalized["source_delivery_id"] = delivery
    if event_type in {"schedule", "reconciliation"}:
        window_id = _require_non_empty_string(event.get("window_id"), "event.window_id")
        normalized["window_id"] = window_id
    return sha256_json(normalized)


def operation_queue_key(operation: dict[str, Any]) -> str:
    return "|".join(
        (
            _require_repository(operation.get("repository")),
            _require_non_empty_string(operation.get("source_ref"), "operation.source_ref"),
            _require_non_empty_string(operation.get("operation_class"), "operation.operation_class"),
        )
    )


def operation_idempotency_key(operation: dict[str, Any]) -> str:
    normalized = {
        "repository": _require_repository(operation.get("repository")),
        "resolved_sha": _require_sha(operation.get("resolved_sha"), "operation.resolved_sha"),
        "source_ref": _require_non_empty_string(operation.get("source_ref"), "operation.source_ref"),
        "operation_class": _require_non_empty_string(operation.get("operation_class"), "operation.operation_class"),
        "analysis_mode": _require_non_empty_string(operation.get("analysis_mode"), "operation.analysis_mode"),
        "applab_sha": _require_sha(operation.get("applab_sha"), "operation.applab_sha"),
        "contract_fingerprint": str(operation.get("contract_fingerprint") or ""),
        "plan_digest_sha256": str(operation.get("plan_digest_sha256") or ""),
        "force_generation": int(operation.get("force_generation", 0) or 0),
    }
    return sha256_json(normalized)


def validate_event(payload: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    payload = _require_dict(payload, "event")
    spec = contract["event"]
    _require_fields(payload, spec["required"], "event")
    if payload.get("schema_version") != 1:
        raise ContractError("event schema_version must be 1")
    if payload.get("record_type") != spec["record_type"]:
        raise ContractError("event record_type mismatch")
    _require_id(payload.get("event_id"), "event_id")
    _require_id(payload.get("correlation_id"), "correlation_id")
    _require_repository(payload.get("repository"))
    _require_non_empty_string(payload.get("source"), "event.source")
    _require_non_empty_string(payload.get("source_event_type"), "event.source_event_type")
    _require_non_empty_string(payload.get("source_ref"), "event.source_ref")
    _require_sha(payload.get("resolved_sha"), "event.resolved_sha")
    if payload.get("admission") not in spec["admissions"]:
        raise ContractError("invalid event admission")
    trust = _require_dict(payload.get("trust"), "event.trust")
    _require_fields(trust, spec["trust_required"], "event.trust")
    for field in spec["trust_required"]:
        if not isinstance(trust[field], bool):
            raise ContractError(f"event.trust.{field} must be boolean")
    expected = event_dedupe_key(payload)
    if payload.get("dedupe_key") != expected:
        raise ContractError("event dedupe_key mismatch")
    if payload.get("admission") == "ADMITTED" and not all(bool(trust[field]) for field in spec["trust_required"]):
        raise ContractError("admitted event must satisfy all trust checks")
    return payload


def validate_operation(payload: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    payload = _require_dict(payload, "operation")
    spec = contract["operation"]
    _require_fields(payload, spec["required"], "operation")
    if payload.get("schema_version") != 1:
        raise ContractError("operation schema_version must be 1")
    if payload.get("record_type") != spec["record_type"]:
        raise ContractError("operation record_type mismatch")
    _require_id(payload.get("operation_id"), "operation_id")
    _require_id(payload.get("correlation_id"), "correlation_id")
    _require_repository(payload.get("repository"))
    _require_non_empty_string(payload.get("source_ref"), "operation.source_ref")
    _require_sha(payload.get("resolved_sha"), "operation.resolved_sha")
    _require_sha(payload.get("applab_sha"), "operation.applab_sha")
    if payload.get("operation_class") not in spec["operation_classes"]:
        raise ContractError("invalid operation_class")
    if payload.get("analysis_mode") not in spec["analysis_modes"]:
        raise ContractError("invalid analysis_mode")
    if payload.get("state") not in spec["states"]:
        raise ContractError("invalid operation state")
    if payload.get("authority") != spec["authority"]:
        raise ContractError("operation authority must remain ORCHESTRATION_ONLY")
    if not isinstance(payload.get("priority"), int) or not 0 <= payload["priority"] <= 1000:
        raise ContractError("operation priority must be an integer from 0 to 1000")
    if payload.get("queue_key") != operation_queue_key(payload):
        raise ContractError("operation queue_key mismatch")
    if payload.get("idempotency_key") != operation_idempotency_key(payload):
        raise ContractError("operation idempotency_key mismatch")
    if payload.get("operation_class") == "CERTIFICATION" and payload.get("analysis_mode") != "certification":
        raise ContractError("CERTIFICATION operation must use certification analysis_mode")
    if payload.get("operation_class") != "CERTIFICATION" and payload.get("analysis_mode") == "certification":
        raise ContractError("certification analysis_mode requires CERTIFICATION operation_class")
    return payload


def validate_attempt(payload: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    payload = _require_dict(payload, "attempt")
    spec = contract["attempt"]
    _require_fields(payload, spec["required"], "attempt")
    if payload.get("schema_version") != 1:
        raise ContractError("attempt schema_version must be 1")
    if payload.get("record_type") != spec["record_type"]:
        raise ContractError("attempt record_type mismatch")
    _require_id(payload.get("attempt_id"), "attempt_id")
    _require_id(payload.get("operation_id"), "operation_id")
    if not isinstance(payload.get("attempt_number"), int) or payload["attempt_number"] < 1:
        raise ContractError("attempt_number must be >= 1")
    _require_non_empty_string(payload.get("executor"), "attempt.executor")
    if payload.get("state") not in spec["states"]:
        raise ContractError("invalid attempt state")
    if payload.get("failure_class") not in spec["failure_classes"]:
        raise ContractError("invalid attempt failure_class")
    if not isinstance(payload.get("retryable"), bool):
        raise ContractError("attempt.retryable must be boolean")
    if payload.get("failure_class") in spec["never_retry_failure_classes"] and payload.get("retryable"):
        raise ContractError("deterministic app/build failure cannot be marked retryable")
    if payload.get("state") == "SUCCEEDED" and payload.get("failure_class") != "NONE":
        raise ContractError("successful attempt must use failure_class NONE")
    return payload


def validate_transition(from_state: str, to_state: str, contract: dict[str, Any]) -> bool:
    allowed = contract["operation"]["allowed_transitions"]
    if from_state not in allowed:
        raise ContractError(f"unknown from_state {from_state}")
    if to_state not in contract["operation"]["states"]:
        raise ContractError(f"unknown to_state {to_state}")
    if to_state not in allowed[from_state]:
        raise ContractError(f"illegal operation transition {from_state} -> {to_state}")
    return True


def _ancestor_of(new_sha: str, old_sha: str, parents: dict[str, list[str]]) -> bool:
    if new_sha == old_sha:
        return False
    seen: set[str] = set()
    stack = list(parents.get(new_sha, []))
    while stack:
        candidate = stack.pop()
        if candidate in seen:
            continue
        if candidate == old_sha:
            return True
        seen.add(candidate)
        stack.extend(parents.get(candidate, []))
    return False


def can_supersede(
    existing: dict[str, Any],
    incoming: dict[str, Any],
    parents: dict[str, list[str]],
    contract: dict[str, Any],
) -> tuple[bool, str]:
    validate_operation(existing, contract)
    validate_operation(incoming, contract)
    policy = contract["queue_policy"]
    if existing["queue_key"] != incoming["queue_key"]:
        return False, "DIFFERENT_QUEUE"
    if existing["operation_class"] not in policy["automatic_supersession_classes"]:
        return False, "CLASS_NOT_AUTOMATICALLY_SUPERSEDED"
    if incoming["operation_class"] != existing["operation_class"]:
        return False, "CLASS_MISMATCH"
    if existing.get("preserve_for_calibration") is True:
        return False, "PRESERVE_FOR_CALIBRATION"
    if existing.get("release_critical_evidence_started") is True:
        return False, "RELEASE_CRITICAL_EVIDENCE_STARTED"
    if not _ancestor_of(incoming["resolved_sha"], existing["resolved_sha"], parents):
        return False, "NOT_PROVEN_DESCENDANT"
    state = existing["state"]
    if state in contract["operation"]["terminal_states"]:
        return False, "EXISTING_TERMINAL"
    if state in {"QUEUED", "READY", "WAITING_RETRY"}:
        return True, "SAFE_PENDING_SUPERSESSION"
    if state == "RUNNING":
        if existing.get("protected_stage_started") is True:
            return False, "PROTECTED_STAGE_STARTED"
        if existing.get("cancel_safe") is True:
            return True, "SAFE_RUNNING_SUPERSESSION"
        return False, "RUNNING_NOT_CANCEL_SAFE"
    return False, "STATE_NOT_SUPERSEDEABLE"


def retry_decision(attempt: dict[str, Any], max_infra_attempts: int, contract: dict[str, Any]) -> dict[str, Any]:
    validate_attempt(attempt, contract)
    if max_infra_attempts < 1:
        raise ContractError("max_infra_attempts must be >= 1")
    if attempt["state"] == "SUCCEEDED":
        return {"retry": False, "reason": "ATTEMPT_SUCCEEDED"}
    if attempt["state"] != "FAILED":
        return {"retry": False, "reason": "ATTEMPT_NOT_FAILED"}
    if attempt["failure_class"] in contract["attempt"]["never_retry_failure_classes"]:
        return {"retry": False, "reason": "DETERMINISTIC_FAILURE"}
    if not attempt["retryable"]:
        return {"retry": False, "reason": "ATTEMPT_NOT_RETRYABLE"}
    if attempt["attempt_number"] >= max_infra_attempts:
        return {"retry": False, "reason": "RETRY_BUDGET_EXHAUSTED"}
    return {"retry": True, "reason": "BOUNDED_RETRY_ALLOWED"}


def simulate_queue(
    operations: list[dict[str, Any]],
    parents: dict[str, list[str]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(operations, list):
        raise ContractError("operations must be a list")
    working: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    seen_idempotency: dict[str, str] = {}
    seen_operation_ids: dict[str, str] = {}
    for index, original in enumerate(operations):
        operation = dict(original)
        validate_operation(operation, contract)
        operation_id = operation["operation_id"]
        key = operation["idempotency_key"]
        if operation_id in seen_operation_ids:
            if seen_operation_ids[operation_id] != key:
                raise ContractError("operation_id reused with conflicting immutable identity")
            actions.append({
                "action": "OPERATION_ID_REPLAY",
                "operation_id": operation_id,
            })
            continue
        seen_operation_ids[operation_id] = key
        if key in seen_idempotency:
            actions.append({
                "action": "IDEMPOTENT_REUSE",
                "operation_id": operation["operation_id"],
                "reused_operation_id": seen_idempotency[key],
            })
            continue
        seen_idempotency[key] = operation["operation_id"]
        for existing in working:
            if existing["state"] in contract["operation"]["terminal_states"]:
                continue
            allowed, reason = can_supersede(existing, operation, parents, contract)
            if allowed:
                previous_state = existing["state"]
                existing["state"] = "SUPERSEDED"
                existing["superseded_by_operation_id"] = operation["operation_id"]
                actions.append({
                    "action": "SUPERSEDE",
                    "operation_id": existing["operation_id"],
                    "by_operation_id": operation["operation_id"],
                    "previous_state": previous_state,
                    "reason": reason,
                })
            elif existing["queue_key"] == operation["queue_key"]:
                actions.append({
                    "action": "KEEP",
                    "operation_id": existing["operation_id"],
                    "incoming_operation_id": operation["operation_id"],
                    "reason": reason,
                })
        operation["arrival_order"] = int(operation.get("arrival_order", index))
        working.append(operation)

    runnable = [
        item for item in working
        if item["state"] not in contract["operation"]["terminal_states"]
    ]
    runnable.sort(key=lambda item: (-int(item["priority"]), int(item.get("arrival_order", 0)), item["operation_id"]))
    return {
        "schema_version": 1,
        "operations": working,
        "actions": actions,
        "dispatch_order": [item["operation_id"] for item in runnable],
    }


def _event_fixture(event_id: str, repository: str, source_ref: str, sha: str, delivery: str = "") -> dict[str, Any]:
    event = {
        "schema_version": 1,
        "record_type": "APPLAB_EVENT",
        "event_id": event_id,
        "correlation_id": "cor_fixture",
        "source": "github",
        "source_event_type": "push",
        "source_delivery_id": delivery,
        "repository": repository,
        "source_ref": source_ref,
        "resolved_sha": sha,
        "dedupe_key": "",
        "admission": "ADMITTED",
        "trust": {
            "signature_verified": True,
            "replay_window_valid": True,
            "source_authenticated": True,
        },
    }
    event["dedupe_key"] = event_dedupe_key(event)
    return event


def _operation_fixture(
    operation_id: str,
    repository: str,
    source_ref: str,
    sha: str,
    applab_sha: str,
    operation_class: str = "VERIFICATION",
    analysis_mode: str = "fast",
    priority: int = 200,
    state: str = "QUEUED",
    force_generation: int = 0,
    **extra: Any,
) -> dict[str, Any]:
    operation = {
        "schema_version": 1,
        "record_type": "APPLAB_OPERATION",
        "operation_id": operation_id,
        "correlation_id": "cor_fixture",
        "operation_class": operation_class,
        "analysis_mode": analysis_mode,
        "repository": repository,
        "source_ref": source_ref,
        "resolved_sha": sha,
        "applab_sha": applab_sha,
        "contract_fingerprint": "sha256:fixture-contract",
        "plan_digest_sha256": "sha256:fixture-plan",
        "force_generation": force_generation,
        "idempotency_key": "",
        "queue_key": "",
        "priority": priority,
        "state": state,
        "authority": "ORCHESTRATION_ONLY",
    }
    operation.update(extra)
    operation["queue_key"] = operation_queue_key(operation)
    operation["idempotency_key"] = operation_idempotency_key(operation)
    return operation


def _attempt_fixture(
    attempt_id: str,
    operation_id: str,
    attempt_number: int,
    state: str,
    failure_class: str,
    retryable: bool,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "APPLAB_ATTEMPT",
        "attempt_id": attempt_id,
        "operation_id": operation_id,
        "attempt_number": attempt_number,
        "executor": "simulation",
        "state": state,
        "failure_class": failure_class,
        "retryable": retryable,
    }


def run_replay_case(case: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    kind = case.get("kind")
    if kind == "transition":
        try:
            validate_transition(case["from_state"], case["to_state"], contract)
            result = {"accepted": True}
        except ContractError as exc:
            result = {"accepted": False, "error": str(exc)}
        return result

    if kind == "event_dedupe":
        events = case.get("events", [])
        keys = []
        for event in events:
            validate_event(event, contract)
            keys.append(event["dedupe_key"])
        return {"dedupe_keys": keys, "unique_count": len(set(keys))}

    if kind == "retry":
        attempt = case["attempt"]
        return retry_decision(attempt, int(case["max_infra_attempts"]), contract)

    if kind == "queue":
        simulation = simulate_queue(case.get("operations", []), case.get("parents", {}), contract)
        return {
            "states": {item["operation_id"]: item["state"] for item in simulation["operations"]},
            "superseded_by": {
                item["operation_id"]: item.get("superseded_by_operation_id")
                for item in simulation["operations"]
                if item.get("superseded_by_operation_id")
            },
            "actions": simulation["actions"],
            "dispatch_order": simulation["dispatch_order"],
        }

    if kind == "queue_reject":
        try:
            simulate_queue(case.get("operations", []), case.get("parents", {}), contract)
        except ContractError as exc:
            return {"rejected": True, "error": str(exc)}
        return {"rejected": False, "error": ""}

    raise ContractError(f"unknown replay case kind: {kind}")


def replay_corpus(path: Path = DEFAULT_CORPUS, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract()
    corpus = json.loads(path.read_text(encoding="utf-8"))
    if corpus.get("schema_version") != 1 or not isinstance(corpus.get("cases"), list):
        raise ContractError("invalid v5.4A replay corpus")
    results = []
    failures = []
    for case in corpus["cases"]:
        name = _require_non_empty_string(case.get("name"), "case.name")
        actual = run_replay_case(case, contract)
        expected = case.get("expected")
        passed = actual == expected
        results.append({"name": name, "passed": passed, "actual": actual, "expected": expected})
        if not passed:
            failures.append(name)
    stable_projection = {
        "schema_version": 1,
        "case_count": len(results),
        "passed": len(failures) == 0,
        "failures": failures,
        "results": results,
    }
    stable_projection["replay_digest_sha256"] = sha256_json(stable_projection)
    return stable_projection


def self_test() -> None:
    contract = load_contract()
    sha_a = "a" * 40
    sha_b = "b" * 40
    app_sha = "c" * 40

    event = _event_fixture("evt_fixture", "owner/app", "refs/heads/main", sha_b, "delivery-1")
    validate_event(event, contract)
    duplicate = dict(event, event_id="evt_duplicate")
    validate_event(duplicate, contract)
    assert duplicate["dedupe_key"] == event["dedupe_key"]

    operation = _operation_fixture("op_fixture", "owner/app", "main", sha_b, app_sha)
    validate_operation(operation, contract)
    assert operation["queue_key"] == "owner/app|main|VERIFICATION"

    attempt = _attempt_fixture("att_fixture", "op_fixture", 1, "FAILED", "INFRA_ERROR", True)
    validate_attempt(attempt, contract)
    assert retry_decision(attempt, 2, contract)["retry"] is True

    deterministic_failure = _attempt_fixture(
        "att_deterministic", "op_fixture", 1, "FAILED", "APP_RUNTIME_FAILURE", False
    )
    assert retry_decision(deterministic_failure, 2, contract)["retry"] is False

    validate_transition("QUEUED", "PLANNING", contract)
    try:
        validate_transition("FAILED", "SUCCEEDED", contract)
    except ContractError:
        pass
    else:
        raise AssertionError("terminal operation was allowed to mutate")

    older = _operation_fixture("op_old", "owner/app", "main", sha_a, app_sha)
    newer = _operation_fixture("op_new", "owner/app", "main", sha_b, app_sha)
    allowed, reason = can_supersede(older, newer, {sha_b: [sha_a]}, contract)
    assert allowed and reason == "SAFE_PENDING_SUPERSESSION"

    protected = _operation_fixture(
        "op_cert", "owner/app", "main", sha_a, app_sha,
        operation_class="CERTIFICATION", analysis_mode="certification", priority=500,
    )
    assert can_supersede(protected, newer, {sha_b: [sha_a]}, contract)[0] is False

    first = replay_corpus(contract=contract)
    second = replay_corpus(contract=contract)
    assert first == second
    assert first["passed"], first["failures"]
    print("AppLab v5.4A Durable Brain contracts & simulator self-test PASS")


def _load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v5.4A offline Durable Brain contract/simulator")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="command")

    for name in ("validate-event", "validate-operation", "validate-attempt"):
        child = sub.add_parser(name)
        child.add_argument("path")

    transition = sub.add_parser("validate-transition")
    transition.add_argument("from_state")
    transition.add_argument("to_state")

    replay = sub.add_parser("replay")
    replay.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    replay.add_argument("--output", default="")

    args = parser.parse_args()
    contract = load_contract(Path(args.contract))
    if args.self_test:
        self_test()
        return 0
    if args.command == "validate-event":
        validate_event(_load_json(args.path), contract)
        print("VALID")
        return 0
    if args.command == "validate-operation":
        validate_operation(_load_json(args.path), contract)
        print("VALID")
        return 0
    if args.command == "validate-attempt":
        validate_attempt(_load_json(args.path), contract)
        print("VALID")
        return 0
    if args.command == "validate-transition":
        validate_transition(args.from_state, args.to_state, contract)
        print("VALID")
        return 0
    if args.command == "replay":
        report = replay_corpus(Path(args.corpus), contract)
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            Path(args.output).write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0 if report["passed"] else 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
