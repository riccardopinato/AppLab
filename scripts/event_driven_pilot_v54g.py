#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import durable_brain_v54a as brain
import durable_queue_v54e as queue_mod
import durable_store_v54b as storemod

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = ROOT / "integration" / "orchestration" / "contracts" / "controlled-event-pilot-v1.json"


class PilotError(ValueError):
    pass


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise PilotError("unsupported pilot policy")
    if payload.get("contract_name") != "APPLAB_CONTROLLED_EVENT_DRIVEN_PILOT":
        raise PilotError("unexpected pilot policy")
    if payload.get("authority") != "ORCHESTRATION_ONLY":
        raise PilotError("pilot authority drift")
    if payload.get("certification_authority_changed") is not False:
        raise PilotError("certification authority must remain unchanged")
    return payload


def effective_policy(
    base: dict[str, Any],
    *,
    enabled: bool | None = None,
    allowed_repositories: list[str] | None = None,
) -> dict[str, Any]:
    result = dict(base)
    if enabled is not None:
        result["enabled"] = bool(enabled)
    if allowed_repositories is not None:
        unique = sorted(set(allowed_repositories))
        if len(unique) > int(base["max_enabled_repositories"]):
            raise PilotError("repository pilot limit exceeded")
        for repo in unique:
            brain._require_repository(repo)
        result["allowed_repositories"] = unique
    else:
        result.setdefault("allowed_repositories", [])
    return result


def _priority(event: dict[str, Any]) -> int:
    if event["source_event_type"] == "pull_request":
        return 350
    if event["source_ref"] in {"refs/heads/main", "refs/heads/master"}:
        return 400
    return 200


def operation_id(
    event: dict[str, Any],
    plan: dict[str, Any],
    applab_sha: str,
) -> str:
    material = {
        "event_id": event["event_id"],
        "repository": event["repository"],
        "source_ref": event["source_ref"],
        "resolved_sha": event["resolved_sha"],
        "analysis_mode": plan["analysis_mode"],
        "plan_digest_sha256": plan["plan_digest_sha256"],
        "applab_sha": applab_sha,
        "operation_class": "VERIFICATION",
    }
    digest = hashlib.sha256(brain.canonical_json(material).encode("utf-8")).hexdigest()
    return "op_" + digest[:32]


def admit(
    event: dict[str, Any],
    plan: dict[str, Any],
    policy: dict[str, Any],
) -> None:
    brain.validate_event(event, brain.load_contract())
    if not bool(policy.get("enabled")):
        raise PilotError("event-driven pilot disabled")
    allowed = set(policy.get("allowed_repositories") or [])
    if event["repository"] not in allowed:
        raise PilotError("repository not allowlisted")
    if event.get("admission") != "ADMITTED":
        raise PilotError("event is not admitted")
    trust = event.get("trust") or {}
    if not all(bool(trust.get(k)) for k in ("signature_verified", "replay_window_valid", "source_authenticated")):
        raise PilotError("event trust is incomplete")
    if not isinstance(plan, dict):
        raise PilotError("authoritative plan missing")
    mode = plan.get("analysis_mode")
    if mode not in set(policy["allowed_analysis_modes"]):
        raise PilotError("analysis mode not allowed by pilot")
    if plan.get("repository") != event["repository"] or plan.get("resolved_sha") != event["resolved_sha"]:
        raise PilotError("plan identity mismatch")
    if not str(plan.get("plan_digest_sha256") or "").startswith("sha256:"):
        raise PilotError("plan digest missing")


