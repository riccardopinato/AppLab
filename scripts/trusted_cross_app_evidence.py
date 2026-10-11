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
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
AUTHORITY = "APPLAB_CROSS_APP_VERIFICATION"
RECORD_TYPE = "CROSS_APP_VERIFICATION"
WORKFLOW_PATH = ".github/workflows/cross-app-verification.yml"
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def clean(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def record_digest(payload: dict[str, Any]) -> str:
    clone = json.loads(json.dumps(payload))
    clone.pop("record_digest_sha256", None)
    return hashlib.sha256(canonical_bytes(clone)).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read JSON object: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def github_json(repository: str, run_id: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "AppLab-cross-app-evidence",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("unable to verify cross-app workflow run") from exc
    if not isinstance(payload, dict):
        raise ValueError("cross-app workflow run response is invalid")
    return payload


def verify_run(repository: str, run_id: str, token: str) -> dict[str, str]:
    if not REPO_RE.fullmatch(repository):
        raise ValueError("repository must use owner/name format")
    if not run_id.isdigit():
        raise ValueError("run id must be numeric")
    payload = github_json(repository, run_id, token)
    if clean(payload.get("path")) != WORKFLOW_PATH:
        raise ValueError("run is not AppLab Cross-App Verification")
    if clean(payload.get("event")) != "workflow_dispatch":
        raise ValueError("cross-app run must be workflow_dispatch")
    if clean(payload.get("head_branch")) != "main":
        raise ValueError("cross-app run must originate from main")
    if clean(payload.get("status")) != "completed" or clean(payload.get("conclusion")) != "success":
        raise ValueError("cross-app run must be completed successfully")
    head_sha = clean(payload.get("head_sha")).lower()
    if not SHA40_RE.fullmatch(head_sha):
        raise ValueError("cross-app run head SHA is invalid")
    attempt = str(payload.get("run_attempt", "")).strip()
    if not attempt.isdigit():
        raise ValueError("cross-app run attempt is invalid")
    return {
        "artifact_name": f"applab-cross-app-verification-{run_id}-{attempt}",
        "run_attempt": attempt,
        "head_sha": head_sha,
    }


def validate_record(
    record: dict[str, Any],
    *,
    expected_repository: str,
    expected_sha: str,
    workflow_repository: str,
    run_id: str,
    run_attempt: str,
    head_sha: str,
) -> None:
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("cross-app evidence schema_version mismatch")
    if clean(record.get("authority")) != AUTHORITY:
        raise ValueError("cross-app evidence authority mismatch")
    if clean(record.get("record_type")) != RECORD_TYPE:
        raise ValueError("cross-app evidence record_type mismatch")

    attestation = record.get("attestation")
    if not isinstance(attestation, dict):
        raise ValueError("cross-app evidence attestation is missing")
    checks = {
        "workflow_repository": (clean(attestation.get("workflow_repository")), workflow_repository),
        "workflow_path": (clean(attestation.get("workflow_path")), WORKFLOW_PATH),
        "workflow_run_id": (clean(attestation.get("workflow_run_id")), run_id),
        "workflow_run_attempt": (clean(attestation.get("workflow_run_attempt")), run_attempt),
        "trusted_applab_sha": (clean(attestation.get("trusted_applab_sha")).lower(), head_sha),
        "event": (clean(attestation.get("event")), "workflow_dispatch"),
    }
    for label, (observed, expected) in checks.items():
        if observed != expected:
            raise ValueError(f"cross-app evidence {label} mismatch")

    expected_digest = clean(record.get("record_digest_sha256")).lower()
    if not SHA256_RE.fullmatch(expected_digest):
        raise ValueError("cross-app evidence digest is invalid")
    if record_digest(record) != expected_digest:
        raise ValueError("cross-app evidence digest mismatch")

    pair = record.get("pair_identity")
    if not isinstance(pair, dict):
        raise ValueError("cross-app pair identity is missing")
    sides = [
        pair.get("producer") if isinstance(pair.get("producer"), dict) else {},
        pair.get("consumer") if isinstance(pair.get("consumer"), dict) else {},
    ]
    match = any(
        clean(side.get("repository")) == expected_repository
        and clean(side.get("resolved_sha")).lower() == expected_sha
        for side in sides
    )
    if not match:
        raise ValueError("cross-app evidence does not contain the reviewed repository/revision")


def write_outputs(path: Path, values: dict[str, str]) -> None:
    output = os.getenv("GITHUB_OUTPUT", "")
    if not output:
        return
    with Path(output).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def self_test() -> None:
    record = {
        "schema_version": 1,
        "authority": AUTHORITY,
        "record_type": RECORD_TYPE,
        "pair_identity": {
            "producer": {
                "repository": "owner/app",
                "resolved_sha": "a" * 40,
            },
            "consumer": {
                "repository": "owner/other",
                "resolved_sha": "b" * 40,
            },
        },
        "attestation": {
            "workflow_repository": "owner/AppLab",
            "workflow_path": WORKFLOW_PATH,
            "workflow_run_id": "123",
            "workflow_run_attempt": "2",
            "trusted_applab_sha": "c" * 40,
            "event": "workflow_dispatch",
        },
    }
    record["record_digest_sha256"] = record_digest(record)
    validate_record(
        record,
        expected_repository="owner/app",
        expected_sha="a" * 40,
        workflow_repository="owner/AppLab",
        run_id="123",
        run_attempt="2",
        head_sha="c" * 40,
    )
    stale = json.loads(json.dumps(record))
    stale["pair_identity"]["producer"]["resolved_sha"] = "d" * 40
    stale["record_digest_sha256"] = record_digest(stale)
    try:
        validate_record(
            stale,
            expected_repository="owner/app",
            expected_sha="a" * 40,
            workflow_repository="owner/AppLab",
            run_id="123",
            run_attempt="2",
            head_sha="c" * 40,
        )
    except ValueError as exc:
        assert "reviewed repository/revision" in str(exc)
    else:
        raise AssertionError("stale cross-app target identity must fail closed")
    tampered = json.loads(json.dumps(record))
    tampered["pair_identity"]["producer"]["repository"] = "owner/tampered"
    try:
        validate_record(
            tampered,
            expected_repository="owner/app",
            expected_sha="a" * 40,
            workflow_repository="owner/AppLab",
            run_id="123",
            run_attempt="2",
            head_sha="c" * 40,
        )
    except ValueError as exc:
        assert "digest mismatch" in str(exc)
    else:
        raise AssertionError("tampered cross-app record must fail closed")
    print("AppLab trusted cross-app evidence self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser("verify-run")
    verify.add_argument("--repository", required=True)
    verify.add_argument("--run-id", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("--record", required=True)
    validate.add_argument("--expected-repository", required=True)
    validate.add_argument("--expected-sha", required=True)
    validate.add_argument("--workflow-repository", required=True)
    validate.add_argument("--run-id", required=True)
    validate.add_argument("--run-attempt", required=True)
    validate.add_argument("--head-sha", required=True)
    validate.add_argument("--output", required=True)

    sub.add_parser("self-test")
    args = parser.parse_args()

    if args.command == "self-test":
        self_test()
        return 0

    if args.command == "verify-run":
        token = os.getenv("GITHUB_TOKEN", "")
        if not token:
            raise ValueError("GITHUB_TOKEN is required")
        values = verify_run(args.repository, args.run_id, token)
        write_outputs(Path("."), values)
        print(json.dumps(values, sort_keys=True))
        return 0

    expected_sha = args.expected_sha.strip().lower()
    if not SHA40_RE.fullmatch(expected_sha):
        raise ValueError("expected SHA must be 40 lowercase hex")
    record = read_json(Path(args.record))
    validate_record(
        record,
        expected_repository=args.expected_repository,
        expected_sha=expected_sha,
        workflow_repository=args.workflow_repository,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        head_sha=args.head_sha.strip().lower(),
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"state": "VERIFIED", "output": args.output}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, AssertionError) as exc:
        raise SystemExit(f"AppLab trusted cross-app evidence failed: {exc}") from exc
