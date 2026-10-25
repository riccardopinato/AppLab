from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

import sys

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import conductor_shadow_v54d as shadow  # noqa: E402
import controlled_event_v54g as pilot  # noqa: E402
import durable_brain_v54a as brain  # noqa: E402
import durable_queue_v54e as queue_mod  # noqa: E402
import durable_store_v54b as storemod  # noqa: E402
import event_gateway_v54c as event_gateway  # noqa: E402


app = FastAPI(title="AppLab v5.4G Event Gateway", version="5.4G-pilot")


def enabled() -> bool:
    return os.getenv("APPLAB_V54G_ENABLED", "false").strip().lower() == "true"


def env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(status_code=503, detail=f"{name} is not configured")
    return value


def store_path() -> Path:
    raw = os.getenv("APPLAB_V54G_STORE_PATH", "/data/v54g.sqlite3").strip()
    path = Path(raw)
    if not path.is_absolute():
        raise HTTPException(status_code=503, detail="APPLAB_V54G_STORE_PATH must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def allowlist() -> dict[str, set[str]]:
    raw = env_required("APPLAB_V54G_PILOT_ALLOWLIST")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail="pilot allowlist is invalid JSON") from exc
    try:
        return pilot.normalize_allowlist(payload)
    except (pilot.PilotError, brain.ContractError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime | None = None) -> str:
    current = value or utc_now()
    return current.isoformat().replace("+00:00", "Z")


def body_signature(body: bytes, secret: bytes) -> str:
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def verify_body_signature(body: bytes, supplied: str, secret: bytes) -> None:
    expected = body_signature(body, secret)
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="pilot request signature verification failed")


def ensure_dispatch_tables(store: storemod.SQLiteShadowStore) -> None:
    store.db.executescript(
        """
        CREATE TABLE IF NOT EXISTS v54g_dispatches (
            event_id TEXT PRIMARY KEY,
            payload_digest_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS v54g_dispatch_history (
            history_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            occurred_at REAL NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE TRIGGER IF NOT EXISTS v54g_dispatch_history_no_update
        BEFORE UPDATE ON v54g_dispatch_history
        BEGIN
            SELECT RAISE(ABORT, 'v54g_dispatch_history append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS v54g_dispatch_history_no_delete
        BEFORE DELETE ON v54g_dispatch_history
        BEGIN
            SELECT RAISE(ABORT, 'v54g_dispatch_history append-only');
        END;
        """
    )
    store.db.commit()


