#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_work_graph_v60a as workgraph  # noqa: E402
import controlled_event_v54g as event_pilot  # noqa: E402
import durable_brain_v54a as brain  # noqa: E402
import durable_queue_v54e as queue_mod  # noqa: E402
import durable_store_v54b as storemod  # noqa: E402
import event_driven_recovery_v61b as recovery  # noqa: E402
import queue_backpressure_budget_v61c as control  # noqa: E402


def expect_budget_error(callback, contains: str) -> None:
    try:
        callback()
    except control.BudgetError as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected BudgetError containing {contains!r}")


def build_work(
    *,
    db_path: Path,
    index: int,
    target_sha: str,
) -> str:
    with storemod.SQLiteShadowStore(db_path) as durable:
        graph = workgraph.AgentWorkGraphStore(durable)
        queue = queue_mod.DurablePerRepoQueue(
            durable, **event_pilot.QUEUE_LIMITS
        )
        operation = brain._operation_fixture(
            f"op_v61c-{index}",
            "riccardopinato/AppLab",
            "refs/heads/main",
            target_sha,
            target_sha,
            state="RUNNING",
            force_generation=index,
        )
        durable.put_operation(operation)
        queue.enqueue(operation["operation_id"], now_ts=10.0 + index)
        item = workgraph.adapt_operation_to_work_item(
            operation,
            work_item_id=f"wrk_v61c-{index}",
            allow_code_edit=True,
            allow_draft_pr_steward=True,
        )
        item["state"] = "VERIFYING"
        graph.put_work_item(item)
        return item["work_item_id"]


