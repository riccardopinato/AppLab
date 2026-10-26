#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import continuous_maintenance_v56 as mod


def main() -> int:
    proof = mod.self_test()
    assert proof["status"] == "PASS"
    assert proof["mode"] == "ROADMAP_FAST_PLUS_CONTINUOUS_MAINTENANCE"
    assert proof["blocking_rules_proven"] is True
    assert proof["current_step_isolation_proven"] is True
    assert proof["background_non_blocking_proven"] is True
    assert proof["dedupe_recurrence_proven"] is True
    assert proof["authority_preserved"] is True

    policy = mod.load_policy()
    queue = mod.build_queue(
        policy=policy,
        history=[],
        explicit_findings=[
            {
                "repository": "owner/app",
                "severity": "P3",
                "category": "INFRASTRUCTURE",
                "code": "WEBRTC_FLAKE",
                "message": "intermittent no-frame infrastructure signature",
            }
        ],
        generated_at="2026-10-26T04:00:00+00:00",
    )
    assert queue["roadmap_gate"] == "CONTINUE"
    assert queue["summary"]["counts"]["BACKGROUND_MAINTENANCE"] == 1
    assert queue["authority"]["can_reduce_test_coverage"] is False
    assert queue["authority"]["can_treat_emulator_as_physical"] is False

    print(json.dumps(proof, sort_keys=True))
    print("v5.6 continuous maintenance contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
