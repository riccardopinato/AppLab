#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import agent_work_graph_v60a as workgraph
import bounded_fix_worker_v60c as fix_worker
import causal_repo_investigator_v60b as investigator
import controlled_event_v54g as event_pilot
import draft_pr_steward_v60e as pr_steward
import durable_brain_v54a as brain
import durable_store_v54b as storemod
import verify_repair_loop_v60d as repair_loop

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = (
    ROOT / "integration" / "orchestration" / "contracts" / "closed-loop-pilot-v1.json"
)
DEFAULT_CONFIG = ROOT / "integration" / "orchestration" / "v61-closed-loop-pilot.json"


class ClosedLoopPilotError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ClosedLoopPilotError("unsupported closed-loop pilot contract version")
    if payload.get("contract_name") != "APPLAB_CLOSED_LOOP_PILOT_ADMISSION":
        raise ClosedLoopPilotError("unexpected closed-loop pilot contract")
    if payload.get("authority") != "ORCHESTRATION_ONLY":
        raise ClosedLoopPilotError("closed-loop pilot authority must remain orchestration-only")
    if payload.get("stage") != "SELF_CANARY":
        raise ClosedLoopPilotError("v6.1A only supports SELF_CANARY")
    if payload.get("allowed_repositories") != ["riccardopinato/AppLab"]:
        raise ClosedLoopPilotError("v6.1A repository allowlist must contain AppLab only")
    if payload.get("allowed_source_refs") != ["refs/heads/main"]:
        raise ClosedLoopPilotError("v6.1A source allowlist must contain AppLab main only")
    if payload.get("require_self_applab_sha_equal_source") is not True:
        raise ClosedLoopPilotError("self-canary must bind AppLab SHA to source SHA")
    if payload.get("github_actions_fallback") is not True:
        raise ClosedLoopPilotError("GitHub Actions fallback must remain enabled")
    if payload.get("release_authority") != "DENIED":
        raise ClosedLoopPilotError("release authority must remain denied")
    return payload


