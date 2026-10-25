#!/usr/bin/env python3
from __future__ import annotations

import copy
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import durable_brain_v54a as brain  # noqa: E402
import durable_store_v54b as storemod  # noqa: E402


def assert_rejected(callback, contains: str) -> None:
    try:
        callback()
    except (storemod.StoreError, brain.ContractError, sqlite3.DatabaseError) as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected rejection containing {contains!r}")


def main() -> int:
    brain_contract = brain.load_contract()
    store_contract = storemod.load_store_contract()
    assert store_contract["mode"] == "SHADOW_NO_DISPATCH"
    assert store_contract["authority"] == "NONE"

    target_sha = "b" * 40
    applab_sha = "c" * 40
    event = brain._event_fixture(
        "evt_contract_store", "owner/app", "refs/heads/main", target_sha, "delivery"
    )
    operation = brain._operation_fixture(
        "op_contract_store", "owner/app", "main", target_sha, applab_sha
    )
    attempt = brain._attempt_fixture(
        "att_contract_store", operation["operation_id"], 1, "FAILED", "INFRA_ERROR", True
    )
    evidence = storemod._evidence_fixture(
        "evr_contract_store", operation, attempt["attempt_id"]
    )

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "durable-shadow.sqlite3"

        with storemod.SQLiteShadowStore(db_path, brain_contract, store_contract) as store:
            assert store.put_event(event) == {
                "status": "INSERTED",
                "event_id": event["event_id"],
            }
            assert store.put_operation(operation)["status"] == "INSERTED"
            assert store.put_attempt(attempt)["status"] == "INSERTED"
            assert store.put_evidence_ref(evidence)["status"] == "INSERTED"

            # Same provider observation under a different event_id dedupes.
            redelivery = dict(event, event_id="evt_contract_store_redelivery")
            assert store.put_event(redelivery)["status"] == "DEDUPED"

            # Same logical operation under a different operation_id reuses identity.
            operation_reuse = dict(operation, operation_id="op_contract_store_reuse")
            assert store.put_operation(operation_reuse) == {
                "status": "IDEMPOTENT_REUSE",
                "operation_id": operation["operation_id"],
            }

            conflicting_operation = copy.deepcopy(operation)
            conflicting_operation["resolved_sha"] = "d" * 40
            conflicting_operation["idempotency_key"] = brain.operation_idempotency_key(
                conflicting_operation
            )
            assert_rejected(
                lambda: store.put_operation(conflicting_operation),
                "operation_id reused with conflicting immutable payload",
            )

            mismatched_evidence = copy.deepcopy(evidence)
            mismatched_evidence["evidence_ref_id"] = "evr_bad_identity"
            mismatched_evidence["resolved_sha"] = "d" * 40
            assert_rejected(
                lambda: store.put_evidence_ref(mismatched_evidence),
                "does not match operation identity",
            )

            untrusted_upgrade = copy.deepcopy(evidence)
            untrusted_upgrade["evidence_ref_id"] = "evr_bad_trust"
            untrusted_upgrade["registry_state"] = "NOT_REGISTERED"
            untrusted_upgrade["trusted"] = True
            assert_rejected(
                lambda: store.put_evidence_ref(untrusted_upgrade),
                "cannot upgrade incompatible/unregistered evidence to trusted",
            )

            t1 = storemod._transition_fixture(
                "trn_contract_1",
                operation["operation_id"],
                "QUEUED",
                "PLANNING",
                "SHADOW_PLAN_START",
            )
            t2 = storemod._transition_fixture(
                "trn_contract_2",
                operation["operation_id"],
                "PLANNING",
                "READY",
                "SHADOW_PLAN_READY",
            )
            assert store.transition_operation(t1)["sequence_number"] == 1
            assert store.transition_operation(t1)["status"] == "REPLAY"
            assert store.transition_operation(t2)["sequence_number"] == 2
            assert store.transition_operation(t2)["status"] == "REPLAY"
            assert store.get_operation(operation["operation_id"])["current_state"] == "READY"
            assert store.rebuild_operation_state(operation["operation_id"]) == "READY"

            stale = storemod._transition_fixture(
                "trn_contract_stale",
                operation["operation_id"],
                "QUEUED",
                "PLANNING",
                "STALE_WRITER",
            )
            assert_rejected(
                lambda: store.transition_operation(stale),
                "from_state does not match durable current_state",
            )
            assert store.get_operation(operation["operation_id"])["current_state"] == "READY"
            assert len(store.list_transitions(operation["operation_id"])) == 2

            # Append-only is enforced by DB triggers, not only by adapter convention.
            assert_rejected(
                lambda: store.db.execute(
                    "UPDATE events SET payload_json='{}' WHERE event_id=?",
                    (event["event_id"],),
                ),
                "events append-only",
            )
            store.db.rollback()
            assert_rejected(
                lambda: store.db.execute(
                    "DELETE FROM evidence_refs WHERE evidence_ref_id=?",
                    (evidence["evidence_ref_id"],),
                ),
                "evidence_refs append-only",
            )
            store.db.rollback()
            assert_rejected(
                lambda: store.db.execute(
                    "UPDATE operations SET resolved_sha=? WHERE operation_id=?",
                    ("e" * 40, operation["operation_id"]),
                ),
                "operation immutable identity",
            )
            store.db.rollback()
            assert_rejected(
                lambda: store.db.execute(
                    "UPDATE operations SET current_state='RUNNING' WHERE operation_id=?",
                    (operation["operation_id"],),
                ),
                "operation state update requires transition",
            )
            store.db.rollback()

            report = store.integrity_report()
            assert report["ok"] is True
            assert report["mode"] == "SHADOW_NO_DISPATCH"
            assert report["authority"] == "NONE"

        # Restart persistence: exact operation state and immutable history survive reopen.
        with storemod.SQLiteShadowStore(db_path, brain_contract, store_contract) as reopened:
            assert reopened.get_operation(operation["operation_id"])["current_state"] == "READY"
            transitions = reopened.list_transitions(operation["operation_id"])
            assert [item["sequence_number"] for item in transitions] == [1, 2]
            assert reopened.rebuild_operation_state(operation["operation_id"]) == "READY"
            assert reopened.integrity_report()["projection_errors"] == []

    postgres_schema = (
        ROOT / "integration" / "orchestration" / "sql" / "postgres-v54b-shadow.sql"
    ).read_text(encoding="utf-8")
    assert postgres_schema.count("CREATE OR REPLACE FUNCTION") == 2
    assert "AS $applab$" in postgres_schema
    assert "$applab$;" in postgres_schema
    assert "AS $\n" not in postgres_schema
    assert "\n$;\n" not in postgres_schema

    for required in (
        "CREATE TABLE IF NOT EXISTS applab_events",
        "CREATE TABLE IF NOT EXISTS applab_operations",
        "CREATE TABLE IF NOT EXISTS applab_attempts",
        "CREATE TABLE IF NOT EXISTS applab_evidence_refs",
        "CREATE TABLE IF NOT EXISTS applab_operation_transitions",
        "applab_reject_mutation",
        "applab_guard_operation_identity",
        "SHADOW_NO_DISPATCH",
    ):
        assert required in postgres_schema, required

    # v5.4B remains a CI-tested storage primitive, not an operational workflow.
    operational = [
        path
        for path in (ROOT / ".github" / "workflows").glob("*.yml")
        if path.name != "ci.yml"
    ]
    wired = [
        path.name
        for path in operational
        if "durable_store_v54b.py" in path.read_text(encoding="utf-8")
    ]
    assert wired == [], f"v5.4B unexpectedly wired into operational workflows: {wired}"

    source = (ROOT / "scripts" / "durable_store_v54b.py").read_text(encoding="utf-8")
    for forbidden in (
        "requests.",
        "urllib.request",
        "socket.",
        "psycopg",
        "conductor",
        "workflow_dispatch",
        "repository_dispatch",
    ):
        assert forbidden not in source, forbidden

    storemod.self_test()
    print("AppLab v5.4B durable store contract test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
