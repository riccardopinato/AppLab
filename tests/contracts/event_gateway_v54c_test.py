#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import event_gateway_v54c as gateway  # noqa: E402
import durable_store_v54b as storemod  # noqa: E402


def expect_rejected(fn, contains: str) -> None:
    try:
        fn()
    except gateway.GatewayError as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected rejection containing {contains!r}")


def signed_headers(event_type: str, delivery: str, body: bytes, key: bytes) -> dict[str, str]:
    return {
        "X-Hub-Signature-256": gateway.compute_signature(body, key),
        "X-GitHub-Delivery": delivery,
        "X-GitHub-Event": event_type,
    }


def main() -> int:
    contract = gateway.load_contract()
    assert contract["mode"] == "SHADOW_NO_DISPATCH"
    assert contract["authority"] == "NONE"

    key = b"contract-test-key"
    now = datetime(2026, 10, 25, 2, 45, tzinfo=timezone.utc)
    now_text = now.isoformat().replace("+00:00", "Z")

    push = {
        "ref": "refs/heads/main",
        "before": "1" * 40,
        "after": "2" * 40,
        "repository": {"full_name": "owner/app"},
    }
    push_body = json.dumps(push, sort_keys=True, separators=(",", ":")).encode()

    pr = {
        "repository": {"full_name": "owner/app"},
        "pull_request": {
            "head": {"ref": "feature/test", "sha": "3" * 40},
            "base": {"ref": "main"},
        },
    }
    pr_body = json.dumps(pr, sort_keys=True, separators=(",", ":")).encode()

    workflow = {
        "repository": {"full_name": "owner/app"},
        "workflow_run": {
            "head_branch": "main",
            "head_sha": "4" * 40,
            "status": "completed",
            "conclusion": "success",
        },
    }
    workflow_body = json.dumps(workflow, sort_keys=True, separators=(",", ":")).encode()

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "gateway.sqlite3"
        with storemod.SQLiteShadowStore(db) as store:
            push_result = gateway.ingest_github_delivery(
                store,
                signed_headers("push", "push-1", push_body, key),
                push_body,
                key,
                received_at=now_text,
                now_epoch=now.timestamp(),
                contract=contract,
            )
            assert push_result["repository"] == "owner/app"
            assert push_result["source_ref"] == "refs/heads/main"
            assert push_result["resolved_sha"] == "2" * 40
            assert push_result["persistence_status"] == "INSERTED"

            pr_result = gateway.ingest_github_delivery(
                store,
                signed_headers("pull_request", "pr-1", pr_body, key),
                pr_body,
                key,
                received_at=now_text,
                now_epoch=now.timestamp(),
                contract=contract,
            )
            assert pr_result["source_ref"] == "refs/heads/feature/test"
            assert pr_result["resolved_sha"] == "3" * 40

            workflow_result = gateway.ingest_github_delivery(
                store,
                signed_headers("workflow_run", "run-1", workflow_body, key),
                workflow_body,
                key,
                received_at=now_text,
                now_epoch=now.timestamp(),
                contract=contract,
            )
            assert workflow_result["source_ref"] == "refs/heads/main"
            assert workflow_result["resolved_sha"] == "4" * 40

            later_text = datetime(2026, 10, 25, 2, 45, 1, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
            replay_later = gateway.ingest_github_delivery(
                store,
                signed_headers("push", "push-1", push_body, key),
                push_body,
                key,
                received_at=later_text,
                now_epoch=datetime(2026, 10, 25, 2, 45, 1, tzinfo=timezone.utc).timestamp(),
                contract=contract,
            )
            assert replay_later["persistence_status"] == "REPLAY"

            # Same logical push delivered under a new provider delivery id is deduped.
            duplicate = gateway.ingest_github_delivery(
                store,
                signed_headers("push", "push-redelivery", push_body, key),
                push_body,
                key,
                received_at=now_text,
                now_epoch=now.timestamp(),
                contract=contract,
            )
            assert duplicate["persistence_status"] == "DEDUPED"
            assert duplicate["event_id"] == push_result["event_id"]

            bad_headers = signed_headers("push", "bad", push_body, key)
            bad_headers["X-Hub-Signature-256"] = "sha256=" + ("f" * 64)
            expect_rejected(
                lambda: gateway.ingest_github_delivery(
                    store,
                    bad_headers,
                    push_body,
                    key,
                    received_at=now_text,
                    now_epoch=now.timestamp(),
                    contract=contract,
                ),
                "signature",
            )

            missing_delivery = signed_headers("push", "ignored", push_body, key)
            missing_delivery["X-GitHub-Delivery"] = ""
            expect_rejected(
                lambda: gateway.ingest_github_delivery(
                    store,
                    missing_delivery,
                    push_body,
                    key,
                    received_at=now_text,
                    now_epoch=now.timestamp(),
                    contract=contract,
                ),
                "delivery",
            )

            unsupported = signed_headers("issues", "issues-1", push_body, key)
            expect_rejected(
                lambda: gateway.ingest_github_delivery(
                    store,
                    unsupported,
                    push_body,
                    key,
                    received_at=now_text,
                    now_epoch=now.timestamp(),
                    contract=contract,
                ),
                "unsupported",
            )

            too_big_contract = dict(contract)
            too_big_contract["max_body_bytes"] = 1
            expect_rejected(
                lambda: gateway.ingest_github_delivery(
                    store,
                    signed_headers("push", "big-1", push_body, key),
                    push_body,
                    key,
                    received_at=now_text,
                    now_epoch=now.timestamp(),
                    contract=too_big_contract,
                ),
                "body limit",
            )

            newer_push = {
                "ref": "refs/heads/main",
                "before": "2" * 40,
                "after": "5" * 40,
                "repository": {"full_name": "owner/app"},
            }
            newer_body = json.dumps(newer_push, sort_keys=True, separators=(",", ":")).encode()
            newer = gateway.ingest_github_delivery(
                store,
                signed_headers("push", "push-2", newer_body, key),
                newer_body,
                key,
                received_at=now_text,
                now_epoch=now.timestamp(),
                contract=contract,
            )
            assert newer["persistence_status"] == "INSERTED"

            latest = gateway.compare_reconciliation_snapshot(
                store,
                [{
                    "repository": "owner/app",
                    "source_ref": "main",
                    "resolved_sha": "5" * 40,
                }],
            )
            assert latest["all_current"] is True

            reconciliation = gateway.compare_reconciliation_snapshot(
                store,
                [
                    {
                        "repository": "owner/app",
                        "source_ref": "refs/heads/main",
                        "resolved_sha": "9" * 40,
                    },
                    {
                        "repository": "owner/missing",
                        "source_ref": "refs/heads/main",
                        "resolved_sha": "8" * 40,
                    },
                ],
            )
            assert reconciliation["matched"] == []
            assert len(reconciliation["stale"]) == 1
            assert reconciliation["stale"][0]["latest_event_sha"] == "5" * 40
            assert len(reconciliation["missing"]) == 1
            assert reconciliation["dispatch"] is False

            row = store.db.execute("SELECT COUNT(*) AS n FROM operations").fetchone()
            assert row["n"] == 0, "v5.4C gateway must not create Operations"

    source = (ROOT / "scripts" / "event_gateway_v54c.py").read_text(encoding="utf-8")
    for forbidden in (
        "requests.",
        "urllib.request",
        "socket.",
        "workflow_dispatch",
        "repository_dispatch",
        "conductor",
        "create_operation",
    ):
        assert forbidden not in source, forbidden

    operational = []
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        if path.name == "ci.yml":
            continue
        if "event_gateway_v54c.py" in path.read_text(encoding="utf-8"):
            operational.append(path.name)
    assert operational == [], f"shadow gateway unexpectedly wired to runtime workflows: {operational}"

    gateway.self_test()
    print("AppLab v5.4C Event Gateway Shadow contract test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
