#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import durable_brain_v54a as brain

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT / "integration" / "orchestration" / "conductor" / "applab-v54d-shadow-workflow-v1.json"
REFERENCE_SHA = "1488804170d159021c7e62dce61514b8f31ef9ff"
WORKFLOW_VERSION = "applab-v54d-shadow-v1"
PHASES = (
    "validate_identity",
    "consume_plan",
    "model_queue",
    "model_worker",
    "compare_actual",
)


class ShadowError(ValueError):
    pass


def load_workflow(path: Path = WORKFLOW_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("name") != "applab_v54d_shadow_compare":
        raise ShadowError("unexpected shadow workflow name")
    if payload.get("version") != 1 or payload.get("schemaVersion") != 2:
        raise ShadowError("unsupported shadow workflow version")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ShadowError("shadow workflow tasks missing")
    refs = []
    for task in tasks:
        if not isinstance(task, dict):
            raise ShadowError("shadow workflow task must be object")
        name = str(task.get("name") or "")
        ref = str(task.get("taskReferenceName") or "")
        if not name or not ref:
            raise ShadowError("shadow workflow task identity missing")
        if int(task.get("retryCount", 0)) != 0:
            raise ShadowError("shadow workflow tasks must not retry side effects")
        refs.append(ref)
    if tuple(refs) != PHASES:
        raise ShadowError("shadow workflow phase order mismatch")
    metadata = payload.get("metadata") or {}
    if metadata.get("mode") != "SHADOW_NO_DISPATCH":
        raise ShadowError("shadow workflow mode drift")
    if metadata.get("authority") != "NONE":
        raise ShadowError("shadow workflow authority drift")
    if metadata.get("reference_sha") != REFERENCE_SHA:
        raise ShadowError("Conductor reference SHA drift")
    return payload


def workflow_digest(workflow: dict[str, Any]) -> str:
    return brain.sha256_json(workflow)


def normalize_authoritative_plan(
    raw_plan: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(raw_plan, dict):
        raise ShadowError("authoritative_plan must be object")

    # Native Smart Test Plan shape.
    if "selected_labs" in raw_plan or "head_sha" in raw_plan:
        selected = raw_plan.get("selected_labs")
        if not isinstance(selected, dict) or any(
            not isinstance(name, str) or not isinstance(enabled, bool)
            for name, enabled in selected.items()
        ):
            raise ShadowError("authoritative Smart Test Plan selected_labs mismatch")
        repository = str(raw_plan.get("repository") or event["repository"])
        resolved_sha = str(raw_plan.get("head_sha") or "")
        analysis_mode = str(raw_plan.get("mode") or "").lower()
        semantic_plan = dict(raw_plan)
        semantic_plan.pop("planner_ms", None)
        normalized = {
            "repository": repository,
            "resolved_sha": resolved_sha,
            "analysis_mode": analysis_mode,
            "required_labs": sorted(name for name, enabled in selected.items() if enabled),
            "plan_digest_sha256": brain.sha256_json(semantic_plan),
            "lane": raw_plan.get("lane"),
            "planner_version": raw_plan.get("planner_version"),
            "source_shape": "SMART_TEST_PLAN",
        }
    else:
        normalized = dict(raw_plan)
        normalized.setdefault("source_shape", "NORMALIZED")

    for field in (
        "repository",
        "resolved_sha",
        "analysis_mode",
        "required_labs",
        "plan_digest_sha256",
    ):
        if field not in normalized:
            raise ShadowError(f"authoritative_plan missing {field}")
    if normalized["repository"] != event["repository"]:
        raise ShadowError("plan repository identity mismatch")
    brain._require_sha(normalized["resolved_sha"], "authoritative_plan.resolved_sha")
    if normalized["resolved_sha"] != event["resolved_sha"]:
        raise ShadowError("plan source SHA identity mismatch")
    if normalized["analysis_mode"] not in {
        "fast",
        "full",
        "certification",
        "diagnostic",
        "none",
    }:
        raise ShadowError("invalid authoritative analysis_mode")
    labs = normalized["required_labs"]
    if not isinstance(labs, list) or any(
        not isinstance(x, str) or not x for x in labs
    ):
        raise ShadowError("required_labs must be string list")
    if not str(normalized["plan_digest_sha256"]).startswith("sha256:"):
        raise ShadowError("plan digest missing sha256 identity")
    return normalized


def _require_plan(plan: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return normalize_authoritative_plan(plan, event)


def _require_actual(actual: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(actual, dict):
        raise ShadowError("actual_execution must be object")
    for field in ("repository", "resolved_sha", "applab_sha", "analysis_mode", "executed_labs", "terminal_state"):
        if field not in actual:
            raise ShadowError(f"actual_execution missing {field}")
    brain._require_repository(actual["repository"])
    brain._require_sha(actual["resolved_sha"], "actual_execution.resolved_sha")
    brain._require_sha(actual["applab_sha"], "actual_execution.applab_sha")
    if not isinstance(actual["executed_labs"], list):
        raise ShadowError("actual executed_labs must be list")
    return actual


def model_queue(event: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    event_type = event["source_event_type"]
    if plan["analysis_mode"] == "certification":
        operation_class = "CERTIFICATION"
        priority = 500
    elif event_type == "pull_request":
        operation_class = "VERIFICATION"
        priority = 350
    elif event["source_ref"] in {"main", "refs/heads/main", "master", "refs/heads/master"}:
        operation_class = "VERIFICATION"
        priority = 400
    else:
        operation_class = "VERIFICATION"
        priority = 200
    source_ref = event["source_ref"]
    queue_key = "|".join((event["repository"], source_ref, operation_class))
    return {
        "operation_class": operation_class,
        "priority": priority,
        "queue_key": queue_key,
    }


def model_worker(
    actual_applab_sha: str,
    required_runtime_profile: str,
    inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    eligible = []
    for worker in inventory:
        if not isinstance(worker, dict):
            continue
        if worker.get("state") != "AVAILABLE":
            continue
        if worker.get("applab_sha") != actual_applab_sha:
            continue
        profiles = worker.get("runtime_profiles") or []
        if required_runtime_profile not in profiles:
            continue
        eligible.append(worker)
    eligible.sort(key=lambda w: (0 if w.get("worker_class") == "WARM_TRUSTED_ANDROID" else 1, str(w.get("worker_id") or "")))
    if eligible:
        chosen = eligible[0]
        return {
            "worker_model": chosen.get("worker_class"),
            "worker_id": chosen.get("worker_id"),
            "fallback": False,
        }
    return {
        "worker_model": "GITHUB_BURST",
        "worker_id": None,
        "fallback": True,
    }


def input_digest(
    event: dict[str, Any],
    plan: dict[str, Any],
    actual: dict[str, Any],
    inventory: list[dict[str, Any]],
    workflow: dict[str, Any],
) -> str:
    return brain.sha256_json({
        "event": event,
        "plan": plan,
        "actual": actual,
        "inventory": inventory,
        "workflow_digest": workflow_digest(workflow),
        "workflow_version": WORKFLOW_VERSION,
    })


def checkpoint(
    next_phase_index: int,
    digest: str,
    partial: dict[str, Any],
) -> dict[str, Any]:
    if not 0 <= next_phase_index <= len(PHASES):
        raise ShadowError("invalid checkpoint phase")
    return {
        "schema_version": 1,
        "record_type": "APPLAB_CONDUCTOR_SHADOW_CHECKPOINT",
        "authority": "NONE_SHADOW_ONLY",
        "workflow_version": WORKFLOW_VERSION,
        "input_digest_sha256": digest,
        "next_phase_index": next_phase_index,
        "partial": partial,
    }


def _apply_phase(
    partial: dict[str, Any],
    phase: str,
    event: dict[str, Any],
    plan: dict[str, Any],
    actual: dict[str, Any],
    worker_inventory: list[dict[str, Any]],
) -> None:
    if phase == "validate_identity":
        partial["identity"] = {
            "event_repository": event["repository"],
            "event_sha": event["resolved_sha"],
            "actual_repository": actual["repository"],
            "actual_sha": actual["resolved_sha"],
            "repository_match": event["repository"] == actual["repository"],
            "sha_match": event["resolved_sha"] == actual["resolved_sha"],
        }
    elif phase == "consume_plan":
        partial["plan"] = {
            "analysis_mode": plan["analysis_mode"],
            "required_labs": sorted(set(plan["required_labs"])),
            "plan_digest_sha256": plan["plan_digest_sha256"],
        }
    elif phase == "model_queue":
        partial["queue"] = model_queue(event, plan)
    elif phase == "model_worker":
        partial["worker"] = model_worker(
            actual["applab_sha"],
            str(actual.get("runtime_profile") or "android-default"),
            worker_inventory,
        )
    elif phase == "compare_actual":
        required = set(partial["plan"]["required_labs"])
        executed = set(actual["executed_labs"])
        partial["comparison"] = {
            "identity_match": bool(
                partial["identity"]["repository_match"]
                and partial["identity"]["sha_match"]
            ),
            "analysis_mode_match": (
                actual["analysis_mode"] == partial["plan"]["analysis_mode"]
            ),
            "required_labs_all_executed": required.issubset(executed),
            "lab_set_exact_match": required == executed,
            "worker_model_match": (
                actual.get("worker_class") is None
                or actual.get("worker_class")
                == partial["worker"]["worker_model"]
            ),
            "actual_terminal_state": actual["terminal_state"],
        }
    else:
        raise ShadowError(f"unknown shadow phase {phase}")


def _recompute_partial(
    completed_phase_count: int,
    event: dict[str, Any],
    plan: dict[str, Any],
    actual: dict[str, Any],
    worker_inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    if not 0 <= completed_phase_count <= len(PHASES):
        raise ShadowError("invalid checkpoint phase")
    partial: dict[str, Any] = {}
    for phase in PHASES[:completed_phase_count]:
        _apply_phase(partial, phase, event, plan, actual, worker_inventory)
    return partial


def execute_shadow(
    event: dict[str, Any],
    authoritative_plan: dict[str, Any],
    actual_execution: dict[str, Any],
    worker_inventory: list[dict[str, Any]],
    *,
    resume_from: dict[str, Any] | None = None,
    stop_after_phase: int | None = None,
) -> dict[str, Any]:
    workflow = load_workflow()
    brain.validate_event(event, brain.load_contract())
    plan = _require_plan(authoritative_plan, event)
    actual = _require_actual(actual_execution)
    digest = input_digest(event, plan, actual, worker_inventory, workflow)

    partial: dict[str, Any] = {}
    start = 0
    if resume_from is not None:
        if resume_from.get("record_type") != "APPLAB_CONDUCTOR_SHADOW_CHECKPOINT":
            raise ShadowError("invalid checkpoint record")
        if resume_from.get("authority") != "NONE_SHADOW_ONLY":
            raise ShadowError("checkpoint authority drift")
        if resume_from.get("workflow_version") != WORKFLOW_VERSION:
            raise ShadowError("checkpoint workflow version mismatch")
        if resume_from.get("input_digest_sha256") != digest:
            raise ShadowError("checkpoint input digest mismatch")
        start = int(resume_from.get("next_phase_index", -1))
        provided_partial = dict(resume_from.get("partial") or {})
        expected_partial = _recompute_partial(
            start, event, plan, actual, worker_inventory
        )
        if brain.sha256_json(provided_partial) != brain.sha256_json(expected_partial):
            raise ShadowError("checkpoint partial state mismatch")
        partial = expected_partial

    for idx in range(start, len(PHASES)):
        phase = PHASES[idx]
        _apply_phase(partial, phase, event, plan, actual, worker_inventory)

        if stop_after_phase is not None and idx + 1 == stop_after_phase:
            return checkpoint(idx + 1, digest, partial)

    comparison = partial["comparison"]
    return {
        "schema_version": 1,
        "record_type": "APPLAB_CONDUCTOR_SHADOW_COMPARISON",
        "authority": "NONE_SHADOW_ONLY",
        "mode": "SHADOW_NO_DISPATCH",
        "workflow_version": WORKFLOW_VERSION,
        "workflow_digest_sha256": workflow_digest(workflow),
        "conductor_reference_sha": REFERENCE_SHA,
        "input_digest_sha256": digest,
        "repository": event["repository"],
        "resolved_sha": event["resolved_sha"],
        "analysis_mode": plan["analysis_mode"],
        "queue_model": partial["queue"],
        "worker_model": partial["worker"],
        "comparison": comparison,
        "shadow_dag": list(PHASES),
        "dispatch": False,
        "verdict_authority": False,
        "promotion_ready_for_dispatch": bool(
            comparison["identity_match"]
            and comparison["analysis_mode_match"]
            and comparison["required_labs_all_executed"]
        ),
    }


def _fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    event = brain._event_fixture("evt_d", "owner/app", "refs/heads/main", "a" * 40, "delivery-d")
    plan = {
        "repository": "owner/app",
        "resolved_sha": "a" * 40,
        "analysis_mode": "full",
        "required_labs": ["system", "persistence", "visual"],
        "plan_digest_sha256": "sha256:" + "1" * 64,
    }
    actual = {
        "repository": "owner/app",
        "resolved_sha": "a" * 40,
        "applab_sha": "b" * 40,
        "analysis_mode": "full",
        "executed_labs": ["system", "persistence", "visual"],
        "terminal_state": "SUCCEEDED",
        "worker_class": "GITHUB_BURST",
        "runtime_profile": "android-default",
    }
    inventory: list[dict[str, Any]] = []
    return event, plan, actual, inventory


def self_test() -> None:
    event, plan, actual, inventory = _fixture()
    first = execute_shadow(event, plan, actual, inventory)
    second = execute_shadow(event, plan, actual, inventory)
    assert first == second
    assert first["dispatch"] is False
    assert first["verdict_authority"] is False
    assert first["comparison"]["identity_match"] is True
    assert first["comparison"]["required_labs_all_executed"] is True

    for stop in range(1, len(PHASES)):
        cp = execute_shadow(event, plan, actual, inventory, stop_after_phase=stop)
        resumed = execute_shadow(event, plan, actual, inventory, resume_from=cp)
        assert resumed == first

    weaker_actual = dict(actual, executed_labs=["system"])
    mismatch = execute_shadow(event, plan, weaker_actual, inventory)
    assert mismatch["comparison"]["required_labs_all_executed"] is False
    assert mismatch["promotion_ready_for_dispatch"] is False

    wrong_sha = dict(actual, resolved_sha="c" * 40)
    identity = execute_shadow(event, plan, wrong_sha, inventory)
    assert identity["comparison"]["identity_match"] is False
    assert identity["promotion_ready_for_dispatch"] is False

    print("AppLab v5.4D Conductor Shadow Pilot self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v5.4D zero-dispatch shadow comparison")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
