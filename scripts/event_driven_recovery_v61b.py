#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any

import agent_work_graph_v60a as workgraph
import closed_loop_pilot_v61a as pilot61a
import controlled_event_v54g as pilot54g
import durable_brain_v54a as brain
import durable_store_v54b as storemod

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = (
    ROOT / "integration" / "orchestration" / "contracts" / "event-driven-recovery-v1.json"
)
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")

WAIT_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent_external_waits (
    wait_id TEXT PRIMARY KEY,
    work_item_id TEXT NOT NULL REFERENCES agent_work_items(work_item_id),
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    repository TEXT NOT NULL,
    target_sha TEXT NOT NULL,
    required_gates_json TEXT NOT NULL,
    gate_states_json TEXT NOT NULL,
    state TEXT NOT NULL,
    fallback_count INTEGER NOT NULL,
    max_fallback_polls INTEGER NOT NULL,
    fallback_interval_seconds INTEGER NOT NULL,
    next_fallback_at REAL NOT NULL,
    superseded_by_sha TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(work_item_id, target_sha)
);

CREATE TABLE IF NOT EXISTS agent_external_observations (
    event_id TEXT PRIMARY KEY,
    wait_id TEXT NOT NULL REFERENCES agent_external_waits(wait_id),
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS agent_external_observations_no_update
BEFORE UPDATE ON agent_external_observations
BEGIN SELECT RAISE(ABORT, 'external observations append-only'); END;

CREATE TRIGGER IF NOT EXISTS agent_external_observations_no_delete
BEFORE DELETE ON agent_external_observations
BEGIN SELECT RAISE(ABORT, 'external observations append-only'); END;

CREATE TRIGGER IF NOT EXISTS agent_external_wait_identity_no_update
BEFORE UPDATE OF wait_id,work_item_id,operation_id,repository,target_sha,
                 required_gates_json,max_fallback_polls,fallback_interval_seconds,created_at
ON agent_external_waits
BEGIN SELECT RAISE(ABORT, 'external wait immutable identity'); END;

CREATE TRIGGER IF NOT EXISTS agent_external_waits_no_delete
BEFORE DELETE ON agent_external_waits
BEGIN SELECT RAISE(ABORT, 'external waits cannot be deleted'); END;
"""


class RecoveryError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RecoveryError("unsupported event-driven recovery contract version")
    if payload.get("contract_name") != "APPLAB_EVENT_DRIVEN_DURABLE_RECOVERY":
        raise RecoveryError("unexpected event-driven recovery contract")
    if payload.get("authority") != "ORCHESTRATION_ONLY":
        raise RecoveryError("event-driven recovery authority drift")
    fallback = payload.get("fallback_polling") or {}
    if fallback.get("primary") is not False:
        raise RecoveryError("fixed polling must not be primary")
    if int(fallback.get("interval_seconds", 0)) < 1:
        raise RecoveryError("fallback interval must be positive")
    if int(fallback.get("max_polls", -1)) < 0:
        raise RecoveryError("fallback poll budget must be non-negative")
    if fallback.get("scope") != "PENDING_GATES_ONLY":
        raise RecoveryError("fallback scope must remain pending gates only")
    return payload


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA40_RE.fullmatch(text):
        raise RecoveryError(f"{label} must be a lowercase 40-hex SHA")
    return text


def _id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:28]
    return f"{prefix}_{digest}"


def _canonical(value: Any) -> str:
    return brain.canonical_json(value)


def _open(db_path: Path) -> tuple[storemod.SQLiteShadowStore, workgraph.AgentWorkGraphStore]:
    durable = storemod.SQLiteShadowStore(db_path)
    graph = workgraph.AgentWorkGraphStore(durable)
    durable.db.executescript(WAIT_SCHEMA)
    durable.db.commit()
    return durable, graph


def _wait_row(durable: storemod.SQLiteShadowStore, wait_id: str) -> dict[str, Any]:
    row = durable.db.execute(
        "SELECT * FROM agent_external_waits WHERE wait_id=?",
        (wait_id,),
    ).fetchone()
    if row is None:
        raise RecoveryError("unknown external wait")
    payload = dict(row)
    payload["required_gates"] = json.loads(payload.pop("required_gates_json"))
    payload["gate_states"] = json.loads(payload.pop("gate_states_json"))
    return payload


def _pending_gates(wait: dict[str, Any]) -> list[str]:
    return [
        gate
        for gate in wait["required_gates"]
        if wait["gate_states"].get(gate) == "PENDING"
    ]


def _operation_transition(
    durable: storemod.SQLiteShadowStore,
    *,
    operation_id: str,
    from_state: str,
    to_state: str,
    reason: str,
    occurred_at: str,
    identity: str,
) -> dict[str, Any]:
    transition_id = _id("trn", operation_id, identity, from_state, to_state, reason)
    metadata = {
        "operation_id": operation_id,
        "from_state": from_state,
        "to_state": to_state,
        "reason": reason,
        "identity": identity,
    }
    payload = {
        "schema_version": 1,
        "record_type": "APPLAB_OPERATION_TRANSITION",
        "transition_id": transition_id,
        "operation_id": operation_id,
        "from_state": from_state,
        "to_state": to_state,
        "reason_code": reason,
        "actor": "v61b-event-driven-recovery",
        "occurred_at": occurred_at,
        "metadata_digest_sha256": brain.sha256_json(metadata),
    }
    return durable.transition_operation(payload)


def _work_transition(
    graph: workgraph.AgentWorkGraphStore,
    *,
    work_item_id: str,
    from_state: str,
    to_state: str,
    reason: str,
    occurred_at: str,
    identity: str,
) -> dict[str, Any]:
    return graph.transition(
        transition_id=_id("trn", work_item_id, identity, from_state, to_state, reason),
        work_item_id=work_item_id,
        from_state=from_state,
        to_state=to_state,
        reason_code=reason,
        created_at=occurred_at,
    )


def _decision(
    graph: workgraph.AgentWorkGraphStore,
    *,
    work_item_id: str,
    kind: str,
    reason: str,
    occurred_at: str,
    identity: str,
) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "record_type": "APPLAB_WORK_DECISION",
        "decision_id": _id("dec", work_item_id, identity, kind, reason),
        "work_item_id": work_item_id,
        "kind": kind,
        "reason_code": reason,
        "evidence_ref_ids": [],
        "created_at": occurred_at,
    }
    return graph.put_decision(payload)


def begin_wait(
    *,
    db_path: Path,
    work_item_id: str,
    target_sha: str,
    required_gates: list[str],
    now_ts: float,
    occurred_at: str,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    target_sha = _sha(target_sha, "target_sha")
    gates = sorted({str(g).strip() for g in required_gates if str(g).strip()})
    if not gates:
        raise RecoveryError("required_gates must be non-empty")

    durable, graph = _open(db_path)
    try:
        item = graph.get_work_item(work_item_id)
        operation = durable.get_operation(item["operation_id"])
        if item["resolved_sha"] != target_sha or operation["resolved_sha"] != target_sha:
            raise RecoveryError("wait target SHA must match immutable WorkItem and operation")
        if item["repository"] != operation["repository"]:
            raise RecoveryError("WorkItem/operation repository mismatch")

        terminal_work = set(graph.contract["work_item"]["terminal_states"])
        terminal_ops = set(durable.brain_contract["operation"]["terminal_states"])
        if item["current_state"] in terminal_work or operation["current_state"] in terminal_ops:
            return {
                "schema_version": 1,
                "record_type": "APPLAB_V61B_WAIT",
                "authority": "ORCHESTRATION_ONLY",
                "state": "STOPPED",
                "reason": "TERMINAL_IDENTITY_PRESERVED",
                "dispatch": False,
                "poll": False,
                "work_item_state": item["current_state"],
                "operation_state": operation["current_state"],
            }

        wait_id = _id("wai", work_item_id, target_sha, *gates)
        existing = durable.db.execute(
            "SELECT wait_id FROM agent_external_waits WHERE wait_id=?",
            (wait_id,),
        ).fetchone()
        if existing:
            wait = _wait_row(durable, wait_id)
            return {
                "schema_version": 1,
                "record_type": "APPLAB_V61B_WAIT",
                "authority": "ORCHESTRATION_ONLY",
                "status": "REPLAY",
                "wait_id": wait_id,
                "state": wait["state"],
                "target_sha": wait["target_sha"],
                "pending_gates": _pending_gates(wait),
                "fallback_count": wait["fallback_count"],
                "dispatch": False,
                "poll": False,
            }

        allowed_work_sources = {"PLANNED", "EXECUTING", "VERIFYING"}
        if item["current_state"] not in allowed_work_sources:
            raise RecoveryError(
                "begin_wait requires PLANNED, EXECUTING or VERIFYING WorkItem"
            )
        if operation["current_state"] != "RUNNING":
            raise RecoveryError("begin_wait requires RUNNING durable operation")

        fallback = contract["fallback_polling"]
        gate_states = {gate: "PENDING" for gate in gates}
        next_fallback = float(now_ts) + int(fallback["interval_seconds"])
        with durable.db:
            durable.db.execute(
                """
                INSERT INTO agent_external_waits(
                    wait_id,work_item_id,operation_id,repository,target_sha,
                    required_gates_json,gate_states_json,state,fallback_count,
                    max_fallback_polls,fallback_interval_seconds,next_fallback_at,
                    superseded_by_sha,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    wait_id,
                    work_item_id,
                    operation["operation_id"],
                    item["repository"],
                    target_sha,
                    _canonical(gates),
                    _canonical(gate_states),
                    "WAITING",
                    0,
                    int(fallback["max_polls"]),
                    int(fallback["interval_seconds"]),
                    next_fallback,
                    "",
                    occurred_at,
                    occurred_at,
                ),
            )

        _decision(
            graph,
            work_item_id=work_item_id,
            kind="WAIT_EXTERNAL",
            reason="V61B_EXTERNAL_GATES_PENDING",
            occurred_at=occurred_at,
            identity=wait_id,
        )
        _work_transition(
            graph,
            work_item_id=work_item_id,
            from_state=item["current_state"],
            to_state="WAITING_EXTERNAL",
            reason="V61B_EXTERNAL_GATES_PENDING",
            occurred_at=occurred_at,
            identity=wait_id,
        )
        _operation_transition(
            durable,
            operation_id=operation["operation_id"],
            from_state="RUNNING",
            to_state="WAITING_EXTERNAL",
            reason="V61B_EXTERNAL_GATES_PENDING",
            occurred_at=occurred_at,
            identity=wait_id,
        )
        return {
            "schema_version": 1,
            "record_type": "APPLAB_V61B_WAIT",
            "authority": "ORCHESTRATION_ONLY",
            "status": "INSERTED",
            "wait_id": wait_id,
            "state": "WAITING",
            "target_sha": target_sha,
            "required_gates": gates,
            "pending_gates": gates,
            "fallback_count": 0,
            "next_fallback_at": next_fallback,
            "dispatch": False,
            "poll": False,
            "primary_progression": "EVENT_DRIVEN",
        }
    finally:
        durable.close()


