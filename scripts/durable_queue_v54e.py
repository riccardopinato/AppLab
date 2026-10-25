#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import durable_brain_v54a as brain
import durable_store_v54b as storemod

RETRYABLE_FAILURES = {"INFRA_ERROR", "UNKNOWN_FAILURE", "FLAKY_SUSPECT"}
PROTECTED_CLASSES = {"CERTIFICATION", "PHYSICAL_VALIDATION", "MANUAL_DIAGNOSTIC"}
PENDING_STATES = {"QUEUED", "DEFERRED", "LEASED"}
TERMINAL_QUEUE_STATES = {"DONE", "BLOCKED", "SUPERSEDED"}


class QueueError(ValueError):
    pass


QUEUE_SCHEMA = """
CREATE TABLE IF NOT EXISTS queue_entries (
    operation_id TEXT PRIMARY KEY REFERENCES operations(operation_id),
    repository TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    operation_class TEXT NOT NULL,
    resolved_sha TEXT NOT NULL,
    priority INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('QUEUED','DEFERRED','LEASED','DONE','BLOCKED','SUPERSEDED')
    ),
    protected INTEGER NOT NULL DEFAULT 0 CHECK (protected IN (0,1)),
    preserve_for_calibration INTEGER NOT NULL DEFAULT 0 CHECK (preserve_for_calibration IN (0,1)),
    enqueued_seq INTEGER NOT NULL UNIQUE,
    enqueued_at REAL NOT NULL,
    available_at REAL NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    max_retries INTEGER NOT NULL DEFAULT 2 CHECK (max_retries >= 0),
    leased_by TEXT,
    lease_until REAL,
    updated_at REAL NOT NULL,
    CHECK (
        (state='LEASED' AND leased_by IS NOT NULL AND lease_until IS NOT NULL)
        OR
        (state<>'LEASED' AND leased_by IS NULL AND lease_until IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS queue_ready_idx
ON queue_entries(state, available_at, priority DESC, enqueued_seq ASC);

CREATE INDEX IF NOT EXISTS queue_repo_idx
ON queue_entries(repository, state, enqueued_seq ASC);

CREATE INDEX IF NOT EXISTS queue_lineage_idx
ON queue_entries(repository, source_ref, operation_class, state, enqueued_seq ASC);

CREATE TABLE IF NOT EXISTS queue_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    action TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    reason TEXT NOT NULL,
    occurred_at REAL NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS queue_history_operation_idx
ON queue_history(operation_id, history_id ASC);

CREATE TABLE IF NOT EXISTS queue_repo_state (
    repository TEXT PRIMARY KEY,
    last_claim_seq INTEGER NOT NULL DEFAULT 0 CHECK (last_claim_seq >= 0)
);

CREATE TRIGGER IF NOT EXISTS queue_history_no_update
BEFORE UPDATE ON queue_history
BEGIN
    SELECT RAISE(ABORT, 'queue_history append-only');
END;

CREATE TRIGGER IF NOT EXISTS queue_history_no_delete
BEFORE DELETE ON queue_history
BEGIN
    SELECT RAISE(ABORT, 'queue_history append-only');
END;

CREATE TRIGGER IF NOT EXISTS queue_entries_identity_no_update
BEFORE UPDATE OF
    operation_id,repository,source_ref,operation_class,resolved_sha,priority,
    protected,preserve_for_calibration,enqueued_seq,enqueued_at,max_retries
ON queue_entries
BEGIN
    SELECT RAISE(ABORT, 'queue immutable identity');
END;

CREATE TRIGGER IF NOT EXISTS queue_entries_no_delete
BEFORE DELETE ON queue_entries
BEGIN
    SELECT RAISE(ABORT, 'queue entries cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS queue_state_requires_history
BEFORE UPDATE OF state ON queue_entries
WHEN NEW.state <> OLD.state
AND NOT EXISTS (
    SELECT 1
    FROM queue_history h
    WHERE h.operation_id = OLD.operation_id
      AND h.from_state IS OLD.state
      AND h.to_state = NEW.state
      AND h.history_id = (
          SELECT MAX(h2.history_id)
          FROM queue_history h2
          WHERE h2.operation_id = OLD.operation_id
      )
)
BEGIN
    SELECT RAISE(ABORT, 'queue state update requires history');
END;
"""


