#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import closed_loop_pilot_v61a as pilot61a  # noqa: E402
import event_driven_recovery_v61b as recovery  # noqa: E402


def prepare_fixture(db_path: Path, sha: str, delivery: str) -> tuple[str, str]:
    admitted = pilot61a.admit_closed_loop(
        db_path=db_path,
        repository="riccardopinato/AppLab",
        source_ref="refs/heads/main",
        resolved_sha=sha,
        applab_sha=sha,
        delivery_id=delivery,
        risk="NORMAL",
        now_ts=1000.0,
    )
    work_item_id = str(admitted["work_item_id"])
    operation_id = str(admitted["operation_id"])

    durable, graph = recovery._open(db_path)
    try:
        item = graph.get_work_item(work_item_id)
        recovery._work_transition(
            graph,
            work_item_id=work_item_id,
            from_state=item["current_state"],
            to_state="PLANNED",
            reason="V61B_TEST_PLANNED",
            occurred_at="2026-10-27T14:00:00Z",
            identity=delivery,
        )
        recovery._work_transition(
            graph,
            work_item_id=work_item_id,
            from_state="PLANNED",
            to_state="VERIFYING",
            reason="V61B_TEST_VERIFYING",
            occurred_at="2026-10-27T14:00:01Z",
            identity=delivery,
        )

        state = durable.get_operation(operation_id)["current_state"]
        path = (
            ("QUEUED", "PLANNING"),
            ("PLANNING", "READY"),
            ("READY", "RUNNING"),
        )
        for index, (expected, next_state) in enumerate(path, start=1):
            if state == expected:
                recovery._operation_transition(
                    durable,
                    operation_id=operation_id,
                    from_state=expected,
                    to_state=next_state,
                    reason=f"V61B_TEST_{next_state}",
                    occurred_at=f"2026-10-27T14:00:0{index + 1}Z",
                    identity=delivery,
                )
                state = next_state
        assert state == "RUNNING"
    finally:
        durable.close()
    return work_item_id, operation_id


