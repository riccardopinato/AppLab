#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HUB_VERSION = "4.5.0"
SCHEMA_VERSION = 1
AUTHORITY = "APPLAB_PHYSICAL_EVIDENCE_HUB"
VERIFIER = "APPLAB_TRUSTED_APK_VERIFIER"
WORKFLOW_PATH = ".github/workflows/physical-evidence-hub.yml"

RESULTS = {"PASS", "FAIL", "BLOCKED"}
CAPABILITIES = {
    "gps",
    "background",
    "sensors",
    "camera",
    "scanner",
    "biometrics",
    "keystore",
    "notifications",
    "storage",
    "file_picker",
    "oem_battery",
    "oauth",
    "billing",
    "play_delivery",
    "model_delivery",
    "cross_app",
}
EVIDENCE_KINDS = {"screenshot", "log", "video", "file", "trace", "report"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read JSON object: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def parse_json_value(raw: str, label: str, expected: type) -> Any:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(value, expected):
        raise ValueError(f"{label} must be a JSON {expected.__name__}")
    return value


def clean_string(value: object, label: str, max_length: int = 1000) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    if len(text) > max_length:
        raise ValueError(f"{label} exceeds {max_length} characters")
    if "\x00" in text:
        raise ValueError(f"{label} contains NUL")
    return text


def optional_string(value: object, max_length: int = 1000) -> str:
    text = str(value or "").strip()
    if len(text) > max_length:
        raise ValueError("Optional text exceeds size limit")
    if "\x00" in text:
        raise ValueError("Optional text contains NUL")
    return text


def normalize_capabilities(values: list[Any]) -> list[str]:
    if not values or len(values) > 32:
        raise ValueError("capabilities must contain between 1 and 32 entries")
    out: list[str] = []
    for raw in values:
        value = clean_string(raw, "capability", 64).lower()
        if value not in CAPABILITIES:
            raise ValueError(f"Unsupported physical capability: {value}")
        if value not in out:
            out.append(value)
    return out


def normalize_string_list(values: list[Any], label: str, max_items: int = 64) -> list[str]:
    if len(values) > max_items:
        raise ValueError(f"{label} exceeds {max_items} entries")
    return [clean_string(item, label, 2000) for item in values]


def normalize_steps(values: list[Any]) -> list[dict[str, str]]:
    if not values or len(values) > 100:
        raise ValueError("steps must contain between 1 and 100 entries")
    out: list[dict[str, str]] = []
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise ValueError(f"steps[{index}] must be an object")
        unknown = set(item) - {"action", "expected", "observed"}
        if unknown:
            raise ValueError(f"steps[{index}] has unsupported fields: {sorted(unknown)}")
        out.append(
            {
                "action": clean_string(item.get("action"), f"steps[{index}].action", 1000),
                "expected": clean_string(item.get("expected"), f"steps[{index}].expected", 1000),
                "observed": clean_string(item.get("observed"), f"steps[{index}].observed", 2000),
            }
        )
    return out


def normalize_evidence_refs(values: list[Any]) -> list[dict[str, str]]:
    if not values or len(values) > 64:
        raise ValueError("evidence_refs must contain between 1 and 64 entries")
    out: list[dict[str, str]] = []
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise ValueError(f"evidence_refs[{index}] must be an object")
        unknown = set(item) - {"kind", "uri", "sha256", "description"}
        if unknown:
            raise ValueError(
                f"evidence_refs[{index}] has unsupported fields: {sorted(unknown)}"
            )
        kind = clean_string(item.get("kind"), f"evidence_refs[{index}].kind", 32).lower()
        if kind not in EVIDENCE_KINDS:
            raise ValueError(f"Unsupported evidence kind: {kind}")
        uri = clean_string(item.get("uri"), f"evidence_refs[{index}].uri", 2000)
        if not (
            uri.startswith("https://")
            or uri.startswith("artifact://")
            or uri.startswith("file-sha256://")
        ):
            raise ValueError(
                f"evidence_refs[{index}].uri must use https://, artifact:// or file-sha256://"
            )
        digest = clean_string(item.get("sha256"), f"evidence_refs[{index}].sha256", 64).lower()
        if not SHA256_RE.fullmatch(digest):
            raise ValueError(f"evidence_refs[{index}].sha256 must be 64 lowercase hex")
        out.append(
            {
                "kind": kind,
                "uri": uri,
                "sha256": digest,
                "description": optional_string(item.get("description"), 500),
            }
        )
    return out


def record_digest_payload(record: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(record))
    attestation = clone.get("attestation")
    if isinstance(attestation, dict):
        attestation["record_digest_sha256"] = ""
    verification = clone.get("verification")
    if isinstance(verification, dict):
        clone.pop("verification", None)
    return clone


def compute_record_digest(record: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(record_digest_payload(record)))


def make_record(
    *,
    repository: str,
    resolved_sha: str,
    artifact_sha256: str,
    package_id: str,
    version_name: str,
    version_code: str,
    device_manufacturer: str,
    device_model: str,
    os_name: str,
    os_version: str,
    os_build: str,
    scenario_id: str,
    scenario_title: str,
    capabilities: list[Any],
    preconditions: list[Any],
    steps: list[Any],
    expected_result: str,
    observed_result: str,
    result: str,
    evidence_refs: list[Any],
    captured_at: str,
    workflow_repository: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
    trusted_applab_sha: str,
    actor: str,
) -> dict[str, Any]:
    repository = clean_string(repository, "repository", 200)
    if not REPOSITORY_RE.fullmatch(repository):
        raise ValueError("repository must use owner/name format")
    resolved_sha = clean_string(resolved_sha, "resolved_sha", 40).lower()
    if not SHA40_RE.fullmatch(resolved_sha):
        raise ValueError("resolved_sha must be an immutable 40-character SHA")
    artifact_sha256 = clean_string(artifact_sha256, "artifact_sha256", 64).lower()
    if not SHA256_RE.fullmatch(artifact_sha256):
        raise ValueError("artifact_sha256 must be 64 lowercase hex")
    package_id = clean_string(package_id, "package_id", 250)
    if not PACKAGE_RE.fullmatch(package_id):
        raise ValueError("package_id is not a valid Android application id")
    version_name = clean_string(version_name, "version_name", 128)
    version_code = clean_string(version_code, "version_code", 64)

    workflow_repository = clean_string(workflow_repository, "workflow_repository", 200)
    if not REPOSITORY_RE.fullmatch(workflow_repository):
        raise ValueError("workflow_repository must use owner/name format")
    workflow_run_id = clean_string(workflow_run_id, "workflow_run_id", 32)
    if not workflow_run_id.isdigit():
        raise ValueError("workflow_run_id must be numeric")
    workflow_run_attempt = clean_string(workflow_run_attempt, "workflow_run_attempt", 16)
    if not workflow_run_attempt.isdigit():
        raise ValueError("workflow_run_attempt must be numeric")
    trusted_applab_sha = clean_string(trusted_applab_sha, "trusted_applab_sha", 40).lower()
    if not SHA40_RE.fullmatch(trusted_applab_sha):
        raise ValueError("trusted_applab_sha must be a 40-character SHA")

    result = clean_string(result, "result", 16).upper()
    if result not in RESULTS:
        raise ValueError("result must be PASS, FAIL or BLOCKED")
    captured_at = optional_string(captured_at, 64) or now_iso()
    try:
        datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("captured_at must be ISO-8601") from exc

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "hub_version": HUB_VERSION,
        "record_type": "PHYSICAL_DEVICE_EVIDENCE",
        "source": {
            "repository": repository,
            "resolved_sha": resolved_sha,
        },
        "artifact": {
            "sha256": artifact_sha256,
            "package_id": package_id,
            "version_name": version_name,
            "version_code": version_code,
        },
        "device": {
            "physical": True,
            "manufacturer": clean_string(device_manufacturer, "device_manufacturer", 128),
            "model": clean_string(device_model, "device_model", 128),
            "os_name": clean_string(os_name, "os_name", 64),
            "os_version": clean_string(os_version, "os_version", 128),
            "os_build": clean_string(os_build, "os_build", 256),
        },
        "scenario": {
            "id": clean_string(scenario_id, "scenario_id", 128),
            "title": clean_string(scenario_title, "scenario_title", 256),
            "capabilities": normalize_capabilities(capabilities),
            "preconditions": normalize_string_list(preconditions, "precondition", 32),
            "steps": normalize_steps(steps),
            "expected_result": clean_string(expected_result, "expected_result", 2000),
            "observed_result": clean_string(observed_result, "observed_result", 4000),
        },
        "result": result,
        "evidence_refs": normalize_evidence_refs(evidence_refs),
        "capture": {
            "captured_at": captured_at,
            "operator": clean_string(actor, "actor", 128),
        },
        "evidence_reference_integrity": {
            "operator_attested_hashes": True,
            "reference_bytes_verified_by_hub": False,
            "note": (
                "The hub records operator-attested hashes/references; referenced external "
                "bytes are not fetched or re-hashed by the v4.5 workflow."
            ),
        },
        "attestation": {
            "authority": AUTHORITY,
            "workflow_repository": workflow_repository,
            "workflow_path": WORKFLOW_PATH,
            "workflow_run_id": workflow_run_id,
            "workflow_run_attempt": workflow_run_attempt,
            "trusted_applab_sha": trusted_applab_sha,
            "event": "workflow_dispatch",
            "record_digest_sha256": "",
        },
    }
    record_id_seed = {
        "repository": repository,
        "resolved_sha": resolved_sha,
        "artifact_sha256": artifact_sha256,
        "device": record["device"],
        "scenario_id": record["scenario"]["id"],
        "captured_at": captured_at,
        "workflow_run_id": workflow_run_id,
    }
    record["record_id"] = sha256_bytes(canonical_bytes(record_id_seed))
    record["attestation"]["record_digest_sha256"] = compute_record_digest(record)
    return record


