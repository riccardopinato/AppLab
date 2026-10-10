#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

CONTRACT_NAME = "Shared Ecosystem Core"
CONTRACT_VERSION = 1

CANONICAL_APP_SCHEMES = {
    "wonderlog": "wonderlog",
    "annas_diary": "annasdiary",
    "notes": "notesapp",
    "trailpath": "trailpath",
}
ALLOWED_TRANSFER_MODES = {"copy", "link"}
ALLOWED_MEDIA_HANDOFFS = {"omitted", "shareToken", "cloudObject"}
PRIVATE_MEDIA_MARKERS = ("file://", "content://", "media://", "/data/", "/private/")
BRIDGE_ID_RE = re.compile(r"^ecosystem:v1:([a-z0-9_]+):([A-Za-z0-9_.-]+):(.+)$")


def clean(value: object, label: str, max_length: int = 1000) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    if len(text) > max_length:
        raise ValueError(f"{label} exceeds {max_length} characters")
    if "\x00" in text:
        raise ValueError(f"{label} contains NUL")
    return text


def validate_protocol(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("protocol must be an object")
    name = clean(raw.get("name"), "protocol.name", 128)
    version = raw.get("version")
    if name != CONTRACT_NAME or version != CONTRACT_VERSION:
        raise ValueError(
            "v4.8 canonical ecosystem verification requires Shared Ecosystem Core v1"
        )
    return {
        "name": name,
        "version": version,
        "contract_ref": clean(raw.get("contract_ref"), "protocol.contract_ref", 500),
        "transport_independent": True,
    }


def validate_media(values: Any) -> list[dict[str, Any]]:
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > 64:
        raise ValueError("observed_contract.media must be an array with <=64 items")
    out: list[dict[str, Any]] = []
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise ValueError(f"media[{index}] must be an object")
        handoff = item.get("handoff")
        if not isinstance(handoff, dict):
            raise ValueError(f"media[{index}].handoff must be an object")
        kind = clean(handoff.get("kind"), f"media[{index}].handoff.kind", 32)
        if kind not in ALLOWED_MEDIA_HANDOFFS:
            raise ValueError(f"Unsupported media handoff kind: {kind}")
        wire = json.dumps(item, sort_keys=True).lower()
        if any(marker in wire for marker in PRIVATE_MEDIA_MARKERS):
            raise ValueError("Private/local media reference is forbidden cross-app")
        if kind == "shareToken" and not str(handoff.get("token", "")).strip():
            raise ValueError("shareToken handoff requires token")
        if kind == "cloudObject" and not str(handoff.get("locator", "")).strip():
            raise ValueError("cloudObject handoff requires locator")
        out.append(item)
    return out


def validate_envelope(
    raw: Any,
    *,
    source_app: str,
    target_app: str,
    expected_mode: str | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("observed_contract must be an object")
    if raw.get("schemaVersion") != 1:
        raise ValueError("schemaVersion must equal 1")
    if clean(raw.get("privacyScope"), "privacyScope", 64) != "explicitShare":
        raise ValueError("privacyScope must be explicitShare")

    bridge_id = clean(raw.get("bridgeId"), "bridgeId", 512)
    match = BRIDGE_ID_RE.fullmatch(bridge_id)
    if not match:
        raise ValueError("bridgeId is not a canonical Shared Ecosystem Core v1 id")
    bridge_owner, bridge_entity_type, bridge_entity_id = match.groups()

    transfer_mode = clean(raw.get("transferMode"), "transferMode", 16).lower()
    if transfer_mode not in ALLOWED_TRANSFER_MODES:
        raise ValueError("transferMode must be copy or link")
    if expected_mode and transfer_mode != expected_mode:
        raise ValueError(f"Expected transferMode {expected_mode}, got {transfer_mode}")

    revision = raw.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("revision must be an integer >= 1")
    if clean(raw.get("sourceApp"), "sourceApp", 64) != source_app:
        raise ValueError("sourceApp does not match scenario direction")

    provenance = raw.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("provenance must be an object")
    owner_app = clean(provenance.get("ownerApp"), "provenance.ownerApp", 64)
    owner_entity_type = clean(
        provenance.get("ownerEntityType"), "provenance.ownerEntityType", 128
    )
    owner_entity_id = clean(
        provenance.get("ownerEntityId"), "provenance.ownerEntityId", 256
    )
    if provenance.get("ownerRevision") != revision:
        raise ValueError("provenance.ownerRevision must match revision")
    if (owner_app, owner_entity_type, owner_entity_id) != (
        bridge_owner,
        bridge_entity_type,
        bridge_entity_id,
    ):
        raise ValueError("bridgeId must derive from canonical provenance ownership")

    canonical_deep_link = str(
        provenance.get("canonicalDeepLink") or raw.get("sourceDeepLink") or ""
    ).strip()
    if transfer_mode == "link" and not canonical_deep_link:
        raise ValueError("LINK requires canonicalDeepLink")
    if canonical_deep_link:
        expected_scheme = CANONICAL_APP_SCHEMES.get(owner_app)
        if expected_scheme and not canonical_deep_link.startswith(expected_scheme + "://"):
            raise ValueError(
                "canonicalDeepLink scheme does not match canonical owner app"
            )

    expected_key = f"{bridge_id}:{revision}:{transfer_mode}"
    observed_key = clean(raw.get("idempotencyKey"), "idempotencyKey", 800)
    if observed_key != expected_key:
        raise ValueError(
            "idempotencyKey does not match bridgeId + revision + transferMode"
        )

    transport = raw.get("transport")
    if not isinstance(transport, dict):
        raise ValueError("observed_contract.transport must be an object")
    if transport.get("transportVersion") != 1:
        raise ValueError("transportVersion must equal 1")
    if clean(transport.get("targetApp"), "transport.targetApp", 64) != target_app:
        raise ValueError("transport.targetApp does not match scenario destination")

    media = validate_media(raw.get("media", []))
    return {
        "schema_version": 1,
        "bridge_id": bridge_id,
        "transfer_mode": transfer_mode,
        "revision": revision,
        "idempotency_key": observed_key,
        "owner_app": owner_app,
        "owner_entity_type": owner_entity_type,
        "owner_entity_id": owner_entity_id,
        "canonical_deep_link": canonical_deep_link,
        "privacy_scope": "explicitShare",
        "target_app": target_app,
        "media_count": len(media),
    }


def self_test() -> None:
    envelope = {
        "schemaVersion": 1,
        "bridgeId": "ecosystem:v1:wonderlog:journey:journey-42",
        "sourceApp": "wonderlog",
        "privacyScope": "explicitShare",
        "transferMode": "copy",
        "revision": 7,
        "idempotencyKey": "ecosystem:v1:wonderlog:journey:journey-42:7:copy",
        "sourceDeepLink": "wonderlog://journey/journey-42",
        "provenance": {
            "ownerApp": "wonderlog",
            "ownerEntityType": "journey",
            "ownerEntityId": "journey-42",
            "ownerRevision": 7,
            "canonicalDeepLink": "wonderlog://journey/journey-42",
        },
        "transport": {"transportVersion": 1, "targetApp": "annas_diary"},
        "media": [{"handoff": {"kind": "omitted"}}],
    }
    projection = validate_envelope(
        envelope, source_app="wonderlog", target_app="annas_diary", expected_mode="copy"
    )
    assert projection["bridge_id"].endswith("journey-42")

    invalid = json.loads(json.dumps(envelope))
    invalid["media"] = [
        {"handoff": {"kind": "cloudObject", "locator": "file:///data/private.jpg"}}
    ]
    try:
        validate_envelope(invalid, source_app="wonderlog", target_app="annas_diary")
    except ValueError as exc:
        assert "Private/local media" in str(exc)
    else:
        raise AssertionError("private media must fail closed")

    link = json.loads(json.dumps(envelope))
    link["transferMode"] = "link"
    link["idempotencyKey"] = "ecosystem:v1:wonderlog:journey:journey-42:7:link"
    validate_envelope(
        link, source_app="wonderlog", target_app="annas_diary", expected_mode="link"
    )
    print("Shared Ecosystem Core v1 verifier self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("use --self-test")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
