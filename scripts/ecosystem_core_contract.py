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
PRIVATE_MEDIA_SCHEMES = {"file", "content", "media"}
PRIVATE_PATH_PREFIXES = ("/", "sdcard/", "storage/", "data/", "private/")
CANONICAL_CONTRACT_REFS = {
    "App-Factory-Core@golden/ecosystem/GOLDEN_ECOSYSTEM_BRIDGE_FLUTTER_v1_DRAFT.txt",
    "App-Factory-Core@a4a97ca79e85d2faebcdcc9a3ae4a9644f5caf03:golden/ecosystem/GOLDEN_ECOSYSTEM_BRIDGE_FLUTTER_v1_DRAFT.txt",
}
BRIDGE_ID_RE = re.compile(r"^ecosystem:v1:([a-z0-9_]+):([A-Za-z0-9_.-]+):(.+)$")


def clean(value: object, label: str, max_length: int = 1000) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} is required")
    if len(text) > max_length:
        raise ValueError(f"{label} exceeds {max_length} characters")
    if "\x00" in text:
        raise ValueError(f"{label} contains NUL")
    return text


def require_contract_version(value: object, label: str, expected: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise ValueError(f"{label} must equal integer {expected}")
    return value


def require_positive_revision(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} must be an integer >= 1")
    return value


def validate_protocol(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("protocol must be an object")
    name = clean(raw.get("name"), "protocol.name", 128)
    version = require_contract_version(raw.get("version"), "protocol.version")
    if name != CONTRACT_NAME:
        raise ValueError(
            "v4.8 canonical ecosystem verification requires Shared Ecosystem Core v1"
        )
    contract_ref = clean(raw.get("contract_ref"), "protocol.contract_ref", 500)
    if contract_ref not in CANONICAL_CONTRACT_REFS:
        raise ValueError("protocol.contract_ref is not the canonical Shared Ecosystem Core v1 Golden")
    return {
        "name": name,
        "version": version,
        "contract_ref": contract_ref,
        "transport_independent": True,
    }


def _string_values(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _string_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _string_values(nested)


def _private_media_reference(value: str) -> bool:
    normalized = value.strip().lower().replace("\\", "/")
    if not normalized:
        return False
    if any(marker in normalized for marker in PRIVATE_MEDIA_MARKERS):
        return True
    scheme = normalized.split(":", 1)[0] if ":" in normalized else ""
    if scheme in PRIVATE_MEDIA_SCHEMES:
        return True
    if normalized.startswith(PRIVATE_PATH_PREFIXES):
        return True
    if re.match(r"^[a-z]:/", normalized):
        return True
    return False


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
        if any(_private_media_reference(value) for value in _string_values(item)):
            raise ValueError("Private/local media reference is forbidden cross-app")
        if kind == "shareToken":
            token = clean(handoff.get("token"), f"media[{index}].handoff.token", 2000)
            if _private_media_reference(token):
                raise ValueError("Private/local media reference is forbidden cross-app")
        if kind == "cloudObject":
            locator = clean(handoff.get("locator"), f"media[{index}].handoff.locator", 2000)
            if _private_media_reference(locator):
                raise ValueError("Private/local media reference is forbidden cross-app")
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
    require_contract_version(raw.get("schemaVersion"), "schemaVersion")
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

    revision = require_positive_revision(raw.get("revision"), "revision")
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
    owner_revision = require_positive_revision(
        provenance.get("ownerRevision"), "provenance.ownerRevision"
    )
    if owner_revision != revision:
        raise ValueError("provenance.ownerRevision must match revision")
    if (owner_app, owner_entity_type, owner_entity_id) != (
        bridge_owner,
        bridge_entity_type,
        bridge_entity_id,
    ):
        raise ValueError("bridgeId must derive from canonical provenance ownership")

    provenance_deep_link = (
        clean(
            provenance.get("canonicalDeepLink"),
            "provenance.canonicalDeepLink",
            2000,
        )
        if "canonicalDeepLink" in provenance
        else ""
    )
    source_deep_link = (
        clean(raw.get("sourceDeepLink"), "sourceDeepLink", 2000)
        if "sourceDeepLink" in raw
        else ""
    )
    canonical_deep_link = provenance_deep_link or source_deep_link
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
    require_contract_version(
        transport.get("transportVersion"), "observed_contract.transport.transportVersion"
    )
    if clean(transport.get("targetApp"), "transport.targetApp", 64) != target_app:
        raise ValueError("transport.targetApp does not match scenario destination")

    media = validate_media(raw.get("media", []))
    return {
        "schema_version": CONTRACT_VERSION,
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

    for field, mutate in (
        ("schemaVersion", lambda item: item.__setitem__("schemaVersion", True)),
        (
            "transportVersion",
            lambda item: item["transport"].__setitem__("transportVersion", True),
        ),
        (
            "ownerRevision",
            lambda item: item["provenance"].__setitem__("ownerRevision", True),
        ),
    ):
        malformed = json.loads(json.dumps(envelope))
        mutate(malformed)
        try:
            validate_envelope(
                malformed,
                source_app="wonderlog",
                target_app="annas_diary",
                expected_mode="copy",
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"boolean {field} must fail closed")

    try:
        validate_protocol(
            {
                "name": CONTRACT_NAME,
                "version": True,
                "contract_ref": "App-Factory-Core@golden/ecosystem/GOLDEN_ECOSYSTEM_BRIDGE_FLUTTER_v1_DRAFT.txt",
            }
        )
    except ValueError:
        pass
    else:
        raise AssertionError("boolean protocol.version must fail closed")

    malformed_text = json.loads(json.dumps(envelope))
    malformed_text["provenance"]["ownerEntityId"] = {"id": "journey-42"}
    malformed_text["bridgeId"] = "ecosystem:v1:wonderlog:journey:{'id': 'journey-42'}"
    malformed_text["idempotencyKey"] = malformed_text["bridgeId"] + ":7:copy"
    try:
        validate_envelope(
            malformed_text,
            source_app="wonderlog",
            target_app="annas_diary",
            expected_mode="copy",
        )
    except ValueError as exc:
        assert "must be a string" in str(exc)
    else:
        raise AssertionError("non-string contract text must fail closed")

    for locator in ("file:/sdcard/DCIM/a.jpg", "content:media/external/images/1", "/sdcard/DCIM/a.jpg"):
        malformed_media = json.loads(json.dumps(envelope))
        malformed_media["media"] = [{"handoff": {"kind": "cloudObject", "locator": locator}}]
        try:
            validate_envelope(
                malformed_media,
                source_app="wonderlog",
                target_app="annas_diary",
                expected_mode="copy",
            )
        except ValueError as exc:
            assert "Private/local media" in str(exc)
        else:
            raise AssertionError(f"local media locator must fail closed: {locator}")

    try:
        validate_protocol(
            {
                "name": CONTRACT_NAME,
                "version": 1,
                "contract_ref": "unrelated-contract",
            }
        )
    except ValueError as exc:
        assert "canonical Shared Ecosystem Core v1 Golden" in str(exc)
    else:
        raise AssertionError("unrelated protocol.contract_ref must fail closed")

    malformed_link = json.loads(json.dumps(link))
    malformed_link["provenance"]["canonicalDeepLink"] = {}
    try:
        validate_envelope(
            malformed_link,
            source_app="wonderlog",
            target_app="annas_diary",
            expected_mode="link",
        )
    except ValueError as exc:
        assert "must be a string" in str(exc)
    else:
        raise AssertionError("non-string provenance deep link must fail closed")

    malformed_source_link = json.loads(json.dumps(link))
    malformed_source_link["sourceDeepLink"] = {}
    try:
        validate_envelope(
            malformed_source_link,
            source_app="wonderlog",
            target_app="annas_diary",
            expected_mode="link",
        )
    except ValueError as exc:
        assert "must be a string" in str(exc)
    else:
        raise AssertionError("non-string source deep link must fail closed")

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