def validate_record_structure(record: dict[str, Any]) -> None:
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("physical evidence schema_version must be 1")
    if record.get("record_type") != "PHYSICAL_DEVICE_EVIDENCE":
        raise ValueError("physical evidence record_type mismatch")
    if record.get("hub_version") != HUB_VERSION:
        raise ValueError("physical evidence hub_version mismatch")

    source = record.get("source")
    artifact = record.get("artifact")
    device = record.get("device")
    scenario = record.get("scenario")
    capture = record.get("capture")
    attestation = record.get("attestation")
    evidence_refs = record.get("evidence_refs")
    for label, value in (
        ("source", source),
        ("artifact", artifact),
        ("device", device),
        ("scenario", scenario),
        ("capture", capture),
        ("attestation", attestation),
    ):
        if not isinstance(value, dict):
            raise ValueError(f"physical evidence {label} must be an object")
    if not isinstance(evidence_refs, list):
        raise ValueError("physical evidence evidence_refs must be an array")

    if not REPOSITORY_RE.fullmatch(str(source.get("repository", ""))):
        raise ValueError("physical evidence repository is invalid")
    if not SHA40_RE.fullmatch(str(source.get("resolved_sha", "")).lower()):
        raise ValueError("physical evidence resolved_sha is invalid")
    if not SHA256_RE.fullmatch(str(artifact.get("sha256", "")).lower()):
        raise ValueError("physical evidence artifact sha256 is invalid")
    if not PACKAGE_RE.fullmatch(str(artifact.get("package_id", ""))):
        raise ValueError("physical evidence package_id is invalid")
    if device.get("physical") is not True:
        raise ValueError("physical evidence must explicitly identify a physical device")
    normalize_capabilities(list(scenario.get("capabilities") or []))
    normalize_string_list(list(scenario.get("preconditions") or []), "precondition", 32)
    normalize_steps(list(scenario.get("steps") or []))
    normalize_evidence_refs(evidence_refs)

    result = str(record.get("result", "")).upper()
    if result not in RESULTS:
        raise ValueError("physical evidence result is invalid")

    if attestation.get("authority") != AUTHORITY:
        raise ValueError("physical evidence authority mismatch")
    if attestation.get("workflow_path") != WORKFLOW_PATH:
        raise ValueError("physical evidence workflow path mismatch")
    if attestation.get("event") != "workflow_dispatch":
        raise ValueError("physical evidence event mismatch")
    trusted_sha = str(attestation.get("trusted_applab_sha", "")).lower()
    if not SHA40_RE.fullmatch(trusted_sha):
        raise ValueError("physical evidence trusted AppLab SHA is invalid")
    run_id = str(attestation.get("workflow_run_id", ""))
    if not run_id.isdigit():
        raise ValueError("physical evidence workflow run id is invalid")

    expected_digest = str(attestation.get("record_digest_sha256", "")).lower()
    if not SHA256_RE.fullmatch(expected_digest):
        raise ValueError("physical evidence record digest is invalid")
    if compute_record_digest(record) != expected_digest:
        raise ValueError("physical evidence record digest mismatch")


