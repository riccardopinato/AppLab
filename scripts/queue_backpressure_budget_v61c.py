#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import agent_work_graph_v60a as workgraph
import controlled_event_v54g as event_pilot
import durable_brain_v54a as brain
import durable_queue_v54e as queue_mod
import durable_store_v54b as storemod
import event_driven_recovery_v61b as recovery

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = (
    ROOT
    / "integration"
    / "orchestration"
    / "contracts"
    / "closed-loop-queue-budgets-v1.json"
)

BUDGET_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent_repair_budgets (
    work_item_id TEXT PRIMARY KEY REFERENCES agent_work_items(work_item_id),
    operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id),
    repository TEXT NOT NULL,
    target_sha TEXT NOT NULL,
    max_files INTEGER NOT NULL,
    max_changed_lines INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    max_runtime_seconds INTEGER NOT NULL,
    max_cost_units INTEGER NOT NULL,
    max_observation_batches INTEGER NOT NULL,
    consumed_attempts INTEGER NOT NULL DEFAULT 0,
    consumed_runtime_seconds INTEGER NOT NULL DEFAULT 0,
    consumed_cost_units INTEGER NOT NULL DEFAULT 0,
    consumed_observation_batches INTEGER NOT NULL DEFAULT 0,
    last_failure_signature TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    stop_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_repair_budget_events (
    budget_event_id TEXT PRIMARY KEY,
    work_item_id TEXT NOT NULL REFERENCES agent_repair_budgets(work_item_id),
    event_kind TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_observation_batches (
    batch_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    target_sha TEXT NOT NULL,
    wait_ids_json TEXT NOT NULL,
    work_item_ids_json TEXT NOT NULL,
    pending_gates_json TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(cycle_id, repository, target_sha)
);

CREATE TRIGGER IF NOT EXISTS agent_repair_budget_identity_no_update
BEFORE UPDATE OF work_item_id,operation_id,repository,target_sha,
                 max_files,max_changed_lines,max_attempts,max_runtime_seconds,
                 max_cost_units,max_observation_batches,created_at
ON agent_repair_budgets
BEGIN SELECT RAISE(ABORT, 'repair budget immutable identity'); END;

CREATE TRIGGER IF NOT EXISTS agent_repair_budgets_no_delete
BEFORE DELETE ON agent_repair_budgets
BEGIN SELECT RAISE(ABORT, 'repair budgets cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS agent_repair_budget_events_no_update
BEFORE UPDATE ON agent_repair_budget_events
BEGIN SELECT RAISE(ABORT, 'repair budget events append-only'); END;

CREATE TRIGGER IF NOT EXISTS agent_repair_budget_events_no_delete
BEFORE DELETE ON agent_repair_budget_events
BEGIN SELECT RAISE(ABORT, 'repair budget events append-only'); END;

CREATE TRIGGER IF NOT EXISTS agent_observation_batches_no_update
BEFORE UPDATE ON agent_observation_batches
BEGIN SELECT RAISE(ABORT, 'observation batches append-only'); END;

CREATE TRIGGER IF NOT EXISTS agent_observation_batches_no_delete
BEFORE DELETE ON agent_observation_batches
BEGIN SELECT RAISE(ABORT, 'observation batches cannot be deleted'); END;
"""


class BudgetError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise BudgetError("unsupported v6.1C contract version")
    if payload.get("contract_name") != "APPLAB_CLOSED_LOOP_QUEUE_BUDGETS":
        raise BudgetError("unexpected v6.1C contract")
    if payload.get("authority") != "ORCHESTRATION_ONLY":
        raise BudgetError("v6.1C authority drift")
    if payload.get("queue_authority") != "EXISTING_DURABLE_PER_REPO_QUEUE":
        raise BudgetError("v6.1C cannot create a second queue authority")
    if payload.get("observation_source") != "V61B_RECONCILIATION_DIRECTIVES":
        raise BudgetError("v6.1C must consume v6.1B reconciliation directives")
    return payload


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:28]
    return f"{prefix}_{digest}"


def _open(
    db_path: Path,
) -> tuple[
    storemod.SQLiteShadowStore,
    workgraph.AgentWorkGraphStore,
    queue_mod.DurablePerRepoQueue,
]:
    durable = storemod.SQLiteShadowStore(db_path)
    graph = workgraph.AgentWorkGraphStore(durable)
    queue = queue_mod.DurablePerRepoQueue(durable, **event_pilot.QUEUE_LIMITS)
    durable.db.executescript(recovery.WAIT_SCHEMA)
    durable.db.executescript(BUDGET_SCHEMA)
    durable.db.commit()
    return durable, graph, queue


def _budget_row(durable: storemod.SQLiteShadowStore, work_item_id: str) -> dict[str, Any]:
    row = durable.db.execute(
        "SELECT * FROM agent_repair_budgets WHERE work_item_id=?",
        (work_item_id,),
    ).fetchone()
    if row is None:
        raise BudgetError("repair budget is not registered for WorkItem")
    return dict(row)


def _wait_row(durable: storemod.SQLiteShadowStore, wait_id: str) -> dict[str, Any]:
    row = durable.db.execute(
        "SELECT * FROM agent_external_waits WHERE wait_id=?",
        (wait_id,),
    ).fetchone()
    if row is None:
        raise BudgetError("unknown v6.1B wait")
    item = dict(row)
    item["required_gates"] = json.loads(item.pop("required_gates_json"))
    item["gate_states"] = json.loads(item.pop("gate_states_json"))
    return item


def _event(
    durable: storemod.SQLiteShadowStore,
    *,
    work_item_id: str,
    event_kind: str,
    payload: dict[str, Any],
    occurred_at: str,
) -> dict[str, Any]:
    event_id = _id("bev", work_item_id, event_kind, _canonical(payload))
    digest = brain.sha256_json(payload)
    existing = durable.db.execute(
        "SELECT payload_sha256 FROM agent_repair_budget_events WHERE budget_event_id=?",
        (event_id,),
    ).fetchone()
    if existing is not None:
        if existing["payload_sha256"] != digest:
            raise BudgetError("budget event id reused with conflicting payload")
        return {"status": "REPLAY", "budget_event_id": event_id}
    durable.db.execute(
        """
        INSERT INTO agent_repair_budget_events(
            budget_event_id,work_item_id,event_kind,payload_sha256,payload_json,created_at
        ) VALUES (?,?,?,?,?,?)
        """,
        (event_id, work_item_id, event_kind, digest, _canonical(payload), occurred_at),
    )
    return {"status": "INSERTED", "budget_event_id": event_id}


def register_budget(
    *,
    db_path: Path,
    work_item_id: str,
    now_ts: float,
    occurred_at: str,
    max_runtime_seconds: int | None = None,
    max_cost_units: int | None = None,
    max_observation_batches: int | None = None,
) -> dict[str, Any]:
    contract = load_contract()
    durable, graph, queue = _open(db_path)
    try:
        item = graph.get_work_item(work_item_id)
        operation = durable.get_operation(item["operation_id"])
        if item["repository"] != operation["repository"]:
            raise BudgetError("WorkItem/operation repository mismatch")
        if item["resolved_sha"] != operation["resolved_sha"]:
            raise BudgetError("WorkItem/operation target SHA mismatch")

        queue_entry = queue._entry(operation["operation_id"])
        if queue_entry is None:
            raise BudgetError("closed-loop operation is not routed through durable queue")

        work_limits = item.get("budgets") or {}
        max_files = int(work_limits.get("max_files", -1))
        max_lines = int(work_limits.get("max_changed_lines", -1))
        max_attempts = int(work_limits.get("max_repair_attempts", -1))
        if min(max_files, max_lines, max_attempts) < 0:
            raise BudgetError("WorkItem repair budgets are incomplete")

        runtime_cfg = contract["runtime_budget"]
        cost_cfg = contract["cost_budget"]
        observation_cfg = contract["observation_budget"]
        runtime = (
            int(runtime_cfg["default_max_seconds"])
            if max_runtime_seconds is None
            else int(max_runtime_seconds)
        )
        cost = (
            int(cost_cfg["default_max_units"])
            if max_cost_units is None
            else int(max_cost_units)
        )
        observations = (
            int(observation_cfg["default_max_batches_per_work_item"])
            if max_observation_batches is None
            else int(max_observation_batches)
        )
        if not 1 <= runtime <= int(runtime_cfg["ceiling_seconds"]):
            raise BudgetError("runtime budget exceeds v6.1C ceiling")
        if not 1 <= cost <= int(cost_cfg["ceiling_units"]):
            raise BudgetError("cost budget exceeds v6.1C ceiling")
        if not 1 <= observations <= int(
            observation_cfg["ceiling_batches_per_work_item"]
        ):
            raise BudgetError("observation budget exceeds v6.1C ceiling")

        existing = durable.db.execute(
            "SELECT * FROM agent_repair_budgets WHERE work_item_id=?",
            (work_item_id,),
        ).fetchone()
        identity = (
            operation["operation_id"],
            item["repository"],
            item["resolved_sha"],
            max_files,
            max_lines,
            max_attempts,
            runtime,
            cost,
            observations,
        )
        if existing is not None:
            persisted = (
                existing["operation_id"],
                existing["repository"],
                existing["target_sha"],
                int(existing["max_files"]),
                int(existing["max_changed_lines"]),
                int(existing["max_attempts"]),
                int(existing["max_runtime_seconds"]),
                int(existing["max_cost_units"]),
                int(existing["max_observation_batches"]),
            )
            if persisted != identity:
                raise BudgetError("budget replay conflicts with immutable budget identity")
            result = "REPLAY"
        else:
            with durable.db:
                durable.db.execute(
                    """
                    INSERT INTO agent_repair_budgets(
                        work_item_id,operation_id,repository,target_sha,max_files,
                        max_changed_lines,max_attempts,max_runtime_seconds,max_cost_units,
                        max_observation_batches,state,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        work_item_id,
                        operation["operation_id"],
                        item["repository"],
                        item["resolved_sha"],
                        max_files,
                        max_lines,
                        max_attempts,
                        runtime,
                        cost,
                        observations,
                        "ACTIVE",
                        occurred_at,
                        occurred_at,
                    ),
                )
            result = "INSERTED"

        integrity = queue.integrity_report()
        if not integrity["ok"]:
            raise BudgetError("durable queue integrity failed")
        row = _budget_row(durable, work_item_id)
        return {
            "schema_version": 1,
            "record_type": "APPLAB_V61C_BUDGET_REGISTRATION",
            "authority": "ORCHESTRATION_ONLY",
            "status": result,
            "work_item_id": work_item_id,
            "operation_id": operation["operation_id"],
            "repository": item["repository"],
            "target_sha": item["resolved_sha"],
            "queue_state": str(queue_entry["state"]),
            "queue_backpressure": str(queue_entry["state"]) == "DEFERRED",
            "budget_state": row["state"],
            "max_files": row["max_files"],
            "max_changed_lines": row["max_changed_lines"],
            "max_attempts": row["max_attempts"],
            "max_runtime_seconds": row["max_runtime_seconds"],
            "max_cost_units": row["max_cost_units"],
            "max_observation_batches": row["max_observation_batches"],
            "queue_integrity": integrity,
            "new_queue_created": False,
        }
    finally:
        durable.close()



def _existing_attempt_reservation(
    durable: storemod.SQLiteShadowStore,
    *,
    work_item_id: str,
    attempt_number: int,
    changed_files: int,
    changed_lines: int,
    runtime_seconds: int,
    cost_units: int,
) -> dict[str, Any] | None:
    rows = durable.db.execute(
        """
        SELECT payload_json
        FROM agent_repair_budget_events
        WHERE work_item_id=? AND event_kind='ATTEMPT_RESERVATION'
        ORDER BY created_at ASC,budget_event_id ASC
        """,
        (work_item_id,),
    ).fetchall()
    requested = {
        "attempt_number": attempt_number,
        "changed_files": changed_files,
        "changed_lines": changed_lines,
        "runtime_seconds": runtime_seconds,
        "cost_units": cost_units,
    }
    for row in rows:
        payload = json.loads(row["payload_json"])
        if int(payload.get("attempt_number", 0)) != attempt_number:
            continue
        persisted = {
            key: int(payload.get(key, -1))
            for key in requested
        }
        if persisted != requested:
            raise BudgetError(
                "attempt reservation replay conflicts with immutable attempt usage"
            )
        return payload
    return None

def reserve_repair_attempt(
    *,
    db_path: Path,
    work_item_id: str,
    attempt_number: int,
    changed_files: int,
    changed_lines: int,
    runtime_seconds: int,
    cost_units: int,
    occurred_at: str,
) -> dict[str, Any]:
    if min(attempt_number, changed_files, changed_lines, runtime_seconds, cost_units) < 0:
        raise BudgetError("attempt reservation values must be non-negative")
    if attempt_number < 1:
        raise BudgetError("attempt_number must be >= 1")

    durable, _, _ = _open(db_path)
    try:
        durable.db.execute("BEGIN IMMEDIATE")
        try:
            row = _budget_row(durable, work_item_id)
            existing_reservation = _existing_attempt_reservation(
                durable,
                work_item_id=work_item_id,
                attempt_number=attempt_number,
                changed_files=changed_files,
                changed_lines=changed_lines,
                runtime_seconds=runtime_seconds,
                cost_units=cost_units,
            )
            if existing_reservation is not None:
                durable.db.commit()
                current = _budget_row(durable, work_item_id)
                return {
                    "authorized": bool(existing_reservation["authorized"]),
                    "reason": str(existing_reservation["reason"]),
                    "budget_state": current["state"],
                    "event_persistence": "REPLAY",
                }
            if row["state"] == "STOPPED":
                durable.db.commit()
                return {
                    "authorized": False,
                    "reason": row["stop_reason"] or "BUDGET_STOPPED",
                    "budget_state": "STOPPED",
                }

            expected_attempt = int(row["consumed_attempts"]) + 1
            if attempt_number != expected_attempt:
                raise BudgetError("repair attempts must be reserved contiguously")

            reason = ""
            if changed_files > int(row["max_files"]):
                reason = "FILES_BUDGET_EXCEEDED"
            elif changed_lines > int(row["max_changed_lines"]):
                reason = "LINES_BUDGET_EXCEEDED"
            elif attempt_number > int(row["max_attempts"]):
                reason = "ATTEMPT_BUDGET_EXCEEDED"
            elif int(row["consumed_runtime_seconds"]) + runtime_seconds > int(
                row["max_runtime_seconds"]
            ):
                reason = "RUNTIME_BUDGET_EXCEEDED"
            elif int(row["consumed_cost_units"]) + cost_units > int(row["max_cost_units"]):
                reason = "COST_BUDGET_EXCEEDED"

            payload = {
                "attempt_number": attempt_number,
                "changed_files": changed_files,
                "changed_lines": changed_lines,
                "runtime_seconds": runtime_seconds,
                "cost_units": cost_units,
                "authorized": not bool(reason),
                "reason": reason or "WITHIN_BUDGET",
            }
            event_result = _event(
                durable,
                work_item_id=work_item_id,
                event_kind="ATTEMPT_RESERVATION",
                payload=payload,
                occurred_at=occurred_at,
            )
            if event_result["status"] == "REPLAY":
                durable.db.commit()
                current = _budget_row(durable, work_item_id)
                return {
                    "authorized": payload["authorized"],
                    "reason": payload["reason"],
                    "budget_state": current["state"],
                    "event_persistence": "REPLAY",
                }

            if reason:
                durable.db.execute(
                    """
                    UPDATE agent_repair_budgets
                    SET state='STOPPED',stop_reason=?,updated_at=?
                    WHERE work_item_id=?
                    """,
                    (reason, occurred_at, work_item_id),
                )
                durable.db.commit()
                return {
                    "authorized": False,
                    "reason": reason,
                    "budget_state": "STOPPED",
                    "event_persistence": "INSERTED",
                }

            consumed_attempts = attempt_number
            consumed_runtime = int(row["consumed_runtime_seconds"]) + runtime_seconds
            consumed_cost = int(row["consumed_cost_units"]) + cost_units
            state = (
                "EXHAUSTED"
                if consumed_attempts >= int(row["max_attempts"])
                else "ACTIVE"
            )
            durable.db.execute(
                """
                UPDATE agent_repair_budgets
                SET consumed_attempts=?,consumed_runtime_seconds=?,
                    consumed_cost_units=?,state=?,updated_at=?
                WHERE work_item_id=?
                """,
                (
                    consumed_attempts,
                    consumed_runtime,
                    consumed_cost,
                    state,
                    occurred_at,
                    work_item_id,
                ),
            )
            durable.db.commit()
            return {
                "authorized": True,
                "reason": "WITHIN_BUDGET",
                "budget_state": state,
                "attempt_number": attempt_number,
                "consumed_attempts": consumed_attempts,
                "consumed_runtime_seconds": consumed_runtime,
                "consumed_cost_units": consumed_cost,
                "event_persistence": "INSERTED",
            }
        except Exception:
            if durable.db.in_transaction:
                durable.db.rollback()
            raise
    finally:
        durable.close()


def note_failure_signature(
    *,
    db_path: Path,
    work_item_id: str,
    failure_signature: str,
    occurred_at: str,
) -> dict[str, Any]:
    signature = str(failure_signature).strip()
    if not signature:
        raise BudgetError("failure_signature must be non-empty")

    durable, _, _ = _open(db_path)
    try:
        durable.db.execute("BEGIN IMMEDIATE")
        try:
            row = _budget_row(durable, work_item_id)
            repeated = bool(row["last_failure_signature"]) and (
                str(row["last_failure_signature"]) == signature
            )
            payload = {
                "failure_signature": signature,
                "repeated": repeated,
            }
            event_result = _event(
                durable,
                work_item_id=work_item_id,
                event_kind="FAILURE_SIGNATURE",
                payload=payload,
                occurred_at=occurred_at,
            )
            if event_result["status"] == "REPLAY":
                durable.db.commit()
                current = _budget_row(durable, work_item_id)
                return {
                    "repeated": repeated,
                    "budget_state": current["state"],
                    "reason": current["stop_reason"] or "RECORDED",
                    "event_persistence": "REPLAY",
                }

            if repeated:
                durable.db.execute(
                    """
                    UPDATE agent_repair_budgets
                    SET state='STOPPED',stop_reason='REPEATED_FAILURE_SIGNATURE',updated_at=?
                    WHERE work_item_id=?
                    """,
                    (occurred_at, work_item_id),
                )
                state = "STOPPED"
                reason = "REPEATED_FAILURE_SIGNATURE"
            else:
                durable.db.execute(
                    """
                    UPDATE agent_repair_budgets
                    SET last_failure_signature=?,updated_at=?
                    WHERE work_item_id=?
                    """,
                    (signature, occurred_at, work_item_id),
                )
                state = str(row["state"])
                reason = "RECORDED"
            durable.db.commit()
            return {
                "repeated": repeated,
                "budget_state": state,
                "reason": reason,
                "event_persistence": "INSERTED",
            }
        except Exception:
            if durable.db.in_transaction:
                durable.db.rollback()
            raise
    finally:
        durable.close()


def _reserve_observation_budget(
    *,
    db_path: Path,
    work_item_id: str,
    occurred_at: str,
    batch_id: str,
) -> bool:
    durable, _, _ = _open(db_path)
    try:
        durable.db.execute("BEGIN IMMEDIATE")
        try:
            row = _budget_row(durable, work_item_id)
            if row["state"] == "STOPPED":
                durable.db.commit()
                return False
            used = int(row["consumed_observation_batches"])
            maximum = int(row["max_observation_batches"])
            if used >= maximum:
                durable.db.execute(
                    """
                    UPDATE agent_repair_budgets
                    SET state='STOPPED',stop_reason='OBSERVATION_BUDGET_EXCEEDED',updated_at=?
                    WHERE work_item_id=?
                    """,
                    (occurred_at, work_item_id),
                )
                durable.db.commit()
                return False
            payload = {"batch_id": batch_id, "next_count": used + 1}
            event_result = _event(
                durable,
                work_item_id=work_item_id,
                event_kind="OBSERVATION_BATCH",
                payload=payload,
                occurred_at=occurred_at,
            )
            if event_result["status"] == "INSERTED":
                durable.db.execute(
                    """
                    UPDATE agent_repair_budgets
                    SET consumed_observation_batches=?,updated_at=?
                    WHERE work_item_id=?
                    """,
                    (used + 1, occurred_at, work_item_id),
                )
            durable.db.commit()
            return True
        except Exception:
            if durable.db.in_transaction:
                durable.db.rollback()
            raise
    finally:
        durable.close()


def plan_observation_batches(
    *,
    db_path: Path,
    wait_ids: list[str],
    cycle_id: str,
    now_ts: float,
    actions_available: bool,
    occurred_at: str,
) -> dict[str, Any]:
    contract = load_contract()
    cycle_id = brain._require_non_empty_string(cycle_id, "cycle_id")
    unique_waits = sorted({str(value).strip() for value in wait_ids if str(value).strip()})

    durable, _, _ = _open(db_path)
    try:
        snapshots = [_wait_row(durable, wait_id) for wait_id in unique_waits]
        budget_rows: dict[str, dict[str, Any]] = {}
        for wait in snapshots:
            budget_rows[wait["work_item_id"]] = _budget_row(
                durable, wait["work_item_id"]
            )
    finally:
        durable.close()

    immediate: list[dict[str, Any]] = []
    due_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    held: list[dict[str, Any]] = []

    for wait in snapshots:
        budget = budget_rows[wait["work_item_id"]]
        if budget["state"] == "STOPPED":
            held.append(
                {
                    "wait_id": wait["wait_id"],
                    "reason": budget["stop_reason"] or "BUDGET_STOPPED",
                }
            )
            continue
        if int(budget["consumed_observation_batches"]) >= int(
            budget["max_observation_batches"]
        ):
            held.append(
                {
                    "wait_id": wait["wait_id"],
                    "reason": "OBSERVATION_BUDGET_EXHAUSTED",
                }
            )
            continue

        state = str(wait["state"])
        if state == "READY_FOR_EVALUATION":
            immediate.append(
                recovery.reconcile_wait(
                    db_path=db_path,
                    wait_id=wait["wait_id"],
                    now_ts=now_ts,
                    actions_available=actions_available,
                    occurred_at=occurred_at,
                )
            )
            continue
        if state != "WAITING":
            immediate.append(
                {
                    "wait_id": wait["wait_id"],
                    "action": "NOOP_TERMINAL_WAIT",
                    "state": state,
                    "poll": False,
                }
            )
            continue
        if not actions_available or float(now_ts) < float(wait["next_fallback_at"]):
            immediate.append(
                recovery.reconcile_wait(
                    db_path=db_path,
                    wait_id=wait["wait_id"],
                    now_ts=now_ts,
                    actions_available=actions_available,
                    occurred_at=occurred_at,
                )
            )
            continue
        if int(wait["fallback_count"]) >= int(wait["max_fallback_polls"]):
            immediate.append(
                recovery.reconcile_wait(
                    db_path=db_path,
                    wait_id=wait["wait_id"],
                    now_ts=now_ts,
                    actions_available=actions_available,
                    occurred_at=occurred_at,
                )
            )
            continue
        key = (str(wait["repository"]), str(wait["target_sha"]))
        due_groups.setdefault(key, []).append(wait)

    obs_cfg = contract["observation_budget"]
    max_global = int(obs_cfg["max_coalesced_batches_per_cycle"])
    max_per_repo = int(obs_cfg["max_coalesced_batches_per_repository_per_cycle"])
    selected: list[tuple[tuple[str, str], list[dict[str, Any]]]] = []
    deferred: list[dict[str, Any]] = []
    per_repo: dict[str, int] = {}

    for key in sorted(due_groups):
        repository, target_sha = key
        if len(selected) >= max_global or per_repo.get(repository, 0) >= max_per_repo:
            deferred.append(
                {
                    "repository": repository,
                    "target_sha": target_sha,
                    "wait_ids": [wait["wait_id"] for wait in due_groups[key]],
                    "reason": "OBSERVATION_BACKPRESSURE",
                }
            )
            continue
        selected.append((key, due_groups[key]))
        per_repo[repository] = per_repo.get(repository, 0) + 1

    batches: list[dict[str, Any]] = []
    for (repository, target_sha), waits in selected:
        batch_id = _id("obs", cycle_id, repository, target_sha)

        durable, _, _ = _open(db_path)
        try:
            existing = durable.db.execute(
                "SELECT * FROM agent_observation_batches WHERE batch_id=?",
                (batch_id,),
            ).fetchone()
            if existing is not None:
                batches.append(
                    {
                        "batch_id": batch_id,
                        "status": "REPLAY",
                        "repository": repository,
                        "target_sha": target_sha,
                        "wait_ids": json.loads(existing["wait_ids_json"]),
                        "work_item_ids": json.loads(existing["work_item_ids_json"]),
                        "pending_gates": json.loads(existing["pending_gates_json"]),
                        "external_query_required": True,
                    }
                )
                continue
        finally:
            durable.close()

        directives: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for wait in waits:
            directive = recovery.reconcile_wait(
                db_path=db_path,
                wait_id=wait["wait_id"],
                now_ts=now_ts,
                actions_available=actions_available,
                occurred_at=occurred_at,
            )
            if directive.get("poll") is True:
                directives.append((wait, directive))
            else:
                immediate.append(directive)

        if not directives:
            continue

        accepted: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for wait, directive in directives:
            if _reserve_observation_budget(
                db_path=db_path,
                work_item_id=wait["work_item_id"],
                occurred_at=occurred_at,
                batch_id=batch_id,
            ):
                accepted.append((wait, directive))
            else:
                held.append(
                    {
                        "wait_id": wait["wait_id"],
                        "reason": "OBSERVATION_BUDGET_EXHAUSTED",
                    }
                )
        if not accepted:
            continue

        wait_id_values = sorted(wait["wait_id"] for wait, _ in accepted)
        work_item_values = sorted({wait["work_item_id"] for wait, _ in accepted})
        gates = sorted(
            {
                gate
                for _, directive in accepted
                for gate in directive.get("pending_gates", [])
            }
        )
        durable, _, _ = _open(db_path)
        try:
            with durable.db:
                durable.db.execute(
                    """
                    INSERT INTO agent_observation_batches(
                        batch_id,cycle_id,repository,target_sha,wait_ids_json,
                        work_item_ids_json,pending_gates_json,state,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        batch_id,
                        cycle_id,
                        repository,
                        target_sha,
                        _canonical(wait_id_values),
                        _canonical(work_item_values),
                        _canonical(gates),
                        "RESERVED",
                        occurred_at,
                    ),
                )
        finally:
            durable.close()

        batches.append(
            {
                "batch_id": batch_id,
                "status": "INSERTED",
                "repository": repository,
                "target_sha": target_sha,
                "wait_ids": wait_id_values,
                "work_item_ids": work_item_values,
                "pending_gates": gates,
                "external_query_required": True,
            }
        )

    covered_waits = sum(len(batch["wait_ids"]) for batch in batches)
    return {
        "schema_version": 1,
        "record_type": "APPLAB_V61C_OBSERVATION_PLAN",
        "authority": "ORCHESTRATION_ONLY",
        "cycle_id": cycle_id,
        "batches": batches,
        "immediate": immediate,
        "held": held,
        "deferred": deferred,
        "external_query_count": len(batches),
        "covered_wait_count": covered_waits,
        "coalesced_wait_savings": max(0, covered_waits - len(batches)),
        "fixed_interval_polling_primary": False,
        "network_call_per_wait": False,
        "target_sha_mutation_performed": False,
    }


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        db_path = root / "v61c.sqlite3"
        sha = "a" * 40

        durable = storemod.SQLiteShadowStore(db_path)
        try:
            graph = workgraph.AgentWorkGraphStore(durable)
            queue = queue_mod.DurablePerRepoQueue(
                durable, **event_pilot.QUEUE_LIMITS
            )
            work_items: list[str] = []
            operation_ids: list[str] = []
            for index in (1, 2, 3):
                operation = brain._operation_fixture(
                    f"op_v61c-{index}",
                    "riccardopinato/AppLab",
                    "refs/heads/main",
                    sha,
                    sha,
                    state="RUNNING",
                    force_generation=index,
                )
                durable.put_operation(operation)
                queue.enqueue(operation["operation_id"], now_ts=10.0 + index)
                item = workgraph.adapt_operation_to_work_item(
                    operation,
                    work_item_id=f"wrk_v61c-{index}",
                    allow_code_edit=True,
                    allow_draft_pr_steward=True,
                )
                item["state"] = "VERIFYING"
                graph.put_work_item(item)
                work_items.append(item["work_item_id"])
                operation_ids.append(operation["operation_id"])
        finally:
            durable.close()

        first_budget = register_budget(
            db_path=db_path,
            work_item_id=work_items[0],
            now_ts=20.0,
            occurred_at="2026-10-27T15:00:00Z",
        )
        second_budget = register_budget(
            db_path=db_path,
            work_item_id=work_items[1],
            now_ts=20.0,
            occurred_at="2026-10-27T15:00:00Z",
        )
        third_budget = register_budget(
            db_path=db_path,
            work_item_id=work_items[2],
            now_ts=20.0,
            occurred_at="2026-10-27T15:00:00Z",
        )
        assert first_budget["queue_state"] == "QUEUED"
        assert second_budget["queue_state"] == "DEFERRED"
        assert third_budget["queue_state"] == "DEFERRED"
        assert second_budget["queue_backpressure"] is True
        assert third_budget["queue_backpressure"] is True
        assert first_budget["new_queue_created"] is False

        attempt1 = reserve_repair_attempt(
            db_path=db_path,
            work_item_id=work_items[2],
            attempt_number=1,
            changed_files=2,
            changed_lines=80,
            runtime_seconds=200,
            cost_units=50,
            occurred_at="2026-10-27T15:01:00Z",
        )
        assert attempt1["authorized"] is True
        attempt1_replay = reserve_repair_attempt(
            db_path=db_path,
            work_item_id=work_items[2],
            attempt_number=1,
            changed_files=2,
            changed_lines=80,
            runtime_seconds=200,
            cost_units=50,
            occurred_at="2026-10-27T15:01:30Z",
        )
        assert attempt1_replay["authorized"] is True
        assert attempt1_replay["event_persistence"] == "REPLAY"

        first_failure = note_failure_signature(
            db_path=db_path,
            work_item_id=work_items[2],
            failure_signature="sig-demo",
            occurred_at="2026-10-27T15:02:00Z",
        )
        assert first_failure["repeated"] is False

        attempt2 = reserve_repair_attempt(
            db_path=db_path,
            work_item_id=work_items[2],
            attempt_number=2,
            changed_files=1,
            changed_lines=40,
            runtime_seconds=150,
            cost_units=40,
            occurred_at="2026-10-27T15:03:00Z",
        )
        assert attempt2["authorized"] is True
        repeated = note_failure_signature(
            db_path=db_path,
            work_item_id=work_items[2],
            failure_signature="sig-demo",
            occurred_at="2026-10-27T15:04:00Z",
        )
        assert repeated["repeated"] is True
        assert repeated["budget_state"] == "STOPPED"

        wait1 = recovery.begin_wait(
            db_path=db_path,
            work_item_id=work_items[0],
            target_sha=sha,
            required_gates=["AppLab CI", "AppLab CodeQL"],
            now_ts=100.0,
            occurred_at="2026-10-27T15:05:00Z",
        )
        wait2 = recovery.begin_wait(
            db_path=db_path,
            work_item_id=work_items[1],
            target_sha=sha,
            required_gates=["AppLab CI", "Emulator Self Test"],
            now_ts=100.0,
            occurred_at="2026-10-27T15:05:00Z",
        )

        plan = plan_observation_batches(
            db_path=db_path,
            wait_ids=[wait1["wait_id"], wait2["wait_id"]],
            cycle_id="cycle-v61c-1",
            now_ts=221.0,
            actions_available=True,
            occurred_at="2026-10-27T15:06:00Z",
        )
        assert plan["external_query_count"] == 1
        assert plan["covered_wait_count"] == 2
        assert plan["coalesced_wait_savings"] == 1
        assert plan["batches"][0]["pending_gates"] == [
            "AppLab CI",
            "AppLab CodeQL",
            "Emulator Self Test",
        ]

        replay = plan_observation_batches(
            db_path=db_path,
            wait_ids=[wait1["wait_id"], wait2["wait_id"]],
            cycle_id="cycle-v61c-1",
            now_ts=221.0,
            actions_available=True,
            occurred_at="2026-10-27T15:06:01Z",
        )
        assert replay["external_query_count"] == 1
        assert replay["batches"][0]["status"] == "REPLAY"

        too_early = plan_observation_batches(
            db_path=db_path,
            wait_ids=[wait1["wait_id"], wait2["wait_id"]],
            cycle_id="cycle-v61c-2",
            now_ts=222.0,
            actions_available=True,
            occurred_at="2026-10-27T15:06:02Z",
        )
        assert too_early["external_query_count"] == 0
        assert all(row.get("poll") is False for row in too_early["immediate"])

        return {
            "schema_version": 1,
            "record_type": "APPLAB_V61C_QUEUE_BUDGET_PROOF",
            "status": "PASS",
            "existing_queue_reused": True,
            "per_repository_backpressure_observed": True,
            "work_item_file_line_attempt_budgets_preserved": True,
            "runtime_cost_budgets_cumulative": True,
            "attempt_reservation_idempotent": True,
            "repeated_failure_signature_stops": True,
            "event_driven_primary": True,
            "same_sha_waits_coalesced": True,
            "coalesced_external_query_count": plan["external_query_count"],
            "coalesced_wait_count": plan["covered_wait_count"],
            "fixed_interval_polling_primary": False,
            "network_call_per_wait": False,
            "target_sha_mutation_performed": False,
            "merge_authority": "UNCHANGED",
            "release_authority": "DENIED",
            "certification_authority": "UNCHANGED",
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AppLab v6.1C queue, backpressure and repair budget control"
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test:
        parser.error("--self-test is required")
    print(json.dumps(self_test(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