def behavioral_proof() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        db_path = root / "v61c.sqlite3"
        sha_a = "a" * 40
        sha_b = "b" * 40

        work_items = [
            build_work(db_path=db_path, index=1, target_sha=sha_a),
            build_work(db_path=db_path, index=2, target_sha=sha_a),
            build_work(db_path=db_path, index=3, target_sha=sha_b),
            build_work(db_path=db_path, index=4, target_sha=sha_a),
        ]
        target_shas = [sha_a, sha_a, sha_b, sha_a]

        budgets = [
            control.register_budget(
                db_path=db_path,
                work_item_id=work_item_id,
                now_ts=20.0,
                occurred_at="2026-10-27T15:00:00Z",
                max_observation_batches=1 if index == 0 else None,
            )
            for index, work_item_id in enumerate(work_items)
        ]
        assert budgets[0]["queue_state"] == "QUEUED"
        assert all(row["queue_state"] == "DEFERRED" for row in budgets[1:])
        assert all(row["queue_backpressure"] is True for row in budgets[1:])
        assert budgets[0]["new_queue_created"] is False

        attempt1 = control.reserve_repair_attempt(
            db_path=db_path,
            work_item_id=work_items[2],
            attempt_number=1,
            changed_files=2,
            changed_lines=80,
            runtime_seconds=200,
            cost_units=50,
            occurred_at="2026-10-27T15:01:00Z",
        )
        assert attempt1["authorized"] is True
        attempt1_replay = control.reserve_repair_attempt(
            db_path=db_path,
            work_item_id=work_items[2],
            attempt_number=1,
            changed_files=2,
            changed_lines=80,
            runtime_seconds=200,
            cost_units=50,
            occurred_at="2026-10-27T15:01:30Z",
        )
        assert attempt1_replay["authorized"] is True
        assert attempt1_replay["event_persistence"] == "REPLAY"
        expect_budget_error(
            lambda: control.reserve_repair_attempt(
                db_path=db_path,
                work_item_id=work_items[2],
                attempt_number=1,
                changed_files=3,
                changed_lines=80,
                runtime_seconds=200,
                cost_units=50,
                occurred_at="2026-10-27T15:01:31Z",
            ),
            "conflicts with immutable attempt usage",
        )
        attempt2 = control.reserve_repair_attempt(
            db_path=db_path,
            work_item_id=work_items[2],
            attempt_number=2,
            changed_files=1,
            changed_lines=40,
            runtime_seconds=150,
            cost_units=40,
            occurred_at="2026-10-27T15:03:00Z",
        )
        assert attempt2["authorized"] is True
        assert attempt2["consumed_runtime_seconds"] == 350
        assert attempt2["consumed_cost_units"] == 90

        # A, B, A, A proves that delivery dedupe is keyed by occurrence rather
        # than signature text. Replaying occurrence 3 remains idempotent.
        sequence = [
            ("failure-1", "sig-a"),
            ("failure-2", "sig-b"),
            ("failure-3", "sig-a"),
        ]
        for occurrence_id, signature in sequence:
            observed = control.note_failure_signature(
                db_path=db_path,
                work_item_id=work_items[3],
                failure_signature=signature,
                occurrence_id=occurrence_id,
                occurred_at="2026-10-27T15:04:00Z",
            )
            assert observed["repeated"] is False
        replayed = control.note_failure_signature(
            db_path=db_path,
            work_item_id=work_items[3],
            failure_signature="sig-a",
            occurrence_id="failure-3",
            occurred_at="2026-10-27T15:04:01Z",
        )
        assert replayed["event_persistence"] == "REPLAY"
        assert replayed["repeated"] is False
        repeated = control.note_failure_signature(
            db_path=db_path,
            work_item_id=work_items[3],
            failure_signature="sig-a",
            occurrence_id="failure-4",
            occurred_at="2026-10-27T15:04:02Z",
        )
        assert repeated["repeated"] is True
        assert repeated["budget_state"] == "STOPPED"

        wait1 = recovery.begin_wait(
            db_path=db_path,
            work_item_id=work_items[0],
            target_sha=target_shas[0],
            required_gates=["AppLab CI", "AppLab CodeQL"],
            now_ts=100.0,
            occurred_at="2026-10-27T15:05:00Z",
        )
        wait2 = recovery.begin_wait(
            db_path=db_path,
            work_item_id=work_items[1],
            target_sha=target_shas[1],
            required_gates=["AppLab CI", "Emulator Self Test"],
            now_ts=100.0,
            occurred_at="2026-10-27T15:05:00Z",
        )
        wait3 = recovery.begin_wait(
            db_path=db_path,
            work_item_id=work_items[2],
            target_sha=target_shas[2],
            required_gates=["AppLab CI"],
            now_ts=100.0,
            occurred_at="2026-10-27T15:05:00Z",
        )
        all_wait_ids = [wait1["wait_id"], wait2["wait_id"], wait3["wait_id"]]

        # Same repo + SHA waits coalesce. A second SHA in the same repository is
        # deferred by persisted per-cycle repository capacity.
        plan = control.plan_observation_batches(
            db_path=db_path,
            wait_ids=all_wait_ids,
            cycle_id="cycle-v61c-1",
            now_ts=221.0,
            actions_available=True,
            occurred_at="2026-10-27T15:06:00Z",
        )
        assert plan["external_query_count"] == 1
        assert plan["covered_wait_count"] == 2
        assert plan["coalesced_wait_savings"] == 1
        assert len(plan["deferred"]) == 1
        assert plan["deferred"][0]["target_sha"] == sha_b
        assert plan["batches"][0]["pending_gates"] == [
            "AppLab CI",
            "AppLab CodeQL",
            "Emulator Self Test",
        ]

        replay = control.plan_observation_batches(
            db_path=db_path,
            wait_ids=all_wait_ids,
            cycle_id="cycle-v61c-1",
            now_ts=221.0,
            actions_available=True,
            occurred_at="2026-10-27T15:06:01Z",
        )
        assert replay["external_query_count"] == 1
        assert replay["batches"][0]["status"] == "REPLAY"
        assert len(replay["deferred"]) == 1
        assert replay["deferred"][0]["target_sha"] == sha_b

        # Journal-first crash recovery: persist batch+budget reservation without
        # consuming v6.1B fallback, then recover it through the normal planner.
        with storemod.SQLiteShadowStore(db_path) as durable:
            wait3_snapshot = control._wait_row(durable, wait3["wait_id"])
        crash_reservation = control._reserve_batch_intent(
            db_path=db_path,
            cycle_id="cycle-v61c-crash",
            repository="riccardopinato/AppLab",
            target_sha=sha_b,
            waits=[wait3_snapshot],
            occurred_at="2026-10-27T15:06:10Z",
            max_global=4,
            max_per_repo=1,
        )
        assert crash_reservation["status"] == "INSERTED"
        with storemod.SQLiteShadowStore(db_path) as durable:
            durable.db.executescript(recovery.WAIT_SCHEMA)
            assert control._wait_row(durable, wait3["wait_id"])["fallback_count"] == 0

        crash_recovery = control.plan_observation_batches(
            db_path=db_path,
            wait_ids=[wait3["wait_id"]],
            cycle_id="cycle-v61c-crash",
            now_ts=221.0,
            actions_available=True,
            occurred_at="2026-10-27T15:06:11Z",
        )
        assert crash_recovery["external_query_count"] == 1
        with storemod.SQLiteShadowStore(db_path) as durable:
            durable.db.executescript(recovery.WAIT_SCHEMA)
            assert control._wait_row(durable, wait3["wait_id"])["fallback_count"] == 1

        # WorkItem 0 has max_observation_batches=1 and consumed it above.
        # Persist READY while injecting a crash before v6.1B can resume the
        # WorkItem; v6.1C must recover READY before applying budget filtering.
        recovery.observe_event(
            db_path=db_path,
            wait_id=wait1["wait_id"],
            event_id="evt_v61c.ready.1",
            target_sha=sha_a,
            gate="AppLab CI",
            status="completed",
            conclusion="success",
            occurred_at="2026-10-27T15:07:00Z",
        )
        original_resume = recovery._resume_ready_wait

        def interrupt_resume(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("injected resume interruption")

        recovery._resume_ready_wait = interrupt_resume
        try:
            try:
                recovery.observe_event(
                    db_path=db_path,
                    wait_id=wait1["wait_id"],
                    event_id="evt_v61c.ready.2",
                    target_sha=sha_a,
                    gate="AppLab CodeQL",
                    status="completed",
                    conclusion="success",
                    occurred_at="2026-10-27T15:07:01Z",
                )
            except RuntimeError as exc:
                assert "injected resume interruption" in str(exc)
            else:
                raise AssertionError("expected injected READY resume interruption")
        finally:
            recovery._resume_ready_wait = original_resume

        ready_recovery = control.plan_observation_batches(
            db_path=db_path,
            wait_ids=[wait1["wait_id"]],
            cycle_id="cycle-v61c-ready-recovery",
            now_ts=230.0,
            actions_available=True,
            occurred_at="2026-10-27T15:07:02Z",
        )
        assert ready_recovery["external_query_count"] == 0
        assert any(
            row.get("action") == "RECOVER_READY_FOR_EVALUATION"
            for row in ready_recovery["immediate"]
        )

        # A terminal durable identity cannot be reopened by the budget layer.
        terminal_db = root / "terminal.sqlite3"
        with storemod.SQLiteShadowStore(terminal_db) as durable:
            graph = workgraph.AgentWorkGraphStore(durable)
            queue = queue_mod.DurablePerRepoQueue(
                durable, **event_pilot.QUEUE_LIMITS
            )
            operation = brain._operation_fixture(
                "op_v61c-terminal",
                "riccardopinato/AppLab",
                "refs/heads/main",
                "c" * 40,
                "c" * 40,
                state="FAILED",
                force_generation=99,
            )
            durable.put_operation(operation)
            queue.enqueue(operation["operation_id"], now_ts=1.0)
            item = workgraph.adapt_operation_to_work_item(
                operation,
                work_item_id="wrk_v61c-terminal",
                allow_code_edit=True,
            )
            graph.put_work_item(item)
        expect_budget_error(
            lambda: control.register_budget(
                db_path=terminal_db,
                work_item_id="wrk_v61c-terminal",
                now_ts=2.0,
                occurred_at="2026-10-27T15:08:00Z",
            ),
            "terminal durable operation",
        )

        return {
            "schema_version": 1,
            "record_type": "APPLAB_V61C_QUEUE_BUDGET_PROOF",
            "status": "PASS",
            "existing_queue_reused": True,
            "per_repository_backpressure_observed": True,
            "work_item_file_line_attempt_budgets_preserved": True,
            "runtime_cost_budgets_cumulative": True,
            "attempt_reservation_idempotent": True,
            "failure_occurrence_idempotent": True,
            "repeated_failure_signature_stops": True,
            "event_driven_primary": True,
            "same_sha_waits_coalesced": True,
            "persisted_batch_replay_recovered": True,
            "cycle_capacity_persisted": True,
            "batch_journal_precedes_fallback_consumption": True,
            "ready_recovery_ignores_observation_exhaustion": True,
            "terminal_identity_reopen_denied": True,
            "coalesced_external_query_count": plan["external_query_count"],
            "coalesced_wait_count": plan["covered_wait_count"],
            "fixed_interval_polling_primary": False,
            "network_call_per_wait": False,
            "target_sha_mutation_performed": False,
            "merge_authority": "UNCHANGED",
            "release_authority": "DENIED",
            "certification_authority": "UNCHANGED",
        }


def main() -> int:
    contract = control.load_contract()
    module_proof = control.self_test()
    proof = behavioral_proof()

    assert contract["authority"] == "ORCHESTRATION_ONLY"
    assert contract["queue_authority"] == "EXISTING_DURABLE_PER_REPO_QUEUE"
    assert contract["observation_source"] == "V61B_RECONCILIATION_DIRECTIVES"
    assert module_proof["status"] == "PASS"

    assert proof["status"] == "PASS"
    assert proof["existing_queue_reused"] is True
    assert proof["per_repository_backpressure_observed"] is True
    assert proof["work_item_file_line_attempt_budgets_preserved"] is True
    assert proof["runtime_cost_budgets_cumulative"] is True
    assert proof["attempt_reservation_idempotent"] is True
    assert proof["failure_occurrence_idempotent"] is True
    assert proof["persisted_batch_replay_recovered"] is True
    assert proof["cycle_capacity_persisted"] is True
    assert proof["batch_journal_precedes_fallback_consumption"] is True
    assert proof["ready_recovery_ignores_observation_exhaustion"] is True
    assert proof["terminal_identity_reopen_denied"] is True
    assert proof["repeated_failure_signature_stops"] is True
    assert proof["same_sha_waits_coalesced"] is True
    assert proof["coalesced_external_query_count"] == 1
    assert proof["coalesced_wait_count"] == 2
    assert proof["fixed_interval_polling_primary"] is False
    assert proof["network_call_per_wait"] is False
    assert proof["target_sha_mutation_performed"] is False
    assert proof["release_authority"] == "DENIED"
    assert proof["certification_authority"] == "UNCHANGED"

    source = (ROOT / "scripts" / "queue_backpressure_budget_v61c.py").read_text(
        encoding="utf-8"
    )
    assert "DurablePerRepoQueue" in source
    assert "recovery.reconcile_wait" in source
    assert "time.sleep(" not in source
    assert "requests." not in source
    assert "urllib." not in source

    print("AppLab v6.1C queue/backpressure/budget contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