def _normalize_gate(
    *,
    status: str,
    conclusion: str | None,
    contract: dict[str, Any],
) -> str:
    status = str(status or "").strip().lower()
    conclusion_text = str(conclusion or "").strip().lower()
    if status in set(contract["pending_statuses"]):
        return "PENDING"
    if status != "completed":
        raise RecoveryError(f"unsupported external gate status: {status}")
    if not conclusion_text:
        raise RecoveryError("completed gate requires conclusion")
    if conclusion_text in set(contract["green_terminal_conclusions"]):
        return "SUCCESS"
    return "FAILURE"


def observe_event(
    *,
    db_path: Path,
    wait_id: str,
    event_id: str,
    target_sha: str,
    gate: str,
    status: str,
    conclusion: str | None,
    occurred_at: str,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    target_sha = _sha(target_sha, "target_sha")
    event_id = brain._require_id(event_id, "event_id")
    gate = brain._require_non_empty_string(gate, "gate")

    durable, graph = _open(db_path)
    try:
        wait = _wait_row(durable, wait_id)
        if wait["target_sha"] != target_sha:
            raise RecoveryError("event target SHA does not match durable wait")
        if gate not in wait["required_gates"]:
            raise RecoveryError("event gate is outside required gate set")

        observation = {
            "schema_version": 1,
            "record_type": "APPLAB_V61B_GATE_OBSERVATION",
            "event_id": event_id,
            "wait_id": wait_id,
            "target_sha": target_sha,
            "gate": gate,
            "status": str(status).lower(),
            "conclusion": str(conclusion or "").lower(),
            "occurred_at": occurred_at,
        }
        digest = brain.sha256_json(observation)
        existing = durable.db.execute(
            "SELECT payload_sha256 FROM agent_external_observations WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if existing:
            if existing["payload_sha256"] != digest:
                raise RecoveryError("event_id replay conflicts with immutable observation")
            current = _wait_row(durable, wait_id)
            return {
                "schema_version": 1,
                "record_type": "APPLAB_V61B_EVENT_RESULT",
                "status": "REPLAY",
                "wait_id": wait_id,
                "state": current["state"],
                "pending_gates": _pending_gates(current),
                "poll": False,
                "dispatch": False,
            }

        if wait["state"] != "WAITING":
            return {
                "schema_version": 1,
                "record_type": "APPLAB_V61B_EVENT_RESULT",
                "status": "TERMINAL_WAIT_PRESERVED",
                "wait_id": wait_id,
                "state": wait["state"],
                "pending_gates": _pending_gates(wait),
                "poll": False,
                "dispatch": False,
            }

        item = graph.get_work_item(wait["work_item_id"])
        operation = durable.get_operation(wait["operation_id"])
        if (
            item["current_state"] in set(graph.contract["work_item"]["terminal_states"])
            or operation["current_state"]
            in set(durable.brain_contract["operation"]["terminal_states"])
        ):
            with durable.db:
                durable.db.execute(
                    "UPDATE agent_external_waits SET state='STOPPED',updated_at=? WHERE wait_id=?",
                    (occurred_at, wait_id),
                )
            return {
                "schema_version": 1,
                "record_type": "APPLAB_V61B_EVENT_RESULT",
                "status": "TERMINAL_IDENTITY_PRESERVED",
                "wait_id": wait_id,
                "state": "STOPPED",
                "poll": False,
                "dispatch": False,
            }

        normalized = _normalize_gate(
            status=status,
            conclusion=conclusion,
            contract=contract,
        )
        gate_states = dict(wait["gate_states"])
        gate_states[gate] = normalized
        pending = [name for name in wait["required_gates"] if gate_states[name] == "PENDING"]
        ready = not pending
        next_state = "READY_FOR_EVALUATION" if ready else "WAITING"

        with durable.db:
            durable.db.execute(
                """
                INSERT INTO agent_external_observations(
                    event_id,wait_id,payload_sha256,payload_json,created_at
                ) VALUES (?,?,?,?,?)
                """,
                (event_id, wait_id, digest, _canonical(observation), occurred_at),
            )
            durable.db.execute(
                """
                UPDATE agent_external_waits
                SET gate_states_json=?,state=?,updated_at=?
                WHERE wait_id=?
                """,
                (_canonical(gate_states), next_state, occurred_at, wait_id),
            )

        if ready:
            current_item = graph.get_work_item(wait["work_item_id"])
            current_operation = durable.get_operation(wait["operation_id"])
            if current_item["current_state"] == "WAITING_EXTERNAL":
                _work_transition(
                    graph,
                    work_item_id=wait["work_item_id"],
                    from_state="WAITING_EXTERNAL",
                    to_state="VERIFYING",
                    reason="V61B_REQUIRED_GATES_TERMINAL",
                    occurred_at=occurred_at,
                    identity=wait_id,
                )
            if current_operation["current_state"] == "WAITING_EXTERNAL":
                _operation_transition(
                    durable,
                    operation_id=wait["operation_id"],
                    from_state="WAITING_EXTERNAL",
                    to_state="RUNNING",
                    reason="V61B_REQUIRED_GATES_TERMINAL",
                    occurred_at=occurred_at,
                    identity=wait_id,
                )

        all_green = ready and all(value == "SUCCESS" for value in gate_states.values())
        return {
            "schema_version": 1,
            "record_type": "APPLAB_V61B_EVENT_RESULT",
            "authority": "ORCHESTRATION_ONLY",
            "status": "RECORDED",
            "wait_id": wait_id,
            "state": next_state,
            "target_sha": target_sha,
            "gate": gate,
            "gate_state": normalized,
            "pending_gates": pending,
            "all_required_gates_terminal": ready,
            "observed_all_green": all_green,
            "verification_authority": "UNCHANGED",
            "poll": False,
            "dispatch": False,
        }
    finally:
        durable.close()


def reconcile_wait(
    *,
    db_path: Path,
    wait_id: str,
    now_ts: float,
    actions_available: bool,
    occurred_at: str,
) -> dict[str, Any]:
    durable, _graph = _open(db_path)
    try:
        wait = _wait_row(durable, wait_id)
        pending = _pending_gates(wait)
        if wait["state"] != "WAITING":
            return {
                "schema_version": 1,
                "record_type": "APPLAB_V61B_RECONCILIATION",
                "authority": "ORCHESTRATION_ONLY",
                "wait_id": wait_id,
                "action": "NOOP_TERMINAL_WAIT",
                "state": wait["state"],
                "pending_gates": pending,
                "poll": False,
                "dispatch": False,
            }
        if not actions_available:
            return {
                "schema_version": 1,
                "record_type": "APPLAB_V61B_RECONCILIATION",
                "authority": "ORCHESTRATION_ONLY",
                "wait_id": wait_id,
                "action": "HOLD_DURABLE_WAIT",
                "reason": "ACTIONS_OUTAGE",
                "state": "WAITING",
                "pending_gates": pending,
                "poll": False,
                "dispatch": False,
            }
        if float(now_ts) < float(wait["next_fallback_at"]):
            return {
                "schema_version": 1,
                "record_type": "APPLAB_V61B_RECONCILIATION",
                "authority": "ORCHESTRATION_ONLY",
                "wait_id": wait_id,
                "action": "WAIT_EVENT",
                "reason": "EVENT_WINDOW_ACTIVE",
                "state": "WAITING",
                "pending_gates": pending,
                "poll": False,
                "dispatch": False,
            }
        if int(wait["fallback_count"]) >= int(wait["max_fallback_polls"]):
            return {
                "schema_version": 1,
                "record_type": "APPLAB_V61B_RECONCILIATION",
                "authority": "ORCHESTRATION_ONLY",
                "wait_id": wait_id,
                "action": "FALLBACK_EXHAUSTED_HOLD",
                "reason": "WATCHDOG_REQUIRED",
                "state": "WAITING",
                "pending_gates": pending,
                "poll": False,
                "dispatch": False,
            }

        count = int(wait["fallback_count"]) + 1
        next_fallback = float(now_ts) + int(wait["fallback_interval_seconds"])
        with durable.db:
            durable.db.execute(
                """
                UPDATE agent_external_waits
                SET fallback_count=?,next_fallback_at=?,updated_at=?
                WHERE wait_id=?
                """,
                (count, next_fallback, occurred_at, wait_id),
            )
        return {
            "schema_version": 1,
            "record_type": "APPLAB_V61B_RECONCILIATION",
            "authority": "ORCHESTRATION_ONLY",
            "wait_id": wait_id,
            "action": "POLL_PENDING_GATES",
            "reason": "BOUNDED_EVENT_LOSS_RECOVERY",
            "state": "WAITING",
            "target_sha": wait["target_sha"],
            "pending_gates": pending,
            "poll": True,
            "dispatch": False,
            "fallback_count": count,
            "max_fallback_polls": wait["max_fallback_polls"],
            "next_fallback_at": next_fallback,
        }
    finally:
        durable.close()


def supersede_wait(
    *,
    db_path: Path,
    wait_id: str,
    new_target_sha: str,
    ancestry_proven: bool,
    occurred_at: str,
) -> dict[str, Any]:
    new_target_sha = _sha(new_target_sha, "new_target_sha")
    if not ancestry_proven:
        raise RecoveryError("superseding SHA requires explicit ancestry proof")

    durable, graph = _open(db_path)
    try:
        wait = _wait_row(durable, wait_id)
        if new_target_sha == wait["target_sha"]:
            raise RecoveryError("superseding SHA must differ from immutable target")
        if wait["state"] != "WAITING":
            return {
                "schema_version": 1,
                "record_type": "APPLAB_V61B_SUPERSESSION",
                "wait_id": wait_id,
                "state": wait["state"],
                "action": "NOOP_TERMINAL_WAIT",
                "dispatch": False,
            }

        item = graph.get_work_item(wait["work_item_id"])
        operation = durable.get_operation(wait["operation_id"])
        terminal_work = set(graph.contract["work_item"]["terminal_states"])
        terminal_ops = set(durable.brain_contract["operation"]["terminal_states"])
        if item["current_state"] in terminal_work or operation["current_state"] in terminal_ops:
            return {
                "schema_version": 1,
                "record_type": "APPLAB_V61B_SUPERSESSION",
                "wait_id": wait_id,
                "state": wait["state"],
                "action": "PRESERVE_TERMINAL_IDENTITY",
                "dispatch": False,
            }

        with durable.db:
            durable.db.execute(
                """
                UPDATE agent_external_waits
                SET state='SUPERSEDED',superseded_by_sha=?,updated_at=?
                WHERE wait_id=?
                """,
                (new_target_sha, occurred_at, wait_id),
            )

        if item["current_state"] == "WAITING_EXTERNAL":
            _work_transition(
                graph,
                work_item_id=wait["work_item_id"],
                from_state="WAITING_EXTERNAL",
                to_state="STOPPED",
                reason="V61B_SUPERSEDED_TARGET_SHA",
                occurred_at=occurred_at,
                identity=wait_id + new_target_sha,
            )
        if operation["current_state"] == "WAITING_EXTERNAL":
            # The durable brain v1 does not permit WAITING_EXTERNAL -> SUPERSEDED.
            # CANCELED is therefore the explicit terminal projection for a running
            # operation whose immutable target has been superseded.
            _operation_transition(
                durable,
                operation_id=wait["operation_id"],
                from_state="WAITING_EXTERNAL",
                to_state="CANCELED",
                reason="V61B_SUPERSEDED_TARGET_SHA",
                occurred_at=occurred_at,
                identity=wait_id + new_target_sha,
            )
        return {
            "schema_version": 1,
            "record_type": "APPLAB_V61B_SUPERSESSION",
            "authority": "ORCHESTRATION_ONLY",
            "wait_id": wait_id,
            "state": "SUPERSEDED",
            "old_target_sha": wait["target_sha"],
            "new_target_sha": new_target_sha,
            "work_item_terminal_state": graph.get_work_item(wait["work_item_id"])["current_state"],
            "operation_terminal_state": durable.get_operation(wait["operation_id"])["current_state"],
            "new_operation_required": True,
            "silent_retarget": False,
            "dispatch": False,
        }
    finally:
        durable.close()


def _prepare_fixture(db_path: Path, sha: str, delivery: str) -> tuple[str, str]:
    admitted = pilot61a.admit_closed_loop(
        db_path=db_path,
        repository="riccardopinato/AppLab",
        source_ref="refs/heads/main",
        resolved_sha=sha,
        applab_sha=sha,
        delivery_id=delivery,
        risk="NORMAL",
        now_ts=1000.0,
    )
    work_item_id = str(admitted["work_item_id"])
    operation_id = str(admitted["operation_id"])
    durable, graph = _open(db_path)
    try:
        item = graph.get_work_item(work_item_id)
        _work_transition(
            graph,
            work_item_id=work_item_id,
            from_state=item["current_state"],
            to_state="PLANNED",
            reason="V61B_SELFTEST_PLANNED",
            occurred_at="2026-10-27T14:00:00Z",
            identity=delivery,
        )
        _work_transition(
            graph,
            work_item_id=work_item_id,
            from_state="PLANNED",
            to_state="VERIFYING",
            reason="V61B_SELFTEST_VERIFYING",
            occurred_at="2026-10-27T14:00:01Z",
            identity=delivery,
        )

        current = durable.get_operation(operation_id)["current_state"]
        for index, (expected, next_state) in enumerate(
            (("QUEUED", "PLANNING"), ("PLANNING", "READY"), ("READY", "RUNNING")),
            start=1,
        ):
            if current == expected:
                _operation_transition(
                    durable,
                    operation_id=operation_id,
                    from_state=expected,
                    to_state=next_state,
                    reason=f"V61B_SELFTEST_{next_state}",
                    occurred_at=f"2026-10-27T14:00:0{index + 1}Z",
                    identity=delivery,
                )
                current = next_state
        if current != "RUNNING":
            raise RecoveryError("self-test operation did not reach RUNNING")
    finally:
        durable.close()
    return work_item_id, operation_id


def self_test() -> dict[str, Any]:
    contract = load_contract()
    sha = "a" * 40
    gates = ["AppLab CI", "AppLab CodeQL", "Emulator Self Test"]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db_path = root / "v61b.sqlite3"
        work_item_id, operation_id = _prepare_fixture(db_path, sha, "v61b-main")
        wait = begin_wait(
            db_path=db_path,
            work_item_id=work_item_id,
            target_sha=sha,
            required_gates=gates,
            now_ts=1000.0,
            occurred_at="2026-10-27T14:01:00Z",
            contract=contract,
        )
        assert wait["state"] == "WAITING"
        assert wait["primary_progression"] == "EVENT_DRIVEN"

        early = reconcile_wait(
            db_path=db_path,
            wait_id=wait["wait_id"],
            now_ts=1050.0,
            actions_available=True,
            occurred_at="2026-10-27T14:01:50Z",
        )
        assert early["action"] == "WAIT_EVENT"
        assert early["poll"] is False

        first = observe_event(
            db_path=db_path,
            wait_id=wait["wait_id"],
            event_id="evt_v61b_ci_green",
            target_sha=sha,
            gate="AppLab CI",
            status="completed",
            conclusion="success",
            occurred_at="2026-10-27T14:02:00Z",
            contract=contract,
        )
        assert first["gate_state"] == "SUCCESS"
        assert first["pending_gates"] == ["AppLab CodeQL", "Emulator Self Test"]

        replay = observe_event(
            db_path=db_path,
            wait_id=wait["wait_id"],
            event_id="evt_v61b_ci_green",
            target_sha=sha,
            gate="AppLab CI",
            status="completed",
            conclusion="success",
            occurred_at="2026-10-27T14:02:00Z",
            contract=contract,
        )
        assert replay["status"] == "REPLAY"

        outage = reconcile_wait(
            db_path=db_path,
            wait_id=wait["wait_id"],
            now_ts=1121.0,
            actions_available=False,
            occurred_at="2026-10-27T14:02:01Z",
        )
        assert outage["action"] == "HOLD_DURABLE_WAIT"
        assert outage["poll"] is False

        fallback = reconcile_wait(
            db_path=db_path,
            wait_id=wait["wait_id"],
            now_ts=1121.0,
            actions_available=True,
            occurred_at="2026-10-27T14:02:02Z",
        )
        assert fallback["action"] == "POLL_PENDING_GATES"
        assert fallback["pending_gates"] == ["AppLab CodeQL", "Emulator Self Test"]
        assert fallback["fallback_count"] == 1

        # Re-open through a fresh call to prove restart-safe persisted projection.
        restart = reconcile_wait(
            db_path=db_path,
            wait_id=wait["wait_id"],
            now_ts=1122.0,
            actions_available=True,
            occurred_at="2026-10-27T14:02:03Z",
        )
        assert restart["action"] == "WAIT_EVENT"
        assert restart["pending_gates"] == ["AppLab CodeQL", "Emulator Self Test"]

        observe_event(
            db_path=db_path,
            wait_id=wait["wait_id"],
            event_id="evt_v61b_codeql_green",
            target_sha=sha,
            gate="AppLab CodeQL",
            status="completed",
            conclusion="success",
            occurred_at="2026-10-27T14:03:00Z",
            contract=contract,
        )
        final = observe_event(
            db_path=db_path,
            wait_id=wait["wait_id"],
            event_id="evt_v61b_emulator_green",
            target_sha=sha,
            gate="Emulator Self Test",
            status="completed",
            conclusion="success",
            occurred_at="2026-10-27T14:03:01Z",
            contract=contract,
        )
        assert final["state"] == "READY_FOR_EVALUATION"
        assert final["observed_all_green"] is True

        durable, graph = _open(db_path)
        try:
            assert graph.get_work_item(work_item_id)["current_state"] == "VERIFYING"
            assert durable.get_operation(operation_id)["current_state"] == "RUNNING"
        finally:
            durable.close()

        sup_db = root / "v61b-supersede.sqlite3"
        sup_work, _sup_op = _prepare_fixture(sup_db, sha, "v61b-sup")
        sup_wait = begin_wait(
            db_path=sup_db,
            work_item_id=sup_work,
            target_sha=sha,
            required_gates=gates,
            now_ts=2000.0,
            occurred_at="2026-10-27T15:00:00Z",
            contract=contract,
        )
        superseded = supersede_wait(
            db_path=sup_db,
            wait_id=sup_wait["wait_id"],
            new_target_sha="b" * 40,
            ancestry_proven=True,
            occurred_at="2026-10-27T15:01:00Z",
        )
        assert superseded["state"] == "SUPERSEDED"
        assert superseded["work_item_terminal_state"] == "STOPPED"
        assert superseded["operation_terminal_state"] == "CANCELED"
        assert superseded["silent_retarget"] is False

        budget_db = root / "v61b-budget.sqlite3"
        budget_work, _ = _prepare_fixture(budget_db, sha, "v61b-budget")
        budget_wait = begin_wait(
            db_path=budget_db,
            work_item_id=budget_work,
            target_sha=sha,
            required_gates=["AppLab CI"],
            now_ts=3000.0,
            occurred_at="2026-10-27T16:00:00Z",
            contract=contract,
        )
        current = 3000.0 + int(contract["fallback_polling"]["interval_seconds"])
        for index in range(int(contract["fallback_polling"]["max_polls"])):
            row = reconcile_wait(
                db_path=budget_db,
                wait_id=budget_wait["wait_id"],
                now_ts=current,
                actions_available=True,
                occurred_at=f"2026-10-27T16:0{index}:00Z",
            )
            assert row["poll"] is True
            current = float(row["next_fallback_at"])
        exhausted = reconcile_wait(
            db_path=budget_db,
            wait_id=budget_wait["wait_id"],
            now_ts=current,
            actions_available=True,
            occurred_at="2026-10-27T16:10:00Z",
        )
        assert exhausted["action"] == "FALLBACK_EXHAUSTED_HOLD"
        assert exhausted["poll"] is False

    return {
        "schema_version": 1,
        "record_type": "APPLAB_V61B_EVENT_DRIVEN_RECOVERY_PROOF",
        "status": "PASS",
        "primary_progression": "EVENT_DRIVEN",
        "durable_wait_recovery": True,
        "duplicate_event_idempotence": True,
        "actions_outage_holds_pending": True,
        "coordinator_restart_recovers_wait": True,
        "fallback_polling_primary": False,
        "fallback_polling_bounded": True,
        "fallback_scope": "PENDING_GATES_ONLY",
        "superseding_sha_explicit": True,
        "silent_retarget": False,
        "terminal_redispatch": False,
        "github_actions_fallback": True,
        "verification_authority": "UNCHANGED",
        "certification_authority": "UNCHANGED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v6.1B durable event-driven recovery")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2, sort_keys=True))
        return 0
    parser.error("v6.1B is a library control-plane primitive; use --self-test")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