def event_from_store(store: storemod.SQLiteShadowStore, event_id: str) -> dict[str, Any]:
    row = store.db.execute(
        "SELECT payload_json FROM events WHERE event_id=?",
        (event_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=409, detail="durable event is missing")
    return json.loads(row["payload_json"])


def dispatch_github(payload: dict[str, Any]) -> None:
    token = env_required("APPLAB_V54G_GITHUB_TOKEN")
    repository = os.getenv("APPLAB_V54G_APPLAB_REPOSITORY", "riccardopinato/AppLab").strip()
    brain._require_repository(repository)
    url = f"https://api.github.com/repos/{repository}/dispatches"
    body = json.dumps(
        {
            "event_type": "applab-v54g-event",
            "client_payload": payload,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "AppLab-v5.4G-Gateway/1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status not in {200, 201, 202, 204}:
                raise RuntimeError(f"unexpected GitHub dispatch status {response.status}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub dispatch HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("GitHub dispatch network error") from exc


def dispatch_once(
    store: storemod.SQLiteShadowStore,
    event: dict[str, Any],
    *,
    now_ts: float,
) -> dict[str, Any]:
    ensure_dispatch_tables(store)
    authorized = pilot.authorize_event(event, allowlist())
    dispatch_secret = env_required("APPLAB_V54G_DISPATCH_SECRET").encode("utf-8")
    payload = pilot.dispatch_payload(
        authorized,
        dispatch_secret,
        gateway_event_id=event["event_id"],
    )
    digest = brain.sha256_json(payload)

    try:
        store.db.execute("BEGIN IMMEDIATE")
        row = store.db.execute(
            "SELECT * FROM v54g_dispatches WHERE event_id=?",
            (event["event_id"],),
        ).fetchone()
        if row is not None and row["payload_digest_sha256"] != digest:
            raise HTTPException(status_code=409, detail="dispatch payload identity conflict")
        if row is not None and row["status"] == "DISPATCHED":
            store.db.commit()
            return {
                "status": "REPLAY",
                "event_id": event["event_id"],
                "dispatch_performed": False,
            }
        attempts = 1 if row is None else int(row["attempt_count"]) + 1
        if attempts > 3:
            raise HTTPException(status_code=503, detail="dispatch retry budget exhausted")
        store.db.execute(
            """
            INSERT INTO v54g_dispatches(
                event_id,payload_digest_sha256,status,attempt_count,last_error,updated_at
            ) VALUES (?,?,?,?,NULL,?)
            ON CONFLICT(event_id) DO UPDATE SET
                status='DISPATCHING',
                attempt_count=excluded.attempt_count,
                last_error=NULL,
                updated_at=excluded.updated_at
            """,
            (event["event_id"], digest, "DISPATCHING", attempts, float(now_ts)),
        )
        store.db.execute(
            """
            INSERT INTO v54g_dispatch_history(
                event_id,action,status,occurred_at,payload_json
            ) VALUES (?,?,?,?,?)
            """,
            (
                event["event_id"],
                "DISPATCH_ATTEMPT",
                "DISPATCHING",
                float(now_ts),
                brain.canonical_json({"attempt": attempts}),
            ),
        )
        store.db.commit()
    except Exception:
        if store.db.in_transaction:
            store.db.rollback()
        raise

    try:
        dispatch_github(payload)
    except Exception as exc:
        with store.db:
            store.db.execute(
                """
                UPDATE v54g_dispatches
                SET status='FAILED',last_error=?,updated_at=?
                WHERE event_id=?
                """,
                (type(exc).__name__, float(time.time()), event["event_id"]),
            )
            store.db.execute(
                """
                INSERT INTO v54g_dispatch_history(
                    event_id,action,status,occurred_at,payload_json
                ) VALUES (?,?,?,?,?)
                """,
                (
                    event["event_id"],
                    "DISPATCH_RESULT",
                    "FAILED",
                    float(time.time()),
                    brain.canonical_json({"error_class": type(exc).__name__}),
                ),
            )
        raise HTTPException(status_code=503, detail="GitHub executor dispatch failed") from exc

    with store.db:
        store.db.execute(
            """
            UPDATE v54g_dispatches
            SET status='DISPATCHED',last_error=NULL,updated_at=?
            WHERE event_id=?
            """,
            (float(time.time()), event["event_id"]),
        )
        store.db.execute(
            """
            INSERT INTO v54g_dispatch_history(
                event_id,action,status,occurred_at,payload_json
            ) VALUES (?,?,?,?,?)
            """,
            (
                event["event_id"],
                "DISPATCH_RESULT",
                "DISPATCHED",
                float(time.time()),
                "{}",
            ),
        )
    return {
        "status": "DISPATCHED",
        "event_id": event["event_id"],
        "dispatch_performed": True,
    }


def transition_record(
    transition_id: str,
    operation_id: str,
    from_state: str,
    to_state: str,
    reason: str,
) -> dict[str, Any]:
    metadata = {
        "operation_id": operation_id,
        "from_state": from_state,
        "to_state": to_state,
        "reason_code": reason,
    }
    return {
        "schema_version": 1,
        "record_type": "APPLAB_OPERATION_TRANSITION",
        "transition_id": transition_id,
        "operation_id": operation_id,
        "from_state": from_state,
        "to_state": to_state,
        "reason_code": reason,
        "actor": "v54g-gateway",
        "occurred_at": utc_text(),
        "metadata_digest_sha256": brain.sha256_json(metadata),
    }


def advance_operation(
    store: storemod.SQLiteShadowStore,
    operation_id: str,
    transitions: list[tuple[str, str, str]],
) -> None:
    for index, (from_state, to_state, reason) in enumerate(transitions, start=1):
        raw = f"{operation_id}|{from_state}|{to_state}|{reason}|{index}"
        transition_id = "trn_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
        record = transition_record(
            transition_id,
            operation_id,
            from_state,
            to_state,
            reason,
        )
        store.transition_operation(record)


class AuthorizeRequest(BaseModel):
    dispatch: dict[str, Any]
    plan: dict[str, Any]
    applab_sha: str
    run_id: str


class CallbackRequest(BaseModel):
    operation_id: str
    run_id: str
    conclusion: str
    failure_class: str = "UNKNOWN_FAILURE"


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "applab-v54g-gateway",
        "enabled": enabled(),
        "authority": "ORCHESTRATION_ONLY",
    }


@app.post("/github-webhook")
async def github_webhook(request: Request) -> dict[str, Any]:
    if not enabled():
        raise HTTPException(status_code=503, detail="v5.4G pilot is disabled")
    body = await request.body()
    headers = {key: value for key, value in request.headers.items()}
    now = utc_now()
    with storemod.SQLiteShadowStore(store_path()) as store:
        try:
            ingested = event_gateway.ingest_github_delivery(
                store,
                headers,
                body,
                env_required("APPLAB_V54G_WEBHOOK_SECRET").encode("utf-8"),
                received_at=utc_text(now),
                now_epoch=now.timestamp(),
            )
        except (event_gateway.GatewayError, brain.ContractError, storemod.StoreError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        event = event_from_store(store, ingested["event_id"])
        if ingested["persistence_status"] in {"INSERTED", "REPLAY", "DEDUPED"}:
            dispatched = dispatch_once(store, event, now_ts=now.timestamp())
        else:
            dispatched = {
                "status": "NOT_DISPATCHED",
                "event_id": event["event_id"],
                "dispatch_performed": False,
            }
        return {
            "ingest": ingested,
            "dispatch": dispatched,
            "verdict_authority": False,
        }


@app.post("/authorize")
async def authorize_execution(
    request: Request,
    x_applab_pilot_signature: str = Header(default=""),
) -> dict[str, Any]:
    if not enabled():
        raise HTTPException(status_code=503, detail="v5.4G pilot is disabled")
    raw = await request.body()
    secret = env_required("APPLAB_V54G_DISPATCH_SECRET").encode("utf-8")
    verify_body_signature(raw, x_applab_pilot_signature, secret)
    try:
        payload = AuthorizeRequest.model_validate_json(raw)
        pilot.verify_dispatch_payload(payload.dispatch, secret)
        applab_sha = brain._require_sha(payload.applab_sha, "authorize.applab_sha")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid authorization payload") from exc

    with storemod.SQLiteShadowStore(store_path()) as store:
        event = event_from_store(store, str(payload.dispatch["event_id"]))
        try:
            normalized_plan = shadow.normalize_authoritative_plan(payload.plan, event)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if normalized_plan["analysis_mode"] == "certification":
            raise HTTPException(status_code=403, detail="webhook pilot cannot authorize certification")

        queue_model = shadow.model_queue(event, normalized_plan)
        if queue_model["operation_class"] != "VERIFICATION":
            raise HTTPException(status_code=403, detail="webhook pilot only authorizes verification")

        operation_material = {
            "event_id": event["event_id"],
            "plan_digest": normalized_plan["plan_digest_sha256"],
            "applab_sha": applab_sha,
            "workflow_run_id": payload.run_id,
        }
        operation_id = "op_" + hashlib.sha256(
            brain.canonical_json(operation_material).encode("utf-8")
        ).hexdigest()[:32]
        operation = brain._operation_fixture(
            operation_id,
            event["repository"],
            event_gateway.canonical_source_ref(event["source_ref"], assume_branch=True),
            event["resolved_sha"],
            applab_sha,
            operation_class="VERIFICATION",
            analysis_mode=normalized_plan["analysis_mode"],
            priority=queue_model["priority"],
            contract_fingerprint=brain.sha256_json(load_contract_for_operation()),
            plan_digest_sha256=normalized_plan["plan_digest_sha256"],
            event_id=event["event_id"],
            gateway_run_id=payload.run_id,
        )
        store.put_operation(operation)
        queue = queue_mod.DurablePerRepoQueue(
            store,
            max_ready_global=4,
            max_ready_per_repo=2,
            max_pending_global=32,
            max_pending_per_repo=8,
            max_active_global=2,
            max_active_per_repo=1,
            lease_seconds=3600,
        )
        queue.recover_expired_leases(now_ts=time.time())
        queue.enqueue(operation_id, now_ts=time.time(), max_retries=0)
        claim = queue.claim_next(
            f"gha:{payload.run_id}",
            now_ts=time.time(),
            expected_operation_id=operation_id,
        )
        if claim is None:
            return {
                "authorized": False,
                "operation_id": operation_id,
                "state": "DEFERRED",
                "authority": "ORCHESTRATION_ONLY",
            }

        advance_operation(
            store,
            operation_id,
            [
                ("QUEUED", "PLANNING", "AUTHORITATIVE_PLAN_RECEIVED"),
                ("PLANNING", "READY", "EXECUTOR_LEASE_GRANTED"),
                ("READY", "RUNNING", "GITHUB_ACTIONS_STARTED"),
            ],
        )
        return {
            "authorized": True,
            "operation_id": operation_id,
            "queue_claim": claim,
            "analysis_mode": normalized_plan["analysis_mode"],
            "authority": "ORCHESTRATION_ONLY",
            "verdict_authority": False,
        }


def load_contract_for_operation() -> dict[str, Any]:
    return pilot.load_contract()


@app.post("/callback")
async def execution_callback(
    request: Request,
    x_applab_pilot_signature: str = Header(default=""),
) -> dict[str, Any]:
    if not enabled():
        raise HTTPException(status_code=503, detail="v5.4G pilot is disabled")
    raw = await request.body()
    secret = env_required("APPLAB_V54G_DISPATCH_SECRET").encode("utf-8")
    verify_body_signature(raw, x_applab_pilot_signature, secret)
    try:
        payload = CallbackRequest.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid callback payload") from exc

    worker_id = f"gha:{payload.run_id}"
    with storemod.SQLiteShadowStore(store_path()) as store:
        queue = queue_mod.DurablePerRepoQueue(
            store,
            max_ready_global=4,
            max_ready_per_repo=2,
            max_pending_global=32,
            max_pending_per_repo=8,
            max_active_global=2,
            max_active_per_repo=1,
            lease_seconds=3600,
        )
        entry = queue._entry(payload.operation_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown operation queue entry")
        if entry["state"] != "LEASED" or entry["leased_by"] != worker_id:
            raise HTTPException(status_code=409, detail="callback lease identity mismatch")

        conclusion = payload.conclusion.strip().lower()
        if conclusion == "success":
            queue.complete(payload.operation_id, worker_id, now_ts=time.time())
            advance_operation(
                store,
                payload.operation_id,
                [("RUNNING", "SUCCEEDED", "GITHUB_ACTIONS_COMPLETED")],
            )
            state = "SUCCEEDED"
        elif conclusion == "cancelled":
            queue.record_failure(
                payload.operation_id,
                worker_id,
                "UNKNOWN_FAILURE",
                retryable=False,
                now_ts=time.time(),
            )
            advance_operation(
                store,
                payload.operation_id,
                [("RUNNING", "CANCELED", "GITHUB_ACTIONS_CANCELED")],
            )
            state = "CANCELED"
        else:
            failure_class = payload.failure_class.strip().upper()
            if failure_class not in brain.load_contract()["attempt"]["failure_classes"]:
                failure_class = "UNKNOWN_FAILURE"
            queue.record_failure(
                payload.operation_id,
                worker_id,
                failure_class,
                retryable=False,
                now_ts=time.time(),
            )
            advance_operation(
                store,
                payload.operation_id,
                [("RUNNING", "FAILED", f"GITHUB_ACTIONS_{failure_class}")],
            )
            state = "FAILED"

        return {
            "operation_id": payload.operation_id,
            "state": state,
            "authority": "ORCHESTRATION_ONLY",
            "verdict_authority": False,
        }
