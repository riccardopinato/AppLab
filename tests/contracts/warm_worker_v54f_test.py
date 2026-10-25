#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import durable_brain_v54a as brain  # noqa: E402
import durable_store_v54b as storemod  # noqa: E402
import warm_worker_v54f as warm  # noqa: E402


def expect_error(fn, contains: str) -> None:
    try:
        fn()
    except (warm.WorkerError, sqlite3.DatabaseError) as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected error containing {contains!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "warm.sqlite3"
        with storemod.SQLiteShadowStore(db) as store:
            op1 = brain._operation_fixture(
                "op_warm_1", "owner/app", "refs/heads/main", "a"*40, "b"*40
            )
            op2 = brain._operation_fixture(
                "op_warm_2", "owner/app", "refs/heads/main", "c"*40, "b"*40,
                force_generation=1,
            )
            store.put_operation(op1)
            store.put_operation(op2)

            pool = warm.WarmWorkerPool(store, lease_seconds=10, heartbeat_timeout=5)
            pool.register(
                "worker-1",
                applab_sha="b"*40,
                runtime_profiles=["android-default", "api35-pixel7pro"],
                snapshot_digest="sha256:" + "1"*64,
                now_ts=100,
            )
            assert pool.worker("worker-1")["state"] == "AVAILABLE"

            lease = pool.acquire(
                op1["operation_id"],
                required_applab_sha="b"*40,
                runtime_profile="api35-pixel7pro",
                now_ts=101,
            )
            assert lease["eligible"] is True
            assert lease["executor"] == "WARM_TRUSTED_ANDROID"
            assert lease["dispatch_performed"] is False

            # Exclusive worker lease.
            fallback = pool.acquire(
                op2["operation_id"],
                required_applab_sha="b"*40,
                runtime_profile="api35-pixel7pro",
                now_ts=102,
            )
            assert fallback["eligible"] is False
            assert fallback["executor"] == "GITHUB_ACTIONS"
            assert fallback["fallback"] is True

            expect_error(
                lambda: pool.heartbeat("worker-1", now_ts=103, lease_id="wrong"),
                "lease mismatch",
            )
            pool.heartbeat("worker-1", now_ts=103, lease_id=lease["lease_id"])

            pool.begin_scrub("worker-1", lease["lease_id"], now_ts=104)
            pool.finish_scrub(
                "worker-1", lease["lease_id"], cleanup_proven=True, now_ts=105
            )
            assert pool.worker("worker-1")["state"] == "AVAILABLE"

            # Capability mismatch fails closed to GitHub fallback.
            mismatch = pool.acquire(
                op2["operation_id"],
                required_applab_sha="d"*40,
                runtime_profile="api35-pixel7pro",
                now_ts=106,
            )
            assert mismatch["eligible"] is False
            assert mismatch["fallback"] is True

            profile_mismatch = pool.acquire(
                op2["operation_id"],
                required_applab_sha="b"*40,
                runtime_profile="api99-unknown",
                now_ts=106,
            )
            assert profile_mismatch["eligible"] is False

            # Lost heartbeat while leased produces UNKNOWN lease + quarantine.
            lease2 = pool.acquire(
                op2["operation_id"],
                required_applab_sha="b"*40,
                runtime_profile="api35-pixel7pro",
                now_ts=107,
            )
            assert lease2["eligible"] is True
            quarantined = pool.reconcile_heartbeats(now_ts=113)
            assert quarantined == ["worker-1"]
            worker = pool.worker("worker-1")
            assert worker["state"] == "QUARANTINED"
            lease_row = pool.db.execute(
                "SELECT state FROM warm_worker_leases WHERE lease_id=?",
                (lease2["lease_id"],),
            ).fetchone()
            assert lease_row["state"] == "UNKNOWN"

            # Explicit re-registration represents out-of-band recovery and increments isolation generation.
            generation = worker["isolation_generation"]
            pool.register(
                "worker-1",
                applab_sha="b"*40,
                runtime_profiles=["api35-pixel7pro"],
                snapshot_digest="sha256:" + "2"*64,
                now_ts=120,
            )
            assert pool.worker("worker-1")["isolation_generation"] == generation + 1

            lease3 = pool.acquire(
                op2["operation_id"],
                required_applab_sha="b"*40,
                runtime_profile="api35-pixel7pro",
                now_ts=121,
            )
            pool.begin_scrub("worker-1", lease3["lease_id"], now_ts=122)
            pool.finish_scrub(
                "worker-1",
                lease3["lease_id"],
                cleanup_proven=False,
                now_ts=123,
                reason="RESIDUAL_PROCESS_DETECTED",
            )
            assert pool.worker("worker-1")["state"] == "QUARANTINED"

            history_id = pool.db.execute(
                "SELECT MIN(history_id) AS n FROM warm_worker_history"
            ).fetchone()["n"]
            expect_error(
                lambda: pool.db.execute(
                    "UPDATE warm_worker_history SET reason='tampered' WHERE history_id=?",
                    (history_id,),
                ),
                "append-only",
            )
            pool.db.rollback()
            assert pool.integrity_report()["ok"] is True

        # Persistent worker history survives Brain process restart.
        with storemod.SQLiteShadowStore(db) as reopened:
            pool2 = warm.WarmWorkerPool(reopened, lease_seconds=10, heartbeat_timeout=5)
            assert pool2.worker("worker-1")["state"] == "QUARANTINED"
            assert pool2.integrity_report()["ok"] is True

    source = (ROOT / "scripts" / "warm_worker_v54f.py").read_text(encoding="utf-8")
    for forbidden in (
        "requests.",
        "urllib.request",
        "socket.",
        "subprocess.",
        "gradlew",
        "flutter build",
        "prepare_command",
        "repository_dispatch",
        "workflow_dispatch",
    ):
        assert forbidden not in source, forbidden

    warm.self_test()
    print("AppLab v5.4F Warm Worker contract test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
