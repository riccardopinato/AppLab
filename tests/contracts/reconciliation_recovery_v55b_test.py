#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import reconciliation_recovery_v55b as mod


def main() -> int:
    proof = mod.self_test()
    assert proof["status"] == "PASS"
    assert proof["proof_count"] == 24
    assert proof["durable_proof_count"] == len(mod.PILOT_REPOSITORIES)
    assert proof["scenario_count"] == 8
    assert proof["repositories"] == list(mod.PILOT_REPOSITORIES)
    assert set(proof["terminal_states"]) == {
        "SUCCEEDED",
        "FAILED",
        "BLOCKED",
        "CANCELED",
        "SUPERSEDED",
    }

    for durable in proof["durable_proofs"]:
        assert durable["duplicate_deduped"] is True
        assert durable["brain_restart_persisted"] is True
        assert durable["expired_lease_requeued"] is True
        assert durable["interrupted_operation_resumed"] is True
        assert durable["watcher_covered"] is True
        assert durable["terminal_state"] == "SUCCEEDED"

    for repo in mod.PILOT_REPOSITORIES:
        duplicate = mod.reconcile(
            repo,
            "DUPLICATE_DELIVERY",
            {
                "operation_state": "QUEUED",
                "duplicate_delivery": True,
                "durable_operation": True,
            },
        )
        assert duplicate.action == "DEDUPE_EXISTING_OPERATION"
        assert duplicate.dispatch is False

        outage = mod.reconcile(
            repo,
            "ACTIONS_OUTAGE",
            {
                "operation_state": "QUEUED",
                "actions_available": False,
                "durable_operation": True,
            },
        )
        assert outage.action == "HOLD_DURABLE_PENDING"
        assert outage.dispatch is False

        for scenario, state in (
            (
                "EVENT_LOSS",
                {
                    "operation_state": "MISSING",
                    "watcher_observed_sha": True,
                    "actions_available": False,
                },
            ),
            (
                "INTERRUPTED_OPERATION",
                {
                    "operation_state": "RUNNING",
                    "durable_operation": True,
                    "actions_available": False,
                },
            ),
            (
                "WATCHER_RECOVERY",
                {
                    "operation_state": "MISSING",
                    "watcher_observed_sha": True,
                    "actions_available": False,
                },
            ),
        ):
            held = mod.reconcile(repo, scenario, state)
            assert held.action == "HOLD_DURABLE_PENDING"
            assert held.dispatch is False
            assert held.executor == ""

        recovered = mod.reconcile(
            repo,
            "WATCHER_RECOVERY",
            {
                "operation_state": "MISSING",
                "watcher_observed_sha": True,
            },
        )
        assert recovered.action == "WATCHER_RECOVER"
        assert recovered.dispatch is True
        assert recovered.executor == "GITHUB_ACTIONS"

        for terminal_state in mod.TERMINAL:
            terminal = mod.reconcile(
                repo,
                "INTERRUPTED_OPERATION",
                {
                    "operation_state": terminal_state,
                    "durable_operation": True,
                },
            )
            assert terminal.action == "PRESERVE_TERMINAL"
            assert terminal.dispatch is False

    try:
        mod.reconcile("other/repo", "EVENT_LOSS", {})
    except mod.ReconciliationError:
        pass
    else:
        raise AssertionError("outside-pilot repository was accepted")

    print("v5.5B reconciliation/recovery contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
