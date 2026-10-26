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

    repeated_history = [
        {
            "repository": "owner/replay",
            "result": "FAIL",
            "recorded_at": f"2026-10-26T05:{index:02d}:00+00:00",
            "watcher_run_url": f"https://example.invalid/replay/{index}",
            "failure_intelligence": {
                "kind": "INFRA_ERROR",
                "reason": "same recurring emulator timeout",
                "failed_labs": [],
            },
        }
        for index in range(21)
    ]
    first = mod.build_queue(
        policy=policy,
        history=repeated_history,
        explicit_findings=[],
        generated_at="2026-10-26T06:00:00+00:00",
    )
    first_item = next(item for item in first["items"] if item["repository"] == "owner/replay")
    assert first_item["occurrences"] == 21
    replayed = mod.build_queue(
        policy=policy,
        history=repeated_history,
        explicit_findings=[],
        previous={item["id"]: dict(item) for item in first["items"]},
        generated_at="2026-10-26T07:00:00+00:00",
    )
    replayed_item = next(item for item in replayed["items"] if item["repository"] == "owner/replay")
    assert replayed_item["occurrences"] == 21

    overflow_findings = [
        {
            "repository": f"owner/app-{index:03d}",
            "severity": "P3",
            "category": "INFRASTRUCTURE",
            "code": f"FINDING_{index:03d}",
            "message": f"maintenance finding {index}",
            "evidence_ref": f"evidence://{index}",
        }
        for index in range(501)
    ]
    overflow = mod.build_queue(
        policy=policy,
        history=[],
        explicit_findings=overflow_findings,
        generated_at="2026-10-26T08:00:00+00:00",
    )
    assert len(overflow["items"]) == 501
    rendered = mod.render_markdown(overflow)
    assert "bounded to 500 of 501 open findings" in rendered

    print(json.dumps(proof, sort_keys=True))
    print("v5.6 continuous maintenance contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
