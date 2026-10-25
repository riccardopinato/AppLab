#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import durable_queue_v54e as queue_mod  # noqa: E402
import durable_store_v54b as storemod  # noqa: E402


def expect_error(fn, contains: str) -> None:
    try:
        fn()
    except (queue_mod.QueueError, sqlite3.DatabaseError) as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected rejection containing {contains!r}")


def queue_for(store: storemod.SQLiteShadowStore) -> queue_mod.DurablePerRepoQueue:
    return queue_mod.DurablePerRepoQueue(
        store,
        max_ready_global=3,
        max_ready_per_repo=2,
        max_pending_global=8,
        max_pending_per_repo=4,
        max_active_global=2,
        max_active_per_repo=1,
        lease_seconds=5,
        retry_base_seconds=1,
        max_age_bonus=20,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "queue-contract.sqlite3"
        with storemod.SQLiteShadowStore(db_path) as store:
            q = queue_for(store)

            a_old = queue_mod._persist_operation(
                store, "op_a_old", "owner/a", "refs/heads/main", "1" * 40
            )
            a_new = queue_mod._persist_operation(
                store, "op_a_new", "owner/a", "refs/heads/main", "2" * 40,
                force_generation=1,
            )
            b = queue_mod._persist_operation(
                store, "op_b", "owner/b", "refs/heads/main", "3" * 40,
                priority=400,
            )
            cert = queue_mod._persist_operation(
                store, "op_cert", "owner/a", "refs/heads/main", "4" * 40,
                operation_class="CERTIFICATION",
                analysis_mode="certification",
                priority=500,
            )
            preserve_old = queue_mod._persist_operation(
                store, "op_preserve_old", "owner/c", "refs/heads/main", "5" * 40
            )
            preserve_new = queue_mod._persist_operation(
                store, "op_preserve_new", "owner/c", "refs/heads/main", "6" * 40,
                force_generation=1,
            )

            assert q.enqueue(a_old["operation_id"], now_ts=10)["state"] == "QUEUED"

            expect_error(
                lambda: q.enqueue(
                    a_new["operation_id"],
                    ancestor_shas={a_old["resolved_sha"]},
                    ancestry_proven=False,
                    now_ts=11,
                ),
                "ancestry_proven",
            )
            assert q._entry(a_old["operation_id"])["state"] == "QUEUED"
            assert q._entry(a_new["operation_id"]) is None

            supersede = q.enqueue(
                a_new["operation_id"],
                ancestor_shas={a_old["resolved_sha"]},
                ancestry_proven=True,
                now_ts=12,
            )
            assert supersede["superseded"] == [a_old["operation_id"]]
            assert q._entry(a_old["operation_id"])["state"] == "SUPERSEDED"
            assert q._entry(a_new["operation_id"])["state"] == "QUEUED"

            # Unrelated repository remains independent.
            assert q.enqueue(b["operation_id"], now_ts=13)["state"] == "QUEUED"
            assert q._entry(b["operation_id"])["state"] == "QUEUED"

            # Protected class shares lineage but is outside normal VERIFICATION supersession.
            cert_result = q.enqueue(cert["operation_id"], now_ts=14)
            assert cert_result["protected"] is True
            assert q._entry(cert["operation_id"])["state"] in {"QUEUED", "DEFERRED"}

            # Calibration-preserved work cannot be superseded.
            preserve_result = q.enqueue(
                preserve_old["operation_id"],
                preserve_for_calibration=True,
                now_ts=15,
            )
            assert preserve_result["state"] == "DEFERRED"
            preserve_new_result = q.enqueue(
                preserve_new["operation_id"],
                ancestor_shas={preserve_old["resolved_sha"]},
                ancestry_proven=True,
                now_ts=16,
            )
            assert preserve_old["operation_id"] not in preserve_new_result["superseded"]
            assert q._entry(preserve_old["operation_id"])["state"] == "DEFERRED"

            # Enqueue replay must preserve immutable queue configuration.
            replay = q.enqueue(
                preserve_old["operation_id"],
                preserve_for_calibration=True,
                now_ts=17,
            )
            assert replay["status"] == "REPLAY"
            expect_error(
                lambda: q.enqueue(
                    preserve_old["operation_id"],
                    preserve_for_calibration=False,
                    now_ts=17,
                ),
                "preserve_for_calibration",
            )

            # Highest-priority ready item is claimed first.
            first = q.claim_next("gha-1", now_ts=18)
            assert first is not None
            assert first["operation_id"] == cert["operation_id"]
            assert first["executor"] == "GITHUB_ACTIONS"
            assert first["dispatch_performed"] is False

            # One active lease per repository forces the next claim to another repo.
            second = q.claim_next("gha-2", now_ts=18)
            assert second is not None
            assert second["repository"] != first["repository"]
            assert q.integrity_report()["ok"] is True

            # Deterministic app failure never retries just because caller asks.
            terminal = q.record_failure(
                second["operation_id"],
                second["worker_id"],
                "APP_RUNTIME_FAILURE",
                retryable=True,
                now_ts=19,
            )
            assert terminal["retry"] is False
            assert q._entry(second["operation_id"])["state"] == "BLOCKED"

            # Infrastructure retry is delayed and bounded.
            retry1 = q.record_failure(
                cert["operation_id"],
                first["worker_id"],
                "INFRA_ERROR",
                retryable=True,
                now_ts=19,
            )
            assert retry1["retry"] is True
            assert retry1["retry_count"] == 1
            assert q._entry(cert["operation_id"])["state"] == "QUEUED"
            early = q.claim_next("too-early", now_ts=19.5)
            if early is not None:
                assert early["operation_id"] != cert["operation_id"]
                q.complete(early["operation_id"], early["worker_id"], now_ts=19.6)

            # Claim certification once its retry delay expires.
            cert_retry_claim = None
            for ts in (20.0, 21.0, 22.0):
                claim = q.claim_next(f"gha-retry-{ts}", now_ts=ts)
                if claim is None:
                    continue
                if claim["operation_id"] == cert["operation_id"]:
                    cert_retry_claim = claim
                    break
                q.complete(claim["operation_id"], claim["worker_id"], now_ts=ts + 0.01)
            assert cert_retry_claim is not None

            retry2 = q.record_failure(
                cert["operation_id"],
                cert_retry_claim["worker_id"],
                "INFRA_ERROR",
                retryable=True,
                now_ts=22.5,
            )
            assert retry2["retry"] is True
            assert retry2["retry_count"] == 2

            final_claim = None
            for ts in (24.5, 25.0, 26.0, 27.0):
                claim = q.claim_next(f"gha-final-{ts}", now_ts=ts)
                if claim is None:
                    continue
                if claim["operation_id"] == cert["operation_id"]:
                    final_claim = claim
                    break
                q.complete(claim["operation_id"], claim["worker_id"], now_ts=ts + 0.01)
            assert final_claim is not None

            exhausted = q.record_failure(
                cert["operation_id"],
                final_claim["worker_id"],
                "INFRA_ERROR",
                retryable=True,
                now_ts=28,
            )
            assert exhausted["retry"] is False
            assert q._entry(cert["operation_id"])["state"] == "BLOCKED"
            assert q._entry(cert["operation_id"])["retry_count"] == 2

            # Queue projection cannot be altered without append-only history.
            target = preserve_old["operation_id"]
            current_state = q._entry(target)["state"]
            expect_error(
                lambda: q.db.execute(
                    "UPDATE queue_entries SET state='BLOCKED' WHERE operation_id=?",
                    (target,),
                ),
                "requires history",
            )
            q.db.rollback()
            assert q._entry(target)["state"] == current_state

            # Identity and history are protected at DB level.
            expect_error(
                lambda: q.db.execute(
                    "UPDATE queue_entries SET resolved_sha=? WHERE operation_id=?",
                    ("f" * 40, target),
                ),
                "immutable identity",
            )
            q.db.rollback()
            history = q.history(cert["operation_id"])
            assert history
            expect_error(
                lambda: q.db.execute(
                    "UPDATE queue_history SET reason='tampered' WHERE history_id=?",
                    (history[0]["history_id"],),
                ),
                "append-only",
            )
            q.db.rollback()
            expect_error(
                lambda: q.db.execute(
                    "DELETE FROM queue_entries WHERE operation_id=?",
                    (target,),
                ),
                "cannot be deleted",
            )
            q.db.rollback()

            assert q.integrity_report()["ok"] is True

        # Restart preserves state, retry counters and reconstructable history.
        with storemod.SQLiteShadowStore(db_path) as reopened:
            q2 = queue_for(reopened)
            assert q2._entry(a_old["operation_id"])["state"] == "SUPERSEDED"
            assert q2._entry(cert["operation_id"])["state"] == "BLOCKED"
            assert q2._entry(cert["operation_id"])["retry_count"] == 2
            assert q2.integrity_report()["ok"] is True

    # Hard pending bounds reject admission atomically rather than silently dropping work.
    with tempfile.TemporaryDirectory() as tmp:
        hard_db = Path(tmp) / "hard-bound.sqlite3"
        with storemod.SQLiteShadowStore(hard_db) as store:
            q = queue_mod.DurablePerRepoQueue(
                store,
                max_ready_global=1,
                max_ready_per_repo=1,
                max_pending_global=2,
                max_pending_per_repo=2,
                max_active_global=1,
                max_active_per_repo=1,
            )
            one = queue_mod._persist_operation(
                store, "op_h1", "owner/h", "refs/heads/main", "7" * 40
            )
            two = queue_mod._persist_operation(
                store, "op_h2", "owner/h", "refs/heads/feature", "8" * 40
            )
            three = queue_mod._persist_operation(
                store, "op_h3", "owner/i", "refs/heads/main", "9" * 40
            )
            assert q.enqueue(one["operation_id"], now_ts=1)["state"] == "QUEUED"
            assert q.enqueue(two["operation_id"], now_ts=2)["state"] == "DEFERRED"
            expect_error(
                lambda: q.enqueue(three["operation_id"], now_ts=3),
                "global pending",
            )
            assert q._entry(three["operation_id"]) is None
            assert q.integrity_report()["ok"] is True

    # Lease expiry follows the same bounded infrastructure retry path.
    with tempfile.TemporaryDirectory() as tmp:
        lease_db = Path(tmp) / "lease-expiry.sqlite3"
        with storemod.SQLiteShadowStore(lease_db) as store:
            q = queue_mod.DurablePerRepoQueue(
                store,
                max_ready_global=1,
                max_ready_per_repo=1,
                max_pending_global=4,
                max_pending_per_repo=4,
                max_active_global=1,
                max_active_per_repo=1,
                lease_seconds=2,
                retry_base_seconds=1,
            )
            op = queue_mod._persist_operation(
                store, "op_expire", "owner/x", "refs/heads/main", "a" * 40
            )
            q.enqueue(op["operation_id"], now_ts=10, max_retries=1)
            lease = q.claim_next("gha-expire", now_ts=11)
            assert lease is not None
            recovered = q.recover_expired_leases(now_ts=14)
            assert recovered and recovered[0]["retry"] is True
            assert q._entry(op["operation_id"])["retry_count"] == 1
            assert q.integrity_report()["ok"] is True

    postgres_schema = (
        ROOT / "integration" / "orchestration" / "sql" / "postgres-v54e-queue.sql"
    ).read_text(encoding="utf-8")
    for required in (
        "CREATE TABLE IF NOT EXISTS applab_queue_entries",
        "CREATE TABLE IF NOT EXISTS applab_queue_history",
        "CREATE TABLE IF NOT EXISTS applab_queue_repo_state",
        "applab_guard_queue_identity",
        "applab_queue_entries_delete_guard",
        "applab_queue_history_append_only_u",
    ):
        assert required in postgres_schema, required

    source = (ROOT / "scripts" / "durable_queue_v54e.py").read_text(encoding="utf-8")
    for forbidden in (
        "requests.",
        "urllib.request",
        "socket.",
        "subprocess.",
        "repository_dispatch",
        "workflow_dispatch",
    ):
        assert forbidden not in source, forbidden

    queue_mod.self_test()
    print("AppLab v5.4E Durable Per-Repo Queue contract test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
