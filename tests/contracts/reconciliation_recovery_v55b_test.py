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
    assert proof["scenario_count"] == 8
    assert proof["repositories"] == list(mod.PILOT_REPOSITORIES)

    for repo in mod.PILOT_REPOSITORIES:
        duplicate = mod.reconcile(repo, "DUPLICATE_DELIVERY", {
            "operation_state": "QUEUED",
            "duplicate_delivery": True,
            "durable_operation": True,
        })
        assert duplicate.action == "DEDUPE_EXISTING_OPERATION"
        assert duplicate.dispatch is False

        outage = mod.reconcile(repo, "ACTIONS_OUTAGE", {
            "operation_state": "QUEUED",
            "actions_available": False,
            "durable_operation": True,
        })
        assert outage.action == "HOLD_DURABLE_PENDING"
        assert outage.dispatch is False

        recovered = mod.reconcile(repo, "WATCHER_RECOVERY", {
            "operation_state": "MISSING",
            "watcher_observed_sha": True,
        })
        assert recovered.action == "WATCHER_RECOVER"
        assert recovered.dispatch is True
        assert recovered.executor == "GITHUB_ACTIONS"

        terminal = mod.reconcile(repo, "INTERRUPTED_OPERATION", {
            "operation_state": "SUCCEEDED",
            "durable_operation": True,
        })
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
