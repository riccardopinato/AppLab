#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import event_driven_recovery_v61b as recovery  # noqa: E402


def main() -> int:
    contract = recovery.load_contract()
    proof = recovery.self_test()

    assert proof["status"] == "PASS"
    assert proof["primary_progression"] == "EVENT_DRIVEN"
    assert proof["durable_wait_recovery"] is True
    assert proof["duplicate_event_idempotence"] is True
    assert proof["actions_outage_holds_pending"] is True
    assert proof["coordinator_restart_recovers_wait"] is True
    assert proof["fallback_polling_primary"] is False
    assert proof["fallback_polling_bounded"] is True
    assert proof["fallback_scope"] == "PENDING_GATES_ONLY"
    assert proof["superseding_sha_explicit"] is True
    assert proof["silent_retarget"] is False
    assert proof["terminal_redispatch"] is False
    assert proof["github_actions_fallback"] is True
    assert proof["certification_authority"] == "UNCHANGED"

    fallback = contract["fallback_polling"]
    assert fallback["primary"] is False
    assert fallback["max_polls"] == 3
    assert fallback["scope"] == "PENDING_GATES_ONLY"

    source = (ROOT / "scripts" / "event_driven_recovery_v61b.py").read_text(
        encoding="utf-8"
    )
    assert "time.sleep(" not in source
    assert "requests." not in source
    assert "POLL_PENDING_GATES" in source
    assert "V61B_SUPERSEDED_TARGET_SHA" in source

    print("AppLab v6.1B event-driven durable recovery contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
