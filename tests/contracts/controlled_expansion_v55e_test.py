#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import controlled_expansion_v55e as mod


def main() -> int:
    proof = mod.self_test()
    assert proof["status"] == "PASS"
    assert proof["stage_sizes"]["PILOT_3"] == 3
    assert proof["stage_sizes"]["EXPANDED_5"] == 5
    assert proof["stage_sizes"]["ALL_COMPATIBLE"] >= 5
    assert proof["all_compatible_matches_enabled_watchlist"] is True
    assert proof["promotion_is_evidence_gated"] is True
    assert proof["global_kill_switch_proven"] is True
    assert proof["per_repository_kill_switch_proven"] is True
    assert proof["watcher_mode"] == "PRIMARY_SCHEDULER_PLUS_RECONCILIATION"
    assert proof["watcher_demotion_allowed"] is False
    assert proof["authority"] == "ORCHESTRATION_ONLY"
    assert proof["coverage_reduction_enabled"] is False
    assert proof["github_actions_fallback"] is True

    policy = mod.load_policy()
    outside = "owner/not-compatible"
    assert mod.dispatch_allowed(policy, "ALL_COMPATIBLE", outside) is False

    # Promotion evidence is repository-complete and fail-closed.
    evidence = {
        repo: {"success": 3, "failure": 0}
        for repo in policy["stages"]["ALL_COMPATIBLE"]
    }
    missing = dict(evidence)
    missing.pop(policy["stages"]["ALL_COMPATIBLE"][-1])
    assert mod.evaluate_promotion(policy, "EXPANDED_5", missing)["decision"] == "HOLD"

    print(json.dumps(proof, sort_keys=True))
    print("v5.5E controlled expansion contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
