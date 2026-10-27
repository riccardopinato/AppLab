#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_work_graph_v60a as graphmod  # noqa: E402
import durable_brain_v54a as brain  # noqa: E402
import durable_store_v54b as storemod  # noqa: E402


def expect_error(callback, contains: str) -> None:
    try:
        callback()
    except graphmod.WorkGraphError as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected WorkGraphError containing {contains!r}")


def main() -> int:
    contract = graphmod.load_contract()
    target_sha = "b" * 40
    applab_sha = "c" * 40
    operation = brain._operation_fixture(
        "op_graph_contract",
        "owner/app",
        "main",
        target_sha,
        applab_sha,
    )
    item = graphmod.adapt_operation_to_work_item(
        operation,
        work_item_id="wrk_graph_contract",
        allow_code_edit=True,
    )
    assert item["budgets"]["max_files"] == 5
    assert item["budgets"]["max_changed_lines"] == 250
    assert item["budgets"]["max_repair_attempts"] == 2
    assert "SELF_MERGE" in item["authority_envelope"]["denied_capabilities"]

    over_budget = copy.deepcopy(item)
    over_budget["budgets"]["max_files"] = 6
    expect_error(
        lambda: graphmod.validate_work_item(over_budget, contract, operation),
        "exceeds contract ceiling",
    )

    missing_denial = copy.deepcopy(item)
    missing_denial["authority_envelope"]["denied_capabilities"].remove("RELEASE")
    expect_error(
        lambda: graphmod.validate_work_item(missing_denial, contract, operation),
        "missing mandatory denials",
    )

    wrong_sha = copy.deepcopy(item)
    wrong_sha["resolved_sha"] = "d" * 40
    expect_error(
        lambda: graphmod.validate_work_item(wrong_sha, contract, operation),
        "must match durable operation",
    )

    assert graphmod.validate_transition("CREATED", "INVESTIGATING", contract)
    expect_error(
        lambda: graphmod.validate_transition("COMPLETE", "EXECUTING", contract),
        "illegal work item transition",
    )

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "shared-control-plane.sqlite3"

        with storemod.SQLiteShadowStore(db_path) as durable:
            durable.put_operation(operation)
            graph = graphmod.AgentWorkGraphStore(durable, contract)
            assert graph.put_work_item(item)["status"] == "INSERTED"
            assert graph.put_work_item(item)["status"] == "REPLAY"
            graph.transition(
                transition_id="trn_graph_1",
                work_item_id=item["work_item_id"],
                from_state="CREATED",
                to_state="INVESTIGATING",
                reason_code="FAILURE_EVIDENCE_RECEIVED",
                created_at="2026-10-27T00:00:00Z",
            )
            graph.transition(
                transition_id="trn_graph_2",
                work_item_id=item["work_item_id"],
                from_state="INVESTIGATING",
                to_state="PLANNED",
                reason_code="CAUSE_LOCALIZED",
                created_at="2026-10-27T00:01:00Z",
            )
            assert graph.rebuild_state(item["work_item_id"]) == "PLANNED"
            report = graph.integrity_report()
            assert report["ok"] is True
            assert report["counts"]["agent_work_items"] == 1
            assert report["counts"]["agent_work_transitions"] == 2

        # Re-open the exact same v5.4 durable database. v6.0A must recover its
        # projection without a second persistence substrate.
        with storemod.SQLiteShadowStore(db_path) as durable:
            graph = graphmod.AgentWorkGraphStore(durable, contract)
            recovered = graph.get_work_item(item["work_item_id"])
            assert recovered["current_state"] == "PLANNED"
            assert graph.rebuild_state(item["work_item_id"]) == "PLANNED"
            assert graph.integrity_report()["ok"] is True

            decision = {
                "schema_version": 1,
                "record_type": "APPLAB_WORK_DECISION",
                "decision_id": "dec_graph_1",
                "work_item_id": item["work_item_id"],
                "kind": "APPLY_PATCH",
                "reason_code": "BOUNDED_FIX_READY",
                "evidence_ref_ids": [],
                "created_at": "2026-10-27T00:02:00Z",
            }
            assert graph.put_decision(decision)["status"] == "INSERTED"
            assert graph.put_decision(decision)["status"] == "REPLAY"

            action = {
                "schema_version": 1,
                "record_type": "APPLAB_WORK_ACTION",
                "action_id": "act_graph_1",
                "work_item_id": item["work_item_id"],
                "decision_id": decision["decision_id"],
                "capability": "ALLOW_CODE_EDIT",
                "state": "PLANNED",
                "created_at": "2026-10-27T00:03:00Z",
            }
            assert graph.put_action(action)["status"] == "INSERTED"

            bad_action = dict(action, action_id="act_graph_bad", capability="CREATE_DRAFT_PR")
            expect_error(
                lambda: graph.put_action(bad_action),
                "outside WorkItem authority envelope",
            )

            verdict = {
                "schema_version": 1,
                "record_type": "APPLAB_WORK_VERDICT",
                "verdict_id": "vrd_graph_1",
                "work_item_id": item["work_item_id"],
                "decision_id": decision["decision_id"],
                "state": "CONTINUE",
                "reason_code": "VERIFY_REQUIRED",
                "evidence_ref_ids": [],
                "authority": "ORCHESTRATION_ONLY",
                "created_at": "2026-10-27T00:04:00Z",
            }
            assert graph.put_verdict(verdict)["status"] == "INSERTED"

            forged = copy.deepcopy(verdict)
            forged["verdict_id"] = "vrd_graph_forged"
            forged["authority"] = "CERTIFICATION"
            expect_error(
                lambda: graph.put_verdict(forged),
                "cannot mint verification authority",
            )

            replay = graph.integrity_report()
            assert replay["ok"] is True
            assert replay["counts"]["agent_work_decisions"] == 1
            assert replay["counts"]["agent_work_actions"] == 1
            assert replay["counts"]["agent_work_verdicts"] == 1

    graphmod.self_test()
    print("AppLab v6.0A unified work graph contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