class DurablePerRepoQueue:
    def __init__(
        self,
        store: storemod.SQLiteShadowStore,
        *,
        max_ready_global: int = 8,
        max_ready_per_repo: int = 2,
        max_pending_global: int = 64,
        max_pending_per_repo: int = 16,
        max_active_global: int = 4,
        max_active_per_repo: int = 1,
        lease_seconds: int = 900,
        retry_base_seconds: int = 60,
        max_age_bonus: int = 50,
    ) -> None:
        values = {
            "max_ready_global": max_ready_global,
            "max_ready_per_repo": max_ready_per_repo,
            "max_pending_global": max_pending_global,
            "max_pending_per_repo": max_pending_per_repo,
            "max_active_global": max_active_global,
            "max_active_per_repo": max_active_per_repo,
            "lease_seconds": lease_seconds,
            "retry_base_seconds": retry_base_seconds,
        }
        for name, value in values.items():
            if int(value) < 1:
                raise QueueError(f"{name} must be positive")
        if max_age_bonus < 0:
            raise QueueError("max_age_bonus must be non-negative")
        if max_pending_global < max_ready_global or max_ready_global < max_active_global:
            raise QueueError("global limits must satisfy pending >= ready >= active")
        if max_pending_per_repo < max_ready_per_repo or max_ready_per_repo < max_active_per_repo:
            raise QueueError("per-repo limits must satisfy pending >= ready >= active")

        self.store = store
        self.db = store.db
        self.max_ready_global = int(max_ready_global)
        self.max_ready_per_repo = int(max_ready_per_repo)
        self.max_pending_global = int(max_pending_global)
        self.max_pending_per_repo = int(max_pending_per_repo)
        self.max_active_global = int(max_active_global)
        self.max_active_per_repo = int(max_active_per_repo)
        self.lease_seconds = int(lease_seconds)
        self.retry_base_seconds = int(retry_base_seconds)
        self.max_age_bonus = int(max_age_bonus)
        self.db.executescript(QUEUE_SCHEMA)
        self.db.commit()

    def _history(
        self,
        operation_id: str,
        action: str,
        from_state: str | None,
        to_state: str,
        reason: str,
        now_ts: float,
        payload: dict[str, Any] | None = None,
    ) -> int:
        cursor = self.db.execute(
            """
            INSERT INTO queue_history(
                operation_id,action,from_state,to_state,reason,occurred_at,payload_json
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                operation_id,
                action,
                from_state,
                to_state,
                reason,
                float(now_ts),
                brain.canonical_json(payload or {}),
            ),
        )
        return int(cursor.lastrowid)

    def _operation(self, operation_id: str) -> sqlite3.Row:
        row = self.db.execute(
            """
            SELECT operation_id,repository,source_ref,resolved_sha,priority,payload_json
            FROM operations
            WHERE operation_id=?
            """,
            (operation_id,),
        ).fetchone()
        if row is None:
            raise QueueError("queue operation is not persisted in durable store")
        return row

    def _entry(self, operation_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM queue_entries WHERE operation_id=?",
            (operation_id,),
        ).fetchone()

    def _pending_count(self) -> int:
        return int(
            self.db.execute(
                "SELECT COUNT(*) AS n FROM queue_entries WHERE state IN ('QUEUED','DEFERRED','LEASED')"
            ).fetchone()["n"]
        )

    def _repo_pending_count(self, repository: str) -> int:
        return int(
            self.db.execute(
                """
                SELECT COUNT(*) AS n
                FROM queue_entries
                WHERE repository=? AND state IN ('QUEUED','DEFERRED','LEASED')
                """,
                (repository,),
            ).fetchone()["n"]
        )

    def _ready_count(self) -> int:
        return int(
            self.db.execute(
                "SELECT COUNT(*) AS n FROM queue_entries WHERE state IN ('QUEUED','LEASED')"
            ).fetchone()["n"]
        )

    def _repo_ready_count(self, repository: str) -> int:
        return int(
            self.db.execute(
                """
                SELECT COUNT(*) AS n
                FROM queue_entries
                WHERE repository=? AND state IN ('QUEUED','LEASED')
                """,
                (repository,),
            ).fetchone()["n"]
        )

    def _active_count(self) -> int:
        return int(
            self.db.execute(
                "SELECT COUNT(*) AS n FROM queue_entries WHERE state='LEASED'"
            ).fetchone()["n"]
        )

    def _repo_active_count(self, repository: str) -> int:
        return int(
            self.db.execute(
                "SELECT COUNT(*) AS n FROM queue_entries WHERE repository=? AND state='LEASED'",
                (repository,),
            ).fetchone()["n"]
        )

    def _effective_priority(self, row: sqlite3.Row, now_ts: float) -> int:
        age_minutes = max(int((float(now_ts) - float(row["enqueued_at"])) // 60), 0)
        return int(row["priority"]) + min(age_minutes, self.max_age_bonus)

    def enqueue(
        self,
        operation_id: str,
        *,
        ancestor_shas: set[str] | None = None,
        ancestry_proven: bool = False,
        preserve_for_calibration: bool = False,
        now_ts: float,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        if max_retries < 0:
            raise QueueError("max_retries must be non-negative")
        ancestor_shas = set(ancestor_shas or set())
        if ancestor_shas and not ancestry_proven:
            raise QueueError("ancestor_shas require explicit ancestry_proven=true")

        try:
            self.db.execute("BEGIN IMMEDIATE")

            existing = self._entry(operation_id)
            if existing is not None:
                persisted_op = self._operation(operation_id)
                persisted_payload = json.loads(persisted_op["payload_json"])
                effective_replay_preserve = bool(preserve_for_calibration) or bool(
                    persisted_payload.get("preserve_for_calibration", False)
                )
                if bool(existing["preserve_for_calibration"]) != effective_replay_preserve:
                    raise QueueError("queue replay conflicts with preserve_for_calibration")
                if int(existing["max_retries"]) != int(max_retries):
                    raise QueueError("queue replay conflicts with max_retries")
                self.db.commit()
                return {
                    "status": "REPLAY",
                    "operation_id": operation_id,
                    "state": existing["state"],
                }

            op = self._operation(operation_id)
            payload = json.loads(op["payload_json"])
            operation_class = str(payload["operation_class"])
            protected = operation_class in PROTECTED_CLASSES
            operation_preserve = bool(payload.get("preserve_for_calibration", False))
            effective_preserve = bool(preserve_for_calibration) or operation_preserve

            superseded: list[str] = []
            if operation_class == "VERIFICATION" and ancestor_shas:
                rows = self.db.execute(
                    """
                    SELECT operation_id,resolved_sha,state,protected,preserve_for_calibration
                    FROM queue_entries
                    WHERE repository=? AND source_ref=? AND operation_class='VERIFICATION'
                      AND state IN ('QUEUED','DEFERRED')
                    ORDER BY enqueued_seq ASC
                    """,
                    (op["repository"], op["source_ref"]),
                ).fetchall()
                for old in rows:
                    if (
                        old["resolved_sha"] in ancestor_shas
                        and not bool(old["protected"])
                        and not bool(old["preserve_for_calibration"])
                    ):
                        self._history(
                            old["operation_id"],
                            "SUPERSEDE",
                            old["state"],
                            "SUPERSEDED",
                            "NEWER_DESCENDANT_SAME_LINEAGE",
                            now_ts,
                            {"superseded_by": operation_id},
                        )
                        self.db.execute(
                            """
                            UPDATE queue_entries
                            SET state='SUPERSEDED',updated_at=?
                            WHERE operation_id=?
                            """,
                            (float(now_ts), old["operation_id"]),
                        )
                        superseded.append(old["operation_id"])

            if self._pending_count() >= self.max_pending_global:
                raise QueueError("global pending queue capacity exhausted")
            if self._repo_pending_count(op["repository"]) >= self.max_pending_per_repo:
                raise QueueError("repository pending queue capacity exhausted")

            if (
                self._ready_count() >= self.max_ready_global
                or self._repo_ready_count(op["repository"]) >= self.max_ready_per_repo
            ):
                initial_state = "DEFERRED"
                reason = "BACKPRESSURE"
            else:
                initial_state = "QUEUED"
                reason = "ENQUEUED"

            seq = int(
                self.db.execute(
                    "SELECT COALESCE(MAX(enqueued_seq),0)+1 AS n FROM queue_entries"
                ).fetchone()["n"]
            )
            self.db.execute(
                """
                INSERT INTO queue_entries(
                    operation_id,repository,source_ref,operation_class,resolved_sha,
                    priority,state,protected,preserve_for_calibration,enqueued_seq,
                    enqueued_at,available_at,retry_count,max_retries,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    operation_id,
                    op["repository"],
                    op["source_ref"],
                    operation_class,
                    op["resolved_sha"],
                    int(op["priority"]),
                    initial_state,
                    int(protected),
                    int(effective_preserve),
                    seq,
                    float(now_ts),
                    float(now_ts),
                    0,
                    int(max_retries),
                    float(now_ts),
                ),
            )
            self._history(
                operation_id,
                "ENQUEUE",
                None,
                initial_state,
                reason,
                now_ts,
                {
                    "protected": protected,
                    "preserve_for_calibration": effective_preserve,
                    "superseded": superseded,
                },
            )
            self.db.commit()
            return {
                "status": "INSERTED",
                "operation_id": operation_id,
                "state": initial_state,
                "superseded": superseded,
                "protected": protected,
            }
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def _reconcile_terminal_pending_locked(self, *, now_ts: float) -> list[str]:
        terminal_states = set(self.store.brain_contract["operation"]["terminal_states"])
        rows = self.db.execute(
            """
            SELECT q.operation_id,q.state,o.current_state AS operation_state
            FROM queue_entries q
            JOIN operations o ON o.operation_id=q.operation_id
            WHERE q.state IN ('QUEUED','DEFERRED')
            ORDER BY q.enqueued_seq ASC
            """
        ).fetchall()
        reconciled: list[str] = []
        for row in rows:
            operation_state = str(row["operation_state"])
            if operation_state not in terminal_states:
                continue
            if operation_state == "SUPERSEDED":
                target_state = "SUPERSEDED"
            elif operation_state == "SUCCEEDED":
                target_state = "DONE"
            else:
                target_state = "BLOCKED"
            self._history(
                row["operation_id"],
                "RECONCILE_TERMINAL",
                row["state"],
                target_state,
                f"DURABLE_OPERATION_TERMINAL:{operation_state}",
                now_ts,
            )
            self.db.execute(
                """
                UPDATE queue_entries
                SET state=?,leased_by=NULL,lease_until=NULL,updated_at=?
                WHERE operation_id=?
                """,
                (target_state, float(now_ts), row["operation_id"]),
            )
            reconciled.append(row["operation_id"])
        return reconciled

    def rebalance(self, *, now_ts: float) -> list[str]:
        promoted: list[str] = []
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self._reconcile_terminal_pending_locked(now_ts=now_ts)
            rows = self.db.execute(
                """
                SELECT q.*, COALESCE(r.last_claim_seq,0) AS last_claim_seq
                FROM queue_entries q
                LEFT JOIN queue_repo_state r ON r.repository=q.repository
                WHERE q.state='DEFERRED'
                """
            ).fetchall()
            ordered = sorted(
                rows,
                key=lambda row: (
                    -self._effective_priority(row, now_ts),
                    int(row["last_claim_seq"]),
                    int(row["enqueued_seq"]),
                ),
            )
            for row in ordered:
                if self._ready_count() >= self.max_ready_global:
                    break
                if self._repo_ready_count(row["repository"]) >= self.max_ready_per_repo:
                    continue
                self._history(
                    row["operation_id"],
                    "PROMOTE",
                    "DEFERRED",
                    "QUEUED",
                    "BACKPRESSURE_RELEASED",
                    now_ts,
                )
                self.db.execute(
                    """
                    UPDATE queue_entries
                    SET state='QUEUED',updated_at=?
                    WHERE operation_id=?
                    """,
                    (float(now_ts), row["operation_id"]),
                )
                promoted.append(row["operation_id"])
            self.db.commit()
            return promoted
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def claim_next(self, worker_id: str, *, now_ts: float) -> dict[str, Any] | None:
        worker_id = brain._require_non_empty_string(worker_id, "worker_id")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self._reconcile_terminal_pending_locked(now_ts=now_ts)
            if self._active_count() >= self.max_active_global:
                self.db.commit()
                return None

            rows = self.db.execute(
                """
                SELECT q.*, COALESCE(r.last_claim_seq,0) AS last_claim_seq,
                       o.current_state AS operation_state
                FROM queue_entries q
                JOIN operations o ON o.operation_id=q.operation_id
                LEFT JOIN queue_repo_state r ON r.repository=q.repository
                WHERE q.state='QUEUED' AND q.available_at<=?
                """,
                (float(now_ts),),
            ).fetchall()
            terminal_states = set(self.store.brain_contract["operation"]["terminal_states"])
            eligible = [
                row
                for row in rows
                if row["operation_state"] not in terminal_states
                and self._repo_active_count(row["repository"]) < self.max_active_per_repo
            ]
            if not eligible:
                self.db.commit()
                return None

            eligible.sort(
                key=lambda row: (
                    -self._effective_priority(row, now_ts),
                    int(row["last_claim_seq"]),
                    int(row["enqueued_seq"]),
                )
            )
            row = eligible[0]
            lease_until = float(now_ts) + self.lease_seconds
            self._history(
                row["operation_id"],
                "CLAIM",
                "QUEUED",
                "LEASED",
                "GITHUB_ACTIONS_EXECUTOR_INTENT",
                now_ts,
                {"worker_id": worker_id, "lease_until": lease_until},
            )
            self.db.execute(
                """
                UPDATE queue_entries
                SET state='LEASED',leased_by=?,lease_until=?,updated_at=?
                WHERE operation_id=?
                """,
                (worker_id, lease_until, float(now_ts), row["operation_id"]),
            )
            next_claim_seq = int(
                self.db.execute(
                    "SELECT COALESCE(MAX(last_claim_seq),0)+1 AS n FROM queue_repo_state"
                ).fetchone()["n"]
            )
            self.db.execute(
                """
                INSERT INTO queue_repo_state(repository,last_claim_seq)
                VALUES (?,?)
                ON CONFLICT(repository) DO UPDATE SET last_claim_seq=excluded.last_claim_seq
                """,
                (row["repository"], next_claim_seq),
            )
            self.db.commit()
            return {
                "operation_id": row["operation_id"],
                "repository": row["repository"],
                "source_ref": row["source_ref"],
                "resolved_sha": row["resolved_sha"],
                "operation_class": row["operation_class"],
                "executor": "GITHUB_ACTIONS",
                "worker_id": worker_id,
                "lease_until": lease_until,
                "dispatch_performed": False,
            }
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def complete(self, operation_id: str, worker_id: str, *, now_ts: float) -> dict[str, Any]:
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self._entry(operation_id)
            if row is None or row["state"] != "LEASED":
                raise QueueError("operation is not leased")
            if row["leased_by"] != worker_id:
                raise QueueError("lease owner mismatch")
            self._history(
                operation_id,
                "COMPLETE",
                "LEASED",
                "DONE",
                "EXECUTOR_COMPLETED",
                now_ts,
            )
            self.db.execute(
                """
                UPDATE queue_entries
                SET state='DONE',leased_by=NULL,lease_until=NULL,updated_at=?
                WHERE operation_id=?
                """,
                (float(now_ts), operation_id),
            )
            self.db.commit()
            return {"operation_id": operation_id, "state": "DONE"}
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def record_failure(
        self,
        operation_id: str,
        worker_id: str,
        failure_class: str,
        *,
        retryable: bool,
        now_ts: float,
    ) -> dict[str, Any]:
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self._entry(operation_id)
            if row is None or row["state"] != "LEASED":
                raise QueueError("operation is not leased")
            if row["leased_by"] != worker_id:
                raise QueueError("lease owner mismatch")

            can_retry = (
                bool(retryable)
                and failure_class in RETRYABLE_FAILURES
                and int(row["retry_count"]) < int(row["max_retries"])
            )
            if can_retry:
                next_retry = int(row["retry_count"]) + 1
                delay = self.retry_base_seconds * (2 ** (next_retry - 1))
                available_at = float(now_ts) + delay
                self._history(
                    operation_id,
                    "RETRY",
                    "LEASED",
                    "QUEUED",
                    failure_class,
                    now_ts,
                    {"retry_count": next_retry, "available_at": available_at},
                )
                self.db.execute(
                    """
                    UPDATE queue_entries
                    SET state='QUEUED',retry_count=?,available_at=?,
                        leased_by=NULL,lease_until=NULL,updated_at=?
                    WHERE operation_id=?
                    """,
                    (next_retry, available_at, float(now_ts), operation_id),
                )
                self.db.commit()
                return {
                    "operation_id": operation_id,
                    "retry": True,
                    "retry_count": next_retry,
                    "available_at": available_at,
                }

            self._history(
                operation_id,
                "FAIL_TERMINAL",
                "LEASED",
                "BLOCKED",
                failure_class,
                now_ts,
                {"retryable_requested": bool(retryable)},
            )
            self.db.execute(
                """
                UPDATE queue_entries
                SET state='BLOCKED',leased_by=NULL,lease_until=NULL,updated_at=?
                WHERE operation_id=?
                """,
                (float(now_ts), operation_id),
            )
            self.db.commit()
            return {"operation_id": operation_id, "retry": False, "state": "BLOCKED"}
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def recover_expired_leases(self, *, now_ts: float) -> list[dict[str, Any]]:
        recovered: list[dict[str, Any]] = []
        try:
            self.db.execute("BEGIN IMMEDIATE")
            rows = self.db.execute(
                """
                SELECT operation_id,leased_by,lease_until,retry_count,max_retries
                FROM queue_entries
                WHERE state='LEASED' AND lease_until IS NOT NULL AND lease_until<?
                ORDER BY enqueued_seq ASC
                """,
                (float(now_ts),),
            ).fetchall()
            for stale in rows:
                current = self.db.execute(
                    """
                    SELECT operation_id,state,leased_by,lease_until,retry_count,max_retries
                    FROM queue_entries
                    WHERE operation_id=?
                    """,
                    (stale["operation_id"],),
                ).fetchone()
                if current is None:
                    continue
                if current["state"] != "LEASED":
                    continue
                if current["leased_by"] != stale["leased_by"]:
                    continue
                if current["lease_until"] != stale["lease_until"]:
                    continue
                if current["lease_until"] is None or float(current["lease_until"]) >= float(now_ts):
                    continue

                can_retry = int(current["retry_count"]) < int(current["max_retries"])
                if can_retry:
                    next_retry = int(current["retry_count"]) + 1
                    delay = self.retry_base_seconds * (2 ** (next_retry - 1))
                    available_at = float(now_ts) + delay
                    self._history(
                        current["operation_id"],
                        "RETRY",
                        "LEASED",
                        "QUEUED",
                        "INFRA_ERROR",
                        now_ts,
                        {
                            "retry_count": next_retry,
                            "available_at": available_at,
                            "recovered_expired_lease": True,
                        },
                    )
                    self.db.execute(
                        """
                        UPDATE queue_entries
                        SET state='QUEUED',retry_count=?,available_at=?,
                            leased_by=NULL,lease_until=NULL,updated_at=?
                        WHERE operation_id=?
                        """,
                        (
                            next_retry,
                            available_at,
                            float(now_ts),
                            current["operation_id"],
                        ),
                    )
                    recovered.append(
                        {
                            "operation_id": current["operation_id"],
                            "retry": True,
                            "retry_count": next_retry,
                            "available_at": available_at,
                        }
                    )
                else:
                    self._history(
                        current["operation_id"],
                        "FAIL_TERMINAL",
                        "LEASED",
                        "BLOCKED",
                        "INFRA_ERROR",
                        now_ts,
                        {
                            "retryable_requested": True,
                            "recovered_expired_lease": True,
                        },
                    )
                    self.db.execute(
                        """
                        UPDATE queue_entries
                        SET state='BLOCKED',leased_by=NULL,lease_until=NULL,updated_at=?
                        WHERE operation_id=?
                        """,
                        (float(now_ts), current["operation_id"]),
                    )
                    recovered.append(
                        {
                            "operation_id": current["operation_id"],
                            "retry": False,
                            "state": "BLOCKED",
                        }
                    )
            self.db.commit()
            return recovered
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def history(self, operation_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """
            SELECT history_id,action,from_state,to_state,reason,occurred_at,payload_json
            FROM queue_history
            WHERE operation_id=?
            ORDER BY history_id ASC
            """,
            (operation_id,),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    def snapshot(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT * FROM queue_entries ORDER BY enqueued_seq ASC"
        ).fetchall()
        return [dict(row) for row in rows]

    def integrity_report(self) -> dict[str, Any]:
        started_snapshot = False
        if not self.db.in_transaction:
            self.db.execute("BEGIN")
            started_snapshot = True
        try:
            violations: list[str] = []

            active = self._active_count()
            if active > self.max_active_global:
                violations.append(f"global_active_limit:{active}:{self.max_active_global}")

            pending = self._pending_count()
            if pending > self.max_pending_global:
                violations.append(f"global_pending_limit:{pending}:{self.max_pending_global}")

            repo_counts = self.db.execute(
                """
                SELECT repository,
                       SUM(CASE WHEN state='LEASED' THEN 1 ELSE 0 END) AS active_n,
                       SUM(CASE WHEN state IN ('QUEUED','DEFERRED','LEASED') THEN 1 ELSE 0 END) AS pending_n
                FROM queue_entries
                GROUP BY repository
                """
            ).fetchall()
            for row in repo_counts:
                if int(row["active_n"] or 0) > self.max_active_per_repo:
                    violations.append(
                        f"repo_active_limit:{row['repository']}:{row['active_n']}:{self.max_active_per_repo}"
                    )
                if int(row["pending_n"] or 0) > self.max_pending_per_repo:
                    violations.append(
                        f"repo_pending_limit:{row['repository']}:{row['pending_n']}:{self.max_pending_per_repo}"
                    )

            lease_projection = self.db.execute(
                """
                SELECT operation_id,state,leased_by,lease_until
                FROM queue_entries
                WHERE (state='LEASED' AND (leased_by IS NULL OR lease_until IS NULL))
                   OR (state<>'LEASED' AND (leased_by IS NOT NULL OR lease_until IS NOT NULL))
                """
            ).fetchall()
            for row in lease_projection:
                violations.append(f"lease_projection:{row['operation_id']}:{row['state']}")

            terminal_states = set(self.store.brain_contract["operation"]["terminal_states"])
            identity_rows = self.db.execute(
                """
                SELECT q.operation_id,q.repository,q.source_ref,q.operation_class,q.resolved_sha,q.priority,
                       q.state AS queue_state,
                       o.repository AS op_repository,o.source_ref AS op_source_ref,
                       o.resolved_sha AS op_sha,o.priority AS op_priority,
                       o.current_state AS operation_state,o.payload_json
                FROM queue_entries q
                LEFT JOIN operations o ON o.operation_id=q.operation_id
                """
            ).fetchall()
            for row in identity_rows:
                if row["op_repository"] is None:
                    violations.append(f"orphan:{row['operation_id']}")
                    continue
                payload = json.loads(row["payload_json"])
                if (
                    row["repository"] != row["op_repository"]
                    or row["source_ref"] != row["op_source_ref"]
                    or row["resolved_sha"] != row["op_sha"]
                    or int(row["priority"]) != int(row["op_priority"])
                    or row["operation_class"] != payload["operation_class"]
                ):
                    violations.append(f"identity_drift:{row['operation_id']}")
                if (
                    row["operation_state"] in terminal_states
                    and row["queue_state"] in PENDING_STATES
                ):
                    violations.append(
                        f"terminal_operation_pending:{row['operation_id']}:{row['operation_state']}"
                    )

            entries = self.db.execute(
                "SELECT * FROM queue_entries ORDER BY enqueued_seq ASC"
            ).fetchall()
            for entry in entries:
                history_rows = self.db.execute(
                    """
                    SELECT history_id,action,from_state,to_state,reason,occurred_at,payload_json
                    FROM queue_history
                    WHERE operation_id=?
                    ORDER BY history_id ASC
                    """,
                    (entry["operation_id"],),
                ).fetchall()
                if not history_rows:
                    violations.append(f"missing_history:{entry['operation_id']}")
                    continue
                state: str | None = None
                for index, record in enumerate(history_rows):
                    if index == 0:
                        if record["action"] != "ENQUEUE" or record["from_state"] is not None:
                            violations.append(
                                f"invalid_initial_history:{entry['operation_id']}"
                            )
                            break
                    if record["from_state"] != state:
                        violations.append(
                            f"history_chain:{entry['operation_id']}:{record['history_id']}"
                        )
                        break
                    state = record["to_state"]
                if state != entry["state"]:
                    violations.append(
                        f"projection_mismatch:{entry['operation_id']}:{state}:{entry['state']}"
                    )

            report = {
                "schema_version": 1,
                "record_type": "APPLAB_DURABLE_QUEUE_INTEGRITY",
                "authority": "ORCHESTRATION_ONLY",
                "executor": "GITHUB_ACTIONS",
                "dispatch_performed": False,
                "violations": violations,
                "ok": not violations,
            }
            if started_snapshot:
                self.db.commit()
            return report
        except Exception:
            if started_snapshot and self.db.in_transaction:
                self.db.rollback()
            raise



def _persist_operation(
    store: storemod.SQLiteShadowStore,
    operation_id: str,
    repository: str,
    source_ref: str,
    sha: str,
    *,
    operation_class: str = "VERIFICATION",
    analysis_mode: str = "fast",
    priority: int = 200,
    force_generation: int = 0,
    preserve_for_calibration: bool = False,
) -> dict[str, Any]:
    op = brain._operation_fixture(
        operation_id,
        repository,
        source_ref,
        sha,
        "f" * 40,
        operation_class=operation_class,
        analysis_mode=analysis_mode,
        priority=priority,
        force_generation=force_generation,
        preserve_for_calibration=preserve_for_calibration,
    )
    store.put_operation(op)
    return op


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "queue.sqlite3"
        with storemod.SQLiteShadowStore(path) as store:
            q = DurablePerRepoQueue(
                store,
                max_ready_global=2,
                max_ready_per_repo=1,
                max_pending_global=8,
                max_pending_per_repo=4,
                max_active_global=2,
                max_active_per_repo=1,
                lease_seconds=10,
                retry_base_seconds=2,
            )
            old = _persist_operation(store, "op_a1", "owner/a", "refs/heads/main", "1" * 40)
            new = _persist_operation(
                store, "op_a2", "owner/a", "refs/heads/main", "2" * 40, force_generation=1
            )
            other = _persist_operation(
                store, "op_b1", "owner/b", "refs/heads/main", "3" * 40, priority=400
            )
            cert = _persist_operation(
                store,
                "op_cert",
                "owner/c",
                "refs/heads/release",
                "4" * 40,
                operation_class="CERTIFICATION",
                analysis_mode="certification",
                priority=500,
            )

            assert q.enqueue(old["operation_id"], now_ts=100)["state"] == "QUEUED"
            second = q.enqueue(
                new["operation_id"],
                ancestor_shas={old["resolved_sha"]},
                ancestry_proven=True,
                now_ts=101,
            )
            assert second["superseded"] == [old["operation_id"]]
            assert q._entry(old["operation_id"])["state"] == "SUPERSEDED"

            assert q.enqueue(other["operation_id"], now_ts=102)["state"] == "QUEUED"
            assert q.enqueue(cert["operation_id"], now_ts=103)["state"] == "DEFERRED"
            assert q.rebalance(now_ts=104) == []

            claim = q.claim_next("gha-1", now_ts=104)
            assert claim is not None and claim["operation_id"] == other["operation_id"]
            assert claim["dispatch_performed"] is False
            q.complete(other["operation_id"], "gha-1", now_ts=105)
            promoted = q.rebalance(now_ts=105)
            assert cert["operation_id"] in promoted
            cert_claim = q.claim_next("gha-2", now_ts=106)
            assert cert_claim is not None and cert_claim["operation_id"] == cert["operation_id"]

            retry = q.record_failure(
                cert["operation_id"],
                "gha-2",
                "INFRA_ERROR",
                retryable=True,
                now_ts=107,
            )
            assert retry["retry"] is True
            assert q.integrity_report()["ok"] is True

        with storemod.SQLiteShadowStore(path) as reopened:
            q2 = DurablePerRepoQueue(
                reopened,
                max_ready_global=2,
                max_ready_per_repo=1,
                max_pending_global=8,
                max_pending_per_repo=4,
                max_active_global=2,
                max_active_per_repo=1,
                lease_seconds=10,
                retry_base_seconds=2,
            )
            assert q2._entry(old["operation_id"])["state"] == "SUPERSEDED"
            assert q2._entry(cert["operation_id"])["retry_count"] == 1
            assert q2.integrity_report()["ok"] is True

    print("AppLab v5.4E Durable Per-Repo Queue self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v5.4E durable per-repository queue")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
