#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import durable_brain_v54a as brain
import event_gateway_v54c as gateway

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = ROOT / "integration" / "orchestration" / "contracts" / "controlled-event-pilot-v1.json"


class PilotError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise PilotError("unsupported controlled-pilot contract version")
    if payload.get("contract_name") != "APPLAB_CONTROLLED_EVENT_DRIVEN_PILOT":
        raise PilotError("unexpected controlled-pilot contract")
    if payload.get("authority") != "ORCHESTRATION_ONLY":
        raise PilotError("controlled pilot cannot become verification authority")
    return payload


def canonical_ref(value: str) -> str:
    return gateway.canonical_source_ref(value, assume_branch=True)


def normalize_allowlist(raw: dict[str, Any]) -> dict[str, set[str]]:
    if not isinstance(raw, dict):
        raise PilotError("pilot allowlist must be object")
    result: dict[str, set[str]] = {}
    for repository, refs in raw.items():
        repo = brain._require_repository(repository)
        if not isinstance(refs, list) or not refs:
            raise PilotError(f"pilot refs missing for {repo}")
        normalized = {
            canonical_ref(brain._require_non_empty_string(ref, "pilot ref"))
            for ref in refs
        }
        result[repo] = normalized
    return result


def authorize_event(
    event: dict[str, Any],
    allowlist: dict[str, set[str]],
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = contract or load_contract()
    brain.validate_event(event, brain.load_contract())
    if event["admission"] != "ADMITTED":
        raise PilotError("only admitted events may enter controlled pilot")
    if event["source"] != "github":
        raise PilotError("controlled pilot accepts GitHub events only")
    if event["source_event_type"] not in spec["supported_live_events"]:
        raise PilotError("event type is not eligible for live execution")
    repository = event["repository"]
    source_ref = canonical_ref(event["source_ref"])
    allowed_refs = allowlist.get(repository)
    if not allowed_refs or source_ref not in allowed_refs:
        raise PilotError("repository/ref is outside pilot allowlist")
    return {
        "repository": repository,
        "source_ref": source_ref,
        "resolved_sha": event["resolved_sha"],
        "event_id": event["event_id"],
        "correlation_id": event["correlation_id"],
        "source_event_type": event["source_event_type"],
        "operation_class": "VERIFICATION",
        "analysis_mode": "fast",
        "certification_allowed": False,
        "authority": "ORCHESTRATION_ONLY",
    }


def dispatch_payload(
    authorized: dict[str, Any],
    dispatch_secret: bytes,
    *,
    gateway_event_id: str,
) -> dict[str, Any]:
    if not dispatch_secret:
        raise PilotError("dispatch secret must not be empty")
    payload = {
        "schema_version": 1,
        "record_type": "APPLAB_V54G_DISPATCH",
        "repository": brain._require_repository(authorized["repository"]),
        "source_ref": canonical_ref(authorized["source_ref"]),
        "resolved_sha": brain._require_sha(
            authorized["resolved_sha"], "dispatch.resolved_sha"
        ),
        "event_id": brain._require_non_empty_string(
            gateway_event_id, "gateway_event_id"
        ),
        "operation_class": "VERIFICATION",
        "analysis_mode": "fast",
        "certification_allowed": False,
        "authority": "ORCHESTRATION_ONLY",
    }
    raw = brain.canonical_json(payload).encode("utf-8")
    payload["gateway_attestation"] = "sha256=" + hmac.new(
        dispatch_secret, raw, hashlib.sha256
    ).hexdigest()
    return payload


def verify_dispatch_payload(payload: dict[str, Any], dispatch_secret: bytes) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PilotError("dispatch payload must be object")
    supplied = str(payload.get("gateway_attestation") or "")
    unsigned = dict(payload)
    unsigned.pop("gateway_attestation", None)
    expected = "sha256=" + hmac.new(
        dispatch_secret,
        brain.canonical_json(unsigned).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise PilotError("dispatch attestation verification failed")
    if unsigned.get("record_type") != "APPLAB_V54G_DISPATCH":
        raise PilotError("dispatch record type mismatch")
    if unsigned.get("operation_class") != "VERIFICATION":
        raise PilotError("controlled pilot cannot dispatch protected operation class")
    if unsigned.get("analysis_mode") != "fast":
        raise PilotError("controlled pilot starts through authoritative FAST planning")
    if unsigned.get("certification_allowed") is not False:
        raise PilotError("controlled pilot cannot enable certification")
    if unsigned.get("authority") != "ORCHESTRATION_ONLY":
        raise PilotError("dispatch authority drift")
    brain._require_repository(unsigned.get("repository"))
    brain._require_sha(unsigned.get("resolved_sha"), "dispatch.resolved_sha")
    canonical_ref(unsigned.get("source_ref"))
    return payload


def concurrency_key(payload: dict[str, Any]) -> str:
    verify_fields = {
        "repository": brain._require_repository(payload.get("repository")),
        "source_ref": canonical_ref(payload.get("source_ref")),
        "operation_class": brain._require_non_empty_string(
            payload.get("operation_class"), "operation_class"
        ),
    }
    return "|".join(
        (
            verify_fields["repository"],
            verify_fields["source_ref"],
            verify_fields["operation_class"],
        )
    )


def self_test() -> None:
    contract = load_contract()
    event = brain._event_fixture(
        "evt_g",
        "owner/app",
        "refs/heads/main",
        "a" * 40,
        "delivery-g",
    )
    allowlist = normalize_allowlist({"owner/app": ["main"]})
    authorized = authorize_event(event, allowlist, contract)
    assert authorized["operation_class"] == "VERIFICATION"
    assert authorized["certification_allowed"] is False

    secret = b"v54g-self-test"
    payload = dispatch_payload(
        authorized,
        secret,
        gateway_event_id=event["event_id"],
    )
    verify_dispatch_payload(payload, secret)
    assert concurrency_key(payload) == "owner/app|refs/heads/main|VERIFICATION"

    tampered = dict(payload, resolved_sha="b" * 40)
    try:
        verify_dispatch_payload(tampered, secret)
    except PilotError as exc:
        assert "attestation" in str(exc)
    else:
        raise AssertionError("tampered dispatch unexpectedly accepted")

    workflow_event = dict(event, source_event_type="workflow_run")
    workflow_event["dedupe_key"] = brain.event_dedupe_key(workflow_event)
    try:
        authorize_event(workflow_event, allowlist, contract)
    except PilotError as exc:
        assert "not eligible" in str(exc)
    else:
        raise AssertionError("workflow_run unexpectedly eligible for live pilot")

    try:
        authorize_event(event, normalize_allowlist({"owner/app": ["beta"]}), contract)
    except PilotError as exc:
        assert "allowlist" in str(exc)
    else:
        raise AssertionError("non-allowlisted ref unexpectedly eligible")

    print("AppLab v5.4G controlled event pilot contract self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v5.4G controlled event pilot")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