def verify_hub_run(
    repository: str,
    run_id: str,
    token: str,
    *,
    api_url: str = "https://api.github.com",
) -> dict[str, str]:
    repository = clean_string(repository, "hub repository", 200)
    if not REPOSITORY_RE.fullmatch(repository):
        raise ValueError("hub repository must use owner/name format")
    run_id = clean_string(run_id, "hub run id", 32)
    if not run_id.isdigit():
        raise ValueError("hub run id must be numeric")
    if not token:
        raise ValueError("GITHUB_TOKEN is required to verify physical evidence provenance")

    url = f"{api_url.rstrip('/')}/repos/{repository}/actions/runs/{run_id}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "AppLab-Physical-Evidence-Hub-v4.5",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to verify AppLab physical evidence workflow run") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid GitHub workflow run response")

    path = str(payload.get("path", ""))
    event = str(payload.get("event", ""))
    conclusion = str(payload.get("conclusion", ""))
    head_branch = str(payload.get("head_branch", ""))
    head_sha = str(payload.get("head_sha", "")).lower()
    run_attempt = str(payload.get("run_attempt", "")).strip()
    run_repository = str((payload.get("repository") or {}).get("full_name", ""))

    if run_repository != repository:
        raise ValueError("Physical evidence run repository mismatch")
    if path != WORKFLOW_PATH:
        raise ValueError("Physical evidence run is not the trusted hub workflow")
    if event != "workflow_dispatch":
        raise ValueError("Physical evidence run must originate from workflow_dispatch")
    if conclusion != "success":
        raise ValueError("Physical evidence run did not complete successfully")
    if head_branch != "main":
        raise ValueError("Physical evidence run must originate from AppLab main")
    if not SHA40_RE.fullmatch(head_sha):
        raise ValueError("Physical evidence run head SHA is invalid")
    if not run_attempt.isdigit():
        raise ValueError("Physical evidence run attempt is invalid")

    return {
        "repository": repository,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "head_sha": head_sha,
        "artifact_name": f"applab-physical-evidence-{run_id}-{run_attempt}",
    }


