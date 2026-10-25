#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import controlled_event_v54g as pilot  # noqa: E402
import durable_store_v54b as storemod  # noqa: E402
import event_gateway_v54c as event_gateway  # noqa: E402


def load_gateway_module():
    path = ROOT / "gateway-v54g" / "app.py"
    spec = importlib.util.spec_from_file_location("applab_v54g_gateway", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def signed_headers(body: bytes, secret: bytes, delivery: str, event_type: str) -> dict[str, str]:
    return {
        "X-Hub-Signature-256": event_gateway.compute_signature(body, secret),
        "X-GitHub-Delivery": delivery,
        "X-GitHub-Event": event_type,
        "Content-Type": "application/json",
    }


def signed_pilot_headers(module, body: bytes, secret: bytes) -> dict[str, str]:
    return {
        "X-AppLab-Pilot-Signature": module.body_signature(body, secret),
        "Content-Type": "application/json",
    }


def main() -> int:
    gateway = load_gateway_module()
    webhook_secret = b"webhook-test-secret"
    dispatch_secret = b"dispatch-test-secret"

    previous_env = dict(os.environ)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["APPLAB_V54G_ENABLED"] = "true"
            os.environ["APPLAB_V54G_STORE_PATH"] = str(Path(tmp) / "v54g.sqlite3")
            os.environ["APPLAB_V54G_WEBHOOK_SECRET"] = webhook_secret.decode()
            os.environ["APPLAB_V54G_DISPATCH_SECRET"] = dispatch_secret.decode()
            os.environ["APPLAB_V54G_GITHUB_TOKEN"] = "test-token-never-used"
            os.environ["APPLAB_V54G_APPLAB_REPOSITORY"] = "owner/applab"
            os.environ["APPLAB_V54G_PILOT_ALLOWLIST"] = json.dumps(
                {"owner/app": ["main"]}
            )

            dispatched: list[dict] = []
            gateway.dispatch_github = lambda payload: dispatched.append(payload)
            client = TestClient(gateway.app)

            push = {
                "ref": "refs/heads/main",
                "before": "1" * 40,
                "after": "2" * 40,
                "repository": {"full_name": "owner/app"},
            }
            body = json.dumps(push, sort_keys=True, separators=(",", ":")).encode()
            headers = signed_headers(body, webhook_secret, "delivery-1", "push")

            first = client.post("/github-webhook", content=body, headers=headers)
            assert first.status_code == 200, first.text
            first_payload = first.json()
            assert first_payload["ingest"]["persistence_status"] == "INSERTED"
            assert first_payload["dispatch"]["status"] == "DISPATCHED"
            assert first_payload["dispatch"]["dispatch_performed"] is True
            assert first_payload["verdict_authority"] is False
            assert len(dispatched) == 1
            dispatch = dispatched[0]
            pilot.verify_dispatch_payload(dispatch, dispatch_secret)

            replay = client.post("/github-webhook", content=body, headers=headers)
            assert replay.status_code == 200, replay.text
            assert replay.json()["dispatch"]["status"] == "REPLAY"
            assert len(dispatched) == 1

            redelivery_headers = signed_headers(
                body, webhook_secret, "delivery-2", "push"
            )
            redelivery = client.post(
                "/github-webhook", content=body, headers=redelivery_headers
            )
            assert redelivery.status_code == 200, redelivery.text
            assert redelivery.json()["ingest"]["persistence_status"] == "DEDUPED"
            assert redelivery.json()["dispatch"]["status"] == "REPLAY"
            assert len(dispatched) == 1

            workflow_event = {
                "repository": {"full_name": "owner/app"},
                "workflow_run": {
                    "head_branch": "main",
                    "head_sha": "2" * 40,
                },
            }
            workflow_body = json.dumps(
                workflow_event, sort_keys=True, separators=(",", ":")
            ).encode()
            workflow_headers = signed_headers(
                workflow_body, webhook_secret, "workflow-1", "workflow_run"
            )
            rejected = client.post(
                "/github-webhook",
                content=workflow_body,
                headers=workflow_headers,
            )
            assert rejected.status_code == 403
            assert len(dispatched) == 1

            plan = {
                "repository": "owner/app",
                "head_sha": "2" * 40,
                "mode": "full",
                "lane": "FULL_RUNTIME",
                "planner_version": "test",
                "planner_ms": 123,
                "selected_labs": {
                    "system": True,
                    "network": True,
                    "persistence": False,
                },
            }
            authorize_body = {
                "dispatch": dispatch,
                "plan": plan,
                "applab_sha": "a" * 40,
                "run_id": "100",
            }
            authorize_raw = json.dumps(
                authorize_body, sort_keys=True, separators=(",", ":")
            ).encode()
            authorized = client.post(
                "/authorize",
                content=authorize_raw,
                headers=signed_pilot_headers(
                    gateway, authorize_raw, dispatch_secret
                ),
            )
            assert authorized.status_code == 200, authorized.text
            auth_payload = authorized.json()
            assert auth_payload["authorized"] is True
            assert auth_payload["analysis_mode"] == "full"
            assert auth_payload["verdict_authority"] is False
            operation_id = auth_payload["operation_id"]

            duplicate_authorize = client.post(
                "/authorize",
                content=authorize_raw,
                headers=signed_pilot_headers(
                    gateway, authorize_raw, dispatch_secret
                ),
            )
            assert duplicate_authorize.status_code == 200
            assert duplicate_authorize.json()["authorized"] is False

            wrong_callback_body = {
                "operation_id": operation_id,
                "run_id": "999",
                "conclusion": "success",
                "failure_class": "NONE",
            }
            wrong_raw = json.dumps(
                wrong_callback_body, sort_keys=True, separators=(",", ":")
            ).encode()
            wrong_callback = client.post(
                "/callback",
                content=wrong_raw,
                headers=signed_pilot_headers(gateway, wrong_raw, dispatch_secret),
            )
            assert wrong_callback.status_code == 409

            callback_body = {
                "operation_id": operation_id,
                "run_id": "100",
                "conclusion": "success",
                "failure_class": "NONE",
            }
            callback_raw = json.dumps(
                callback_body, sort_keys=True, separators=(",", ":")
            ).encode()
            callback = client.post(
                "/callback",
                content=callback_raw,
                headers=signed_pilot_headers(
                    gateway, callback_raw, dispatch_secret
                ),
            )
            assert callback.status_code == 200, callback.text
            assert callback.json()["state"] == "SUCCEEDED"
            assert callback.json()["verdict_authority"] is False

            with storemod.SQLiteShadowStore(Path(os.environ["APPLAB_V54G_STORE_PATH"])) as store:
                operation = store.get_operation(operation_id)
                assert operation["current_state"] == "SUCCEEDED"
                queue_row = store.db.execute(
                    "SELECT state FROM queue_entries WHERE operation_id=?",
                    (operation_id,),
                ).fetchone()
                assert queue_row["state"] == "DONE"
                dispatch_row = store.db.execute(
                    "SELECT status,attempt_count FROM v54g_dispatches WHERE event_id=?",
                    (dispatch["event_id"],),
                ).fetchone()
                assert dispatch_row["status"] == "DISPATCHED"
                assert dispatch_row["attempt_count"] == 1

            # Disabled is fail-closed even when all secrets remain present.
            os.environ["APPLAB_V54G_ENABLED"] = "false"
            disabled = client.post("/github-webhook", content=body, headers=headers)
            assert disabled.status_code == 503

    finally:
        os.environ.clear()
        os.environ.update(previous_env)

    contract = pilot.load_contract()
    assert contract["activation_default"] == "DISABLED"
    assert "workflow_run" not in contract["supported_live_events"]

    workflow_text = (
        ROOT / ".github" / "workflows" / "controlled-event-pilot.yml"
    ).read_text(encoding="utf-8")
    assert "repository_dispatch:" in workflow_text
    assert "cancel-in-progress: false" in workflow_text
    assert "publish_release_artifact: false" in workflow_text
    assert "production-certification" not in workflow_text

    compose = (ROOT / "docker-compose.live.yml").read_text(encoding="utf-8")
    assert 'profiles: ["v54g"]' in compose
    assert "APPLAB_V54G_ENABLED: ${APPLAB_V54G_ENABLED:-false}" in compose

    pilot.self_test()
    print("AppLab v5.4G controlled event pilot contract test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