def load_config(
    path: Path = DEFAULT_CONFIG,
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    payload = event_pilot.load_config(path)
    if payload.get("rollout") != "SELF_REPO_MAIN_CANARY":
        raise ClosedLoopPilotError("v6.1A config must be SELF_REPO_MAIN_CANARY")
    closed = payload.get("closed_loop")
    if not isinstance(closed, dict):
        raise ClosedLoopPilotError("closed_loop config must be an object")
    for field in ("enabled", "mutation_enabled", "draft_pr_enabled"):
        if not isinstance(closed.get(field), bool):
            raise ClosedLoopPilotError(f"closed_loop.{field} must be boolean")
    if closed.get("allowed_repositories") != contract["allowed_repositories"]:
        raise ClosedLoopPilotError("closed-loop repository allowlist drift")
    if closed.get("allowed_source_refs") != contract["allowed_source_refs"]:
        raise ClosedLoopPilotError("closed-loop source-ref allowlist drift")
    if closed.get("allowed_mutation_risks") != contract["autonomous_mutation_risks"]:
        raise ClosedLoopPilotError("closed-loop mutation risk allowlist drift")
    if closed.get("github_actions_fallback") is not True:
        raise ClosedLoopPilotError("closed-loop config must retain GitHub Actions fallback")
    if closed.get("post_gate_merge_authority") != "EXTERNAL_REPOSITORY_AUTOMATION":
        raise ClosedLoopPilotError("post-gate merge authority drift")
    if closed.get("release_authority") != "DENIED":
        raise ClosedLoopPilotError("closed-loop release authority must remain denied")
    targets = payload.get("pilot_targets") or []
    if len(targets) != 1:
        raise ClosedLoopPilotError("v6.1A must expose exactly one pilot target")
    target = targets[0]
    if target.get("repository") != "riccardopinato/AppLab":
        raise ClosedLoopPilotError("v6.1A pilot target must be AppLab")
    if target.get("source_ref") != "refs/heads/main":
        raise ClosedLoopPilotError("v6.1A pilot target must be AppLab main")
    return payload


def _component_contracts(contract: dict[str, Any]) -> dict[str, str]:
    graph_contract = workgraph.load_contract()
    investigator_contract = investigator.load_contract()
    fix_contract = fix_worker.load_contract()
    repair_contract = repair_loop.load_contract()
    steward_contract = pr_steward.load_contract()

    expected = {
        "work_graph": "ORCHESTRATION_ONLY",
        "investigator": "PROPOSAL_ONLY",
        "fix_worker": "BRANCH_WORKSPACE_ONLY",
        "repair_loop": "ORCHESTRATION_ONLY",
        "draft_pr_steward": "DRAFT_BRANCH_AND_PR_ONLY",
    }
    observed = {
        "work_graph": str(graph_contract.get("authority")),
        "investigator": str(investigator_contract.get("authority")),
        "fix_worker": str(fix_contract.get("authority")),
        "repair_loop": str(repair_contract.get("authority")),
        "draft_pr_steward": str(steward_contract.get("authority")),
    }
    if observed != expected:
        raise ClosedLoopPilotError("v6 component authority boundary drift")
    work_denials = set(graph_contract["authority_envelope"]["mandatory_denials"])
    missing = sorted(set(contract["mandatory_denials"]) - work_denials)
    if missing:
        raise ClosedLoopPilotError(
            "work graph is missing v6.1A mandatory denials: " + ", ".join(missing)
        )
    return observed


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _denied(
    *,
    repository: str,
    source_ref: str,
    resolved_sha: str,
    reason: str,
    risk: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "APPLAB_V61A_CLOSED_LOOP_ADMISSION",
        "authority": "ORCHESTRATION_ONLY",
        "stage": "SELF_CANARY",
        "admitted": False,
        "reason": reason,
        "repository": repository,
        "source_ref": source_ref,
        "resolved_sha": resolved_sha,
        "risk": risk,
        "mutation_authorized": False,
        "draft_pr_authorized": False,
        "dispatch": False,
        "merge_authority": "POST_GATE_EXTERNAL_ONLY",
        "release_authority": "DENIED",
        "certification_authority": "UNCHANGED",
    }


def _persist_work_item(
    *,
    db_path: Path,
    operation_id: str,
    allow_code_edit: bool,
    allow_draft_pr: bool,
    risk: str,
    reason_code: str = "V61A_SELF_CANARY_ADMITTED",
) -> dict[str, Any]:
    graph_contract = workgraph.load_contract()
    with storemod.SQLiteShadowStore(db_path) as durable:
        operation = durable.get_operation(operation_id)
        graph = workgraph.AgentWorkGraphStore(durable, graph_contract)

        existing_row = durable.db.execute(
            "SELECT work_item_id FROM agent_work_items WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        requested_work_item_id = _stable_id(
            "wrk",
            operation["operation_id"],
            operation["repository"],
            operation["source_ref"],
            operation["resolved_sha"],
            operation["applab_sha"],
        )

        if existing_row is not None:
            work_item_id = str(existing_row["work_item_id"])
            persisted = {"status": "OPERATION_REUSE", "work_item_id": work_item_id}
            current = graph.get_work_item(work_item_id)
        else:
            item = workgraph.adapt_operation_to_work_item(
                operation,
                work_item_id=requested_work_item_id,
                risk=risk,
                allow_code_edit=allow_code_edit,
                allow_draft_pr_steward=allow_draft_pr,
            )
            persisted = graph.put_work_item(item)
            work_item_id = str(persisted["work_item_id"])
            current = graph.get_work_item(work_item_id)

        persisted_capabilities = set(
            current["authority_envelope"]["allowed_capabilities"]
        )
        persisted_edit = "ALLOW_CODE_EDIT" in persisted_capabilities
        persisted_draft = {
            "CREATE_DRAFT_PR",
            "UPDATE_DRAFT_PR",
        }.issubset(persisted_capabilities)
        policy_revoked = (
            (persisted_edit and not allow_code_edit)
            or (persisted_draft and not allow_draft_pr)
        )
        requested_escalation_blocked = (
            (allow_code_edit and not persisted_edit)
            or (allow_draft_pr and not persisted_draft)
        )

        terminal_states = set(graph_contract["work_item"]["terminal_states"])
        if current["current_state"] in terminal_states:
            return {
                "work_item_id": work_item_id,
                "work_item_persistence": persisted["status"],
                "work_item_state": current["current_state"],
                "terminal_reuse": True,
                "policy_action": "PRESERVE_TERMINAL",
                "effective_mutation_authorized": False,
                "effective_draft_pr_authorized": False,
                "decision_persistence": "TERMINAL_NO_REDISPATCH",
                "transition_persistence": "TERMINAL_NO_REDISPATCH",
                "integrity": graph.integrity_report(),
            }

        row = durable.db.execute(
            "SELECT created_at FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        created_at = str(row["created_at"]) if row else "1970-01-01T00:00:00Z"

        if policy_revoked:
            transition_id = _stable_id(
                "trn",
                work_item_id,
                current["current_state"],
                "STOPPED",
                "V61A_POLICY_REVOKED",
            )
            transition_result = graph.transition(
                transition_id=transition_id,
                work_item_id=work_item_id,
                from_state=current["current_state"],
                to_state="STOPPED",
                reason_code="V61A_POLICY_REVOKED",
                created_at=created_at,
            )
            current = graph.get_work_item(work_item_id)
            return {
                "work_item_id": work_item_id,
                "work_item_persistence": persisted["status"],
                "work_item_state": current["current_state"],
                "terminal_reuse": False,
                "policy_action": "STOPPED_POLICY_REVOKED",
                "effective_mutation_authorized": False,
                "effective_draft_pr_authorized": False,
                "decision_persistence": "POLICY_STOP_NO_NEW_DECISION",
                "transition_persistence": transition_result["status"],
                "integrity": graph.integrity_report(),
            }

        if current["current_state"] == "CREATED":
            decision_id = _stable_id("dec", work_item_id, "INVESTIGATE")
            decision = {
                "schema_version": 1,
                "record_type": "APPLAB_WORK_DECISION",
                "decision_id": decision_id,
                "work_item_id": work_item_id,
                "kind": "INVESTIGATE",
                "reason_code": reason_code,
                "evidence_ref_ids": [],
                "created_at": created_at,
            }
            decision_result = graph.put_decision(decision)
            transition_id = _stable_id("trn", work_item_id, "CREATED", "INVESTIGATING")
            transition_result = graph.transition(
                transition_id=transition_id,
                work_item_id=work_item_id,
                from_state="CREATED",
                to_state="INVESTIGATING",
                reason_code=reason_code,
                created_at=created_at,
            )
        else:
            decision_result = {"status": "REUSE_CURRENT_STATE"}
            transition_result = {"status": "REUSE_CURRENT_STATE"}

        current = graph.get_work_item(work_item_id)
        return {
            "work_item_id": work_item_id,
            "work_item_persistence": persisted["status"],
            "work_item_state": current["current_state"],
            "terminal_reuse": False,
            "policy_action": (
                "IMMUTABLE_ENVELOPE_RESTRICTS_REPLAY"
                if requested_escalation_blocked
                else "MATCHED_OR_REUSED"
            ),
            "effective_mutation_authorized": bool(
                allow_code_edit and persisted_edit
            ),
            "effective_draft_pr_authorized": bool(
                allow_draft_pr and persisted_draft
            ),
            "decision_persistence": decision_result["status"],
            "transition_persistence": transition_result["status"],
            "integrity": graph.integrity_report(),
        }


def admit_closed_loop(
    *,
    db_path: Path,
    config_path: Path = DEFAULT_CONFIG,
    repository: str,
    source_ref: str,
    resolved_sha: str,
    applab_sha: str,
    delivery_id: str,
    risk: str = "NORMAL",
    live_requested: bool = False,
    now_ts: float | None = None,
) -> dict[str, Any]:
    contract = load_contract()
    config = load_config(config_path, contract=contract)
    components = _component_contracts(contract)

    repository = brain._require_repository(repository)
    source_ref = brain._require_non_empty_string(source_ref, "source_ref")
    resolved_sha = brain._require_sha(resolved_sha, "resolved_sha")
    applab_sha = brain._require_sha(applab_sha, "applab_sha")
    delivery_id = brain._require_non_empty_string(delivery_id, "delivery_id")
    risk = str(risk).upper()
    if risk not in workgraph.load_contract()["work_item"]["risk_levels"]:
        raise ClosedLoopPilotError("unsupported WorkItem risk")

    if repository not in contract["allowed_repositories"]:
        return _denied(
            repository=repository,
            source_ref=source_ref,
            resolved_sha=resolved_sha,
            reason="REPOSITORY_NOT_ALLOWLISTED",
            risk=risk,
        )
    if source_ref not in contract["allowed_source_refs"]:
        return _denied(
            repository=repository,
            source_ref=source_ref,
            resolved_sha=resolved_sha,
            reason="SOURCE_REF_NOT_ALLOWLISTED",
            risk=risk,
        )
    if contract["require_self_applab_sha_equal_source"] and resolved_sha != applab_sha:
        return _denied(
            repository=repository,
            source_ref=source_ref,
            resolved_sha=resolved_sha,
            reason="SELF_IDENTITY_MISMATCH",
            risk=risk,
        )

    closed = config["closed_loop"]
    if not config["enabled"] or not closed["enabled"]:
        return _denied(
            repository=repository,
            source_ref=source_ref,
            resolved_sha=resolved_sha,
            reason="PILOT_DISABLED",
            risk=risk,
        )
    if config["kill_switch"]:
        return _denied(
            repository=repository,
            source_ref=source_ref,
            resolved_sha=resolved_sha,
            reason="GLOBAL_KILL_SWITCH",
            risk=risk,
        )

    mutation_authorized = bool(
        closed["mutation_enabled"]
        and risk in set(contract["autonomous_mutation_risks"])
    )
    draft_pr_authorized = bool(
        mutation_authorized and closed["draft_pr_enabled"]
    )

    # v6.1A deliberately reuses the v5.4/v5.5 durable admission/store/queue
    # path but never creates a competing live dispatcher. Live event-driven
    # progression/recovery is completed in v6.1B; v6.1C adds backpressure and
    # bounded observation budgets. GitHub Actions remains the fallback.
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
            reason="DURABLE_ADMISSION_DENIED",
            risk=risk,
        )

    started = _persist_work_item(
        db_path=db_path,
        operation_id=str(durable["operation_id"]),
        allow_code_edit=mutation_authorized,
        allow_draft_pr=draft_pr_authorized,
        risk=risk,
    )
    if not started["integrity"]["ok"]:
        raise ClosedLoopPilotError("agent work graph integrity failure")

    return {
        "schema_version": 1,
        "record_type": "APPLAB_V61A_CLOSED_LOOP_ADMISSION",
        "authority": "ORCHESTRATION_ONLY",
        "stage": "SELF_CANARY",
        "admitted": True,
        "reason": (
            "SELF_CANARY_POLICY_REVOKED_STOPPED"
            if started["policy_action"] == "STOPPED_POLICY_REVOKED"
            else "SELF_CANARY_MUTATION_ADMITTED"
            if started["effective_mutation_authorized"]
            else "SELF_CANARY_INVESTIGATION_ONLY"
        ),
        "repository": repository,
        "source_ref": source_ref,
        "resolved_sha": resolved_sha,
        "applab_sha": applab_sha,
        "risk": risk,
        "mutation_authorized": started["effective_mutation_authorized"],
        "draft_pr_authorized": started["effective_draft_pr_authorized"],
        "requested_mutation_authorized": mutation_authorized,
        "requested_draft_pr_authorized": draft_pr_authorized,
        "live_requested": bool(live_requested),
        "dispatch": False,
        "dispatch_owner": "EXISTING_DURABLE_CONTROL_PLANE",
        "event_persistence": durable["event_persistence"],
        "operation_id": durable["operation_id"],
        "operation_persistence": durable["operation_persistence"],
        "queue_state": durable["queue_state"],
        **started,
        "component_authorities": components,
        "github_actions_fallback": True,
        "fixed_interval_polling_primary": False,
        "v61b_progression": "EVENT_DRIVEN_PLUS_RECONCILIATION_WITH_BOUNDED_POLLING_FALLBACK",
        "merge_authority": "POST_GATE_EXTERNAL_ONLY",
        "release_authority": "DENIED",
        "verification_authority": "UNCHANGED",
        "certification_authority": "UNCHANGED",
    }


def self_test() -> dict[str, Any]:
    contract = load_contract()
    config = load_config(contract=contract)
    sha = "a" * 40

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "v61a.sqlite3"
        admitted = admit_closed_loop(
            db_path=db_path,
            repository="riccardopinato/AppLab",
            source_ref="refs/heads/main",
            resolved_sha=sha,
            applab_sha=sha,
            delivery_id="v61a-selftest",
            risk="NORMAL",
            live_requested=True,
            now_ts=1000.0,
        )
        assert admitted["admitted"] is True
        assert admitted["mutation_authorized"] is True
        assert admitted["draft_pr_authorized"] is True
        assert admitted["work_item_state"] == "INVESTIGATING"
        assert admitted["dispatch"] is False
        assert admitted["github_actions_fallback"] is True
        assert admitted["fixed_interval_polling_primary"] is False

        replay = admit_closed_loop(
            db_path=db_path,
            repository="riccardopinato/AppLab",
            source_ref="refs/heads/main",
            resolved_sha=sha,
            applab_sha=sha,
            delivery_id="v61a-selftest",
            risk="NORMAL",
            live_requested=True,
            now_ts=1001.0,
        )
        assert replay["operation_id"] == admitted["operation_id"]
        assert replay["work_item_id"] == admitted["work_item_id"]
        assert replay["work_item_state"] == "INVESTIGATING"
        assert replay["mutation_authorized"] is True

        high = admit_closed_loop(
            db_path=Path(tmp) / "v61a-high.sqlite3",
            repository="riccardopinato/AppLab",
            source_ref="refs/heads/main",
            resolved_sha=sha,
            applab_sha=sha,
            delivery_id="v61a-high",
            risk="HIGH",
            now_ts=1002.0,
        )
        assert high["admitted"] is True
        assert high["mutation_authorized"] is False
        assert high["draft_pr_authorized"] is False

        outside = admit_closed_loop(
            db_path=Path(tmp) / "v61a-outside.sqlite3",
            repository="owner/other",
            source_ref="refs/heads/main",
            resolved_sha=sha,
            applab_sha=sha,
            delivery_id="v61a-outside",
            risk="NORMAL",
            now_ts=1003.0,
        )
        assert outside["admitted"] is False
        assert outside["reason"] == "REPOSITORY_NOT_ALLOWLISTED"

        mismatch = admit_closed_loop(
            db_path=Path(tmp) / "v61a-mismatch.sqlite3",
            repository="riccardopinato/AppLab",
            source_ref="refs/heads/main",
            resolved_sha=sha,
            applab_sha="b" * 40,
            delivery_id="v61a-mismatch",
            risk="NORMAL",
            now_ts=1004.0,
        )
        assert mismatch["admitted"] is False
        assert mismatch["reason"] == "SELF_IDENTITY_MISMATCH"

        killed_cfg = json.loads(json.dumps(config))
        killed_cfg["kill_switch"] = True
        killed_path = Path(tmp) / "v61a-killed.json"
        killed_path.write_text(
            json.dumps(killed_cfg, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        killed = admit_closed_loop(
            db_path=Path(tmp) / "v61a-killed.sqlite3",
            config_path=killed_path,
            repository="riccardopinato/AppLab",
            source_ref="refs/heads/main",
            resolved_sha=sha,
            applab_sha=sha,
            delivery_id="v61a-killed",
            risk="NORMAL",
            now_ts=1005.0,
        )
        assert killed["admitted"] is False
        assert killed["reason"] == "GLOBAL_KILL_SWITCH"

        policy_cfg = json.loads(json.dumps(config))
        policy_cfg["closed_loop"]["mutation_enabled"] = False
        policy_cfg["closed_loop"]["draft_pr_enabled"] = False
        policy_path = Path(tmp) / "v61a-policy-revoked.json"
        policy_path.write_text(
            json.dumps(policy_cfg, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        policy_replay = admit_closed_loop(
            db_path=db_path,
            config_path=policy_path,
            repository="riccardopinato/AppLab",
            source_ref="refs/heads/main",
            resolved_sha=sha,
            applab_sha=sha,
            delivery_id="v61a-selftest",
            risk="NORMAL",
            now_ts=1006.0,
        )
        assert policy_replay["work_item_id"] == admitted["work_item_id"]
        assert policy_replay["work_item_state"] == "STOPPED"
        assert policy_replay["policy_action"] == "STOPPED_POLICY_REVOKED"
        assert policy_replay["mutation_authorized"] is False
        assert policy_replay["draft_pr_authorized"] is False

        seeded_db = Path(tmp) / "v61a-seeded.sqlite3"
        seeded_delivery = "v61a-seeded"
        seeded_durable = event_pilot.admit(
            db_path=seeded_db,
            config_path=DEFAULT_CONFIG,
            repository="riccardopinato/AppLab",
            source_ref="refs/heads/main",
            resolved_sha=sha,
            applab_sha=sha,
            delivery_id=seeded_delivery,
            live_requested=False,
            now_ts=1007.0,
        )
        with storemod.SQLiteShadowStore(seeded_db) as durable_store:
            operation = durable_store.get_operation(seeded_durable["operation_id"])
            graph = workgraph.AgentWorkGraphStore(durable_store)
            seeded_item = workgraph.adapt_operation_to_work_item(
                operation,
                work_item_id="wrk_seeded_v61a",
                risk="NORMAL",
                allow_code_edit=True,
                allow_draft_pr_steward=True,
            )
            graph.put_work_item(seeded_item)

        seeded = admit_closed_loop(
            db_path=seeded_db,
            repository="riccardopinato/AppLab",
            source_ref="refs/heads/main",
            resolved_sha=sha,
            applab_sha=sha,
            delivery_id=seeded_delivery,
            risk="NORMAL",
            now_ts=1008.0,
        )
        assert seeded["work_item_id"] == "wrk_seeded_v61a"
        assert seeded["work_item_persistence"] == "OPERATION_REUSE"
        assert seeded["work_item_state"] == "INVESTIGATING"

    return {
        "schema_version": 1,
        "record_type": "APPLAB_V61A_CLOSED_LOOP_PILOT_PROOF",
        "status": "PASS",
        "stage": "SELF_CANARY",
        "repository_allowlist": contract["allowed_repositories"],
        "source_ref_allowlist": contract["allowed_source_refs"],
        "immutable_self_identity_proven": True,
        "global_kill_switch_proven": True,
        "normal_risk_mutation_admitted": True,
        "high_risk_investigation_only": True,
        "duplicate_delivery_reuses_operation_and_work_item": True,
        "policy_revocation_stops_existing_mutable_work_item": True,
        "operation_reuse_uses_persisted_work_item_id": True,
        "existing_durable_substrate_reused": True,
        "parallel_dispatcher_created": False,
        "fixed_interval_polling_primary": False,
        "github_actions_fallback": True,
        "merge_authority": "POST_GATE_EXTERNAL_ONLY",
        "release_authority": "DENIED",
        "certification_authority": "UNCHANGED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v6.1A closed-loop self-canary admission")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--repository", default="riccardopinato/AppLab")
    parser.add_argument("--source-ref", default="refs/heads/main")
    parser.add_argument("--resolved-sha")
    parser.add_argument("--applab-sha")
    parser.add_argument("--delivery-id")
    parser.add_argument("--risk", default="NORMAL")
    parser.add_argument("--live-requested", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        print(json.dumps(self_test(), indent=2, sort_keys=True))
        return 0

    if not args.db or not args.resolved_sha or not args.applab_sha or not args.delivery_id:
        parser.error("--db, --resolved-sha, --applab-sha and --delivery-id are required")

    report = admit_closed_loop(
        db_path=args.db,
        config_path=args.config,
        repository=args.repository,
        source_ref=args.source_ref,
        resolved_sha=args.resolved_sha,
        applab_sha=args.applab_sha,
        delivery_id=args.delivery_id,
        risk=args.risk,
        live_requested=args.live_requested,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
