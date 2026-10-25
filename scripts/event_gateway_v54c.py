#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import durable_brain_v54a as brain
import durable_store_v54b as storemod

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = ROOT / "integration" / "orchestration" / "contracts" / "event-gateway-shadow-contract-v1.json"


class GatewayError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise GatewayError("unsupported gateway contract version")
    if payload.get("contract_name") != "APPLAB_EVENT_GATEWAY_SHADOW":
        raise GatewayError("unexpected gateway contract")
    if payload.get("mode") != "SHADOW_NO_DISPATCH" or payload.get("authority") != "NONE":
        raise GatewayError("gateway must remain shadow-only with zero authority")
    return payload


def _utc_epoch(value: str) -> float:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise GatewayError("received_at must include timezone")
    return parsed.timestamp()


def _header(headers: dict[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return str(value)
    raise GatewayError(f"missing required header {name}")


def compute_signature(body: bytes, shared_key: bytes) -> str:
    digest = hmac.new(shared_key, body, hashlib.sha256).hexdigest()
    return "sha256=" + digest


def verify_signature(body: bytes, supplied: str, shared_key: bytes) -> bool:
    if not supplied.startswith("sha256="):
        return False
    expected = compute_signature(body, shared_key)
    return hmac.compare_digest(expected, supplied)


def _require_sha(value: Any, label: str) -> str:
    return brain._require_sha(value, label)


def _repo(payload: dict[str, Any]) -> str:
    repo = payload.get("repository")
    if not isinstance(repo, dict):
        raise GatewayError("payload.repository missing")
    return brain._require_repository(repo.get("full_name"))


def normalize_github_event(
    event_type: str,
    delivery_id: str,
    payload: dict[str, Any],
    received_at: str,
) -> dict[str, Any]:
    repository = _repo(payload)
    if event_type == "push":
        source_ref = brain._require_non_empty_string(payload.get("ref"), "push.ref")
        resolved_sha = _require_sha(payload.get("after"), "push.after")
        previous_sha = str(payload.get("before") or "")
    elif event_type == "pull_request":
        pr = brain._require_dict(payload.get("pull_request"), "pull_request")
        head = brain._require_dict(pr.get("head"), "pull_request.head")
        source_ref = brain._require_non_empty_string(head.get("ref"), "pull_request.head.ref")
        resolved_sha = _require_sha(head.get("sha"), "pull_request.head.sha")
        previous_sha = ""
    elif event_type == "workflow_run":
        run = brain._require_dict(payload.get("workflow_run"), "workflow_run")
        source_ref = brain._require_non_empty_string(run.get("head_branch"), "workflow_run.head_branch")
        resolved_sha = _require_sha(run.get("head_sha"), "workflow_run.head_sha")
        previous_sha = ""
    else:
        raise GatewayError(f"unsupported github event {event_type}")

    identity_material = {
        "provider": "github",
        "delivery_id": delivery_id,
        "event_type": event_type,
    }
    event_id = "evt_" + hashlib.sha256(
        brain.canonical_json(identity_material).encode("utf-8")
    ).hexdigest()[:32]
    correlation_id = "cor_" + hashlib.sha256(
        f"{repository}|{source_ref}|{resolved_sha}".encode("utf-8")
    ).hexdigest()[:32]
    event: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "APPLAB_EVENT",
        "event_id": event_id,
        "correlation_id": correlation_id,
        "source": "github",
        "source_event_type": event_type,
        "source_delivery_id": delivery_id,
        "observed_at": received_at,
        "repository": repository,
        "source_ref": source_ref,
        "resolved_sha": resolved_sha,
        "previous_sha": previous_sha,
        "dedupe_key": "",
        "admission": "ADMITTED",
        "trust": {
            "signature_verified": True,
            "replay_window_valid": True,
            "source_authenticated": True,
        },
    }
    event["dedupe_key"] = brain.event_dedupe_key(event)
    return event


def ingest_github_delivery(
    store: storemod.SQLiteShadowStore,
    headers: dict[str, str],
    body: bytes,
    shared_key: bytes,
    *,
    received_at: str,
    now_epoch: float | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = contract or load_contract()
    if len(body) > int(spec["max_body_bytes"]):
        raise GatewayError("payload exceeds gateway body limit")
    signature = _header(headers, "X-Hub-Signature-256")
    delivery_id = _header(headers, "X-GitHub-Delivery").strip()
    event_type = _header(headers, "X-GitHub-Event").strip()
    if not delivery_id:
        raise GatewayError("github delivery id must not be empty")
    if event_type not in spec["supported_events"]:
        raise GatewayError(f"unsupported github event {event_type}")
    if not verify_signature(body, signature, shared_key):
        raise GatewayError("github signature verification failed")

    receipt_epoch = _utc_epoch(received_at)
    current = time.time() if now_epoch is None else float(now_epoch)
    if abs(current - receipt_epoch) > int(spec["max_receive_skew_seconds"]):
        raise GatewayError("gateway receive window exceeded")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GatewayError("invalid github JSON payload") from exc
    if not isinstance(payload, dict):
        raise GatewayError("github payload must be a JSON object")

    event = normalize_github_event(event_type, delivery_id, payload, received_at)
    brain.validate_event(event, store.brain_contract)
    result = store.put_event(event)
    return {
        "schema_version": 1,
        "mode": "SHADOW_NO_DISPATCH",
        "authority": "NONE",
        "delivery_id": delivery_id,
        "event_type": event_type,
        "event_id": result["event_id"],
        "persistence_status": result["status"],
        "dedupe_key": event["dedupe_key"],
        "repository": event["repository"],
        "source_ref": event["source_ref"],
        "resolved_sha": event["resolved_sha"],
        "dispatch": False,
    }


def compare_reconciliation_snapshot(
    store: storemod.SQLiteShadowStore,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = store.db.execute(
        "SELECT payload_json FROM events ORDER BY created_at ASC, event_id ASC"
    ).fetchall()
    events = [json.loads(row["payload_json"]) for row in rows]
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        if event.get("admission") != "ADMITTED":
            continue
        key = (event["repository"], event["source_ref"])
        latest[key] = event

    matched: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    stale: list[dict[str, str]] = []
    for raw in observations:
        repository = brain._require_repository(raw.get("repository"))
        source_ref = brain._require_non_empty_string(raw.get("source_ref"), "snapshot.source_ref")
        resolved_sha = _require_sha(raw.get("resolved_sha"), "snapshot.resolved_sha")
        key = (repository, source_ref)
        event = latest.get(key)
        record = {
            "repository": repository,
            "source_ref": source_ref,
            "resolved_sha": resolved_sha,
        }
        if event is None:
            missing.append(record)
        elif event["resolved_sha"] == resolved_sha:
            matched.append(record)
        else:
            stale.append(
                {
                    **record,
                    "latest_event_sha": event["resolved_sha"],
                }
            )
    return {
        "schema_version": 1,
        "mode": "SHADOW_NO_DISPATCH",
        "authority": "NONE",
        "matched": matched,
        "missing": missing,
        "stale": stale,
        "all_current": not missing and not stale,
        "dispatch": False,
    }


def _push_payload(repository: str, ref: str, before: str, after: str) -> dict[str, Any]:
    return {
        "ref": ref,
        "before": before,
        "after": after,
        "repository": {"full_name": repository},
        "head_commit": {"id": after},
    }


def _headers(event_type: str, delivery_id: str, body: bytes, key: bytes) -> dict[str, str]:
    return {
        "X-Hub-Signature-256": compute_signature(body, key),
        "X-GitHub-Delivery": delivery_id,
        "X-GitHub-Event": event_type,
    }


def self_test() -> None:
    contract = load_contract()
    key = b"applab-v54c-self-test-key"
    now = datetime(2026, 10, 25, 2, 30, tzinfo=timezone.utc)
    now_text = now.isoformat().replace("+00:00", "Z")
    target = "a" * 40
    previous = "b" * 40
    payload = _push_payload("owner/app", "refs/heads/main", previous, target)
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = _headers("push", "delivery-1", body, key)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "gateway-shadow.sqlite3"
        with storemod.SQLiteShadowStore(db_path) as store:
            first = ingest_github_delivery(
                store, headers, body, key,
                received_at=now_text, now_epoch=now.timestamp(), contract=contract
            )
            assert first["persistence_status"] == "INSERTED"
            assert first["dispatch"] is False

            replay = ingest_github_delivery(
                store, headers, body, key,
                received_at=now_text, now_epoch=now.timestamp(), contract=contract
            )
            assert replay["persistence_status"] == "REPLAY"

            second_headers = _headers("push", "delivery-2", body, key)
            redelivery = ingest_github_delivery(
                store, second_headers, body, key,
                received_at=now_text, now_epoch=now.timestamp(), contract=contract
            )
            assert redelivery["persistence_status"] == "DEDUPED"
            assert redelivery["event_id"] == first["event_id"]

            bad = dict(headers)
            bad["X-Hub-Signature-256"] = "sha256=" + "0" * 64
            try:
                ingest_github_delivery(
                    store, bad, body, key,
                    received_at=now_text, now_epoch=now.timestamp(), contract=contract
                )
            except GatewayError as exc:
                assert "signature" in str(exc)
            else:
                raise AssertionError("invalid signature unexpectedly accepted")

            stale_time = datetime(2026, 10, 25, 2, 0, tzinfo=timezone.utc)
            try:
                ingest_github_delivery(
                    store, headers, body, key,
                    received_at=stale_time.isoformat().replace("+00:00", "Z"),
                    now_epoch=now.timestamp(),
                    contract=contract,
                )
            except GatewayError as exc:
                assert "receive window" in str(exc)
            else:
                raise AssertionError("stale gateway receipt unexpectedly accepted")

            snapshot = compare_reconciliation_snapshot(
                store,
                [
                    {
                        "repository": "owner/app",
                        "source_ref": "refs/heads/main",
                        "resolved_sha": target,
                    },
                    {
                        "repository": "owner/other",
                        "source_ref": "refs/heads/main",
                        "resolved_sha": "c" * 40,
                    },
                ],
            )
            assert len(snapshot["matched"]) == 1
            assert len(snapshot["missing"]) == 1
            assert snapshot["stale"] == []
            assert snapshot["all_current"] is False
            assert snapshot["dispatch"] is False

        with storemod.SQLiteShadowStore(db_path) as reopened:
            persisted = compare_reconciliation_snapshot(
                reopened,
                [{
                    "repository": "owner/app",
                    "source_ref": "refs/heads/main",
                    "resolved_sha": target,
                }],
            )
            assert persisted["all_current"] is True

    print("AppLab v5.4C Event Gateway Shadow self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v5.4C shadow GitHub event gateway")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
