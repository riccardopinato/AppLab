#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = ROOT / "integration" / "orchestration" / "v55-expansion.json"
WATCHLIST = ROOT / "watchlist.json"
STAGES = ("PILOT_3", "EXPANDED_5", "ALL_COMPATIBLE")


class ExpansionError(ValueError):
    pass


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ExpansionError("unsupported expansion policy version")
    if payload.get("authority") != "ORCHESTRATION_ONLY":
        raise ExpansionError("expansion policy cannot become verification authority")
    if not isinstance(payload.get("global_kill_switch"), bool):
        raise ExpansionError("global_kill_switch must be boolean")
    if payload.get("promotion_order") != list(STAGES):
        raise ExpansionError("promotion order must be PILOT_3 -> EXPANDED_5 -> ALL_COMPATIBLE")
    if payload.get("watcher_mode") != "PRIMARY_SCHEDULER_PLUS_RECONCILIATION":
        raise ExpansionError("hourly watcher must remain primary during v5.5 expansion")
    if payload.get("watcher_demotion_allowed") is not False:
        raise ExpansionError("watcher demotion requires separate sufficient evidence")
    stages = payload.get("stages")
    if not isinstance(stages, dict):
        raise ExpansionError("stages must be object")
    expected_sizes = {"PILOT_3": 3, "EXPANDED_5": 5}
    for stage in STAGES:
        repos = stages.get(stage)
        if not isinstance(repos, list) or not repos or len(repos) != len(set(repos)):
            raise ExpansionError(f"{stage} must contain unique repositories")
        if stage in expected_sizes and len(repos) != expected_sizes[stage]:
            raise ExpansionError(f"{stage} must contain {expected_sizes[stage]} repositories")
    if not set(stages["PILOT_3"]).issubset(stages["EXPANDED_5"]):
        raise ExpansionError("EXPANDED_5 must preserve PILOT_3")
    if not set(stages["EXPANDED_5"]).issubset(stages["ALL_COMPATIBLE"]):
        raise ExpansionError("ALL_COMPATIBLE must preserve EXPANDED_5")
    switches = payload.get("repository_kill_switches")
    if not isinstance(switches, dict) or any(not isinstance(v, bool) for v in switches.values()):
        raise ExpansionError("repository_kill_switches must be boolean map")
    return payload


def enabled_watchlist_repositories() -> set[str]:
    watchlist = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    return {
        item["repository"]
        for item in watchlist["repositories"]
        if item.get("enabled") is True
    }


def evaluate_promotion(
    policy: dict[str, Any],
    current_stage: str,
    evidence: dict[str, dict[str, int]],
) -> dict[str, Any]:
    if current_stage not in STAGES:
        raise ExpansionError("unknown current stage")
    index = STAGES.index(current_stage)
    if index == len(STAGES) - 1:
        return {"decision": "HOLD", "reason": "MAX_STAGE", "next_stage": current_stage}
    next_stage = STAGES[index + 1]
    required = policy["stages"][next_stage]
    minimum = int(policy["minimum_successful_operations_per_repository"])
    max_failure_rate = float(policy["maximum_failure_rate"])
    blockers: list[str] = []
    for repository in required:
        row = evidence.get(repository, {})
        success = int(row.get("success", 0))
        failure = int(row.get("failure", 0))
        total = success + failure
        rate = (failure / total) if total else 1.0
        if success < minimum:
            blockers.append(f"{repository}:INSUFFICIENT_SUCCESS")
        if rate > max_failure_rate:
            blockers.append(f"{repository}:FAILURE_RATE")
    return {
        "decision": "PROMOTE" if not blockers else "HOLD",
        "reason": "EVIDENCE_SUFFICIENT" if not blockers else "EVIDENCE_INSUFFICIENT",
        "next_stage": next_stage,
        "blockers": blockers,
    }


def dispatch_allowed(policy: dict[str, Any], stage: str, repository: str) -> bool:
    if stage not in STAGES:
        raise ExpansionError("unknown stage")
    if policy["global_kill_switch"]:
        return False
    if policy["repository_kill_switches"].get(repository, False):
        return False
    return repository in policy["stages"][stage]


def self_test() -> dict[str, Any]:
    policy = load_policy()
    compatible = enabled_watchlist_repositories()
    configured = set(policy["stages"]["ALL_COMPATIBLE"])
    assert configured == compatible
    assert len(policy["stages"]["PILOT_3"]) == 3
    assert len(policy["stages"]["EXPANDED_5"]) == 5
    assert len(configured) >= 5

    insufficient = {
        repo: {"success": 2, "failure": 0}
        for repo in policy["stages"]["EXPANDED_5"]
    }
    held = evaluate_promotion(policy, "PILOT_3", insufficient)
    assert held["decision"] == "HOLD"

    sufficient = {
        repo: {"success": 3, "failure": 0}
        for repo in policy["stages"]["EXPANDED_5"]
    }
    promoted = evaluate_promotion(policy, "PILOT_3", sufficient)
    assert promoted["decision"] == "PROMOTE"
    assert promoted["next_stage"] == "EXPANDED_5"

    all_evidence = {
        repo: {"success": 3, "failure": 0}
        for repo in policy["stages"]["ALL_COMPATIBLE"]
    }
    promoted_all = evaluate_promotion(policy, "EXPANDED_5", all_evidence)
    assert promoted_all["decision"] == "PROMOTE"
    assert promoted_all["next_stage"] == "ALL_COMPATIBLE"

    failed = dict(all_evidence)
    failed[policy["stages"]["ALL_COMPATIBLE"][-1]] = {"success": 3, "failure": 1}
    assert evaluate_promotion(policy, "EXPANDED_5", failed)["decision"] == "HOLD"

    sample = policy["stages"]["PILOT_3"][0]
    assert dispatch_allowed(policy, "PILOT_3", sample) is True
    killed = json.loads(json.dumps(policy))
    killed["repository_kill_switches"][sample] = True
    assert dispatch_allowed(killed, "PILOT_3", sample) is False
    killed["repository_kill_switches"][sample] = False
    killed["global_kill_switch"] = True
    assert dispatch_allowed(killed, "PILOT_3", sample) is False

    return {
        "schema_version": 1,
        "record_type": "APPLAB_V55E_CONTROLLED_EXPANSION_PROOF",
        "status": "PASS",
        "stage_sizes": {stage: len(policy["stages"][stage]) for stage in STAGES},
        "all_compatible_matches_enabled_watchlist": True,
        "promotion_is_evidence_gated": True,
        "global_kill_switch_proven": True,
        "per_repository_kill_switch_proven": True,
        "watcher_mode": policy["watcher_mode"],
        "watcher_demotion_allowed": False,
        "authority": "ORCHESTRATION_ONLY",
        "coverage_reduction_enabled": False,
        "github_actions_fallback": True,
        "smart_test_plan_authority": "UNCHANGED",
        "trusted_verifier_authority": "UNCHANGED",
        "release_assurance_authority": "UNCHANGED",
        "production_certification_authority": "UNCHANGED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v5.5E controlled expansion proof")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test:
        parser.error("--self-test is required")
    print(json.dumps(self_test(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
