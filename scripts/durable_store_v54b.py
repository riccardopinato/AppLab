#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import durable_brain_v54a as brain

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE_CONTRACT = ROOT / "integration" / "orchestration" / "contracts" / "durable-store-shadow-contract-v1.json"
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class StoreError(ValueError):
    pass


def load_store_contract(path: Path = DEFAULT_STORE_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise StoreError("unsupported durable store contract version")
    if payload.get("contract_name") != "APPLAB_DURABLE_STORE_SHADOW":
        raise StoreError("unexpected durable store contract")
    if payload.get("mode") != "SHADOW_NO_DISPATCH" or payload.get("authority") != "NONE":
        raise StoreError("v5.4B store must remain SHADOW_NO_DISPATCH with NONE authority")
    return payload


def _require_sha256(value: Any, label: str) -> str:
    text = brain._require_non_empty_string(value, label)
    if not SHA256_RE.fullmatch(text):
        raise StoreError(f"{label} must be sha256:<64 lowercase hex>")
    return text


def validate_evidence_ref(
    payload: dict[str, Any],
    store_contract: dict[str, Any],
) -> dict[str, Any]:
    payload = brain._require_dict(payload, "evidence_ref")
    spec = store_contract["evidence_ref"]
    brain._require_fields(payload, spec["required"], "evidence_ref")
    if payload.get("schema_version") != 1:
        raise StoreError("evidence_ref schema_version must be 1")
    if payload.get("record_type") != spec["record_type"]:
        raise StoreError("evidence_ref record_type mismatch")
    brain._require_id(payload.get("evidence_ref_id"), "evidence_ref_id")
    brain._require_id(payload.get("operation_id"), "operation_id")
    attempt_id = payload.get("attempt_id")
    if attempt_id not in {None, ""}:
        brain._require_id(attempt_id, "attempt_id")
    brain._require_non_empty_string(payload.get("artifact_name"), "artifact_name")
    brain._require_non_empty_string(payload.get("evidence_class"), "evidence_class")
    brain._require_non_empty_string(payload.get("producer"), "producer")
    if payload.get("registry_state") not in spec["registry_states"]:
        raise StoreError("invalid evidence registry_state")
    _require_sha256(payload.get("content_sha256"), "content_sha256")
    if not isinstance(payload.get("byte_size"), int) or payload["byte_size"] < 0:
        raise StoreError("evidence byte_size must be a non-negative integer")
    uri = brain._require_non_empty_string(payload.get("storage_uri"), "storage_uri")
    if not any(uri.startswith(prefix) for prefix in spec["allowed_storage_schemes"]):
        raise StoreError("evidence storage_uri uses a non-shadow/non-object scheme")
    brain._require_repository(payload.get("repository"))
    brain._require_sha(payload.get("resolved_sha"), "evidence_ref.resolved_sha")
    brain._require_sha(payload.get("applab_sha"), "evidence_ref.applab_sha")
    brain._require_non_empty_string(payload.get("generated_at"), "generated_at")
    if payload.get("retention_class") not in spec["retention_classes"]:
        raise StoreError("invalid evidence retention_class")
    if payload.get("trusted") is True and payload.get("registry_state") != "COMPATIBLE":
        raise StoreError("EvidenceRef cannot upgrade incompatible/unregistered evidence to trusted")
    return payload


def validate_transition_record(
    payload: dict[str, Any],
    store_contract: dict[str, Any],
    brain_contract: dict[str, Any],
) -> dict[str, Any]:
    payload = brain._require_dict(payload, "transition")
    spec = store_contract["transition"]
    brain._require_fields(payload, spec["required"], "transition")
    if payload.get("schema_version") != 1:
        raise StoreError("transition schema_version must be 1")
    if payload.get("record_type") != spec["record_type"]:
        raise StoreError("transition record_type mismatch")
    brain._require_id(payload.get("transition_id"), "transition_id")
    brain._require_id(payload.get("operation_id"), "operation_id")
    brain._require_non_empty_string(payload.get("reason_code"), "reason_code")
    brain._require_non_empty_string(payload.get("actor"), "actor")
    brain._require_non_empty_string(payload.get("occurred_at"), "occurred_at")
    _require_sha256(payload.get("metadata_digest_sha256"), "metadata_digest_sha256")
    brain.validate_transition(payload["from_state"], payload["to_state"], brain_contract)
    return payload


SQLITE_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    queue_key TEXT NOT NULL,
    repository TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    resolved_sha TEXT NOT NULL,
    applab_sha TEXT NOT NULL,
    initial_state TEXT NOT NULL,
    current_state TEXT NOT NULL,
    priority INTEGER NOT NULL,
    immutable_identity_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS operations_queue_idx
ON operations(queue_key, priority DESC, created_at ASC);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    attempt_number INTEGER NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(operation_id, attempt_number)
);