def validate_against_artifact(
    record: dict[str, Any],
    contract: dict[str, Any],
    artifact_path: Path,
    *,
    expected_hub_repository: str,
    expected_hub_run_id: str,
    expected_hub_run_attempt: str,
    expected_hub_head_sha: str,
    verifier_run_id: str,
    verifier_trusted_applab_sha: str,
) -> dict[str, Any]:
    validate_record_structure(record)

    if not artifact_path.is_file():
        raise ValueError("Exact APK bytes are unavailable for physical evidence validation")
    actual_sha = sha256_file(artifact_path)

    apk = contract.get("apk")
    if not isinstance(apk, dict):
        raise ValueError("Build contract APK identity is missing")
    contract_repository = str(contract.get("repository", "")).strip()
    contract_sha = str(contract.get("resolved_sha", "")).strip().lower()
    contract_artifact_sha = str(apk.get("sha256", "")).strip().lower()
    contract_package = str(apk.get("package_id", "") or contract.get("package_id", "")).strip()
    contract_version_name = str(apk.get("version_name", "")).strip()
    contract_version_code = str(apk.get("version_code", "")).strip()

    source = record["source"]
    artifact = record["artifact"]
    attestation = record["attestation"]

    checks = {
        "repository": (str(source.get("repository", "")), contract_repository),
        "resolved_sha": (str(source.get("resolved_sha", "")).lower(), contract_sha),
        "artifact_sha256": (str(artifact.get("sha256", "")).lower(), contract_artifact_sha),
        "package_id": (str(artifact.get("package_id", "")), contract_package),
        "version_name": (str(artifact.get("version_name", "")), contract_version_name),
        "version_code": (str(artifact.get("version_code", "")), contract_version_code),
    }
    for label, (observed, expected) in checks.items():
        if not expected or observed != expected:
            raise ValueError(f"Physical evidence {label} binding mismatch")

    if actual_sha != contract_artifact_sha:
        raise ValueError("Physical evidence exact APK bytes do not match build contract")
    if str(attestation.get("workflow_repository", "")) != expected_hub_repository:
        raise ValueError("Physical evidence hub repository binding mismatch")
    if str(attestation.get("workflow_run_id", "")) != str(expected_hub_run_id):
        raise ValueError("Physical evidence hub run binding mismatch")
    if str(attestation.get("workflow_run_attempt", "")) != str(expected_hub_run_attempt):
        raise ValueError("Physical evidence hub run attempt binding mismatch")
    if str(attestation.get("trusted_applab_sha", "")).lower() != expected_hub_head_sha.lower():
        raise ValueError("Physical evidence hub SHA binding mismatch")

    verified = json.loads(json.dumps(record))
    verified["verification"] = {
        "state": "VERIFIED",
        "verifier": VERIFIER,
        "validated_at": now_iso(),
        "verifier_run_id": clean_string(verifier_run_id, "verifier_run_id", 32),
        "verifier_trusted_applab_sha": clean_string(
            verifier_trusted_applab_sha, "verifier_trusted_applab_sha", 40
        ).lower(),
        "hub_run_id": str(expected_hub_run_id),
        "hub_run_attempt": str(expected_hub_run_attempt),
        "hub_head_sha": expected_hub_head_sha.lower(),
        "exact_artifact_sha256": actual_sha,
        "exact_artifact_match": True,
        "evidence_reference_bytes_verified": False,
    }
    return verified


