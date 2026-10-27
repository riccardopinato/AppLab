#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import agent_work_graph_v60a as workgraph
import closed_loop_pilot_v61a as self_pilot
import controlled_event_v54g as event_pilot
import controlled_expansion_v55e as legacy_expansion
import durable_brain_v54a as brain
import queue_backpressure_budget_v61c as budgets

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = (
    ROOT
    / "integration"
    / "orchestration"
    / "contracts"
    / "controlled-closed-loop-expansion-v1.json"
)
DEFAULT_POLICY = ROOT / "integration" / "orchestration" / "v61d-expansion.json"
STAGES = ("SELF_CANARY", "PILOT_3", "PILOT_5")


class ExpansionError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ExpansionError("unsupported v6.1D contract version")
    if payload.get("contract_name") != "APPLAB_CONTROLLED_CLOSED_LOOP_EXPANSION":
        raise ExpansionError("unexpected v6.1D contract")
    if payload.get("authority") != "ORCHESTRATION_ONLY":
        raise ExpansionError("v6.1D authority drift")
    if payload.get("promotion_order") != list(STAGES):
        raise ExpansionError("v6.1D promotion order drift")
    if "ALL_COMPATIBLE" in payload.get("promotion_order", []):
        raise ExpansionError("ALL_COMPATIBLE is not authorized by v6.1D")
    return payload