def main() -> int:
    contract = recovery.load_contract()
    static = recovery.self_test()
    assert static["status"] == "PASS"
    assert static["primary_progression"] == "EVENT_DRIVEN"
    assert static["fallback_polling_primary"] is False

    source = (ROOT / "scripts" / "event_driven_recovery_v61b.py").read_text(
        encoding="utf-8"
    )
    assert "time.sleep(" not in source
    assert "requests." not in source
    assert "POLL_PENDING_GATES" in source
    assert "V61B_SUPERSEDED_TARGET_SHA" in source

    sha = "a" * 40
    gates = ["AppLab CI", "AppLab CodeQL", "Emulator Self Test"]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        db_path = root / "main.sqlite3"
        work_item_id, operation_id = prepare_fixture(db_path, sha, "v61b-main")
        wait = recovery.begin_wait(
            db_path=db_path,
            work_item_id=work_item_id,
            target_sha=sha,
            required_gates=gates,
            now_ts=1000.0,
            occurred_at="2026-10-27T14:01:00Z",
            contract=contract,
        )
        assert wait["state"] == "WAITING"
        assert wait["primary_progression"] == "EVENT_DRIVEN"

        replay_wait = recovery.begin_wait(
            db_path=db_path,
            work_item_id=work_item_id,
            target_sha=sha,
            required_gates=list(reversed(gates)),
            now_ts=1001.0,
            occurred_at="2026-10-27T14:01:01Z",
            contract=contract,
        )
        assert replay_wait["status"] == "REPLAY"
        assert replay_wait["wait_id"] == wait["wait_id"]

        early = recovery.reconcile_wait(
            db_path=db_path,
            wait_id=wait["wait_id"],
            now_ts=1050.0,
            actions_available=True,
            occurred_at="2026-10-27T14:01:50Z",
        )
        assert early["action"] == "WAIT_EVENT"
        assert early["poll"] is False

        first = recovery.observe_event(
            db_path=db_path,
            wait_id=wait["wait_id"],
            event_id="evt_v61b_ci_green",
            target_sha=sha,
            gate="AppLab CI",
            status="completed",
            conclusion="success",
            occurred_at="2026-10-27T14:02:00Z",
            run_id="run-ci",
            run_attempt=1,
            contract=contract,
        )
        assert first["gate_state"] == "SUCCESS"
        assert first["pending_gates"] == ["AppLab CodeQL", "Emulator Self Test"]
        assert first["poll"] is False

        duplicate = recovery.observe_event(
            db_path=db_path,
            wait_id=wait["wait_id"],
            event_id="evt_v61b_ci_green",
            target_sha=sha,
            gate="AppLab CI",
            status="completed",
            conclusion="success",
            occurred_at="2026-10-27T14:02:00Z",
            run_id="run-ci",
            run_attempt=1,
            contract=contract,
        )
        assert duplicate["status"] == "REPLAY"

        stale = recovery.observe_event(
            db_path=db_path,
            wait_id=wait["wait_id"],
            event_id="evt_v61b_ci_stale",
            target_sha=sha,
            gate="AppLab CI",
            status="in_progress",
            conclusion=None,
            occurred_at="2026-10-27T14:01:59Z",
            run_id="run-ci",
            run_attempt=1,
            contract=contract,
        )
        assert stale["status"] == "STALE_EVENT_IGNORED"
        assert stale["gate_state"] == "SUCCESS"
        assert stale["pending_gates"] == ["AppLab CodeQL", "Emulator Self Test"]

        outage = recovery.reconcile_wait(
            db_path=db_path,
            wait_id=wait["wait_id"],
            now_ts=1121.0,
            actions_available=False,
            occurred_at="2026-10-27T14:02:01Z",
        )
        assert outage["action"] == "HOLD_DURABLE_WAIT"
        assert outage["poll"] is False

        fallback = recovery.reconcile_wait(
            db_path=db_path,
            wait_id=wait["wait_id"],
            now_ts=1121.0,
            actions_available=True,
            occurred_at="2026-10-27T14:02:02Z",
        )
        assert fallback["action"] == "POLL_PENDING_GATES"
        assert fallback["pending_gates"] == ["AppLab CodeQL", "Emulator Self Test"]
        assert fallback["fallback_count"] == 1

        # A fresh SQLite connection sees the same pending gates and fallback budget.
        restart = recovery.reconcile_wait(
            db_path=db_path,
            wait_id=wait["wait_id"],
            now_ts=1122.0,
            actions_available=True,
            occurred_at="2026-10-27T14:02:03Z",
        )
        assert restart["action"] == "WAIT_EVENT"
        assert restart["pending_gates"] == ["AppLab CodeQL", "Emulator Self Test"]

        recovery.observe_event(
            db_path=db_path,
            wait_id=wait["wait_id"],
            event_id="evt_v61b_codeql_green",
            target_sha=sha,
            gate="AppLab CodeQL",
            status="completed",
            conclusion="success",
            occurred_at="2026-10-27T14:03:00Z",
            contract=contract,
        )
        final = recovery.observe_event(
            db_path=db_path,
            wait_id=wait["wait_id"],
            event_id="evt_v61b_emulator_green",
            target_sha=sha,
            gate="Emulator Self Test",
            status="completed",
            conclusion="success",
            occurred_at="2026-10-27T14:03:01Z",
            contract=contract,
        )
        assert final["state"] == "READY_FOR_EVALUATION"
        assert final["observed_all_green"] is True
        assert final["pending_gates"] == []

        durable, graph = recovery._open(db_path)
        try:
            assert graph.get_work_item(work_item_id)["current_state"] == "VERIFYING"
            assert durable.get_operation(operation_id)["current_state"] == "RUNNING"
            assert recovery._wait_row(durable, wait["wait_id"])["fallback_count"] == 1
        finally:
            durable.close()

        # Interrupted initialization replays into a fully active durable wait.
        init_db = root / "init-recovery.sqlite3"
        init_work, init_op = prepare_fixture(init_db, sha, "v61b-init")
        original_operation_transition = recovery._operation_transition
        fail_once = {"armed": True}

        def interrupted_operation_transition(*args, **kwargs):
            if (
                fail_once["armed"]
                and kwargs.get("to_state") == "WAITING_EXTERNAL"
            ):
                fail_once["armed"] = False
                raise RuntimeError("injected operation transition interruption")
            return original_operation_transition(*args, **kwargs)

        recovery._operation_transition = interrupted_operation_transition
        try:
            try:
                recovery.begin_wait(
                    db_path=init_db,
                    work_item_id=init_work,
                    target_sha=sha,
                    required_gates=gates,
                    now_ts=1500.0,
                    occurred_at="2026-10-27T14:30:00Z",
                    contract=contract,
                )
                raise AssertionError("injected interruption did not fire")
            except RuntimeError as exc:
                assert "injected operation transition" in str(exc)
        finally:
            recovery._operation_transition = original_operation_transition

        recovered_wait = recovery.begin_wait(
            db_path=init_db,
            work_item_id=init_work,
            target_sha=sha,
            required_gates=gates,
            now_ts=1501.0,
            occurred_at="2026-10-27T14:30:01Z",
            contract=contract,
        )
        assert recovered_wait["status"] == "REPLAY"
        init_store, init_graph = recovery._open(init_db)
        try:
            assert init_graph.get_work_item(init_work)["current_state"] == "WAITING_EXTERNAL"
            assert init_store.get_operation(init_op)["current_state"] == "WAITING_EXTERNAL"
        finally:
            init_store.close()

        # A committed READY projection is repaired by reconciliation if the
        # coordinator died before WorkItem/operation transitions completed.
        ready_db = root / "ready-recovery.sqlite3"
        ready_work, ready_op = prepare_fixture(ready_db, sha, "v61b-ready")
        ready_wait = recovery.begin_wait(
            db_path=ready_db,
            work_item_id=ready_work,
            target_sha=sha,
            required_gates=["AppLab CI"],
            now_ts=1700.0,
            occurred_at="2026-10-27T14:40:00Z",
            contract=contract,
        )
        original_resume = recovery._resume_ready_wait

        def interrupted_resume(*args, **kwargs):
            raise RuntimeError("injected ready transition interruption")

        recovery._resume_ready_wait = interrupted_resume
        try:
            try:
                recovery.observe_event(
                    db_path=ready_db,
                    wait_id=ready_wait["wait_id"],
                    event_id="evt_v61b_ready_green",
                    target_sha=sha,
                    gate="AppLab CI",
                    status="completed",
                    conclusion="success",
                    occurred_at="2026-10-27T14:41:00Z",
                    run_id="run-ready",
                    contract=contract,
                )
                raise AssertionError("injected ready interruption did not fire")
            except RuntimeError as exc:
                assert "injected ready transition" in str(exc)
        finally:
            recovery._resume_ready_wait = original_resume

        recovered_ready = recovery.reconcile_wait(
            db_path=ready_db,
            wait_id=ready_wait["wait_id"],
            now_ts=1800.0,
            actions_available=True,
            occurred_at="2026-10-27T14:42:00Z",
        )
        assert recovered_ready["action"] == "RECOVER_READY_FOR_EVALUATION"
        ready_store, ready_graph = recovery._open(ready_db)
        try:
            assert ready_graph.get_work_item(ready_work)["current_state"] == "VERIFYING"
            assert ready_store.get_operation(ready_op)["current_state"] == "RUNNING"
        finally:
            ready_store.close()

        # Two reconcilers racing the same due wait reserve one fallback poll.
        race_db = root / "race.sqlite3"
        race_work, _ = prepare_fixture(race_db, sha, "v61b-race")
        race_wait = recovery.begin_wait(
            db_path=race_db,
            work_item_id=race_work,
            target_sha=sha,
            required_gates=["AppLab CI"],
            now_ts=1900.0,
            occurred_at="2026-10-27T14:50:00Z",
            contract=contract,
        )

        def reconcile_race(index: int):
            return recovery.reconcile_wait(
                db_path=race_db,
                wait_id=race_wait["wait_id"],
                now_ts=2020.0,
                actions_available=True,
                occurred_at=f"2026-10-27T14:52:0{index}Z",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            raced = list(executor.map(reconcile_race, [1, 2]))
        assert sum(1 for row in raced if row["poll"]) == 1
        assert {row["action"] for row in raced} == {
            "POLL_PENDING_GATES",
            "WAIT_EVENT",
        }

        # Explicit supersession never mutates the old target identity.
        sup_db = root / "supersede.sqlite3"
        sup_work, _ = prepare_fixture(sup_db, sha, "v61b-sup")
        sup_wait = recovery.begin_wait(
            db_path=sup_db,
            work_item_id=sup_work,
            target_sha=sha,
            required_gates=gates,
            now_ts=2000.0,
            occurred_at="2026-10-27T15:00:00Z",
            contract=contract,
        )
        superseded = recovery.supersede_wait(
            db_path=sup_db,
            wait_id=sup_wait["wait_id"],
            new_target_sha="b" * 40,
            ancestry_proven=True,
            occurred_at="2026-10-27T15:01:00Z",
        )
        assert superseded["state"] == "SUPERSEDED"
        assert superseded["work_item_terminal_state"] == "STOPPED"
        assert superseded["operation_terminal_state"] == "CANCELED"
        assert superseded["silent_retarget"] is False
        assert superseded["new_operation_required"] is True

        superseded_replay = recovery.supersede_wait(
            db_path=sup_db,
            wait_id=sup_wait["wait_id"],
            new_target_sha="b" * 40,
            ancestry_proven=True,
            occurred_at="2026-10-27T15:01:01Z",
        )
        assert superseded_replay["action"] == "REPLAY_COMPLETED"

        # Fallback observation is bounded; exhaustion holds for watchdog recovery.
        budget_db = root / "budget.sqlite3"
        budget_work, _ = prepare_fixture(budget_db, sha, "v61b-budget")
        budget_wait = recovery.begin_wait(
            db_path=budget_db,
            work_item_id=budget_work,
            target_sha=sha,
            required_gates=["AppLab CI"],
            now_ts=3000.0,
            occurred_at="2026-10-27T16:00:00Z",
            contract=contract,
        )
        current = 3000.0 + int(contract["fallback_polling"]["interval_seconds"])
        for index in range(int(contract["fallback_polling"]["max_polls"])):
            row = recovery.reconcile_wait(
                db_path=budget_db,
                wait_id=budget_wait["wait_id"],
                now_ts=current,
                actions_available=True,
                occurred_at=f"2026-10-27T16:0{index}:00Z",
            )
            assert row["poll"] is True
            current = float(row["next_fallback_at"])
        exhausted = recovery.reconcile_wait(
            db_path=budget_db,
            wait_id=budget_wait["wait_id"],
            now_ts=current,
            actions_available=True,
            occurred_at="2026-10-27T16:10:00Z",
        )
        assert exhausted["action"] == "FALLBACK_EXHAUSTED_HOLD"
        assert exhausted["poll"] is False

    print("AppLab v6.1B event-driven durable recovery contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