CREATE TABLE IF NOT EXISTS evidence_refs (
    evidence_ref_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    attempt_id TEXT REFERENCES attempts(attempt_id),
    content_sha256 TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS operation_transitions (
    transition_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    sequence_number INTEGER NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(operation_id, sequence_number)
);

CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events append-only'); END;

CREATE TRIGGER IF NOT EXISTS attempts_no_update
BEFORE UPDATE ON attempts BEGIN SELECT RAISE(ABORT, 'attempts append-only'); END;
CREATE TRIGGER IF NOT EXISTS attempts_no_delete
BEFORE DELETE ON attempts BEGIN SELECT RAISE(ABORT, 'attempts append-only'); END;

CREATE TRIGGER IF NOT EXISTS evidence_refs_no_update
BEFORE UPDATE ON evidence_refs BEGIN SELECT RAISE(ABORT, 'evidence_refs append-only'); END;
CREATE TRIGGER IF NOT EXISTS evidence_refs_no_delete
BEFORE DELETE ON evidence_refs BEGIN SELECT RAISE(ABORT, 'evidence_refs append-only'); END;

CREATE TRIGGER IF NOT EXISTS transitions_no_update
BEFORE UPDATE ON operation_transitions BEGIN SELECT RAISE(ABORT, 'operation_transitions append-only'); END;
CREATE TRIGGER IF NOT EXISTS transitions_no_delete
BEFORE DELETE ON operation_transitions BEGIN SELECT RAISE(ABORT, 'operation_transitions append-only'); END;

CREATE TRIGGER IF NOT EXISTS operations_identity_no_update
BEFORE UPDATE OF
    operation_id,idempotency_key,queue_key,repository,source_ref,resolved_sha,
    applab_sha,initial_state,priority,immutable_identity_sha256,payload_json,created_at
ON operations
BEGIN
    SELECT RAISE(ABORT, 'operation immutable identity');
END;

CREATE TRIGGER IF NOT EXISTS operations_no_delete
BEFORE DELETE ON operations BEGIN SELECT RAISE(ABORT, 'operations cannot be deleted'); END;
"""


class SQLiteShadowStore:
    def __init__(
        self,
        path: Path,
        brain_contract: dict[str, Any] | None = None,
        store_contract: dict[str, Any] | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.brain_contract = brain_contract or brain.load_contract()
        self.store_contract = store_contract or load_store_contract()
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SQLITE_SCHEMA)
        self.db.executemany(
            "INSERT OR REPLACE INTO store_meta(key,value) VALUES (?,?)",
            [
                ("schema_version", "1"),
                ("mode", "SHADOW_NO_DISPATCH"),
                ("authority", "NONE"),
            ],
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "SQLiteShadowStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @staticmethod
    def _payload_digest(payload: dict[str, Any]) -> str:
        return brain.sha256_json(payload)

    def _existing_payload(self, table: str, id_field: str, identity: str) -> tuple[str, dict[str, Any]] | None:
        row = self.db.execute(
            f"SELECT payload_sha256,payload_json FROM {table} WHERE {id_field}=?",
            (identity,),
        ).fetchone()
        if row is None:
            return None
        return row["payload_sha256"], json.loads(row["payload_json"])

    def put_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        brain.validate_event(payload, self.brain_contract)
        digest = self._payload_digest(payload)
        existing = self._existing_payload("events", "event_id", payload["event_id"])
        if existing:
            if existing[0] != digest:
                raise StoreError("event_id reused with conflicting immutable payload")
            return {"status": "REPLAY", "event_id": payload["event_id"]}
        row = self.db.execute(
            "SELECT event_id FROM events WHERE dedupe_key=?",
            (payload["dedupe_key"],),
        ).fetchone()
        if row:
            return {"status": "DEDUPED", "event_id": row["event_id"]}
        with self.db:
            self.db.execute(
                "INSERT INTO events(event_id,dedupe_key,payload_sha256,payload_json) VALUES (?,?,?,?)",
                (payload["event_id"], payload["dedupe_key"], digest, brain.canonical_json(payload)),
            )
        return {"status": "INSERTED", "event_id": payload["event_id"]}

    def put_operation(self, payload: dict[str, Any]) -> dict[str, Any]:
        brain.validate_operation(payload, self.brain_contract)
        digest = self._payload_digest(payload)
        existing = self.db.execute(
            "SELECT immutable_identity_sha256 FROM operations WHERE operation_id=?",
            (payload["operation_id"],),
        ).fetchone()
        if existing:
            if existing["immutable_identity_sha256"] != digest:
                raise StoreError("operation_id reused with conflicting immutable payload")
            return {"status": "REPLAY", "operation_id": payload["operation_id"]}
        row = self.db.execute(
            "SELECT operation_id FROM operations WHERE idempotency_key=?",
            (payload["idempotency_key"],),
        ).fetchone()
        if row:
            return {"status": "IDEMPOTENT_REUSE", "operation_id": row["operation_id"]}
        with self.db:
            self.db.execute(
                """
                INSERT INTO operations(
                    operation_id,idempotency_key,queue_key,repository,source_ref,
                    resolved_sha,applab_sha,initial_state,current_state,priority,
                    immutable_identity_sha256,payload_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    payload["operation_id"], payload["idempotency_key"], payload["queue_key"],
                    payload["repository"], payload["source_ref"], payload["resolved_sha"],
                    payload["applab_sha"], payload["state"], payload["state"], payload["priority"],
                    digest, brain.canonical_json(payload),
                ),
            )
        return {"status": "INSERTED", "operation_id": payload["operation_id"]}

    def put_attempt(self, payload: dict[str, Any]) -> dict[str, Any]:
        brain.validate_attempt(payload, self.brain_contract)
        operation = self.db.execute(
            "SELECT operation_id FROM operations WHERE operation_id=?",
            (payload["operation_id"],),
        ).fetchone()
        if operation is None:
            raise StoreError("attempt references unknown operation")
        digest = self._payload_digest(payload)
        existing = self._existing_payload("attempts", "attempt_id", payload["attempt_id"])
        if existing:
            if existing[0] != digest:
                raise StoreError("attempt_id reused with conflicting immutable payload")
            return {"status": "REPLAY", "attempt_id": payload["attempt_id"]}
        numbered = self.db.execute(
            "SELECT attempt_id FROM attempts WHERE operation_id=? AND attempt_number=?",
            (payload["operation_id"], payload["attempt_number"]),
        ).fetchone()
        if numbered:
            raise StoreError("operation attempt_number already belongs to another attempt")
        with self.db:
            self.db.execute(
                "INSERT INTO attempts(attempt_id,operation_id,attempt_number,payload_sha256,payload_json) VALUES (?,?,?,?,?)",
                (
                    payload["attempt_id"], payload["operation_id"], payload["attempt_number"],
                    digest, brain.canonical_json(payload),
                ),
            )
        return {"status": "INSERTED", "attempt_id": payload["attempt_id"]}

    def put_evidence_ref(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_evidence_ref(payload, self.store_contract)
        operation = self.db.execute(
            "SELECT repository,resolved_sha,applab_sha FROM operations WHERE operation_id=?",
            (payload["operation_id"],),
        ).fetchone()
        if operation is None:
            raise StoreError("EvidenceRef references unknown operation")
        for field in ("repository", "resolved_sha", "applab_sha"):
            if payload[field] != operation[field]:
                raise StoreError(f"EvidenceRef {field} does not match operation identity")
        attempt_id = payload.get("attempt_id")
        if attempt_id:
            attempt = self.db.execute(
                "SELECT operation_id FROM attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if attempt is None or attempt["operation_id"] != payload["operation_id"]:
                raise StoreError("EvidenceRef attempt identity mismatch")
        digest = self._payload_digest(payload)
        existing = self._existing_payload("evidence_refs", "evidence_ref_id", payload["evidence_ref_id"])
        if existing:
            if existing[0] != digest:
                raise StoreError("evidence_ref_id reused with conflicting immutable payload")
            return {"status": "REPLAY", "evidence_ref_id": payload["evidence_ref_id"]}
        with self.db:
            self.db.execute(
                """
                INSERT INTO evidence_refs(
                    evidence_ref_id,operation_id,attempt_id,content_sha256,payload_sha256,payload_json
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    payload["evidence_ref_id"], payload["operation_id"], attempt_id or None,
                    payload["content_sha256"], digest, brain.canonical_json(payload),
                ),
            )
        return {"status": "INSERTED", "evidence_ref_id": payload["evidence_ref_id"]}

    def transition_operation(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_transition_record(payload, self.store_contract, self.brain_contract)
        row = self.db.execute(
            "SELECT current_state FROM operations WHERE operation_id=?",
            (payload["operation_id"],),
        ).fetchone()
        if row is None:
            raise StoreError("transition references unknown operation")
        if row["current_state"] != payload["from_state"]:
            raise StoreError("transition from_state does not match durable current_state")
        digest = self._payload_digest(payload)
        existing = self._existing_payload(
            "operation_transitions", "transition_id", payload["transition_id"]
        )
        if existing:
            if existing[0] != digest:
                raise StoreError("transition_id reused with conflicting immutable payload")
            return {"status": "REPLAY", "transition_id": payload["transition_id"]}
        next_sequence = self.db.execute(
            "SELECT COALESCE(MAX(sequence_number),0)+1 AS n FROM operation_transitions WHERE operation_id=?",
            (payload["operation_id"],),
        ).fetchone()["n"]
        with self.db:
            self.db.execute(
                """
                INSERT INTO operation_transitions(
                    transition_id,operation_id,sequence_number,from_state,to_state,
                    payload_sha256,payload_json
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    payload["transition_id"], payload["operation_id"], next_sequence,
                    payload["from_state"], payload["to_state"], digest, brain.canonical_json(payload),
                ),
            )
            self.db.execute(
                "UPDATE operations SET current_state=?,updated_at=CURRENT_TIMESTAMP WHERE operation_id=?",
                (payload["to_state"], payload["operation_id"]),
            )
        return {
            "status": "INSERTED",
            "transition_id": payload["transition_id"],
            "sequence_number": next_sequence,
            "current_state": payload["to_state"],
        }

    def get_operation(self, operation_id: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            raise StoreError("unknown operation")
        payload = json.loads(row["payload_json"])
        payload["initial_state"] = row["initial_state"]
        payload["current_state"] = row["current_state"]
        return payload

    def list_transitions(self, operation_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """
            SELECT sequence_number,payload_json
            FROM operation_transitions
            WHERE operation_id=?
            ORDER BY sequence_number ASC
            """,
            (operation_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = json.loads(row["payload_json"])
            item["sequence_number"] = row["sequence_number"]
            result.append(item)
        return result

    def rebuild_operation_state(self, operation_id: str) -> str:
        operation = self.get_operation(operation_id)
        state = operation["initial_state"]
        for transition in self.list_transitions(operation_id):
            if transition["from_state"] != state:
                raise StoreError("transition history is not replayable from initial_state")
            brain.validate_transition(state, transition["to_state"], self.brain_contract)
            state = transition["to_state"]
        return state

    def integrity_report(self) -> dict[str, Any]:
        operation_rows = self.db.execute(
            "SELECT operation_id,current_state FROM operations ORDER BY operation_id"
        ).fetchall()
        projection_errors: list[str] = []
        for row in operation_rows:
            rebuilt = self.rebuild_operation_state(row["operation_id"])
            if rebuilt != row["current_state"]:
                projection_errors.append(row["operation_id"])
        counts = {}
        for table in ("events", "operations", "attempts", "evidence_refs", "operation_transitions"):
            counts[table] = self.db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        return {
            "schema_version": 1,
            "mode": "SHADOW_NO_DISPATCH",
            "authority": "NONE",
            "counts": counts,
            "projection_errors": projection_errors,
            "ok": not projection_errors,
        }


def _transition_fixture(
    transition_id: str,
    operation_id: str,
    from_state: str,
    to_state: str,
    reason_code: str,
) -> dict[str, Any]:
    metadata = {
        "operation_id": operation_id,
        "from_state": from_state,
        "to_state": to_state,
        "reason_code": reason_code,
    }
    return {
        "schema_version": 1,
        "record_type": "APPLAB_OPERATION_TRANSITION",
        "transition_id": transition_id,
        "operation_id": operation_id,
        "from_state": from_state,
        "to_state": to_state,
        "reason_code": reason_code,
        "actor": "durable-brain-shadow",
        "occurred_at": "2026-10-25T02:00:00Z",
        "metadata_digest_sha256": brain.sha256_json(metadata),
    }


def _evidence_fixture(
    evidence_ref_id: str,
    operation: dict[str, Any],
    attempt_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "APPLAB_EVIDENCE_REF",
        "evidence_ref_id": evidence_ref_id,
        "operation_id": operation["operation_id"],
        "attempt_id": attempt_id,
        "artifact_name": "shadow-result.json",
        "evidence_class": "SHADOW_CONTROL_PLANE",
        "producer": "v5.4b-shadow-store-self-test",
        "registry_state": "COMPATIBLE",
        "content_sha256": "sha256:" + "1" * 64,
        "byte_size": 123,
        "storage_uri": "file://shadow/immutable/shadow-result.json",
        "repository": operation["repository"],
        "resolved_sha": operation["resolved_sha"],
        "applab_sha": operation["applab_sha"],
        "generated_at": "2026-10-25T02:01:00Z",
        "retention_class": "STANDARD",
        "expires_at": None,
    }


def self_test() -> None:
    brain_contract = brain.load_contract()
    store_contract = load_store_contract()
    target_sha = "b" * 40
    applab_sha = "c" * 40
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "shadow.db"
        event = brain._event_fixture(
            "evt_store", "owner/app", "refs/heads/main", target_sha, "delivery-1"
        )
        operation = brain._operation_fixture(
            "op_store", "owner/app", "main", target_sha, applab_sha
        )
        attempt = brain._attempt_fixture(
            "att_store", "op_store", 1, "FAILED", "INFRA_ERROR", True
        )

        with SQLiteShadowStore(db_path, brain_contract, store_contract) as store:
            assert store.put_event(event)["status"] == "INSERTED"
            assert store.put_event(event)["status"] == "REPLAY"
            duplicate = dict(event, event_id="evt_store_duplicate")
            assert store.put_event(duplicate)["status"] == "DEDUPED"

            assert store.put_operation(operation)["status"] == "INSERTED"
            assert store.put_operation(operation)["status"] == "REPLAY"

            assert store.put_attempt(attempt)["status"] == "INSERTED"
            assert store.put_attempt(attempt)["status"] == "REPLAY"

            first = _transition_fixture(
                "trn_store_1", "op_store", "QUEUED", "PLANNING", "SHADOW_PLAN_START"
            )
            second = _transition_fixture(
                "trn_store_2", "op_store", "PLANNING", "READY", "SHADOW_PLAN_READY"
            )
            assert store.transition_operation(first)["sequence_number"] == 1
            assert store.transition_operation(second)["sequence_number"] == 2
            assert store.rebuild_operation_state("op_store") == "READY"
            assert store.get_operation("op_store")["current_state"] == "READY"

            evidence = _evidence_fixture("evr_store", operation, "att_store")
            assert store.put_evidence_ref(evidence)["status"] == "INSERTED"
            assert store.put_evidence_ref(evidence)["status"] == "REPLAY"

            report = store.integrity_report()
            assert report["ok"] is True
            assert report["counts"] == {
                "events": 1,
                "operations": 1,
                "attempts": 1,
                "evidence_refs": 1,
                "operation_transitions": 2,
            }

        # Persistence is proven by closing and reopening the file-backed store.
        with SQLiteShadowStore(db_path, brain_contract, store_contract) as reopened:
            assert reopened.get_operation("op_store")["current_state"] == "READY"
            assert reopened.rebuild_operation_state("op_store") == "READY"
            assert reopened.integrity_report()["ok"] is True

            illegal = _transition_fixture(
                "trn_illegal", "op_store", "QUEUED", "RUNNING", "STALE_WRITER"
            )
            try:
                reopened.transition_operation(illegal)
            except StoreError as exc:
                assert "from_state does not match" in str(exc)
            else:
                raise AssertionError("stale transition unexpectedly mutated durable state")
            assert reopened.get_operation("op_store")["current_state"] == "READY"
            assert len(reopened.list_transitions("op_store")) == 2

    print("AppLab v5.4B Durable Store Shadow self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v5.4B shadow-only durable store")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--db", default="")
    parser.add_argument("--integrity-report", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.integrity_report:
        if not args.db:
            raise SystemExit("--db is required for --integrity-report")
        with SQLiteShadowStore(Path(args.db)) as store:
            print(json.dumps(store.integrity_report(), indent=2, sort_keys=True))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
