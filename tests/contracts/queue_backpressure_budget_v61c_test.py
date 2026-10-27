#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import queue_backpressure_budget_v61c as control  # noqa: E402


def main() -> int:
    contract = control.load_contract()
    proof = control.self_test()

    assert contract["authority"] == "ORCHESTRATION_ONLY"
    assert contract["queue_authority"] == "EXISTING_DURABLE_PER_REPO_QUEUE"
    assert contract["observation_source"] == "V61B_RECONCILIATION_DIRECTIVES"

    assert proof["status"] == "PASS"
    assert proof["existing_queue_reused"] is True
    assert proof["per_repository_backpressure_observed"] is True
    assert proof["work_item_file_line_attempt_budgets_preserved"] is True
    assert proof["runtime_cost_budgets_cumulative"] is True
    assert proof["attempt_reservation_idempotent"] is True
    assert proof["repeated_failure_signature_stops"] is True
    assert proof["event_driven_primary"] is True
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
    assert "target_sha_mutation_performed" in source

    print("AppLab v6.1C queue/backpressure/budget contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