def render_markdown(record: dict[str, Any], *, verified: bool) -> str:
    source = record["source"]
    artifact = record["artifact"]
    device = record["device"]
    scenario = record["scenario"]
    attestation = record["attestation"]
    lines = [
        "# AppLab Physical Evidence",
        "",
        f"- State: **{'VERIFIED' if verified else 'ATTESTED'}**",
        f"- Result: **{record['result']}**",
        f"- Record ID: `{record['record_id']}`",
        f"- Repository: `{source['repository']}@{source['resolved_sha']}`",
        f"- Package: `{artifact['package_id']}`",
        f"- Version: `{artifact['version_name']} ({artifact['version_code']})`",
        f"- APK SHA-256: `{artifact['sha256']}`",
        f"- Device: {device['manufacturer']} {device['model']}",
        f"- OS: {device['os_name']} {device['os_version']} ({device['os_build']})",
        f"- Scenario: **{scenario['title']}** (`{scenario['id']}`)",
        f"- Capabilities: {', '.join(scenario['capabilities'])}",
        f"- Captured at: {record['capture']['captured_at']}",
        f"- Operator: {record['capture']['operator']}",
        f"- Hub run: `{attestation['workflow_run_id']}`",
        "",
        "## Preconditions",
        "",
    ]
    for item in scenario["preconditions"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Steps", ""])
    for index, step in enumerate(scenario["steps"], start=1):
        lines.append(
            f"{index}. {step['action']} — expected: {step['expected']} — observed: {step['observed']}"
        )
    lines.extend(
        [
            "",
            "## Outcome",
            "",
            f"- Expected: {scenario['expected_result']}",
            f"- Observed: {scenario['observed_result']}",
            "",
            "## Evidence references",
            "",
        ]
    )
    for ref in record["evidence_refs"]:
        lines.append(
            f"- {ref['kind']}: {ref['uri']} — SHA-256 `{ref['sha256']}`"
        )
    if verified:
        verification = record["verification"]
        lines.extend(
            [
                "",
                "## Trusted verification",
                "",
                f"- Verifier: {verification['verifier']}",
                f"- Verifier run: `{verification['verifier_run_id']}`",
                f"- Hub run: `{verification['hub_run_id']}`",
                f"- Exact artifact match: **{verification['exact_artifact_match']}**",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def write_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_github_output(values: dict[str, str]) -> None:
    target = os.getenv("GITHUB_OUTPUT", "").strip()
    if not target:
        return
    with Path(target).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        apk = root / "app.apk"
        apk.write_bytes(b"physical-device-apk")
        digest = sha256_file(apk)
        contract = {
            "repository": "owner/demo",
            "resolved_sha": "a" * 40,
            "package_id": "com.example.demo",
            "apk": {
                "sha256": digest,
                "package_id": "com.example.demo",
                "version_name": "2.0.0",
                "version_code": "20",
            },
        }
        record = make_record(
            repository="owner/demo",
            resolved_sha="a" * 40,
            artifact_sha256=digest,
            package_id="com.example.demo",
            version_name="2.0.0",
            version_code="20",
            device_manufacturer="Samsung",
            device_model="SM-S921B",
            os_name="Android",
            os_version="16",
            os_build="BP2A.test",
            scenario_id="gps-background",
            scenario_title="GPS background journey",
            capabilities=["gps", "background"],
            preconditions=["Location permission granted", "Battery above 30%"],
            steps=[
                {
                    "action": "Start journey and lock device",
                    "expected": "Tracking continues",
                    "observed": "Tracking continued for 10 minutes",
                }
            ],
            expected_result="Journey remains recorded while screen is off.",
            observed_result="Journey remained recorded without gaps.",
            result="PASS",
            evidence_refs=[
                {
                    "kind": "screenshot",
                    "uri": "artifact://phone/screenshot.png",
                    "sha256": "b" * 64,
                    "description": "Final route screenshot",
                }
            ],
            captured_at="2026-10-10T15:00:00+00:00",
            workflow_repository="owner/AppLab",
            workflow_run_id="123",
            workflow_run_attempt="1",
            trusted_applab_sha="c" * 40,
            actor="tester",
        )
        validate_record_structure(record)
        assert compute_record_digest(record) == record["attestation"]["record_digest_sha256"]

        verified = validate_against_artifact(
            record,
            contract,
            apk,
            expected_hub_repository="owner/AppLab",
            expected_hub_run_id="123",
            expected_hub_run_attempt="1",
            expected_hub_head_sha="c" * 40,
            verifier_run_id="456",
            verifier_trusted_applab_sha="d" * 40,
        )
        assert verified["verification"]["state"] == "VERIFIED"
        assert verified["verification"]["exact_artifact_match"] is True
        assert verified["verification"]["evidence_reference_bytes_verified"] is False

        bad = json.loads(json.dumps(record))
        bad["artifact"]["sha256"] = "0" * 64
        bad["attestation"]["record_digest_sha256"] = compute_record_digest(bad)
        try:
            validate_against_artifact(
                bad,
                contract,
                apk,
                expected_hub_repository="owner/AppLab",
                expected_hub_run_id="123",
                expected_hub_head_sha="c" * 40,
                verifier_run_id="456",
                verifier_trusted_applab_sha="d" * 40,
            )
        except ValueError as exc:
            assert "artifact_sha256 binding mismatch" in str(exc)
        else:
            raise AssertionError("Physical evidence artifact mismatch must fail")

        forged = json.loads(json.dumps(record))
        forged["scenario"]["observed_result"] = "Tampered"
        try:
            validate_record_structure(forged)
        except ValueError as exc:
            assert "record digest mismatch" in str(exc)
        else:
            raise AssertionError("Tampered physical record digest must fail")

    print("AppLab v4.5 Physical Evidence Hub self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=False)

    create = sub.add_parser("create")
    create.add_argument("--repository", required=True)
    create.add_argument("--resolved-sha", required=True)
    create.add_argument("--artifact-sha256", required=True)
    create.add_argument("--package-id", required=True)
    create.add_argument("--version-name", required=True)
    create.add_argument("--version-code", required=True)
    create.add_argument("--device-manufacturer", required=True)
    create.add_argument("--device-model", required=True)
    create.add_argument("--os-name", default="Android")
    create.add_argument("--os-version", required=True)
    create.add_argument("--os-build", required=True)
    create.add_argument("--scenario-id", required=True)
    create.add_argument("--scenario-title", required=True)
    create.add_argument("--capabilities-json", required=True)
    create.add_argument("--preconditions-json", default="[]")
    create.add_argument("--steps-json", required=True)
    create.add_argument("--expected-result", required=True)
    create.add_argument("--observed-result", required=True)
    create.add_argument("--result", required=True)
    create.add_argument("--evidence-refs-json", required=True)
    create.add_argument("--captured-at", required=True)
    create.add_argument("--workflow-repository", required=True)
    create.add_argument("--workflow-run-id", required=True)
    create.add_argument("--workflow-run-attempt", required=True)
    create.add_argument("--trusted-applab-sha", required=True)
    create.add_argument("--actor", required=True)
    create.add_argument("--output", required=True)
    create.add_argument("--summary", required=True)

    verify_run = sub.add_parser("verify-run")
    verify_run.add_argument("--repository", required=True)
    verify_run.add_argument("--run-id", required=True)
    verify_run.add_argument("--token-env", default="GITHUB_TOKEN")

    validate = sub.add_parser("validate")
    validate.add_argument("--record", required=True)
    validate.add_argument("--contract", required=True)
    validate.add_argument("--artifact", required=True)
    validate.add_argument("--expected-hub-repository", required=True)
    validate.add_argument("--expected-hub-run-id", required=True)
    validate.add_argument("--expected-hub-run-attempt", required=True)
    validate.add_argument("--expected-hub-head-sha", required=True)
    validate.add_argument("--verifier-run-id", required=True)
    validate.add_argument("--verifier-trusted-applab-sha", required=True)
    validate.add_argument("--output", required=True)
    validate.add_argument("--summary", required=True)

    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if args.command == "create":
        record = make_record(
            repository=args.repository,
            resolved_sha=args.resolved_sha,
            artifact_sha256=args.artifact_sha256,
            package_id=args.package_id,
            version_name=args.version_name,
            version_code=args.version_code,
            device_manufacturer=args.device_manufacturer,
            device_model=args.device_model,
            os_name=args.os_name,
            os_version=args.os_version,
            os_build=args.os_build,
            scenario_id=args.scenario_id,
            scenario_title=args.scenario_title,
            capabilities=parse_json_value(args.capabilities_json, "capabilities-json", list),
            preconditions=parse_json_value(args.preconditions_json, "preconditions-json", list),
            steps=parse_json_value(args.steps_json, "steps-json", list),
            expected_result=args.expected_result,
            observed_result=args.observed_result,
            result=args.result,
            evidence_refs=parse_json_value(args.evidence_refs_json, "evidence-refs-json", list),
            captured_at=args.captured_at,
            workflow_repository=args.workflow_repository,
            workflow_run_id=args.workflow_run_id,
            workflow_run_attempt=args.workflow_run_attempt,
            trusted_applab_sha=args.trusted_applab_sha,
            actor=args.actor,
        )
        write_record(Path(args.output), record)
        Path(args.summary).write_text(render_markdown(record, verified=False), encoding="utf-8")
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0

    if args.command == "verify-run":
        token = os.getenv(args.token_env, "").strip()
        result = verify_hub_run(args.repository, args.run_id, token)
        write_github_output(result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "validate":
        record = read_json(Path(args.record))
        contract = read_json(Path(args.contract))
        verified = validate_against_artifact(
            record,
            contract,
            Path(args.artifact),
            expected_hub_repository=args.expected_hub_repository,
            expected_hub_run_id=args.expected_hub_run_id,
            expected_hub_run_attempt=args.expected_hub_run_attempt,
            expected_hub_head_sha=args.expected_hub_head_sha,
            verifier_run_id=args.verifier_run_id,
            verifier_trusted_applab_sha=args.verifier_trusted_applab_sha,
        )
        write_record(Path(args.output), verified)
        Path(args.summary).write_text(render_markdown(verified, verified=True), encoding="utf-8")
        print(json.dumps(verified, indent=2, sort_keys=True))
        return 0

    raise SystemExit("Choose create, verify-run, validate or --self-test")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, AssertionError) as exc:
        raise SystemExit(f"AppLab Physical Evidence Hub failed: {exc}") from exc
