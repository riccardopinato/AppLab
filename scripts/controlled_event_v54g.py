#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import durable_brain_v54a as brain
import durable_queue_v54e as queue_mod
import durable_store_v54b as storemod

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = ROOT / "integration" / "orchestration" / "contracts" / "controlled-event-pilot-v1.json"
DEFAULT_CONFIG = ROOT / "integration" / "orchestration" / "v54g-pilot.json"

QUEUE_LIMITS = {
    "max_ready_global": 2,
    "max_ready_per_repo": 1,
    "max_pending_global": 8,
    "max_pending_per_repo": 4,
    "max_active_global": 1,
    "max_active_per_repo": 1,
    "lease_seconds": 3600,
    "retry_base_seconds": 60,
    "max_age_bonus": 20,
}


class PilotError(ValueError):
    pass


def _bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    raise PilotError(f"invalid boolean: {value!r}")


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise PilotError("unsupported controlled-pilot contract version")
    if payload.get("contract_name") != "APPLAB_CONTROLLED_EVENT_DRIVEN_PILOT":
        raise PilotError("unexpected controlled-pilot contract")
    if payload.get("authority") != "ORCHESTRATION_ONLY":
        raise PilotError("controlled pilot authority drift")
    if payload.get("certification_authority_changed") is not False:
        raise PilotError("certification authority must remain unchanged")
    return payload


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise PilotError("unsupported pilot config version")
    if not isinstance(payload.get("enabled"), bool):
        raise PilotError("pilot enabled must be boolean")
    if not isinstance(payload.get("kill_switch"), bool):
        raise PilotError("pilot kill_switch must be boolean")
    targets = payload.get("pilot_targets")
    if not isinstance(targets, list) or not targets:
        raise PilotError("pilot_targets must be a non-empty list")
    if int(payload.get("max_live_operations_per_event", 0)) != 1:
        raise PilotError("v5.4G canary must allow exactly one live operation per event")
    seen: set[tuple[str, str]] = set()
    for item in targets:
        if not isinstance(item, dict):
            raise PilotError("pilot target must be object")
        repository = brain._require_repository(item.get("repository"))
        source_ref = brain._require_non_empty_string(item.get("source_ref"), "target.source_ref")
        key = (repository, source_ref)
        if key in seen:
            raise PilotError("duplicate pilot target")
        seen.add(key)
        events = item.get("event_types")
        if not isinstance(events, list) or "push" not in events:
            raise PilotError("pilot target must explicitly allow push")
        if item.get("analysis_mode") != "fast":
            raise PilotError("controlled canary must request fast; Smart Test Plan may escalate")
        if item.get("engine") != "native_android":
            raise PilotError("initial v5.4G canary is native_android only")
    return payload


def _target_for(
    config: dict[str, Any],
    repository: str,
    source_ref: str,
    event_type: str,
) -> dict[str, Any] | None:
    for target in config["pilot_targets"]:
        if (
            target["repository"] == repository
            and target["source_ref"] == source_ref
            and event_type in target["event_types"]
        ):
            return target
    return None


def _event_id(repository: str, delivery_id: str) -> str:
    raw = f"github-actions-platform|{repository}|{delivery_id}"
    return "evt_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _correlation_id(repository: str, source_ref: str, sha: str) -> str:
    raw = f"{repository}|{source_ref}|{sha}"
    return "cor_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def platform_push_event(
    repository: str,
    source_ref: str,
    resolved_sha: str,
    delivery_id: str,
) -> dict[str, Any]:
    event = {
        "schema_version": 1,
        "record_type": "APPLAB_EVENT",
        "event_id": _event_id(repository, delivery_id),
        "correlation_id": _correlation_id(repository, source_ref, resolved_sha),
        "source": "github_actions_platform",
        "source_event_type": "push",
        "source_delivery_id": delivery_id,
        "repository": repository,
        "source_ref": source_ref,
        "resolved_sha": resolved_sha,
        "dedupe_key": "",
        "admission": "ADMITTED",
        "trust": {
            # The Actions event is admitted by GitHub's own authenticated event
            # delivery boundary. Raw webhook HMAC remains the v5.4C adapter path.
            "signature_verified": True,
            "replay_window_valid": True,
            "source_authenticated": True,
        },
        "trust_attestation": {
            "method": "GITHUB_ACTIONS_PLATFORM_EVENT",
            "raw_webhook_hmac_observed_by_applab": False,
        },
    }
    event["dedupe_key"] = brain.event_dedupe_key(event)
    return event


