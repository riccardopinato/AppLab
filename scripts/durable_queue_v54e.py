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
ACTIVE_STATES = {"QUEUED", "LEASED"}
PENDING_STATES = {"QUEUED", "DEFERRED"}
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
    state TEXT NOT NULL,
    protected INTEGER NOT NULL DEFAULT 0,
    preserve_for_calibration INTEGER NOT NULL DEFAULT 0,
    enqueued_seq INTEGER NOT NULL UNIQUE,
    enqueued_at REAL NOT NULL,
    available_at REAL NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 2,
    leased_by TEXT,
    lease_until REAL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS queue_ready_idx
ON queue_entries(state, available_at, priority DESC, enqueued_seq ASC);

CREATE INDEX IF NOT EXISTS queue_repo_idx
ON queue_entries(repository, state, enqueued_seq ASC);

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

CREATE TRIGGER IF NOT EXISTS queue_history_no_update
BEFORE UPDATE ON queue_history BEGIN
    SELECT RAISE(ABORT, 'queue_history append-only');
END;

CREATE TRIGGER IF NOT EXISTS queue_history_no_delete
BEFORE DELETE ON queue_history BEGIN
    SELECT RAISE(ABORT, 'queue_history append-only');
END;

CREATE TABLE IF NOT EXISTS queue_repo_state (
    repository TEXT PRIMARY KEY,
    last_claim_seq INTEGER NOT NULL DEFAULT 0
);
"""


class DurablePerRepoQueue:
    def __init__(
        self,
        store: storemod.SQLiteShadowStore,
        *,
        max_ready_global: int = 8,
        max_ready_per_repo: int = 2,
        max_active_per_repo: int = 1,
        max_pending_global: int = 1000,
        max_age_bonus: int = 500,
        lease_seconds: int = 900,
        retry_base_seconds: int = 60,
    ) -> None:
        self.store = store
        self.db = store.db
        if min(
            max_ready_global,
            max_ready_per_repo,
            max_active_per_repo,
            max_pending_global,
            max_age_bonus,
            lease_seconds,
            retry_base_seconds,
        ) < 1:
            raise QueueError("queue limits must be positive")
        self.max_ready_global = max_ready_global
        self.max_ready_per_repo = max_ready_per_repo
        self.max_active_per_repo = max_active_per_repo
        self.max_pending_global = max_pending_global
        self.max_age_bonus = max_age_bonus
        self.lease_seconds = lease_seconds
        self.retry_base_seconds = retry_base_seconds
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
    ) -> None:
        self.db.execute(
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

    def _active_count(self) -> int:
        return self.db.execute(
            "SELECT COUNT(*) AS n FROM queue_entries WHERE state IN ('QUEUED','LEASED')"
        ).fetchone()["n"]

    def _pending_count(self) -> int:
        return self.db.execute(
            "SELECT COUNT(*) AS n FROM queue_entries WHERE state IN ('QUEUED','LEASED','DEFERRED')"
        ).fetchone()["n"]

    def _repo_ready_count(self, repository: str) -> int:
        return self.db.execute(
            """
            SELECT COUNT(*) AS n
            FROM queue_entries
            WHERE repository=? AND state IN ('QUEUED','LEASED')
            """,
            (repository,),
        ).fetchone()["n"]

    def _repo_leased_count(self, repository: str) -> int:
        return self.db.execute(
            "SELECT COUNT(*) AS n FROM queue_entries WHERE repository=? AND state='LEASED'",
            (repository,),
        ).fetchone()["n"]

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
            raise QueueError("ancestor set requires proven ancestry")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            existing = self._entry(operation_id)
            if existing is not None:
                if bool(existing["preserve_for_calibration"]) != bool(preserve_for_calibration):
                    raise QueueError("queue replay conflicts with preserve_for_calibration")
                if int(existing["max_retries"]) != int(max_retries):
                    raise QueueError("queue replay conflicts with max_retries")
                result = {
                    "status": "REPLAY",
                    "operation_id": operation_id,
                    "state": existing["state"],
                }
                self.db.commit()
                return result

            op = self._operation(operation_id)
            payload = json.loads(op["payload_json"])
            operation_class = str(payload["operation_class"])
            protected = operation_class in PROTECTED_CLASSES

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
                        self.db.execute(
                            "UPDATE queue_entries SET state='SUPERSEDED',updated_at=? WHERE operation_id=?",
                            (float(now_ts), old["operation_id"]),
                        )
                        self._history(
                            old["operation_id"],
                            "SUPERSEDE",
                            old["state"],
                            "SUPERSEDED",
                            "NEWER_DESCENDANT_SAME_LINEAGE",
                            now_ts,
                            {"superseded_by": operation_id},
                        )
                        superseded.append(old["operation_id"])

            if self._pending_count() >= self.max_pending_global:
                raise QueueError("queue hard pending limit reached")

            if protected:
                initial_state = "QUEUED"
                reason = "PROTECTED_WORK_ACCEPTED"
            elif (
                self._active_count() >= self.max_ready_global
                or self._repo_ready_count(op["repository"]) >= self.max_ready_per_repo
            ):
                initial_state = "DEFERRED"
                reason = "BACKPRESSURE"
            else:
                initial_state = "QUEUED"
                reason = "ENQUEUED"

            seq = self.db.execute(
                "SELECT COALESCE(MAX(enqueued_seq),0)+1 AS n FROM queue_entries"
            ).fetchone()["n"]
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
                    int(bool(preserve_for_calibration)),
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
                {"superseded": superseded},
            )
            self.db.commit()
            return {
                "status": "INSERTED",
                "operation_id": operation_id,
                "state": initial_state,
                "superseded": superseded,
            }
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def rebalance(self, *, now_ts: float) -> list[str]:
        promoted: list[str] = []
        try:
            self.db.execute("BEGIN IMMEDIATE")
            rows = self.db.execute(
                """
                SELECT *
                FROM queue_entries
                WHERE state='DEFERRED'
                ORDER BY priority DESC,enqueued_seq ASC
                """
            ).fetchall()
            for row in rows:
                if self._active_count() >= self.max_ready_global:
                    break
                if self._repo_ready_count(row["repository"]) >= self.max_ready_per_repo:
                    continue
                self.db.execute(
                    "UPDATE queue_entries SET state='QUEUED',updated_at=? WHERE operation_id=?",
                    (float(now_ts), row["operation_id"]),
                )
                self._history(
                    row["operation_id"],
                    "PROMOTE",
                    "DEFERRED",
                    "QUEUED",
                    "BACKPRESSURE_RELEASED",
                    now_ts,
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
            leased_repos = {
                row["repository"]
                for row in self.db.execute(
                    "SELECT DISTINCT repository FROM queue_entries WHERE state='LEASED'"
                ).fetchall()
            }
            rows = self.db.execute(
                """
                SELECT q.*, COALESCE(r.last_claim_seq,0) AS last_claim_seq
                FROM queue_entries q
                LEFT JOIN queue_repo_state r ON r.repository=q.repository
                WHERE q.state='QUEUED' AND q.available_at<=?
                """,
                (float(now_ts),),
            ).fetchall()
            candidates = []
            for row in rows:
                if self._repo_leased_count(row["repository"]) >= self.max_active_per_repo:
                    continue
                age_bonus = min(
                    max(int((float(now_ts) - row["enqueued_at"]) // 60), 0),
                    self.max_age_bonus,
                )
                candidates.append((-(row["priority"] + age_bonus), row["last_claim_seq"], row["enqueued_seq"], row))
            if not candidates:
                self.db.commit()
                return None

            candidates.sort(key=lambda item: (item[0], item[1], item[2]))
            row = candidates[0][3]
            lease_until = float(now_ts) + self.lease_seconds
            self.db.execute(
                """
                UPDATE queue_entries
                SET state='LEASED',leased_by=?,lease_until=?,updated_at=?
                WHERE operation_id=?
                """,
                (worker_id, lease_until, float(now_ts), row["operation_id"]),
            )
            next_claim_seq = self.db.execute(
                "SELECT COALESCE(MAX(last_claim_seq),0)+1 AS n FROM queue_repo_state"
            ).fetchone()["n"]
            self.db.execute(
                """
                INSERT INTO queue_repo_state(repository,last_claim_seq)
                VALUES (?,?)
                ON CONFLICT(repository) DO UPDATE SET last_claim_seq=excluded.last_claim_seq
                """,
                (row["repository"], next_claim_seq),
            )
            self._history(
                row["operation_id"],
                "CLAIM",
                "QUEUED",
                "LEASED",
                "GITHUB_ACTIONS_EXECUTOR_INTENT",
                now_ts,
                {"worker_id": worker_id, "lease_until": lease_until},
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

    def complete(self, operation_id: str, worker_id: str, *, now_ts: float) -> None:
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self._entry(operation_id)
            if row is None or row["state"] != "LEASED":
                raise QueueError("operation is not leased")
            if row["leased_by"] != worker_id:
                raise QueueError("lease owner mismatch")
            self.db.execute(
                """
                UPDATE queue_entries
                SET state='DONE',leased_by=NULL,lease_until=NULL,updated_at=?
                WHERE operation_id=?
                """,
                (float(now_ts), operation_id),
            )
            self._history(operation_id, "COMPLETE", "LEASED", "DONE", "EXECUTOR_COMPLETED", now_ts)
            self.db.commit()
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
                retryable
                and failure_class in RETRYABLE_FAILURES
                and row["retry_count"] < row["max_retries"]
            )
            if can_retry:
                next_retry = row["retry_count"] + 1
                delay = self.retry_base_seconds * (2 ** (next_retry - 1))
                available_at = float(now_ts) + delay
                self.db.execute(
                    """
                    UPDATE queue_entries
                    SET state='QUEUED',retry_count=?,available_at=?,
                        leased_by=NULL,lease_until=NULL,updated_at=?
                    WHERE operation_id=?
                    """,
                    (next_retry, available_at, float(now_ts), operation_id),
                )
                self._history(
                    operation_id,
                    "RETRY",
                    "LEASED",
                    "QUEUED",
                    failure_class,
                    now_ts,
                    {"retry_count": next_retry, "available_at": available_at},
                )
                self.db.commit()
                return {
                    "retry": True,
                    "retry_count": next_retry,
                    "available_at": available_at,
                }

            self.db.execute(
                """
                UPDATE queue_entries
                SET state='BLOCKED',leased_by=NULL,lease_until=NULL,updated_at=?
                WHERE operation_id=?
                """,
                (float(now_ts), operation_id),
            )
            self._history(
                operation_id,
                "FAIL_TERMINAL",
                "LEASED",
                "BLOCKED",
                failure_class,
                now_ts,
                {"retryable_requested": bool(retryable)},
            )
            self.db.commit()
            return {"retry": False, "state": "BLOCKED"}
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def recover_expired_leases(self, *, now_ts: float) -> list[dict[str, Any]]:
        recovered = []
        rows = self.db.execute(
            """
            SELECT operation_id,leased_by
            FROM queue_entries
            WHERE state='LEASED' AND lease_until IS NOT NULL AND lease_until<?
            ORDER BY enqueued_seq ASC
            """,
            (float(now_ts),),
        ).fetchall()
        for row in rows:
            recovered.append(
                {
                    "operation_id": row["operation_id"],
                    **self.record_failure(
                        row["operation_id"],
                        row["leased_by"],
                        "INFRA_ERROR",
                        retryable=True,
                        now_ts=now_ts,
                    ),
                }
            )
        return recovered

    def snapshot(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT * FROM queue_entries ORDER BY enqueued_seq ASC"
        ).fetchall()
        return [dict(row) for row in rows]

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
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    def integrity_report(self) -> dict[str, Any]:
        violations: list[str] = []
        leased = self.db.execute(
            """
            SELECT repository,COUNT(*) AS n
            FROM queue_entries
            WHERE state='LEASED'
            GROUP BY repository
            HAVING COUNT(*)>?
            """,
            (self.max_active_per_repo,),
        ).fetchall()
        for row in leased:
            violations.append(f"repo_active_limit:{row['repository']}:{row['n']}")
        pending_count = self._pending_count()
        if pending_count > self.max_pending_global:
            violations.append(
                f"global_pending_limit:{pending_count}:{self.max_pending_global}"
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
        orphans = self.db.execute(
            """
            SELECT q.operation_id
            FROM queue_entries q
            LEFT JOIN operations o ON o.operation_id=q.operation_id
            WHERE o.operation_id IS NULL
            """
        ).fetchall()
        for row in orphans:
            violations.append(f"orphan:{row['operation_id']}")
        return {
            "schema_version": 1,
            "record_type": "APPLAB_DURABLE_QUEUE_INTEGRITY",
            "authority": "ORCHESTRATION_ONLY",
            "executor": "GITHUB_ACTIONS",
            "dispatch_performed": False,
            "violations": violations,
            "ok": not violations,
        }


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
                max_active_per_repo=1,
                lease_seconds=10,
                retry_base_seconds=2,
            )
            old = _persist_operation(store, "op_a1", "owner/a", "refs/heads/main", "1" * 40)
            new = _persist_operation(store, "op_a2", "owner/a", "refs/heads/main", "2" * 40, force_generation=1)
            other = _persist_operation(store, "op_b1", "owner/b", "refs/heads/main", "3" * 40, priority=400)
            cert = _persist_operation(
                store,
                "op_cert",
                "owner/a",
                "refs/heads/main",
                "4" * 40,
                operation_class="CERTIFICATION",
                analysis_mode="certification",
                priority=500,
            )

            assert q.enqueue(old["operation_id"], now_ts=100)["state"] == "QUEUED"
            second = q.enqueue(new["operation_id"], ancestor_shas={old["resolved_sha"]}, ancestry_proven=True, now_ts=101)
            assert old["operation_id"] in second["superseded"]
            assert q._entry(old["operation_id"])["state"] == "SUPERSEDED"

            assert q.enqueue(other["operation_id"], now_ts=102)["state"] == "QUEUED"
            assert q.enqueue(cert["operation_id"], now_ts=103)["state"] == "QUEUED"

            claim = q.claim_next("gha-1", now_ts=104)
            assert claim is not None
            assert claim["operation_id"] == cert["operation_id"]
            assert claim["executor"] == "GITHUB_ACTIONS"
            assert claim["dispatch_performed"] is False

            retry = q.record_failure(
                cert["operation_id"],
                "gha-1",
                "INFRA_ERROR",
                retryable=True,
                now_ts=105,
            )
            assert retry["retry"] is True
            assert q.claim_next("gha-2", now_ts=105) is not None

            q.integrity_report()["ok"]

        with storemod.SQLiteShadowStore(path) as reopened:
            q2 = DurablePerRepoQueue(
                reopened,
                max_ready_global=2,
                max_ready_per_repo=1,
                max_active_per_repo=1,
                lease_seconds=10,
                retry_base_seconds=2,
            )
            assert q2._entry(old["operation_id"])["state"] == "SUPERSEDED"
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
