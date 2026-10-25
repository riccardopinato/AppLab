#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import durable_store_v54b as storemod  # noqa: E402
import warm_worker_v54f as warm  # noqa: E402


def expect_error(fn, contains: str) -> None:
    try:
        fn()
    except (warm.WorkerError, sqlite3.DatabaseError) as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected error containing {contains!r}")


def capabilities(*, profile: str = "android-default") -> dict:
    return {
        "kvm": True,
        "android_runtime": True,
        "disposable_avd": True,
        "evidence_capture": True,
        "runtime_profiles": [profile],
        "api_levels": [35],
        "screen_capture": True,
    }


def activate(registry: warm.WarmWorkerRegistry, worker_id: str, sha: str, now: float) -> None:
    registry.register(
        worker_id,
        sha,
        capabilities(),
        "sha256:" + ("1" * 64),
        now_ts=now,
    )
    registry.activate(
        worker_id,
        now_ts=now + 0.1,
        kvm_attested=True,
        snapshot_verified=True,
        clean_process_table=True,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "warm-worker.sqlite3"
        with storemod.SQLiteShadowStore(db_path) as store:
            registry = warm.WarmWorkerRegistry(
                store,
                heartbeat_ttl_seconds=5,
                default_lease_seconds=4,
            )
            activate(registry, "warm-a", "a" * 40, 1)

            # Exact worker identity can replay, but cannot drift.
            replay = registry.register(
                "warm-a",
                "a" * 40,
                capabilities(),
                "sha256:" + ("1" * 64),
                now_ts=2,
            )
            assert replay["status"] == "REPLAY"
            expect_error(
                lambda: registry.register(
                    "warm-a",
                    "b" * 40,
                    capabilities(),
                    "sha256:" + ("1" * 64),
                    now_ts=2,
                ),
                "conflicting immutable identity",
            )

            # AppLab SHA/profile mismatch falls back rather than weakening eligibility.
            mismatch = registry.acquire_lease(
                "op-sha-mismatch",
                "b" * 40,
                "android-default",
                now_ts=2.2,
            )
            assert mismatch["executor"] == "GITHUB_ACTIONS"
            assert mismatch["fallback"] is True
            profile = registry.acquire_lease(
                "op-profile-mismatch",
                "a" * 40,
                "api99-unknown",
                now_ts=2.2,
            )
            assert profile["fallback"] is True

            lease = registry.acquire_lease(
                "op-1",
                "a" * 40,
                "android-default",
                now_ts=2.5,
            )
            assert lease["executor"] == "WARM_TRUSTED_ANDROID"
            assert lease["fallback"] is False
            assert lease["dispatch_performed"] is False

            # Exclusive lease: same worker cannot accept another operation.
            no_second = registry.acquire_lease(
                "op-2",
                "a" * 40,
                "android-default",
                now_ts=2.6,
            )
            assert no_second["fallback"] is True

            registry.begin_scrub(lease["lease_id"], now_ts=3)
            clean = {name: True for name in warm.REQUIRED_CLEANUP_ATTESTATIONS}
            released = registry.release_after_scrub(
                lease["lease_id"],
                clean,
                now_ts=3.5,
            )
            assert released["state"] == "AVAILABLE"

            # Incomplete cleanup can never return a worker to AVAILABLE.
            dirty_lease = registry.acquire_lease(
                "op-dirty",
                "a" * 40,
                "android-default",
                now_ts=4,
            )
            registry.begin_scrub(dirty_lease["lease_id"], now_ts=4.5)
            dirty = dict(clean)
            dirty["app_data_discarded"] = False
            quarantined = registry.release_after_scrub(
                dirty_lease["lease_id"],
                dirty,
                now_ts=5,
            )
            assert quarantined["state"] == "QUARANTINED"
            assert registry.acquire_lease(
                "op-after-quarantine",
                "a" * 40,
                "android-default",
                now_ts=5.1,
            )["fallback"] is True

            # Direct SQL cannot mutate identity/history/state without history.
            expect_error(
                lambda: registry.db.execute(
                    "UPDATE warm_workers SET applab_sha=? WHERE worker_id='warm-a'",
                    ("c" * 40,),
                ),
                "immutable identity",
            )
            registry.db.rollback()
            history_id = registry.db.execute(
                "SELECT MIN(history_id) AS n FROM warm_worker_history WHERE worker_id='warm-a'"
            ).fetchone()["n"]
            expect_error(
                lambda: registry.db.execute(
                    "UPDATE warm_worker_history SET reason='tampered' WHERE history_id=?",
                    (history_id,),
                ),
                "append-only",
            )
            registry.db.rollback()
            expect_error(
                lambda: registry.db.execute(
                    "UPDATE warm_workers SET state='AVAILABLE' WHERE worker_id='warm-a'"
                ),
                "requires history",
            )
            registry.db.rollback()
            assert registry.integrity_report()["ok"] is True

            # Separate fresh worker: stale heartbeat quarantines AVAILABLE worker.
            activate(registry, "warm-stale", "a" * 40, 10)
            stale_actions = registry.sweep(now_ts=20)
            assert any(
                item["worker_id"] == "warm-stale" and item["state"] == "QUARANTINED"
                for item in stale_actions
            )

            # Separate fresh worker: expired lease is uncertain cleanup -> quarantine.
            activate(registry, "warm-expire", "a" * 40, 30)
            expiring = registry.acquire_lease(
                "op-expire",
                "a" * 40,
                "android-default",
                now_ts=31,
                lease_seconds=2,
            )
            assert expiring["fallback"] is False
            expired_actions = registry.sweep(now_ts=34)
            assert any(
                item["worker_id"] == "warm-expire"
                and item["state"] == "QUARANTINED"
                for item in expired_actions
            )
            assert registry.integrity_report()["ok"] is True

        # Restart preserves quarantine/lease history and projections.
        with storemod.SQLiteShadowStore(db_path) as reopened:
            registry = warm.WarmWorkerRegistry(
                reopened,
                heartbeat_ttl_seconds=5,
                default_lease_seconds=4,
            )
            states = {item["worker_id"]: item["state"] for item in registry.worker_snapshot()}
            assert states["warm-a"] == "QUARANTINED"
            assert states["warm-stale"] == "QUARANTINED"
            assert states["warm-expire"] == "QUARANTINED"
            assert registry.integrity_report()["ok"] is True

    # Equivalence can only become promotion-candidate with exact identity,
    # matching lab/verdict outcomes, clean isolation and measurable improvement.
    control = {
        "repository": "owner/app",
        "resolved_sha": "d" * 40,
        "applab_sha": "e" * 40,
        "apk_sha256": "sha256:" + ("2" * 64),
        "package_id": "dev.applab.selftest",
        "analysis_mode": "full",
        "result": "PASS",
        "labs": {"system_lab": "PASS", "network_lab": "WARN"},
        "runtime_seconds": 100.0,
    }
    fast_warm = dict(control, runtime_seconds=70.0)
    equivalent = warm.compare_equivalence(
        control,
        fast_warm,
        isolation_clean=True,
        minimum_improvement_percent=5.0,
    )
    assert equivalent["equivalent"] is True
    assert equivalent["promotion_candidate"] is True

    no_improvement = warm.compare_equivalence(
        control,
        dict(control, runtime_seconds=101.0),
        isolation_clean=True,
        minimum_improvement_percent=1.0,
    )
    assert no_improvement["equivalent"] is True
    assert no_improvement["promotion_candidate"] is False

    dirty = warm.compare_equivalence(
        control,
        fast_warm,
        isolation_clean=False,
    )
    assert dirty["promotion_candidate"] is False

    mismatch = warm.compare_equivalence(
        control,
        dict(fast_warm, result="FAIL"),
        isolation_clean=True,
    )
    assert mismatch["verdict_match"] is False
    assert mismatch["promotion_candidate"] is False

    postgres_schema = (
        ROOT / "integration" / "orchestration" / "sql" / "postgres-v54f-workers.sql"
    ).read_text(encoding="utf-8")
    for required in (
        "CREATE TABLE IF NOT EXISTS applab_warm_workers",
        "CREATE TABLE IF NOT EXISTS applab_warm_worker_leases",
        "CREATE TABLE IF NOT EXISTS applab_warm_worker_history",
        "applab_warm_active_lease_one_per_worker",
        "applab_guard_warm_worker_identity",
        "applab_warm_history_append_only_u",
    ):
        assert required in postgres_schema, required

    source = (ROOT / "scripts" / "warm_worker_v54f.py").read_text(encoding="utf-8")
    for forbidden in (
        "requests.",
        "urllib.request",
        "socket.",
        "subprocess.",
        "repository_dispatch",
        "workflow_dispatch",
        "prepare_command",
        "gradle",
        "flutter build",
    ):
        assert forbidden not in source.lower(), forbidden

    warm.self_test()
    print("AppLab v5.4F Warm Worker contract test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
