#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import durable_queue_v54e as queue_mod  # noqa: E402
import durable_store_v54b as storemod  # noqa: E402
import event_driven_pilot_v54g as pilot  # noqa: E402


def expect_reject(fn, contains: str) -> None:
    try:
        fn()
    except pilot.PilotError as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected rejection containing {contains!r}")


def main() -> int:
    base = pilot.load_policy()
    assert base["enabled"] is False
    assert base["authority"] == "ORCHESTRATION_ONLY"
    assert base["certification_authority_changed"] is False
    assert base["watcher_remains_watchdog"] is True
    assert base["github_actions_remains_burst_fallback"] is True
    assert pilot.readiness(base)["activation_ready"] is False

    expect_reject(
        lambda: pilot.effective_policy(
            base,
            enabled=True,
            allowed_repositories=["o/a", "o/b", "o/c", "o/d"],
        ),
        "limit exceeded",
    )

    event = pilot._fixture_event()
    plan = pilot._fixture_plan()

    with tempfile.TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "pilot.sqlite3"
        with storemod.SQLiteShadowStore(store_path) as store:
            q = queue_mod.DurablePerRepoQueue(
                store,
                max_ready_global=4,
                max_ready_per_repo=2,
                max_active_per_repo=1,
            )

            expect_reject(
                lambda: pilot.enqueue_event_operation(
                    store, q, event, plan, "b"*40, base, now_ts=10
                ),
                "disabled",
            )
            assert store.db.execute("SELECT COUNT(*) AS n FROM operations").fetchone()["n"] == 0

            enabled = pilot.effective_policy(
                base, enabled=True, allowed_repositories=["owner/app"]
            )
            first = pilot.enqueue_event_operation(
                store, q, event, plan, "b"*40, enabled, now_ts=11
            )
            second = pilot.enqueue_event_operation(
                store, q, event, plan, "b"*40, enabled, now_ts=12
            )
            assert first["operation_id"] == second["operation_id"]
            assert first["dispatch_performed"] is False
            assert second["dispatch_performed"] is False

            operation_count = store.db.execute(
                "SELECT COUNT(*) AS n FROM operations"
            ).fetchone()["n"]
            assert operation_count == 1, "idempotent event must converge to one Operation"

            intent = pilot.next_executor_intent(q, now_ts=13)
            assert intent is not None
            assert intent["record_type"] == "APPLAB_EXECUTOR_INTENT"
            assert intent["executor"] == "GITHUB_ACTIONS"
            assert intent["dispatch_performed"] is False
            assert intent["transport_required"] is True

            # A non-allowlisted repo never creates work.
            denied = pilot.effective_policy(
                base, enabled=True, allowed_repositories=["owner/other"]
            )
            expect_reject(
                lambda: pilot.create_or_reuse_operation(
                    store, event, plan, "b"*40, denied
                ),
                "allowlisted",
            )

            # Certification cannot be auto-admitted by policy.
            cert_plan = dict(plan, analysis_mode="certification")
            expect_reject(
                lambda: pilot.create_or_reuse_operation(
                    store, event, cert_plan, "b"*40, enabled
                ),
                "analysis mode",
            )

            # Trust boundary is mandatory.
            untrusted = dict(event)
            untrusted["trust"] = dict(event["trust"], signature_verified=False)
            expect_reject(
                lambda: pilot.create_or_reuse_operation(
                    store, untrusted, plan, "b"*40, enabled
                ),
                "trust",
            )

        # Durable restart preserves the admitted operation/queue projection.
        with storemod.SQLiteShadowStore(store_path) as reopened:
            q2 = queue_mod.DurablePerRepoQueue(reopened)
            assert reopened.db.execute(
                "SELECT COUNT(*) AS n FROM operations"
            ).fetchone()["n"] == 1
            assert q2.integrity_report()["ok"] is True

    source = (ROOT / "scripts" / "event_driven_pilot_v54g.py").read_text(encoding="utf-8")
    for forbidden in (
        "requests.",
        "urllib.request",
        "socket.",
        "subprocess.",
        "repository_dispatch",
        "workflow_dispatch",
        "certification_gate",
    ):
        assert forbidden not in source, forbidden

    pilot.self_test()
    print("AppLab v5.4G controlled pilot readiness contract test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
