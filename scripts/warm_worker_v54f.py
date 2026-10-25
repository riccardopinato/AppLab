#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import durable_brain_v54a as brain
import durable_store_v54b as storemod

WORKER_CLASS = "WARM_TRUSTED_ANDROID"
FALLBACK_EXECUTOR = "GITHUB_ACTIONS"
ELIGIBLE_STATES = {"AVAILABLE"}
QUARANTINE_STATES = {"LEASED", "SCRUBBING", "AVAILABLE", "UNHEALTHY"}
REQUIRED_CLEANUP_ATTESTATIONS = (
    "emulator_destroyed",
    "target_processes_absent",
    "app_data_discarded",
    "snapshot_digest_verified",
    "evidence_hashes_verified",
)


class WorkerError(ValueError):
    pass


WORKER_SCHEMA = """
CREATE TABLE IF NOT EXISTS warm_workers (
    worker_id TEXT PRIMARY KEY,
    worker_class TEXT NOT NULL,
    state TEXT NOT NULL,
    applab_sha TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    capability_digest_sha256 TEXT NOT NULL,
    snapshot_digest_sha256 TEXT NOT NULL,
    heartbeat_at REAL NOT NULL,
    current_lease_id TEXT,
    quarantine_reason TEXT,
    registered_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS warm_worker_leases (
    lease_id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL REFERENCES warm_workers(worker_id),
    operation_id TEXT NOT NULL,
    issued_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    status TEXT NOT NULL,
    cleanup_attested INTEGER NOT NULL DEFAULT 0 CHECK (cleanup_attested IN (0,1)),
    released_at REAL
);

CREATE INDEX IF NOT EXISTS warm_worker_lease_worker_idx
ON warm_worker_leases(worker_id, status, issued_at);

CREATE UNIQUE INDEX IF NOT EXISTS warm_worker_active_lease_one_per_worker
ON warm_worker_leases(worker_id)
WHERE status='ACTIVE';

CREATE TRIGGER IF NOT EXISTS warm_lease_identity_no_update
BEFORE UPDATE OF lease_id,worker_id,operation_id,issued_at,expires_at
ON warm_worker_leases
BEGIN
    SELECT RAISE(ABORT, 'warm lease immutable identity');
END;

CREATE TRIGGER IF NOT EXISTS warm_lease_no_delete
BEFORE DELETE ON warm_worker_leases
BEGIN
    SELECT RAISE(ABORT, 'warm lease cannot be deleted');
END;

CREATE TABLE IF NOT EXISTS warm_worker_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT NOT NULL REFERENCES warm_workers(worker_id),
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

CREATE TRIGGER IF NOT EXISTS warm_worker_identity_no_update
BEFORE UPDATE OF
    worker_id,worker_class,applab_sha,capabilities_json,
    capability_digest_sha256,snapshot_digest_sha256,registered_at
ON warm_workers
BEGIN
    SELECT RAISE(ABORT, 'warm worker immutable identity');
END;

CREATE TRIGGER IF NOT EXISTS warm_worker_no_delete
BEFORE DELETE ON warm_workers BEGIN
    SELECT RAISE(ABORT, 'warm worker cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS warm_worker_state_requires_history
BEFORE UPDATE OF state ON warm_workers
WHEN NEW.state <> OLD.state
AND NOT EXISTS (
    SELECT 1
    FROM warm_worker_history h
    WHERE h.worker_id=OLD.worker_id
      AND h.from_state IS OLD.state
      AND h.to_state=NEW.state
      AND h.history_id=(
          SELECT MAX(h2.history_id)
          FROM warm_worker_history h2
          WHERE h2.worker_id=OLD.worker_id
      )
)
BEGIN
    SELECT RAISE(ABORT, 'warm worker state update requires history');
END;
"""


def _sha256_json(payload: Any) -> str:
    return brain.sha256_json(payload)


def _require_digest(value: Any, label: str) -> str:
    text = brain._require_non_empty_string(value, label)
    if not text.startswith("sha256:") or len(text) != 71:
        raise WorkerError(f"{label} must be sha256:<64 hex>")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise WorkerError(f"{label} must be sha256:<64 hex>") from exc
    return text.lower()