def create_or_reuse_operation(
    store: storemod.SQLiteShadowStore,
    event: dict[str, Any],
    plan: dict[str, Any],
    applab_sha: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    admit(event, plan, policy)
    brain._require_sha(applab_sha, "applab_sha")
    op_id = operation_id(event, plan, applab_sha)
    operation = brain._operation_fixture(
        op_id,
        event["repository"],
        event["source_ref"],
        event["resolved_sha"],
        applab_sha,
        operation_class="VERIFICATION",
        analysis_mode=plan["analysis_mode"],
        priority=_priority(event),
    )
    operation["correlation_id"] = event["correlation_id"]
    operation["plan_digest_sha256"] = plan["plan_digest_sha256"]
    operation["source_event_id"] = event["event_id"]
    operation["idempotency_key"] = brain.operation_idempotency_key(operation)
    result = store.put_operation(operation)
    return {
        "operation": operation,
        "persistence_status": result["status"],
        "canonical_operation_id": result["operation_id"],
    }


def enqueue_event_operation(
    store: storemod.SQLiteShadowStore,
    queue: queue_mod.DurablePerRepoQueue,
    event: dict[str, Any],
    plan: dict[str, Any],
    applab_sha: str,
    policy: dict[str, Any],
    *,
    now_ts: float,
    ancestor_shas: set[str] | None = None,
) -> dict[str, Any]:
    persisted = create_or_reuse_operation(store, event, plan, applab_sha, policy)
    op_id = persisted["canonical_operation_id"]
    queued = queue.enqueue(
        op_id,
        ancestor_shas=set(ancestor_shas or set()),
        now_ts=now_ts,
    )
    return {
        "schema_version": 1,
        "record_type": "APPLAB_EVENT_DRIVEN_ADMISSION",
        "authority": "ORCHESTRATION_ONLY",
        "event_id": event["event_id"],
        "operation_id": op_id,
        "operation_persistence": persisted["persistence_status"],
        "queue_status": queued["status"],
        "queue_state": queued["state"],
        "superseded": queued.get("superseded", []),
        "dispatch_performed": False,
    }


def next_executor_intent(
    queue: queue_mod.DurablePerRepoQueue,
    *,
    now_ts: float,
    worker_id: str = "github-actions-adapter",
) -> dict[str, Any] | None:
    claim = queue.claim_next(worker_id, now_ts=now_ts)
    if claim is None:
        return None
    return {
        "schema_version": 1,
        "record_type": "APPLAB_EXECUTOR_INTENT",
        "authority": "ORCHESTRATION_ONLY",
        "executor": "GITHUB_ACTIONS",
        "operation_id": claim["operation_id"],
        "repository": claim["repository"],
        "source_ref": claim["source_ref"],
        "resolved_sha": claim["resolved_sha"],
        "operation_class": claim["operation_class"],
        "dispatch_performed": False,
        "transport_required": True,
    }


def readiness(policy: dict[str, Any]) -> dict[str, Any]:
    external = list(policy.get("external_requirements") or [])
    return {
        "schema_version": 1,
        "record_type": "APPLAB_V54G_READINESS",
        "policy_enabled": bool(policy.get("enabled")),
        "allowed_repository_count": len(policy.get("allowed_repositories") or []),
        "watcher_remains_watchdog": bool(policy.get("watcher_remains_watchdog")),
        "github_actions_fallback": bool(policy.get("github_actions_remains_burst_fallback")),
        "certification_authority_changed": bool(policy.get("certification_authority_changed")),
        "external_requirements": external,
        "activation_ready": bool(policy.get("enabled")) and not external,
    }


def _fixture_event() -> dict[str, Any]:
    return brain._event_fixture(
        "evt_g", "owner/app", "refs/heads/main", "a"*40, "delivery-g"
    )


def _fixture_plan() -> dict[str, Any]:
    return {
        "repository": "owner/app",
        "resolved_sha": "a"*40,
        "analysis_mode": "fast",
        "required_labs": [],
        "plan_digest_sha256": "sha256:" + "1"*64,
    }


def self_test() -> None:
    base = load_policy()
    assert base["enabled"] is False
    assert readiness(base)["activation_ready"] is False
    event = _fixture_event()
    plan = _fixture_plan()
    with tempfile.TemporaryDirectory() as tmp:
        with storemod.SQLiteShadowStore(Path(tmp) / "pilot.sqlite3") as store:
            q = queue_mod.DurablePerRepoQueue(store)
            try:
                enqueue_event_operation(
                    store, q, event, plan, "b"*40, base, now_ts=100
                )
            except PilotError as exc:
                assert "disabled" in str(exc)
            else:
                raise AssertionError("disabled policy unexpectedly admitted event")

            pilot = effective_policy(
                base, enabled=True, allowed_repositories=["owner/app"]
            )
            first = enqueue_event_operation(
                store, q, event, plan, "b"*40, pilot, now_ts=101
            )
            assert first["dispatch_performed"] is False
            second = enqueue_event_operation(
                store, q, event, plan, "b"*40, pilot, now_ts=102
            )
            assert second["operation_id"] == first["operation_id"]
            assert second["operation_persistence"] in {"REPLAY", "IDEMPOTENT_REUSE"}

            intent = next_executor_intent(q, now_ts=103)
            assert intent is not None
            assert intent["executor"] == "GITHUB_ACTIONS"
            assert intent["dispatch_performed"] is False
            assert intent["transport_required"] is True

            denied = effective_policy(
                base, enabled=True, allowed_repositories=["owner/other"]
            )
            try:
                create_or_reuse_operation(store, event, plan, "b"*40, denied)
            except PilotError as exc:
                assert "allowlisted" in str(exc)
            else:
                raise AssertionError("non-allowlisted repository admitted")

    print("AppLab v5.4G controlled pilot readiness self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v5.4G controlled event-driven pilot readiness")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
