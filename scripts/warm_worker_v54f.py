#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import durable_store_v54b as storemod
import durable_brain_v54a as brain

WORKER_STATES = {"STARTING", "AVAILABLE", "LEASED", "SCRUBBING", "UNHEALTHY", "QUARANTINED", "DRAINING", "OFFLINE"}
LEASE_STATES = {"ACTIVE", "RELEASED", "UNKNOWN", "QUARANTINED"}
TRUSTED_CLASS = "WARM_TRUSTED_ANDROID"


class WorkerError(ValueError):
    pass


WORKER_SCHEMA = """
CREATE TABLE IF NOT EXISTS warm_workers (
    worker_id TEXT PRIMARY KEY,
    worker_class TEXT NOT NULL,
    applab_sha TEXT NOT NULL,
    runtime_profiles_json TEXT NOT NULL,
    snapshot_digest TEXT NOT NULL,
    state TEXT NOT NULL,
    last_heartbeat REAL NOT NULL,
    current_lease_id TEXT,
    isolation_generation INTEGER NOT NULL DEFAULT 1,
    health_reason TEXT,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS warm_worker_leases (
    lease_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    worker_id TEXT NOT NULL REFERENCES warm_workers(worker_id),
    state TEXT NOT NULL,
    acquired_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    released_at REAL,
    cleanup_proven INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_lease_per_worker
ON warm_worker_leases(worker_id)
WHERE state='ACTIVE';

CREATE TABLE IF NOT EXISTS warm_worker_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT NOT NULL,
    lease_id TEXT,
    action TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    reason TEXT NOT NULL,
    occurred_at REAL NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS warm_history_no_update
BEFORE UPDATE ON warm_worker_history BEGIN
  SELECT RAISE(ABORT, 'warm_worker_history append-only');
END;

CREATE TRIGGER IF NOT EXISTS warm_history_no_delete
BEFORE DELETE ON warm_worker_history BEGIN
  SELECT RAISE(ABORT, 'warm_worker_history append-only');
END;
"""