def normalize_capabilities(capabilities: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(capabilities, dict):
        raise WorkerError("capabilities must be object")
    profiles = capabilities.get("runtime_profiles")
    if not isinstance(profiles, list) or not profiles:
        raise WorkerError("runtime_profiles must be non-empty list")
    if any(not isinstance(item, str) or not item for item in profiles):
        raise WorkerError("runtime_profiles must contain non-empty strings")
    normalized = {
        "kvm": bool(capabilities.get("kvm")),
        "android_runtime": bool(capabilities.get("android_runtime")),
        "disposable_avd": bool(capabilities.get("disposable_avd")),
        "evidence_capture": bool(capabilities.get("evidence_capture")),
        "runtime_profiles": sorted(set(profiles)),
        "api_levels": sorted({int(x) for x in (capabilities.get("api_levels") or [])}),
        "screen_capture": bool(capabilities.get("screen_capture", True)),
    }
    return normalized


class WarmWorkerRegistry:
    def __init__(
        self,
        store: storemod.SQLiteShadowStore,
        *,
        heartbeat_ttl_seconds: int = 90,
        default_lease_seconds: int = 900,
    ) -> None:
        if heartbeat_ttl_seconds < 1 or default_lease_seconds < 1:
            raise WorkerError("worker timing limits must be positive")
        self.store = store
        self.db = store.db
        self.heartbeat_ttl_seconds = int(heartbeat_ttl_seconds)
        self.default_lease_seconds = int(default_lease_seconds)
        self.db.executescript(WORKER_SCHEMA)
        self.db.commit()

    def _worker(self, worker_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM warm_workers WHERE worker_id=?",
            (worker_id,),
        ).fetchone()

    def _lease(self, lease_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM warm_worker_leases WHERE lease_id=?",
            (lease_id,),
        ).fetchone()

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
                worker_id,
                lease_id,
                action,
                from_state,
                to_state,
                reason,
                float(now_ts),
                brain.canonical_json(payload or {}),
            ),
        )

    def register(
        self,
        worker_id: str,
        applab_sha: str,
        capabilities: dict[str, Any],
        snapshot_digest_sha256: str,
        *,
        now_ts: float,
    ) -> dict[str, Any]:
        worker_id = brain._require_non_empty_string(worker_id, "worker_id")
        applab_sha = brain._require_sha(applab_sha, "worker.applab_sha")
        snapshot_digest_sha256 = _require_digest(
            snapshot_digest_sha256, "snapshot_digest_sha256"
        )
        normalized = normalize_capabilities(capabilities)
        required_flags = ("kvm", "android_runtime", "disposable_avd", "evidence_capture")
        if not all(normalized[key] for key in required_flags):
            raise WorkerError("warm worker missing mandatory trusted-runtime capability")
        capability_digest = _sha256_json(normalized)

        try:
            self.db.execute("BEGIN IMMEDIATE")
            existing = self._worker(worker_id)
            if existing is not None:
                if (
                    existing["worker_class"] != WORKER_CLASS
                    or existing["applab_sha"] != applab_sha
                    or existing["capability_digest_sha256"] != capability_digest
                    or existing["snapshot_digest_sha256"] != snapshot_digest_sha256
                ):
                    raise WorkerError("worker_id reused with conflicting immutable identity")
                self.db.execute(
                    """
                    UPDATE warm_workers
                    SET heartbeat_at=?,updated_at=?
                    WHERE worker_id=?
                    """,
                    (float(now_ts), float(now_ts), worker_id),
                )
                self.db.commit()
                return {"status": "REPLAY", "worker_id": worker_id, "state": existing["state"]}

            self.db.execute(
                """
                INSERT INTO warm_workers(
                    worker_id,worker_class,state,applab_sha,capabilities_json,
                    capability_digest_sha256,snapshot_digest_sha256,heartbeat_at,
                    current_lease_id,quarantine_reason,registered_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    worker_id,
                    WORKER_CLASS,
                    "STARTING",
                    applab_sha,
                    brain.canonical_json(normalized),
                    capability_digest,
                    snapshot_digest_sha256,
                    float(now_ts),
                    None,
                    None,
                    float(now_ts),
                    float(now_ts),
                ),
            )
            self._history(
                worker_id,
                "REGISTER",
                None,
                "STARTING",
                "WORKER_REGISTERED",
                now_ts,
                payload={"capability_digest_sha256": capability_digest},
            )
            self.db.commit()
            return {"status": "INSERTED", "worker_id": worker_id, "state": "STARTING"}
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def activate(
        self,
        worker_id: str,
        *,
        now_ts: float,
        kvm_attested: bool,
        snapshot_verified: bool,
        clean_process_table: bool,
    ) -> dict[str, Any]:
        try:
            self.db.execute("BEGIN IMMEDIATE")
            worker = self._worker(worker_id)
            if worker is None:
                raise WorkerError("unknown worker")
            if worker["state"] != "STARTING":
                raise WorkerError("only STARTING worker may activate")
            if not (kvm_attested and snapshot_verified and clean_process_table):
                raise WorkerError("worker activation attestation incomplete")
            self._history(
                worker_id,
                "ACTIVATE",
                "STARTING",
                "AVAILABLE",
                "TRUSTED_RUNTIME_READY",
                now_ts,
                payload={
                    "kvm_attested": True,
                    "snapshot_verified": True,
                    "clean_process_table": True,
                },
            )
            self.db.execute(
                """
                UPDATE warm_workers
                SET state='AVAILABLE',heartbeat_at=?,updated_at=?
                WHERE worker_id=?
                """,
                (float(now_ts), float(now_ts), worker_id),
            )
            self.db.commit()
            return {"worker_id": worker_id, "state": "AVAILABLE"}
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def heartbeat(self, worker_id: str, *, now_ts: float) -> dict[str, Any]:
        try:
            self.db.execute("BEGIN IMMEDIATE")
            worker = self._worker(worker_id)
            if worker is None:
                raise WorkerError("unknown worker")
            if worker["state"] in {"OFFLINE", "QUARANTINED"}:
                raise WorkerError("offline/quarantined worker cannot heartbeat into service")
            self.db.execute(
                """
                UPDATE warm_workers
                SET heartbeat_at=?,updated_at=?
                WHERE worker_id=?
                """,
                (float(now_ts), float(now_ts), worker_id),
            )
            self.db.commit()
            return {"worker_id": worker_id, "heartbeat_at": float(now_ts)}
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def _eligible(
        self,
        worker: sqlite3.Row,
        required_applab_sha: str,
        runtime_profile: str,
        now_ts: float,
    ) -> bool:
        if worker["state"] not in ELIGIBLE_STATES:
            return False
        if worker["current_lease_id"] is not None:
            return False
        if worker["applab_sha"] != required_applab_sha:
            return False
        if float(now_ts) - float(worker["heartbeat_at"]) > self.heartbeat_ttl_seconds:
            return False
        capabilities = json.loads(worker["capabilities_json"])
        if runtime_profile not in capabilities.get("runtime_profiles", []):
            return False
        if not all(
            bool(capabilities.get(key))
            for key in ("kvm", "android_runtime", "disposable_avd", "evidence_capture")
        ):
            return False
        return True

    def acquire_lease(
        self,
        operation_id: str,
        required_applab_sha: str,
        runtime_profile: str,
        *,
        now_ts: float,
        lease_seconds: int | None = None,
    ) -> dict[str, Any]:
        operation_id = brain._require_non_empty_string(operation_id, "operation_id")
        required_applab_sha = brain._require_sha(
            required_applab_sha, "required_applab_sha"
        )
        runtime_profile = brain._require_non_empty_string(
            runtime_profile, "runtime_profile"
        )
        ttl = self.default_lease_seconds if lease_seconds is None else int(lease_seconds)
        if ttl < 1:
            raise WorkerError("lease_seconds must be positive")

        try:
            self.db.execute("BEGIN IMMEDIATE")
            workers = self.db.execute(
                "SELECT * FROM warm_workers ORDER BY worker_id ASC"
            ).fetchall()
            eligible = [
                worker
                for worker in workers
                if self._eligible(worker, required_applab_sha, runtime_profile, now_ts)
            ]
            if not eligible:
                self.db.commit()
                return {
                    "executor": FALLBACK_EXECUTOR,
                    "fallback": True,
                    "reason": "NO_ELIGIBLE_WARM_WORKER",
                    "operation_id": operation_id,
                    "dispatch_performed": False,
                }

            worker = eligible[0]
            raw = f"{worker['worker_id']}|{operation_id}|{float(now_ts):.6f}"
            lease_id = "lease_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
            expires_at = float(now_ts) + ttl
            self.db.execute(
                """
                INSERT INTO warm_worker_leases(
                    lease_id,worker_id,operation_id,issued_at,expires_at,status,
                    cleanup_attested,released_at
                ) VALUES (?,?,?,?,?,'ACTIVE',0,NULL)
                """,
                (lease_id, worker["worker_id"], operation_id, float(now_ts), expires_at),
            )
            self._history(
                worker["worker_id"],
                "LEASE",
                "AVAILABLE",
                "LEASED",
                "EXCLUSIVE_RUNTIME_LEASE",
                now_ts,
                lease_id=lease_id,
                payload={
                    "operation_id": operation_id,
                    "runtime_profile": runtime_profile,
                    "expires_at": expires_at,
                },
            )
            self.db.execute(
                """
                UPDATE warm_workers
                SET state='LEASED',current_lease_id=?,updated_at=?
                WHERE worker_id=?
                """,
                (lease_id, float(now_ts), worker["worker_id"]),
            )
            self.db.commit()
            return {
                "executor": WORKER_CLASS,
                "fallback": False,
                "worker_id": worker["worker_id"],
                "lease_id": lease_id,
                "operation_id": operation_id,
                "expires_at": expires_at,
                "snapshot_digest_sha256": worker["snapshot_digest_sha256"],
                "dispatch_performed": False,
            }
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def begin_scrub(self, lease_id: str, *, now_ts: float) -> dict[str, Any]:
        try:
            self.db.execute("BEGIN IMMEDIATE")
            lease = self._lease(lease_id)
            if lease is None or lease["status"] != "ACTIVE":
                raise WorkerError("lease is not active")
            worker = self._worker(lease["worker_id"])
            if worker is None or worker["current_lease_id"] != lease_id:
                raise WorkerError("worker/lease projection mismatch")
            if worker["state"] != "LEASED":
                raise WorkerError("worker must be LEASED before scrub")
            self._history(
                worker["worker_id"],
                "BEGIN_SCRUB",
                "LEASED",
                "SCRUBBING",
                "RUNTIME_FINISHED",
                now_ts,
                lease_id=lease_id,
            )
            self.db.execute(
                "UPDATE warm_workers SET state='SCRUBBING',updated_at=? WHERE worker_id=?",
                (float(now_ts), worker["worker_id"]),
            )
            self.db.commit()
            return {"worker_id": worker["worker_id"], "state": "SCRUBBING"}
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def _quarantine_locked(
        self,
        worker: sqlite3.Row,
        reason: str,
        *,
        now_ts: float,
        lease_id: str | None = None,
    ) -> dict[str, Any]:
        if worker["state"] == "OFFLINE":
            raise WorkerError("offline worker cannot be quarantined")
        if lease_id is not None and worker["current_lease_id"] != lease_id:
            raise WorkerError("quarantine lease does not own current worker projection")
        current_lease = lease_id or worker["current_lease_id"]
        self._history(
            worker["worker_id"],
            "QUARANTINE",
            worker["state"],
            "QUARANTINED",
            reason,
            now_ts,
            lease_id=current_lease,
        )
        if current_lease:
            self.db.execute(
                """
                UPDATE warm_worker_leases
                SET status='QUARANTINED',released_at=?
                WHERE lease_id=? AND status='ACTIVE'
                """,
                (float(now_ts), current_lease),
            )
        self.db.execute(
            """
            UPDATE warm_workers
            SET state='QUARANTINED',current_lease_id=NULL,
                quarantine_reason=?,updated_at=?
            WHERE worker_id=?
            """,
            (reason, float(now_ts), worker["worker_id"]),
        )
        return {
            "worker_id": worker["worker_id"],
            "state": "QUARANTINED",
            "reason": reason,
        }

    def quarantine(
        self,
        worker_id: str,
        reason: str,
        *,
        now_ts: float,
        lease_id: str | None = None,
    ) -> dict[str, Any]:
        reason = brain._require_non_empty_string(reason, "quarantine reason")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            worker = self._worker(worker_id)
            if worker is None:
                raise WorkerError("unknown worker")
            result = self._quarantine_locked(
                worker,
                reason,
                now_ts=now_ts,
                lease_id=lease_id,
            )
            self.db.commit()
            return result
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def release_after_scrub(
        self,
        lease_id: str,
        cleanup_attestation: dict[str, Any],
        *,
        now_ts: float,
    ) -> dict[str, Any]:
        if not isinstance(cleanup_attestation, dict):
            raise WorkerError("cleanup_attestation must be object")
        missing = [
            name
            for name in REQUIRED_CLEANUP_ATTESTATIONS
            if cleanup_attestation.get(name) is not True
        ]

        try:
            self.db.execute("BEGIN IMMEDIATE")
            lease = self._lease(lease_id)
            if lease is None or lease["status"] != "ACTIVE":
                raise WorkerError("lease is not active")
            worker = self._worker(lease["worker_id"])
            if worker is None:
                raise WorkerError("unknown worker")
            if worker["state"] != "SCRUBBING":
                raise WorkerError("worker must be SCRUBBING before release")
            if worker["current_lease_id"] != lease_id:
                raise WorkerError("worker/lease projection mismatch")

            if float(lease["expires_at"]) < float(now_ts):
                result = self._quarantine_locked(
                    worker,
                    "LEASE_EXPIRED_UNCERTAIN_CLEANUP",
                    now_ts=now_ts,
                    lease_id=lease_id,
                )
                self.db.commit()
                return result

            if missing:
                result = self._quarantine_locked(
                    worker,
                    "CLEANUP_ATTESTATION_FAILED:" + ",".join(sorted(missing)),
                    now_ts=now_ts,
                    lease_id=lease_id,
                )
                self.db.commit()
                return result

            self._history(
                worker["worker_id"],
                "RELEASE",
                "SCRUBBING",
                "AVAILABLE",
                "CLEANUP_ATTESTED",
                now_ts,
                lease_id=lease_id,
                payload={name: True for name in REQUIRED_CLEANUP_ATTESTATIONS},
            )
            self.db.execute(
                """
                UPDATE warm_worker_leases
                SET status='RELEASED',cleanup_attested=1,released_at=?
                WHERE lease_id=? AND status='ACTIVE'
                """,
                (float(now_ts), lease_id),
            )
            if self.db.execute("SELECT changes() AS n").fetchone()["n"] != 1:
                raise WorkerError("lease release lost ownership")
            self.db.execute(
                """
                UPDATE warm_workers
                SET state='AVAILABLE',current_lease_id=NULL,
                    quarantine_reason=NULL,heartbeat_at=?,updated_at=?
                WHERE worker_id=? AND current_lease_id=? AND state='SCRUBBING'
                """,
                (float(now_ts), float(now_ts), worker["worker_id"], lease_id),
            )
            if self.db.execute("SELECT changes() AS n").fetchone()["n"] != 1:
                raise WorkerError("worker release lost lease projection")
            self.db.commit()
            return {
                "worker_id": worker["worker_id"],
                "state": "AVAILABLE",
                "lease_id": lease_id,
                "cleanup_attested": True,
            }
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def sweep(self, *, now_ts: float) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        try:
            self.db.execute("BEGIN IMMEDIATE")
            workers = self.db.execute(
                "SELECT * FROM warm_workers ORDER BY worker_id"
            ).fetchall()
            for worker in workers:
                if worker["state"] == "AVAILABLE":
                    if (
                        float(now_ts) - float(worker["heartbeat_at"])
                        > self.heartbeat_ttl_seconds
                    ):
                        actions.append(
                            self._quarantine_locked(
                                worker,
                                "STALE_HEARTBEAT",
                                now_ts=now_ts,
                            )
                        )
                elif (
                    worker["state"] in {"LEASED", "SCRUBBING"}
                    and worker["current_lease_id"]
                ):
                    lease = self._lease(worker["current_lease_id"])
                    if (
                        lease is not None
                        and lease["status"] == "ACTIVE"
                        and float(lease["expires_at"]) < float(now_ts)
                    ):
                        # worker + current lease are read from the same write-locked
                        # snapshot, so a renewed/replaced lease cannot be quarantined
                        # by a stale sweep observation.
                        actions.append(
                            self._quarantine_locked(
                                worker,
                                "LEASE_EXPIRED_UNCERTAIN_CLEANUP",
                                now_ts=now_ts,
                                lease_id=lease["lease_id"],
                            )
                        )
            self.db.commit()
            return actions
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def worker_snapshot(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT * FROM warm_workers ORDER BY worker_id"
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["capabilities"] = json.loads(item.pop("capabilities_json"))
            result.append(item)
        return result

    def integrity_report(self) -> dict[str, Any]:
        violations: list[str] = []
        active = self.db.execute(
            """
            SELECT worker_id,COUNT(*) AS n
            FROM warm_worker_leases
            WHERE status='ACTIVE'
            GROUP BY worker_id
            HAVING COUNT(*)>1
            """
        ).fetchall()
        for row in active:
            violations.append(f"multiple_active_leases:{row['worker_id']}:{row['n']}")

        projection = self.db.execute(
            """
            SELECT w.worker_id,w.state,w.current_lease_id,l.status
            FROM warm_workers w
            LEFT JOIN warm_worker_leases l ON l.lease_id=w.current_lease_id
            """
        ).fetchall()
        for row in projection:
            if row["state"] in {"LEASED", "SCRUBBING"}:
                if row["current_lease_id"] is None or row["status"] != "ACTIVE":
                    violations.append(f"lease_projection:{row['worker_id']}:{row['state']}")
            elif row["current_lease_id"] is not None:
                violations.append(f"unexpected_lease_projection:{row['worker_id']}:{row['state']}")

        for worker in self.worker_snapshot():
            rows = self.db.execute(
                """
                SELECT from_state,to_state
                FROM warm_worker_history
                WHERE worker_id=?
                ORDER BY history_id ASC
                """,
                (worker["worker_id"],),
            ).fetchall()
            state: str | None = None
            for index, row in enumerate(rows):
                if index == 0 and row["from_state"] is not None:
                    violations.append(f"invalid_initial_history:{worker['worker_id']}")
                    break
                if row["from_state"] != state:
                    violations.append(f"history_chain:{worker['worker_id']}")
                    break
                state = row["to_state"]
            if state != worker["state"]:
                violations.append(
                    f"projection_mismatch:{worker['worker_id']}:{state}:{worker['state']}"
                )

        return {
            "schema_version": 1,
            "record_type": "APPLAB_WARM_WORKER_INTEGRITY",
            "authority": "ORCHESTRATION_ONLY",
            "dispatch_performed": False,
            "violations": violations,
            "ok": not violations,
        }


def compare_equivalence(
    control: dict[str, Any],
    warm: dict[str, Any],
    *,
    isolation_clean: bool,
    minimum_improvement_percent: float = 0.0,
) -> dict[str, Any]:
    identity_fields = (
        "repository",
        "resolved_sha",
        "applab_sha",
        "apk_sha256",
        "package_id",
        "analysis_mode",
    )
    identity_match = all(control.get(field) == warm.get(field) for field in identity_fields)
    control_labs = control.get("labs") or {}
    warm_labs = warm.get("labs") or {}
    labs_match = control_labs == warm_labs
    verdict_match = control.get("result") == warm.get("result")

    control_seconds = float(
        control.get("startup_seconds", control.get("runtime_seconds")) or 0.0
    )
    warm_seconds = float(
        warm.get("startup_seconds", warm.get("runtime_seconds")) or 0.0
    )
    improvement_percent = 0.0
    if control_seconds > 0:
        improvement_percent = ((control_seconds - warm_seconds) / control_seconds) * 100.0

    equivalent = bool(identity_match and labs_match and verdict_match)
    promotion_candidate = bool(
        equivalent
        and isolation_clean
        and warm_seconds > 0
        and control_seconds > 0
        and improvement_percent >= float(minimum_improvement_percent)
    )
    return {
        "schema_version": 1,
        "record_type": "APPLAB_WARM_WORKER_EQUIVALENCE",
        "authority": "NONE_PILOT_EVIDENCE",
        "identity_match": identity_match,
        "labs_match": labs_match,
        "verdict_match": verdict_match,
        "isolation_clean": bool(isolation_clean),
        "control_startup_seconds": control_seconds,
        "warm_startup_seconds": warm_seconds,
        "improvement_percent": round(improvement_percent, 3),
        "equivalent": equivalent,
        "promotion_candidate": promotion_candidate,
    }


def _capabilities() -> dict[str, Any]:
    return {
        "kvm": True,
        "android_runtime": True,
        "disposable_avd": True,
        "evidence_capture": True,
        "runtime_profiles": ["android-default", "api35-pixel7pro"],
        "api_levels": [35],
        "screen_capture": True,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "warm-worker.sqlite3"
        with storemod.SQLiteShadowStore(db_path) as store:
            registry = WarmWorkerRegistry(
                store, heartbeat_ttl_seconds=10, default_lease_seconds=5
            )
            snapshot = "sha256:" + "1" * 64
            assert registry.register(
                "warm-1", "a" * 40, _capabilities(), snapshot, now_ts=1
            )["state"] == "STARTING"
            registry.activate(
                "warm-1",
                now_ts=2,
                kvm_attested=True,
                snapshot_verified=True,
                clean_process_table=True,
            )
            fallback = registry.acquire_lease(
                "op-mismatch", "b" * 40, "android-default", now_ts=3
            )
            assert fallback["executor"] == FALLBACK_EXECUTOR
            assert fallback["fallback"] is True

            lease = registry.acquire_lease(
                "op-1", "a" * 40, "android-default", now_ts=3
            )
            assert lease["executor"] == WORKER_CLASS
            assert lease["fallback"] is False
            second = registry.acquire_lease(
                "op-2", "a" * 40, "android-default", now_ts=3
            )
            assert second["fallback"] is True

            registry.begin_scrub(lease["lease_id"], now_ts=4)
            clean = {name: True for name in REQUIRED_CLEANUP_ATTESTATIONS}
            release = registry.release_after_scrub(
                lease["lease_id"], clean, now_ts=5
            )
            assert release["state"] == "AVAILABLE"

            lease2 = registry.acquire_lease(
                "op-3", "a" * 40, "android-default", now_ts=6, lease_seconds=2
            )
            assert lease2["fallback"] is False
            swept = registry.sweep(now_ts=9)
            assert swept and swept[0]["state"] == "QUARANTINED"
            assert registry.integrity_report()["ok"] is True

        with storemod.SQLiteShadowStore(db_path) as reopened:
            registry = WarmWorkerRegistry(
                reopened, heartbeat_ttl_seconds=10, default_lease_seconds=5
            )
            assert registry.worker_snapshot()[0]["state"] == "QUARANTINED"
            assert registry.integrity_report()["ok"] is True

    control = {
        "repository": "owner/app",
        "resolved_sha": "c" * 40,
        "applab_sha": "d" * 40,
        "apk_sha256": "sha256:" + "2" * 64,
        "package_id": "dev.app",
        "analysis_mode": "full",
        "result": "PASS",
        "labs": {"system": "PASS", "network": "WARN"},
        "runtime_seconds": 100,
    }
    warm = dict(control, runtime_seconds=70)
    report = compare_equivalence(
        control, warm, isolation_clean=True, minimum_improvement_percent=5
    )
    assert report["equivalent"] is True
    assert report["promotion_candidate"] is True

    mismatch = compare_equivalence(
        control,
        dict(warm, apk_sha256="sha256:" + "3" * 64),
        isolation_clean=True,
    )
    assert mismatch["identity_match"] is False
    assert mismatch["promotion_candidate"] is False

    print("AppLab v5.4F Warm Trusted-Runtime Worker self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v5.4F warm trusted-runtime worker")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
