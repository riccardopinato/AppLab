#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from typing import Any

PILOT_REPOSITORIES = (
    "riccardopinato/AppLab",
    "riccardopinato/CamperBoss",
    "riccardopinato/TrailPath",
)
SCENARIOS = (
    "EVENT_LOSS",
    "DUPLICATE_DELIVERY",
    "ACTIONS_OUTAGE",
    "INTERRUPTED_OPERATION",
    "BRAIN_RESTART",
    "EXPIRED_LEASE",
    "SUPERSEDING_SHA",
    "WATCHER_RECOVERY",
)
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "SUPERSEDED"}


class ReconciliationError(ValueError):
    pass


@dataclass(frozen=True)
class RecoveryDecision:
    repository: str
    scenario: str
    action: str
    dispatch: bool
    executor: str
    authority: str = "ORCHESTRATION_ONLY"
    certification_authority_changed: bool = False
    coverage_reduction_enabled: bool = False
    github_actions_fallback: bool = True
    smart_test_plan_authority: str = "UNCHANGED"
    trusted_verifier_authority: str = "UNCHANGED"
    release_assurance_authority: str = "UNCHANGED"
    production_certification_authority: str = "UNCHANGED"


def reconcile(repository: str, scenario: str, state: dict[str, Any]) -> RecoveryDecision:
    if repository not in PILOT_REPOSITORIES:
        raise ReconciliationError("repository is outside the v5.5 pilot set")
    if scenario not in SCENARIOS:
        raise ReconciliationError("unknown reconciliation scenario")

    operation_state = str(state.get("operation_state", "MISSING")).upper()
    watcher_observed_sha = bool(state.get("watcher_observed_sha", False))
    duplicate_delivery = bool(state.get("duplicate_delivery", False))
    actions_available = bool(state.get("actions_available", True))
    durable_operation = bool(state.get("durable_operation", False))
    lease_expired = bool(state.get("lease_expired", False))
    superseded = bool(state.get("superseded", False))

    action = "NOOP"
    dispatch = False
    executor = ""

    if operation_state in TERMINAL:
        action = "PRESERVE_TERMINAL"
    elif scenario == "EVENT_LOSS":
        if watcher_observed_sha and operation_state == "MISSING":
            action, dispatch, executor = "WATCHER_RECOVER", True, "GITHUB_ACTIONS"
        else:
            action = "WAIT_FOR_WATCHER"
    elif scenario == "DUPLICATE_DELIVERY":
        action = "DEDUPE_EXISTING_OPERATION" if duplicate_delivery or durable_operation else "ADMIT_ONCE"
        dispatch = action == "ADMIT_ONCE"
        executor = "GITHUB_ACTIONS" if dispatch else ""
    elif scenario == "ACTIONS_OUTAGE":
        action = "HOLD_DURABLE_PENDING" if not actions_available else "DISPATCH_ACTIONS"
        dispatch = actions_available
        executor = "GITHUB_ACTIONS" if dispatch else ""
    elif scenario == "INTERRUPTED_OPERATION":
        action = "RESUME_DURABLE_OPERATION" if durable_operation else "WATCHER_RECOVER"
        dispatch = True
        executor = "GITHUB_ACTIONS"
    elif scenario == "BRAIN_RESTART":
        action = "RESTORE_DURABLE_OPERATION" if durable_operation else "WATCHER_RECONCILE"
        dispatch = False
    elif scenario == "EXPIRED_LEASE":
        action = "REQUEUE_EXPIRED_LEASE" if lease_expired else "KEEP_LEASE"
        dispatch = False
    elif scenario == "SUPERSEDING_SHA":
        action = "MARK_SUPERSEDED" if superseded else "KEEP_CURRENT"
        dispatch = False
    elif scenario == "WATCHER_RECOVERY":
        if watcher_observed_sha and operation_state == "MISSING":
            action, dispatch, executor = "WATCHER_RECOVER", True, "GITHUB_ACTIONS"
        else:
            action = "WATCHER_RECONCILED"

    return RecoveryDecision(repository, scenario, action, dispatch, executor)


def scenario_corpus() -> list[dict[str, Any]]:
    templates = {
        "EVENT_LOSS": {"operation_state": "MISSING", "watcher_observed_sha": True},
        "DUPLICATE_DELIVERY": {"operation_state": "QUEUED", "duplicate_delivery": True, "durable_operation": True},
        "ACTIONS_OUTAGE": {"operation_state": "QUEUED", "actions_available": False, "durable_operation": True},
        "INTERRUPTED_OPERATION": {"operation_state": "RUNNING", "durable_operation": True},
        "BRAIN_RESTART": {"operation_state": "QUEUED", "durable_operation": True},
        "EXPIRED_LEASE": {"operation_state": "READY", "lease_expired": True, "durable_operation": True},
        "SUPERSEDING_SHA": {"operation_state": "QUEUED", "superseded": True, "durable_operation": True},
        "WATCHER_RECOVERY": {"operation_state": "MISSING", "watcher_observed_sha": True},
    }
    return [
        {"repository": repo, "scenario": scenario, "state": dict(templates[scenario])}
        for repo in PILOT_REPOSITORIES
        for scenario in SCENARIOS
    ]


def self_test() -> dict[str, Any]:
    rows = []
    for item in scenario_corpus():
        decision = reconcile(item["repository"], item["scenario"], item["state"])
        payload = asdict(decision)
        assert payload["authority"] == "ORCHESTRATION_ONLY"
        assert payload["certification_authority_changed"] is False
        assert payload["coverage_reduction_enabled"] is False
        assert payload["github_actions_fallback"] is True
        if payload["dispatch"]:
            assert payload["executor"] == "GITHUB_ACTIONS"
        rows.append(payload)

    by_scenario = {row["scenario"]: row["action"] for row in rows if row["repository"] == PILOT_REPOSITORIES[0]}
    assert by_scenario == {
        "EVENT_LOSS": "WATCHER_RECOVER",
        "DUPLICATE_DELIVERY": "DEDUPE_EXISTING_OPERATION",
        "ACTIONS_OUTAGE": "HOLD_DURABLE_PENDING",
        "INTERRUPTED_OPERATION": "RESUME_DURABLE_OPERATION",
        "BRAIN_RESTART": "RESTORE_DURABLE_OPERATION",
        "EXPIRED_LEASE": "REQUEUE_EXPIRED_LEASE",
        "SUPERSEDING_SHA": "MARK_SUPERSEDED",
        "WATCHER_RECOVERY": "WATCHER_RECOVER",
    }
    return {
        "schema_version": 1,
        "record_type": "APPLAB_V55B_RECONCILIATION_PROOF",
        "status": "PASS",
        "repositories": list(PILOT_REPOSITORIES),
        "scenario_count": len(SCENARIOS),
        "proof_count": len(rows),
        "authority": "ORCHESTRATION_ONLY",
        "github_actions_fallback": True,
        "coverage_reduction_enabled": False,
        "certification_authority_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v5.5B reconciliation/recovery proof harness")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test:
        parser.error("--self-test is required")
    print(json.dumps(self_test(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