class WarmWorkerPool:
    def __init__(self, store: storemod.SQLiteShadowStore, *, lease_seconds: int = 900, heartbeat_timeout: int = 120) -> None:
        if lease_seconds < 1 or heartbeat_timeout < 1:
            raise WorkerError("worker timeouts must be positive")
        self.store = store
        self.db = store.db
        self.lease_seconds = lease_seconds
        self.heartbeat_timeout = heartbeat_timeout
        self.db.executescript(WORKER_SCHEMA)
        self.db.commit()

    def _history(
        self,
        worker_id: str,
        action: str,
        from_state: str | None,
        to_state: str,
        reason: str,
        now_ts: float,
        *,
        lease_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO warm_worker_history(
              worker_id,lease_id,action,from_state,to_state,reason,occurred_at,payload_json
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                worker_id, lease_id, action, from_state, to_state, reason,
                float(now_ts), brain.canonical_json(payload or {}),
            ),
        )

    def register(
        self,
        worker_id: str,
        *,
        applab_sha: str,
        runtime_profiles: list[str],
        snapshot_digest: str,
        now_ts: float,
        worker_class: str = TRUSTED_CLASS,
    ) -> None:
        worker_id = brain._require_non_empty_string(worker_id, "worker_id")
        brain._require_sha(applab_sha, "worker.applab_sha")
        if worker_class != TRUSTED_CLASS:
            raise WorkerError("initial warm pool accepts only WARM_TRUSTED_ANDROID")
        if not runtime_profiles or any(not isinstance(x, str) or not x for x in runtime_profiles):
            raise WorkerError("runtime_profiles must be non-empty strings")
        if not snapshot_digest.startswith("sha256:"):
            raise WorkerError("snapshot_digest must be sha256-bound")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            existing = self.db.execute(
                "SELECT state,current_lease_id FROM warm_workers WHERE worker_id=?",
                (worker_id,),
            ).fetchone()
            if existing and existing["current_lease_id"]:
                raise WorkerError("cannot re-register leased worker")
            previous = existing["state"] if existing else None
            self.db.execute(
                """
                INSERT INTO warm_workers(
                  worker_id,worker_class,applab_sha,runtime_profiles_json,snapshot_digest,
                  state,last_heartbeat,current_lease_id,isolation_generation,health_reason,updated_at
                ) VALUES (?,?,?,?,?,'AVAILABLE',?,NULL,1,NULL,?)
                ON CONFLICT(worker_id) DO UPDATE SET
                  worker_class=excluded.worker_class,
                  applab_sha=excluded.applab_sha,
                  runtime_profiles_json=excluded.runtime_profiles_json,
                  snapshot_digest=excluded.snapshot_digest,
                  state='AVAILABLE',
                  last_heartbeat=excluded.last_heartbeat,
                  current_lease_id=NULL,
                  isolation_generation=warm_workers.isolation_generation+1,
                  health_reason=NULL,
                  updated_at=excluded.updated_at
                """,
                (
                    worker_id, worker_class, applab_sha,
                    json.dumps(sorted(set(runtime_profiles))),
                    snapshot_digest, float(now_ts), float(now_ts),
                ),
            )
            self._history(worker_id, "REGISTER", previous, "AVAILABLE", "IDENTITY_VERIFIED", now_ts)
            self.db.commit()
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def heartbeat(self, worker_id: str, *, now_ts: float, lease_id: str | None = None) -> None:
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                "SELECT state,current_lease_id FROM warm_workers WHERE worker_id=?",
                (worker_id,),
            ).fetchone()
            if row is None:
                raise WorkerError("unknown worker")
            if row["state"] == "LEASED" and row["current_lease_id"] != lease_id:
                raise WorkerError("heartbeat lease mismatch")
            self.db.execute(
                "UPDATE warm_workers SET last_heartbeat=?,updated_at=? WHERE worker_id=?",
                (float(now_ts), float(now_ts), worker_id),
            )
            self.db.commit()
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def acquire(
        self,
        operation_id: str,
        *,
        required_applab_sha: str,
        runtime_profile: str,
        now_ts: float,
    ) -> dict[str, Any]:
        brain._require_sha(required_applab_sha, "required_applab_sha")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            op = self.db.execute(
                "SELECT operation_id FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if op is None:
                raise WorkerError("operation must exist before worker lease")

            rows = self.db.execute(
                """
                SELECT *
                FROM warm_workers
                WHERE state='AVAILABLE'
                ORDER BY last_heartbeat DESC,worker_id ASC
                """
            ).fetchall()
            chosen = None
            for row in rows:
                if row["applab_sha"] != required_applab_sha:
                    continue
                if float(now_ts) - row["last_heartbeat"] > self.heartbeat_timeout:
                    continue
                profiles = set(json.loads(row["runtime_profiles_json"]))
                if runtime_profile not in profiles:
                    continue
                chosen = row
                break
            if chosen is None:
                self.db.commit()
                return {
                    "eligible": False,
                    "executor": "GITHUB_ACTIONS",
                    "fallback": True,
                    "dispatch_performed": False,
                    "reason": "NO_ELIGIBLE_WARM_WORKER",
                }

            lease_id = "lease_" + brain.sha256_json({
                "operation_id": operation_id,
                "worker_id": chosen["worker_id"],
                "generation": chosen["isolation_generation"],
                "acquired_at": float(now_ts),
            }).split(":", 1)[1][:32]
            expires_at = float(now_ts) + self.lease_seconds
            self.db.execute(
                """
                INSERT INTO warm_worker_leases(
                  lease_id,operation_id,worker_id,state,acquired_at,expires_at,payload_json
                ) VALUES (?,?,?,'ACTIVE',?,?,?)
                """,
                (
                    lease_id, operation_id, chosen["worker_id"], float(now_ts),
                    expires_at,
                    brain.canonical_json({
                        "applab_sha": chosen["applab_sha"],
                        "snapshot_digest": chosen["snapshot_digest"],
                        "runtime_profile": runtime_profile,
                        "isolation_generation": chosen["isolation_generation"],
                    }),
                ),
            )
            self.db.execute(
                """
                UPDATE warm_workers
                SET state='LEASED',current_lease_id=?,updated_at=?
                WHERE worker_id=?
                """,
                (lease_id, float(now_ts), chosen["worker_id"]),
            )
            self._history(
                chosen["worker_id"], "LEASE", "AVAILABLE", "LEASED",
                "CAPABILITY_MATCH", now_ts, lease_id=lease_id,
                payload={"operation_id": operation_id},
            )
            self.db.commit()
            return {
                "eligible": True,
                "executor": TRUSTED_CLASS,
                "fallback": False,
                "dispatch_performed": False,
                "worker_id": chosen["worker_id"],
                "lease_id": lease_id,
                "expires_at": expires_at,
                "snapshot_digest": chosen["snapshot_digest"],
            }
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def begin_scrub(self, worker_id: str, lease_id: str, *, now_ts: float) -> None:
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                "SELECT state,current_lease_id FROM warm_workers WHERE worker_id=?",
                (worker_id,),
            ).fetchone()
            if row is None or row["state"] != "LEASED" or row["current_lease_id"] != lease_id:
                raise WorkerError("invalid lease for scrub")
            self.db.execute(
                "UPDATE warm_workers SET state='SCRUBBING',updated_at=? WHERE worker_id=?",
                (float(now_ts), worker_id),
            )
            self._history(worker_id, "SCRUB_START", "LEASED", "SCRUBBING", "RUNTIME_FINISHED", now_ts, lease_id=lease_id)
            self.db.commit()
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def finish_scrub(
        self,
        worker_id: str,
        lease_id: str,
        *,
        cleanup_proven: bool,
        now_ts: float,
        reason: str = "CLEANUP_VERIFIED",
    ) -> None:
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                "SELECT state,current_lease_id FROM warm_workers WHERE worker_id=?",
                (worker_id,),
            ).fetchone()
            if row is None or row["state"] != "SCRUBBING" or row["current_lease_id"] != lease_id:
                raise WorkerError("worker is not scrubbing this lease")
            lease = self.db.execute(
                "SELECT state FROM warm_worker_leases WHERE lease_id=? AND worker_id=?",
                (lease_id, worker_id),
            ).fetchone()
            if lease is None or lease["state"] != "ACTIVE":
                raise WorkerError("active worker lease missing")

            if cleanup_proven:
                self.db.execute(
                    """
                    UPDATE warm_worker_leases
                    SET state='RELEASED',released_at=?,cleanup_proven=1
                    WHERE lease_id=?
                    """,
                    (float(now_ts), lease_id),
                )
                self.db.execute(
                    """
                    UPDATE warm_workers
                    SET state='AVAILABLE',current_lease_id=NULL,health_reason=NULL,
                        last_heartbeat=?,updated_at=?
                    WHERE worker_id=?
                    """,
                    (float(now_ts), float(now_ts), worker_id),
                )
                self._history(worker_id, "SCRUB_OK", "SCRUBBING", "AVAILABLE", reason, now_ts, lease_id=lease_id)
            else:
                self.db.execute(
                    """
                    UPDATE warm_worker_leases
                    SET state='QUARANTINED',released_at=?,cleanup_proven=0
                    WHERE lease_id=?
                    """,
                    (float(now_ts), lease_id),
                )
                self.db.execute(
                    """
                    UPDATE warm_workers
                    SET state='QUARANTINED',current_lease_id=NULL,health_reason=?,updated_at=?
                    WHERE worker_id=?
                    """,
                    (reason, float(now_ts), worker_id),
                )
                self._history(worker_id, "SCRUB_FAIL", "SCRUBBING", "QUARANTINED", reason, now_ts, lease_id=lease_id)
            self.db.commit()
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def reconcile_heartbeats(self, *, now_ts: float) -> list[str]:
        quarantined: list[str] = []
        try:
            self.db.execute("BEGIN IMMEDIATE")
            rows = self.db.execute(
                """
                SELECT worker_id,state,current_lease_id,last_heartbeat
                FROM warm_workers
                WHERE state IN ('AVAILABLE','LEASED','SCRUBBING')
                """
            ).fetchall()
            for row in rows:
                if float(now_ts) - row["last_heartbeat"] <= self.heartbeat_timeout:
                    continue
                if row["current_lease_id"]:
                    self.db.execute(
                        "UPDATE warm_worker_leases SET state='UNKNOWN' WHERE lease_id=? AND state='ACTIVE'",
                        (row["current_lease_id"],),
                    )
                self.db.execute(
                    """
                    UPDATE warm_workers
                    SET state='QUARANTINED',health_reason='HEARTBEAT_TIMEOUT',updated_at=?
                    WHERE worker_id=?
                    """,
                    (float(now_ts), row["worker_id"]),
                )
                self._history(
                    row["worker_id"], "HEARTBEAT_LOST", row["state"], "QUARANTINED",
                    "HEARTBEAT_TIMEOUT", now_ts, lease_id=row["current_lease_id"],
                )
                quarantined.append(row["worker_id"])
            self.db.commit()
            return quarantined
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def worker(self, worker_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM warm_workers WHERE worker_id=?", (worker_id,)).fetchone()
        if row is None:
            raise WorkerError("unknown worker")
        result = dict(row)
        result["runtime_profiles"] = json.loads(result.pop("runtime_profiles_json"))
        return result

    def integrity_report(self) -> dict[str, Any]:
        violations: list[str] = []
        rows = self.db.execute(
            """
            SELECT w.worker_id,w.state,w.current_lease_id,l.state AS lease_state
            FROM warm_workers w
            LEFT JOIN warm_worker_leases l ON l.lease_id=w.current_lease_id
            """
        ).fetchall()
        for row in rows:
            if row["state"] in {"LEASED","SCRUBBING"} and row["lease_state"] != "ACTIVE":
                violations.append(f"lease_projection:{row['worker_id']}")
            if row["state"] == "AVAILABLE" and row["current_lease_id"] is not None:
                violations.append(f"available_has_lease:{row['worker_id']}")
        return {
            "schema_version": 1,
            "record_type": "APPLAB_WARM_WORKER_INTEGRITY",
            "authority": "NONE_WORKER_CAPABILITY_ONLY",
            "violations": violations,
            "ok": not violations,
        }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "worker.sqlite3"
        with storemod.SQLiteShadowStore(path) as store:
            op = brain._operation_fixture("op_warm", "owner/app", "refs/heads/main", "a"*40, "b"*40)
            store.put_operation(op)
            pool = WarmWorkerPool(store, lease_seconds=10, heartbeat_timeout=5)
            pool.register(
                "warm-1",
                applab_sha="b"*40,
                runtime_profiles=["android-default"],
                snapshot_digest="sha256:" + "1"*64,
                now_ts=100,
            )
            lease = pool.acquire(
                op["operation_id"],
                required_applab_sha="b"*40,
                runtime_profile="android-default",
                now_ts=101,
            )
            assert lease["eligible"] is True
            assert lease["fallback"] is False
            assert lease["dispatch_performed"] is False

            no_second = pool.acquire(
                op["operation_id"],
                required_applab_sha="b"*40,
                runtime_profile="android-default",
                now_ts=102,
            )
            assert no_second["fallback"] is True

            pool.heartbeat("warm-1", now_ts=103, lease_id=lease["lease_id"])
            pool.begin_scrub("warm-1", lease["lease_id"], now_ts=104)
            pool.finish_scrub("warm-1", lease["lease_id"], cleanup_proven=True, now_ts=105)
            assert pool.worker("warm-1")["state"] == "AVAILABLE"

            mismatch = pool.acquire(
                op["operation_id"],
                required_applab_sha="c"*40,
                runtime_profile="android-default",
                now_ts=106,
            )
            assert mismatch["fallback"] is True
            assert mismatch["executor"] == "GITHUB_ACTIONS"

            lease2 = pool.acquire(
                op["operation_id"],
                required_applab_sha="b"*40,
                runtime_profile="android-default",
                now_ts=107,
            )
            pool.begin_scrub("warm-1", lease2["lease_id"], now_ts=108)
            pool.finish_scrub(
                "warm-1", lease2["lease_id"], cleanup_proven=False,
                now_ts=109, reason="RESIDUAL_STATE_DETECTED",
            )
            assert pool.worker("warm-1")["state"] == "QUARANTINED"
            assert pool.integrity_report()["ok"] is True

    print("AppLab v5.4F Warm Worker protocol self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v5.4F warm trusted-runtime worker protocol")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