def _operation(
    event: dict[str, Any],
    applab_sha: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    identity = {
        "repository": event["repository"],
        "source_ref": event["source_ref"],
        "resolved_sha": event["resolved_sha"],
        "applab_sha": applab_sha,
        "operation_class": "VERIFICATION",
        "contract": contract["contract_name"],
    }
    operation_id = "op_" + hashlib.sha256(
        brain.canonical_json(identity).encode("utf-8")
    ).hexdigest()[:32]
    operation = {
        "schema_version": 1,
        "record_type": "APPLAB_OPERATION",
        "operation_id": operation_id,
        "correlation_id": event["correlation_id"],
        "operation_class": "VERIFICATION",
        "analysis_mode": "fast",
        "repository": event["repository"],
        "source_ref": event["source_ref"],
        "resolved_sha": event["resolved_sha"],
        "applab_sha": applab_sha,
        "contract_fingerprint": brain.sha256_json(contract),
        # Smart Test Plan remains authoritative and computes the real plan inside
        # the trusted runner. The control plane must not invent that digest here.
        "plan_digest_sha256": "",
        "force_generation": 0,
        "idempotency_key": "",
        "queue_key": "",
        "priority": 400,
        "state": "QUEUED",
        "authority": "ORCHESTRATION_ONLY",
    }
    operation["queue_key"] = brain.operation_queue_key(operation)
    operation["idempotency_key"] = brain.operation_idempotency_key(operation)
    return operation


def _transition(
    operation_id: str,
    index: int,
    from_state: str,
    to_state: str,
    reason: str,
) -> dict[str, Any]:
    metadata = {
        "operation_id": operation_id,
        "from_state": from_state,
        "to_state": to_state,
        "reason": reason,
        "sequence_hint": index,
    }
    return {
        "schema_version": 1,
        "record_type": "APPLAB_OPERATION_TRANSITION",
        "transition_id": f"trn_{operation_id}_{index}",
        "operation_id": operation_id,
        "from_state": from_state,
        "to_state": to_state,
        "reason_code": reason,
        "actor": "v54g-controlled-event-pilot",
        "occurred_at": "2026-10-25T00:00:00Z",
        "metadata_digest_sha256": brain.sha256_json(metadata),
    }


def _write_outputs(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    lines: list[str] = []
    for key, value in payload.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif value is None:
            rendered = ""
        elif isinstance(value, (dict, list)):
            rendered = json.dumps(value, separators=(",", ":"), sort_keys=True)
        else:
            rendered = str(value)
        if "\n" in rendered or "\r" in rendered:
            raise PilotError(f"github output {key} contains newline")
        lines.append(f"{key}={rendered}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def admit(
    *,
    db_path: Path,
    config_path: Path,
    repository: str,
    source_ref: str,
    resolved_sha: str,
    applab_sha: str,
    delivery_id: str,
    live_requested: bool,
) -> dict[str, Any]:
    contract = load_contract()
    config = load_config(config_path)
    repository = brain._require_repository(repository)
    source_ref = brain._require_non_empty_string(source_ref, "source_ref")
    resolved_sha = brain._require_sha(resolved_sha, "resolved_sha")
    applab_sha = brain._require_sha(applab_sha, "applab_sha")
    delivery_id = brain._require_non_empty_string(delivery_id, "delivery_id")

    target = _target_for(config, repository, source_ref, "push")
    if target is None:
        return {
            "schema_version": 1,
            "record_type": "APPLAB_V54G_ADMISSION",
            "admitted": False,
            "live": False,
            "dispatch": False,
            "reason": "NOT_ALLOWLISTED",
            "repository": repository,
            "source_ref": source_ref,
            "resolved_sha": resolved_sha,
        }

    live = bool(
        live_requested
        and config["enabled"]
        and not config["kill_switch"]
    )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with storemod.SQLiteShadowStore(db_path) as store:
        event = platform_push_event(
            repository,
            source_ref,
            resolved_sha,
            delivery_id,
        )
        brain.validate_event(event, store.brain_contract)
        event_result = store.put_event(event)

        operation = _operation(event, applab_sha, contract)
        operation_result = store.put_operation(operation)

        queue = queue_mod.DurablePerRepoQueue(store, **QUEUE_LIMITS)
        queue_result = queue.enqueue(operation["operation_id"], now_ts=1.0)

        worker_id = f"gha-v54g-{delivery_id}".replace(":", "-")
        claim: dict[str, Any] | None = None
        if live and queue_result["state"] == "QUEUED":
            claim = queue.claim_next(worker_id, now_ts=2.0)
            if claim is not None and claim["operation_id"] == operation["operation_id"]:
                # Planning is delegated to the existing trusted runner. This state
                # transition records dispatch preparation only; it is not a plan verdict.
                store.transition_operation(
                    _transition(
                        operation["operation_id"],
                        1,
                        "QUEUED",
                        "PLANNING",
                        "TRUSTED_RUNNER_DISPATCH_PREPARED",
                    )
                )

        dispatch = bool(
            live
            and claim is not None
            and claim.get("operation_id") == operation["operation_id"]
            and claim.get("executor") == "GITHUB_ACTIONS"
        )

        report = {
            "schema_version": 1,
            "record_type": "APPLAB_V54G_ADMISSION",
            "authority": "ORCHESTRATION_ONLY",
            "admitted": True,
            "live": live,
            "dispatch": dispatch,
            "reason": (
                "LIVE_CANARY_DISPATCH"
                if dispatch
                else "DRY_RUN"
                if not live
                else "ALREADY_HANDLED_OR_NO_QUEUE_CAPACITY"
            ),
            "repository": repository,
            "source_ref": source_ref,
            "resolved_sha": resolved_sha,
            "applab_sha": applab_sha,
            "event_id": event["event_id"],
            "event_persistence": event_result["status"],
            "operation_id": operation_result["operation_id"],
            "operation_persistence": operation_result["status"],
            "queue_state": queue._entry(operation["operation_id"])["state"],
            "worker_id": worker_id if dispatch else "",
            "executor": "GITHUB_ACTIONS" if dispatch else "",
            "watchdog": "HOURLY_REPO_WATCHER",
            "certification_authority_changed": False,
            "ledger_authority": config["ledger_authority"],
            "target": target,
            "integrity": queue.integrity_report(),
        }
        if not report["integrity"]["ok"]:
            raise PilotError(f"queue integrity failure: {report['integrity']}")
        return report


def _advance_to_running(
    store: storemod.SQLiteShadowStore,
    operation_id: str,
) -> None:
    current = store.get_operation(operation_id)["current_state"]
    sequence = len(store.list_transitions(operation_id)) + 1
    path = {
        "QUEUED": ("PLANNING", "RUNNER_JOB_OBSERVED"),
        "PLANNING": ("READY", "SMART_TEST_PLAN_DELEGATED"),
        "READY": ("RUNNING", "TRUSTED_RUNNER_EXECUTED"),
    }
    while current in path:
        next_state, reason = path[current]
        store.transition_operation(
            _transition(operation_id, sequence, current, next_state, reason)
        )
        sequence += 1
        current = next_state


def finalize(
    *,
    db_path: Path,
    operation_id: str,
    worker_id: str,
    job_result: str,
) -> dict[str, Any]:
    operation_id = brain._require_non_empty_string(operation_id, "operation_id")
    worker_id = brain._require_non_empty_string(worker_id, "worker_id")
    normalized = str(job_result).strip().lower()
    if normalized not in {"success", "failure", "cancelled", "skipped"}:
        raise PilotError(f"unsupported verification job result {job_result!r}")

    with storemod.SQLiteShadowStore(db_path) as store:
        queue = queue_mod.DurablePerRepoQueue(store, **QUEUE_LIMITS)
        entry = queue._entry(operation_id)
        if entry is None:
            raise PilotError("finalize references missing queue operation")
        if entry["state"] != "LEASED":
            raise PilotError("finalize requires active queue lease")
        if entry["leased_by"] != worker_id:
            raise PilotError("finalize worker/lease ownership mismatch")

        _advance_to_running(store, operation_id)
        current = store.get_operation(operation_id)["current_state"]
        if current != "RUNNING":
            raise PilotError(f"operation did not reach RUNNING: {current}")

        attempt_count = int(
            store.db.execute(
                "SELECT COUNT(*) AS n FROM attempts WHERE operation_id=?",
                (operation_id,),
            ).fetchone()["n"]
        )
        success = normalized == "success"
        attempt = {
            "schema_version": 1,
            "record_type": "APPLAB_ATTEMPT",
            "attempt_id": f"att_{operation_id}_{attempt_count + 1}",
            "operation_id": operation_id,
            "attempt_number": attempt_count + 1,
            "executor": "GITHUB_ACTIONS",
            "state": "SUCCEEDED" if success else "FAILED",
            "failure_class": "NONE" if success else "UNKNOWN_FAILURE",
            "retryable": False,
        }
        store.put_attempt(attempt)

        sequence = len(store.list_transitions(operation_id)) + 1
        if success:
            queue.complete(operation_id, worker_id, now_ts=10.0)
            store.transition_operation(
                _transition(
                    operation_id,
                    sequence,
                    "RUNNING",
                    "SUCCEEDED",
                    "TRUSTED_RUNNER_JOB_SUCCEEDED",
                )
            )
            terminal = "SUCCEEDED"
            watchdog_required = False
        else:
            queue.record_failure(
                operation_id,
                worker_id,
                "UNKNOWN_FAILURE",
                retryable=False,
                now_ts=10.0,
            )
            store.transition_operation(
                _transition(
                    operation_id,
                    sequence,
                    "RUNNING",
                    "FAILED",
                    "TRUSTED_RUNNER_JOB_FAILED",
                )
            )
            terminal = "FAILED"
            watchdog_required = True

        queue_integrity = queue.integrity_report()
        if not queue_integrity["ok"]:
            raise PilotError(f"queue integrity failure after finalize: {queue_integrity}")

        return {
            "schema_version": 1,
            "record_type": "APPLAB_V54G_FINAL",
            "authority": "ORCHESTRATION_ONLY",
            "operation_id": operation_id,
            "attempt_id": attempt["attempt_id"],
            "verification_job_result": normalized,
            "operation_terminal_state": terminal,
            "queue_state": queue._entry(operation_id)["state"],
            "watchdog_required": watchdog_required,
            "watchdog": "HOURLY_REPO_WATCHER",
            "certification_authority_changed": False,
            "queue_integrity": queue_integrity,
        }


def self_test() -> None:
    import tempfile

    contract = load_contract()
    assert contract["certification_authority_changed"] is False
    config = load_config()
    assert config["enabled"] is True
    assert config["kill_switch"] is False
    target = config["pilot_targets"][0]

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "v54g.sqlite3"

        dry = admit(
            db_path=db_path,
            config_path=DEFAULT_CONFIG,
            repository=target["repository"],
            source_ref=target["source_ref"],
            resolved_sha="a" * 40,
            applab_sha="b" * 40,
            delivery_id="dry-1",
            live_requested=False,
        )
        assert dry["admitted"] is True
        assert dry["live"] is False
        assert dry["dispatch"] is False

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "v54g-live.sqlite3"
        live = admit(
            db_path=db_path,
            config_path=DEFAULT_CONFIG,
            repository=target["repository"],
            source_ref=target["source_ref"],
            resolved_sha="c" * 40,
            applab_sha="d" * 40,
            delivery_id="live-1",
            live_requested=True,
        )
        assert live["dispatch"] is True
        final = finalize(
            db_path=db_path,
            operation_id=live["operation_id"],
            worker_id=live["worker_id"],
            job_result="success",
        )
        assert final["operation_terminal_state"] == "SUCCEEDED"
        assert final["queue_state"] == "DONE"

        replay = admit(
            db_path=db_path,
            config_path=DEFAULT_CONFIG,
            repository=target["repository"],
            source_ref=target["source_ref"],
            resolved_sha="c" * 40,
            applab_sha="d" * 40,
            delivery_id="live-2",
            live_requested=True,
        )
        assert replay["event_persistence"] == "DEDUPED"
        assert replay["dispatch"] is False

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "v54g-fail.sqlite3"
        live = admit(
            db_path=db_path,
            config_path=DEFAULT_CONFIG,
            repository=target["repository"],
            source_ref=target["source_ref"],
            resolved_sha="e" * 40,
            applab_sha="f" * 40,
            delivery_id="fail-1",
            live_requested=True,
        )
        final = finalize(
            db_path=db_path,
            operation_id=live["operation_id"],
            worker_id=live["worker_id"],
            job_result="failure",
        )
        assert final["operation_terminal_state"] == "FAILED"
        assert final["queue_state"] == "BLOCKED"
        assert final["watchdog_required"] is True

    not_allowed = admit(
        db_path=Path(tmp) / "noop.sqlite3",
        config_path=DEFAULT_CONFIG,
        repository="owner/not-allowed",
        source_ref="refs/heads/main",
        resolved_sha="1" * 40,
        applab_sha="2" * 40,
        delivery_id="nope",
        live_requested=True,
    )
    assert not_allowed["admitted"] is False
    assert not_allowed["dispatch"] is False

    print("AppLab v5.4G Controlled Event-Driven Pilot self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v5.4G controlled event-driven pilot")
    sub = parser.add_subparsers(dest="command", required=True)

    admit_p = sub.add_parser("admit")
    admit_p.add_argument("--db", required=True)
    admit_p.add_argument("--config", default=str(DEFAULT_CONFIG))
    admit_p.add_argument("--repository", required=True)
    admit_p.add_argument("--source-ref", required=True)
    admit_p.add_argument("--resolved-sha", required=True)
    admit_p.add_argument("--applab-sha", required=True)
    admit_p.add_argument("--delivery-id", required=True)
    admit_p.add_argument("--live-requested", default="false")
    admit_p.add_argument("--output", required=True)
    admit_p.add_argument("--github-output", default="")

    final_p = sub.add_parser("finalize")
    final_p.add_argument("--db", required=True)
    final_p.add_argument("--operation-id", required=True)
    final_p.add_argument("--worker-id", required=True)
    final_p.add_argument("--job-result", required=True)
    final_p.add_argument("--output", required=True)

    sub.add_parser("self-test")

    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    if args.command == "admit":
        report = admit(
            db_path=Path(args.db),
            config_path=Path(args.config),
            repository=args.repository,
            source_ref=args.source_ref,
            resolved_sha=args.resolved_sha,
            applab_sha=args.applab_sha,
            delivery_id=args.delivery_id,
            live_requested=_bool(args.live_requested),
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        target = report.get("target") or {}
        outputs = {
            "admitted": bool(report.get("admitted")),
            "live": bool(report.get("live")),
            "dispatch": bool(report.get("dispatch")),
            "operation_id": report.get("operation_id", ""),
            "worker_id": report.get("worker_id", ""),
            "repository": target.get("repository", ""),
            "target_sha": report.get("resolved_sha", ""),
            "source_ref": report.get("source_ref", ""),
            "working_directory": target.get("working_directory", ""),
            "java_version": target.get("java_version", ""),
            "gradle_version": target.get("gradle_version", ""),
            "compile_sdk": target.get("compile_sdk", ""),
            "build_tools": target.get("build_tools", ""),
            "build_command": target.get("build_command", ""),
            "apk_path": target.get("apk_path", ""),
            "package_id": target.get("package_id", ""),
            "api_level": target.get("api_level", ""),
            "emulator_profile": target.get("emulator_profile", ""),
            "run_maestro": bool(target.get("run_maestro", False)),
            "history_key": target.get("history_key", ""),
            "analysis_mode": target.get("analysis_mode", ""),
        }
        _write_outputs(Path(args.github_output) if args.github_output else None, outputs)
        return 0

    report = finalize(
        db_path=Path(args.db),
        operation_id=args.operation_id,
        worker_id=args.worker_id,
        job_result=args.job_result,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