def load_policy(
    path: Path = DEFAULT_POLICY,
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ExpansionError("unsupported v6.1D policy version")
    for field in ("enabled", "global_kill_switch"):
        if not isinstance(payload.get(field), bool):
            raise ExpansionError(f"{field} must be boolean")
    if payload.get("promotion_order") != list(STAGES):
        raise ExpansionError("policy promotion order drift")
    if payload.get("active_stage") not in STAGES:
        raise ExpansionError("unknown active v6.1D stage")
    if payload.get("active_stage") == "PILOT_5" and "ALL_COMPATIBLE" in payload.get(
        "stages", {}
    ):
        raise ExpansionError("v6.1D cannot pre-authorize ALL_COMPATIBLE")

    stages = payload.get("stages")
    if not isinstance(stages, dict) or set(stages) != set(STAGES):
        raise ExpansionError("v6.1D policy must define exactly SELF_CANARY/PILOT_3/PILOT_5")
    expected_sizes = contract["stage_sizes"]
    for stage in STAGES:
        repos = stages.get(stage)
        if not isinstance(repos, list) or len(repos) != len(set(repos)):
            raise ExpansionError(f"{stage} must contain unique repositories")
        if len(repos) != int(expected_sizes[stage]):
            raise ExpansionError(f"{stage} size does not match contract")
    if stages["SELF_CANARY"] != [contract["self_repository"]]:
        raise ExpansionError("SELF_CANARY must contain AppLab only")
    if not set(stages["SELF_CANARY"]).issubset(stages["PILOT_3"]):
        raise ExpansionError("PILOT_3 must preserve SELF_CANARY")
    if not set(stages["PILOT_3"]).issubset(stages["PILOT_5"]):
        raise ExpansionError("PILOT_5 must preserve PILOT_3")

    # Reuse the already-proven v5.5 cohort topology without inheriting its
    # mutation authority. v6.1 promotion remains separately evidence-gated.
    legacy = legacy_expansion.load_policy()
    if stages["PILOT_3"] != legacy["stages"]["PILOT_3"]:
        raise ExpansionError("PILOT_3 must reuse the validated v5.5 cohort topology")
    if stages["PILOT_5"] != legacy["stages"]["EXPANDED_5"]:
        raise ExpansionError("PILOT_5 must reuse the validated v5.5 cohort topology")

    switches = payload.get("repository_kill_switches")
    if not isinstance(switches, dict):
        raise ExpansionError("repository_kill_switches must be an object")
    if set(switches) != set(stages["PILOT_5"]):
        raise ExpansionError("repository kill switches must cover the full PILOT_5 cohort")
    if any(not isinstance(value, bool) for value in switches.values()):
        raise ExpansionError("repository kill switches must be boolean")

    closed = payload.get("closed_loop")
    if not isinstance(closed, dict):
        raise ExpansionError("closed_loop policy must be an object")
    for field in (
        "mutation_enabled",
        "draft_pr_enabled",
        "github_actions_fallback",
        "event_driven_waiting_primary",
    ):
        if not isinstance(closed.get(field), bool):
            raise ExpansionError(f"closed_loop.{field} must be boolean")
    if closed.get("github_actions_fallback") is not True:
        raise ExpansionError("GitHub Actions fallback must remain enabled")
    if closed.get("event_driven_waiting_primary") is not True:
        raise ExpansionError("event-driven waiting must remain primary")
    if closed.get("release_authority") != "DENIED":
        raise ExpansionError("v6.1D cannot grant release authority")
    if closed.get("post_gate_merge_authority") != "EXTERNAL_REPOSITORY_AUTOMATION":
        raise ExpansionError("merge authority must remain external")

    promotion = payload.get("promotion")
    if not isinstance(promotion, dict):
        raise ExpansionError("promotion policy must be an object")
    if promotion.get("automatic") is not False:
        raise ExpansionError("v6.1D stage promotion cannot be automatic")
    if promotion.get("requires_explicit_policy_change") is not True:
        raise ExpansionError("stage promotion requires explicit policy change")
    if promotion.get("v55_evidence_can_grant_mutation_authority") is not False:
        raise ExpansionError("v5.5 evidence cannot grant v6.1 mutation authority")
    return payload


def _target_catalog(
    repositories: list[str],
) -> dict[str, dict[str, Any]]:
    watchlist = json.loads(legacy_expansion.WATCHLIST.read_text(encoding="utf-8"))
    watch_by_repo = {
        item["repository"]: item
        for item in watchlist["repositories"]
        if item.get("enabled") is True and item.get("repository")
    }
    pilot = json.loads(legacy_expansion.PILOT.read_text(encoding="utf-8"))
    pilot_by_repo = {
        item["repository"]: dict(item)
        for item in pilot["pilot_targets"]
    }

    catalog: dict[str, dict[str, Any]] = {}
    for repository in repositories:
        row = watch_by_repo.get(repository)
        if row is None:
            raise ExpansionError(
                f"active-stage repository is not enabled in watchlist: {repository}"
            )
        engine = row.get("engine")
        if engine not in legacy_expansion.SUPPORTED_ENGINES:
            raise ExpansionError(f"unsupported live engine for {repository}")
        if repository in pilot_by_repo:
            target = pilot_by_repo[repository]
        else:
            ref = str(row.get("ref") or "main")
            target = {
                "repository": repository,
                "source_ref": f"refs/heads/{ref}",
                "event_types": [
                    "push",
                    "repository_dispatch",
                    "workflow_dispatch",
                ],
                "run_maestro": bool(row.get("run_maestro", False)),
                "history_key": (
                    "v61d-"
                    + repository.split("/", 1)[-1].lower().replace("_", "-")
                ),
                "analysis_mode": "fast",
                "engine": engine,
            }
        catalog[repository] = target
    return catalog


def materialize_event_config(
    policy: dict[str, Any],
    *,
    stage: str | None = None,
) -> dict[str, Any]:
    stage = str(stage or policy["active_stage"])
    if stage not in STAGES:
        raise ExpansionError("unknown materialization stage")
    enabled_repositories = [
        repository
        for repository in policy["stages"][stage]
        if not policy["repository_kill_switches"][repository]
    ]
    if not enabled_repositories:
        raise ExpansionError(
            "all active-stage repositories are disabled by repository kill switches"
        )
    catalog = _target_catalog(enabled_repositories)
    targets = [catalog[repo] for repo in enabled_repositories]
    return {
        "schema_version": 1,
        "enabled": bool(policy["enabled"]),
        "kill_switch": bool(policy["global_kill_switch"]),
        "rollout": "MULTI_PROJECT_PILOT_SET",
        "max_live_operations_per_event": 1,
        "ledger_authority": "NON_AUTHORITATIVE_PILOT_CONTINUITY",
        "pilot_targets": targets,
    }


def promotion_decision(
    *,
    policy: dict[str, Any],
    evidence: dict[str, dict[str, int]],
    current_stage: str | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    stage = str(current_stage or policy["active_stage"])
    if stage not in STAGES:
        raise ExpansionError("unknown current stage")
    index = STAGES.index(stage)
    if index == len(STAGES) - 1:
        return {
            "decision": "HOLD",
            "reason": "MAX_V61D_STAGE",
            "current_stage": stage,
            "next_stage": stage,
            "automatic": False,
            "policy_changed": False,
        }

    thresholds = contract["promotion_thresholds"]
    blockers: list[str] = []
    required = policy["stages"][stage]
    for repository in required:
        row = evidence.get(repository)
        if not isinstance(row, dict):
            blockers.append(f"{repository}:MISSING_V61_EVIDENCE")
            continue
        success = int(row.get("successful_closed_loop_operations", 0))
        failure = int(row.get("failed_closed_loop_operations", 0))
        authority = int(row.get("authority_breaches", 0))
        false_repairs = int(row.get("false_repairs", 0))
        recovery = int(row.get("recovery_failures", 0))
        identity = int(row.get("exact_identity_violations", 0))
        if success < int(
            thresholds["minimum_successful_closed_loop_operations_per_repository"]
        ):
            blockers.append(f"{repository}:INSUFFICIENT_CLOSED_LOOP_SUCCESS")
        if failure > int(
            thresholds["maximum_failed_closed_loop_operations_per_repository"]
        ):
            blockers.append(f"{repository}:CLOSED_LOOP_FAILURE")
        if authority > int(thresholds["maximum_authority_breaches"]):
            blockers.append(f"{repository}:AUTHORITY_BREACH")
        if false_repairs > int(thresholds["maximum_false_repairs"]):
            blockers.append(f"{repository}:FALSE_REPAIR")
        if recovery > int(thresholds["maximum_recovery_failures"]):
            blockers.append(f"{repository}:RECOVERY_FAILURE")
        if identity > int(thresholds["maximum_exact_identity_violations"]):
            blockers.append(f"{repository}:EXACT_IDENTITY_VIOLATION")

    next_stage = STAGES[index + 1]
    return {
        "decision": "ELIGIBLE_FOR_EXPLICIT_PROMOTION" if not blockers else "HOLD",
        "reason": "V61_EVIDENCE_SUFFICIENT" if not blockers else "V61_EVIDENCE_INSUFFICIENT",
        "current_stage": stage,
        "next_stage": next_stage,
        "required_repositories": required,
        "blockers": blockers,
        "automatic": False,
        "policy_changed": False,
        "v55_evidence_grants_mutation_authority": False,
    }


def _denied(
    *,
    repository: str,
    source_ref: str,
    resolved_sha: str,
    stage: str,
    risk: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "APPLAB_V61D_EXPANSION_ADMISSION",
        "authority": "ORCHESTRATION_ONLY",
        "stage": stage,
        "admitted": False,
        "reason": reason,
        "repository": repository,
        "source_ref": source_ref,
        "resolved_sha": resolved_sha,
        "risk": risk,
        "mutation_authorized": False,
        "draft_pr_authorized": False,
        "dispatch": False,
        "remote_write_performed": False,
        "merge_authority": "POST_GATE_EXTERNAL_ONLY",
        "release_authority": "DENIED",
        "certification_authority": "UNCHANGED",
    }


def admit_closed_loop(
    *,
    db_path: Path,
    repository: str,
    source_ref: str,
    resolved_sha: str,
    applab_sha: str,
    delivery_id: str,
    risk: str = "NORMAL",
    policy_path: Path = DEFAULT_POLICY,
    now_ts: float | None = None,
) -> dict[str, Any]:
    contract = load_contract()
    policy = load_policy(policy_path, contract=contract)
    repository = brain._require_repository(repository)
    source_ref = brain._require_non_empty_string(source_ref, "source_ref")
    resolved_sha = brain._require_sha(resolved_sha, "resolved_sha")
    applab_sha = brain._require_sha(applab_sha, "applab_sha")
    delivery_id = brain._require_non_empty_string(delivery_id, "delivery_id")
    risk = str(risk).upper()
    if risk not in workgraph.load_contract()["work_item"]["risk_levels"]:
        raise ExpansionError("unsupported WorkItem risk")

    stage = policy["active_stage"]
    if not policy["enabled"]:
        return _denied(
            repository=repository,
            source_ref=source_ref,
            resolved_sha=resolved_sha,
            stage=stage,
            risk=risk,
            reason="EXPANSION_DISABLED",
        )
    if policy["global_kill_switch"]:
        return _denied(
            repository=repository,
            source_ref=source_ref,
            resolved_sha=resolved_sha,
            stage=stage,
            risk=risk,
            reason="GLOBAL_KILL_SWITCH",
        )
    if repository not in policy["stages"][stage]:
        return _denied(
            repository=repository,
            source_ref=source_ref,
            resolved_sha=resolved_sha,
            stage=stage,
            risk=risk,
            reason="REPOSITORY_OUTSIDE_ACTIVE_STAGE",
        )
    if policy["repository_kill_switches"][repository]:
        return _denied(
            repository=repository,
            source_ref=source_ref,
            resolved_sha=resolved_sha,
            stage=stage,
            risk=risk,
            reason="REPOSITORY_KILL_SWITCH",
        )
    if source_ref not in contract["allowed_source_refs"]:
        return _denied(
            repository=repository,
            source_ref=source_ref,
            resolved_sha=resolved_sha,
            stage=stage,
            risk=risk,
            reason="SOURCE_REF_NOT_ALLOWLISTED",
        )
    if repository == contract["self_repository"] and resolved_sha != applab_sha:
        return _denied(
            repository=repository,
            source_ref=source_ref,
            resolved_sha=resolved_sha,
            stage=stage,
            risk=risk,
            reason="SELF_IDENTITY_MISMATCH",
        )

    closed = policy["closed_loop"]
    mutation_requested = bool(
        closed["mutation_enabled"]
        and risk in set(contract["autonomous_mutation_risks"])
    )
    draft_requested = bool(mutation_requested and closed["draft_pr_enabled"])

    event_config = materialize_event_config(policy, stage=stage)
    with tempfile.TemporaryDirectory() as raw:
        config_path = Path(raw) / "event-config.json"
        config_path.write_text(
            json.dumps(event_config, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        durable = event_pilot.admit(
            db_path=db_path,
            config_path=config_path,
            repository=repository,
            source_ref=source_ref,
            resolved_sha=resolved_sha,
            applab_sha=applab_sha,
            delivery_id=delivery_id,
            live_requested=False,
            now_ts=now_ts,
        )

    if not durable.get("admitted"):
        return _denied(
            repository=repository,
            source_ref=source_ref,
            resolved_sha=resolved_sha,
            stage=stage,
            risk=risk,
            reason="DURABLE_ADMISSION_DENIED",
        )

    started = self_pilot._persist_work_item(
        db_path=db_path,
        operation_id=str(durable["operation_id"]),
        allow_code_edit=mutation_requested,
        allow_draft_pr=draft_requested,
        risk=risk,
        reason_code=f"V61D_{stage}_ADMITTED",
    )
    if not started["integrity"]["ok"]:
        raise ExpansionError("agent work graph integrity failure")

    terminal_states = set(
        workgraph.load_contract()["work_item"]["terminal_states"]
    )
    terminal_reuse = bool(started["terminal_reuse"]) or (
        started["work_item_state"] in terminal_states
    )
    if terminal_reuse or started["policy_action"] == "STOPPED_POLICY_REVOKED":
        budget_state = "TERMINAL_NO_NEW_BUDGET_ACTIVITY"
        queue_backpressure = durable["queue_state"] == "DEFERRED"
    else:
        budget = budgets.register_budget(
            db_path=db_path,
            work_item_id=str(started["work_item_id"]),
            now_ts=float(now_ts or 0.0),
            occurred_at="1970-01-01T00:00:00Z",
        )
        budget_state = budget["budget_state"]
        queue_backpressure = budget["queue_backpressure"]

    return {
        "schema_version": 1,
        "record_type": "APPLAB_V61D_EXPANSION_ADMISSION",
        "authority": "ORCHESTRATION_ONLY",
        "stage": stage,
        "admitted": True,
        "reason": (
            "POLICY_REVOKED_STOPPED"
            if started["policy_action"] == "STOPPED_POLICY_REVOKED"
            else "TERMINAL_REUSE_PRESERVED"
            if terminal_reuse
            else "BOUNDED_MUTATION_ADMITTED"
            if started["effective_mutation_authorized"]
            else "INVESTIGATION_ONLY_ADMITTED"
        ),
        "repository": repository,
        "source_ref": source_ref,
        "resolved_sha": resolved_sha,
        "applab_sha": applab_sha,
        "risk": risk,
        "mutation_authorized": started["effective_mutation_authorized"],
        "draft_pr_authorized": started["effective_draft_pr_authorized"],
        "operation_id": durable["operation_id"],
        "operation_persistence": durable["operation_persistence"],
        "queue_state": durable["queue_state"],
        "work_item_id": started["work_item_id"],
        "work_item_persistence": started["work_item_persistence"],
        "work_item_state": started["work_item_state"],
        "policy_action": started["policy_action"],
        "budget_state": budget_state,
        "queue_backpressure": queue_backpressure,
        "dispatch": False,
        "remote_write_performed": False,
        "dispatch_owner": "EXISTING_DURABLE_CONTROL_PLANE",
        "github_actions_fallback": True,
        "event_driven_waiting_primary": True,
        "merge_authority": "POST_GATE_EXTERNAL_ONLY",
        "release_authority": "DENIED",
        "verification_authority": "UNCHANGED",
        "certification_authority": "UNCHANGED",
    }


def self_test() -> dict[str, Any]:
    contract = load_contract()
    policy = load_policy(contract=contract)
    assert policy["active_stage"] == "SELF_CANARY"
    assert "ALL_COMPATIBLE" not in policy["stages"]

    insufficient = {
        "riccardopinato/AppLab": {
            "successful_closed_loop_operations": 2,
            "failed_closed_loop_operations": 0,
            "authority_breaches": 0,
            "false_repairs": 0,
            "recovery_failures": 0,
            "exact_identity_violations": 0,
        }
    }
    held = promotion_decision(policy=policy, evidence=insufficient)
    assert held["decision"] == "HOLD"

    sufficient = json.loads(json.dumps(insufficient))
    sufficient["riccardopinato/AppLab"]["successful_closed_loop_operations"] = 3
    eligible = promotion_decision(policy=policy, evidence=sufficient)
    assert eligible["decision"] == "ELIGIBLE_FOR_EXPLICIT_PROMOTION"
    assert eligible["next_stage"] == "PILOT_3"
    assert eligible["policy_changed"] is False

    pilot3 = json.loads(json.dumps(policy))
    pilot3["active_stage"] = "PILOT_3"
    config = materialize_event_config(pilot3)
    assert [item["repository"] for item in config["pilot_targets"]] == policy["stages"]["PILOT_3"]

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        policy_path = root / "pilot3.json"
        policy_path.write_text(
            json.dumps(pilot3, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        applab_sha = "a" * 40
        camper_sha = "b" * 40

        camper = admit_closed_loop(
            db_path=root / "pilot.sqlite3",
            repository="riccardopinato/CamperBoss",
            source_ref="refs/heads/main",
            resolved_sha=camper_sha,
            applab_sha=applab_sha,
            delivery_id="v61d-camper",
            risk="NORMAL",
            policy_path=policy_path,
            now_ts=100.0,
        )
        assert camper["admitted"] is True
        assert camper["mutation_authorized"] is True
        assert camper["draft_pr_authorized"] is True
        assert camper["dispatch"] is False
        assert camper["remote_write_performed"] is False

        replay = admit_closed_loop(
            db_path=root / "pilot.sqlite3",
            repository="riccardopinato/CamperBoss",
            source_ref="refs/heads/main",
            resolved_sha=camper_sha,
            applab_sha=applab_sha,
            delivery_id="v61d-camper",
            risk="NORMAL",
            policy_path=policy_path,
            now_ts=101.0,
        )
        assert replay["operation_id"] == camper["operation_id"]
        assert replay["work_item_id"] == camper["work_item_id"]

        high = admit_closed_loop(
            db_path=root / "high.sqlite3",
            repository="riccardopinato/TrailPath",
            source_ref="refs/heads/main",
            resolved_sha="c" * 40,
            applab_sha=applab_sha,
            delivery_id="v61d-trail-high",
            risk="HIGH",
            policy_path=policy_path,
            now_ts=102.0,
        )
        assert high["admitted"] is True
        assert high["mutation_authorized"] is False
        assert high["draft_pr_authorized"] is False

        outside = admit_closed_loop(
            db_path=root / "outside.sqlite3",
            repository="riccardopinato/Notes-Ecosistema",
            source_ref="refs/heads/main",
            resolved_sha="d" * 40,
            applab_sha=applab_sha,
            delivery_id="v61d-outside",
            policy_path=policy_path,
            now_ts=103.0,
        )
        assert outside["admitted"] is False
        assert outside["reason"] == "REPOSITORY_OUTSIDE_ACTIVE_STAGE"

        killed_policy = json.loads(json.dumps(pilot3))
        killed_policy["repository_kill_switches"]["riccardopinato/CamperBoss"] = True
        killed_path = root / "killed.json"
        killed_path.write_text(
            json.dumps(killed_policy, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        killed_config = materialize_event_config(killed_policy)
        assert [
            item["repository"] for item in killed_config["pilot_targets"]
        ] == ["riccardopinato/AppLab", "riccardopinato/TrailPath"]

        killed = admit_closed_loop(
            db_path=root / "killed.sqlite3",
            repository="riccardopinato/CamperBoss",
            source_ref="refs/heads/main",
            resolved_sha="e" * 40,
            applab_sha=applab_sha,
            delivery_id="v61d-killed",
            policy_path=killed_path,
            now_ts=104.0,
        )
        assert killed["admitted"] is False
        assert killed["reason"] == "REPOSITORY_KILL_SWITCH"

        revoked_db = root / "revoked.sqlite3"
        first_mutable = admit_closed_loop(
            db_path=revoked_db,
            repository="riccardopinato/CamperBoss",
            source_ref="refs/heads/main",
            resolved_sha="f" * 40,
            applab_sha=applab_sha,
            delivery_id="v61d-revoked",
            policy_path=policy_path,
            now_ts=105.0,
        )
        assert first_mutable["mutation_authorized"] is True

        revoked_policy = json.loads(json.dumps(pilot3))
        revoked_policy["closed_loop"]["mutation_enabled"] = False
        revoked_policy["closed_loop"]["draft_pr_enabled"] = False
        revoked_path = root / "revoked-policy.json"
        revoked_path.write_text(
            json.dumps(revoked_policy, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        revoked = admit_closed_loop(
            db_path=revoked_db,
            repository="riccardopinato/CamperBoss",
            source_ref="refs/heads/main",
            resolved_sha="f" * 40,
            applab_sha=applab_sha,
            delivery_id="v61d-revoked",
            policy_path=revoked_path,
            now_ts=106.0,
        )
        assert revoked["reason"] == "POLICY_REVOKED_STOPPED"
        assert revoked["work_item_state"] == "STOPPED"
        assert revoked["budget_state"] == "TERMINAL_NO_NEW_BUDGET_ACTIVITY"
        assert revoked["dispatch"] is False

        original_watchlist = legacy_expansion.WATCHLIST
        watchlist = json.loads(original_watchlist.read_text(encoding="utf-8"))
        for item in watchlist["repositories"]:
            if item.get("repository") == "riccardopinato/Notes-Ecosistema":
                item["enabled"] = False
        isolated_watchlist = root / "watchlist-isolated.json"
        isolated_watchlist.write_text(
            json.dumps(watchlist, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            legacy_expansion.WATCHLIST = isolated_watchlist
            isolated = materialize_event_config(policy)
        finally:
            legacy_expansion.WATCHLIST = original_watchlist
        assert [item["repository"] for item in isolated["pilot_targets"]] == [
            "riccardopinato/AppLab"
        ]

    return {
        "schema_version": 1,
        "record_type": "APPLAB_V61D_CONTROLLED_EXPANSION_PROOF",
        "status": "PASS",
        "active_stage": policy["active_stage"],
        "promotion_order": list(STAGES),
        "all_compatible_pre_authorized": False,
        "v55_topology_reused_without_authority_inheritance": True,
        "promotion_requires_v61_closed_loop_evidence": True,
        "promotion_is_explicit_not_automatic": True,
        "pilot3_materialization_proven": True,
        "downstream_bounded_mutation_admission_proven": True,
        "high_risk_investigation_only": True,
        "global_and_repository_kill_switches_preserved": True,
        "repository_kill_switch_materialization_proven": True,
        "inactive_out_of_cohort_watchlist_isolated": True,
        "terminal_replay_skips_budget_activity": True,
        "existing_durable_queue_work_graph_and_budgets_reused": True,
        "remote_dispatch_created": False,
        "github_actions_fallback": True,
        "merge_authority": "POST_GATE_EXTERNAL_ONLY",
        "release_authority": "DENIED",
        "certification_authority": "UNCHANGED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AppLab v6.1D controlled multi-repository closed-loop expansion"
    )
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--materialize-stage-config", type=Path)
    parser.add_argument("--stage", choices=STAGES)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2, sort_keys=True))
        return 0
    if args.materialize_stage_config is not None:
        policy = load_policy()
        payload = materialize_event_config(policy, stage=args.stage)
        args.materialize_stage_config.parent.mkdir(parents=True, exist_ok=True)
        args.materialize_stage_config.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0
    parser.error("--self-test or --materialize-stage-config is required")


if __name__ == "__main__":
    raise SystemExit(main())
