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
        raise AssertionError(f"expected error containing {contains!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "queue-contract.sqlite3"

        with storemod.SQLiteShadowStore(db_path) as store:
            q = queue_mod.DurablePerRepoQueue(
                store,
                max_ready_global=2,
                max_ready_per_repo=1,
                max_active_per_repo=1,
                lease_seconds=5,
                retry_base_seconds=1,
            )

            a1 = queue_mod._persist_operation(
                store, "op_a1", "owner/a", "refs/heads/main", "1" * 40
            )
            a2 = queue_mod._persist_operation(
                store, "op_a2", "owner/a", "refs/heads/main", "2" * 40,
                force_generation=1,
            )
            b1 = queue_mod._persist_operation(
                store, "op_b1", "owner/b", "refs/heads/main", "3" * 40,
                priority=400,
            )
            cert = queue_mod._persist_operation(
                store, "op_cert", "owner/a", "refs/heads/main", "4" * 40,
                operation_class="CERTIFICATION",
                analysis_mode="certification",
                priority=500,
            )
            preserve = queue_mod._persist_operation(
                store, "op_preserve", "owner/c", "refs/heads/main", "5" * 40
            )
            preserve_new = queue_mod._persist_operation(
                store, "op_preserve_new", "owner/c", "refs/heads/main", "6" * 40,
                force_generation=1,
            )

            assert q.enqueue(a1["operation_id"], now_ts=10)["state"] == "QUEUED"
            expect_error(
                lambda: q.enqueue(
                    a2["operation_id"],
                    ancestor_shas={a1["resolved_sha"]},
                    now_ts=10.5,
                ),
                "proven ancestry",
            )
            supersede = q.enqueue(
                a2["operation_id"],
                ancestor_shas={a1["resolved_sha"]},
                ancestry_proven=True,
                now_ts=11,
            )
            assert supersede["superseded"] == [a1["operation_id"]]
            assert q._entry(a1["operation_id"])["state"] == "SUPERSEDED"
            assert q._entry(a2["operation_id"])["state"] == "QUEUED"
            expect_error(
                lambda: q.enqueue(
                    a2["operation_id"],
                    preserve_for_calibration=True,
                    now_ts=11.5,
                ),
                "replay conflicts",
            )

            # Different repository is independent and cannot be superseded by repo A.
            assert q.enqueue(b1["operation_id"], now_ts=12)["state"] == "QUEUED"
            assert q._entry(b1["operation_id"])["state"] == "QUEUED"

            # Protected work bypasses soft queue pressure and cannot be auto-superseded.
            assert q.enqueue(cert["operation_id"], now_ts=13)["state"] == "QUEUED"
            assert q._entry(cert["operation_id"])["protected"] == 1

            # Calibration-preservation prevents normal supersession.
            preserve_result = q.enqueue(
                preserve["operation_id"],
                preserve_for_calibration=True,
                now_ts=14,
            )
            assert preserve_result["state"] == "DEFERRED"
            preserve_new_result = q.enqueue(
                preserve_new["operation_id"],
                ancestor_shas={preserve["resolved_sha"]},
                ancestry_proven=True,
                now_ts=15,
            )
            assert preserve["operation_id"] not in preserve_new_result["superseded"]
            assert q._entry(preserve["operation_id"])["state"] == "DEFERRED"

            first_claim = q.claim_next("gha-a", now_ts=16)
            assert first_claim is not None
            assert first_claim["operation_id"] == cert["operation_id"]
            assert first_claim["executor"] == "GITHUB_ACTIONS"
            assert first_claim["dispatch_performed"] is False

            # A second claim may use another repo but never a second lease for same repo.
            second_claim = q.claim_next("gha-b", now_ts=16)
            assert second_claim is not None
            assert second_claim["repository"] != first_claim["repository"]
            assert q.integrity_report()["ok"] is True

            # Deterministic app failure is terminal even when caller asks for retry.
            terminal = q.record_failure(
                second_claim["operation_id"],
                "gha-b",
                "APP_RUNTIME_FAILURE",
                retryable=True,
                now_ts=17,
            )
            assert terminal["retry"] is False
            assert q._entry(second_claim["operation_id"])["state"] == "BLOCKED"

            # Infrastructure retry is bounded.
            retry1 = q.record_failure(
                cert["operation_id"],
                "gha-a",
                "INFRA_ERROR",
                retryable=True,
                now_ts=17,
            )
            assert retry1["retry"] is True
            assert retry1["retry_count"] == 1

            claim_retry = q.claim_next("gha-c", now_ts=18)
            assert claim_retry is not None
            # If another higher-priority eligible item is chosen first, complete it then retry.
            if claim_retry["operation_id"] != cert["operation_id"]:
                q.complete(claim_retry["operation_id"], "gha-c", now_ts=18.1)
                claim_retry = q.claim_next("gha-c2", now_ts=19)
            assert claim_retry is not None
            assert claim_retry["operation_id"] == cert["operation_id"]

            retry2 = q.record_failure(
                cert["operation_id"],
                claim_retry["worker_id"],
                "INFRA_ERROR",
                retryable=True,
                now_ts=19,
            )
            assert retry2["retry"] is True
            assert retry2["retry_count"] == 2

            claim_final = q.claim_next("gha-d", now_ts=22)
            while claim_final is not None and claim_final["operation_id"] != cert["operation_id"]:
                q.complete(claim_final["operation_id"], claim_final["worker_id"], now_ts=22.1)
                claim_final = q.claim_next("gha-d2", now_ts=23)
            assert claim_final is not None
            final = q.record_failure(
                cert["operation_id"],
                claim_final["worker_id"],
                "INFRA_ERROR",
                retryable=True,
                now_ts=24,
            )
            assert final["retry"] is False
            assert q._entry(cert["operation_id"])["state"] == "BLOCKED"

            q.rebalance(now_ts=25)

            # History is enforced append-only by the database.
            history = q.history(cert["operation_id"])
            assert len(history) >= 4
            history_id = history[0]["history_id"]
            expect_error(
                lambda: q.db.execute(
                    "UPDATE queue_history SET reason='tampered' WHERE history_id=?",
                    (history_id,),
                ),
                "append-only",
            )
            q.db.rollback()

            report = q.integrity_report()
            assert report["ok"] is True
            assert report["dispatch_performed"] is False

        # Restart preserves queue projection, retry counters and append-only history.
        with storemod.SQLiteShadowStore(db_path) as reopened:
            q2 = queue_mod.DurablePerRepoQueue(
                reopened,
                max_ready_global=2,
                max_ready_per_repo=1,
                max_active_per_repo=1,
                lease_seconds=5,
                retry_base_seconds=1,
            )
            assert q2._entry(a1["operation_id"])["state"] == "SUPERSEDED"
            assert q2._entry(cert["operation_id"])["retry_count"] == 2
            assert q2._entry(cert["operation_id"])["state"] == "BLOCKED"
            assert q2.integrity_report()["ok"] is True

    with tempfile.TemporaryDirectory() as hard_tmp:
        hard_path = Path(hard_tmp) / "hard-cap.sqlite3"
        with storemod.SQLiteShadowStore(hard_path) as hard_store:
            hard_q = queue_mod.DurablePerRepoQueue(
                hard_store,
                max_ready_global=1,
                max_ready_per_repo=1,
                max_active_per_repo=1,
                max_pending_global=1,
            )
            h1 = queue_mod._persist_operation(
                hard_store, "op_h1", "owner/h", "refs/heads/main", "7" * 40
            )
            h2 = queue_mod._persist_operation(
                hard_store, "op_h2", "owner/i", "refs/heads/main", "8" * 40
            )
            assert hard_q.enqueue(h1["operation_id"], now_ts=1)["state"] == "QUEUED"
            expect_error(
                lambda: hard_q.enqueue(h2["operation_id"], now_ts=2),
                "hard pending limit",
            )
            assert hard_q.integrity_report()["ok"] is True

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
