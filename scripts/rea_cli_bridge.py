#!/usr/bin/env python3
"""Opt-in, evidence-only REA CLI bridge for local PE inspection (no MCP)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from rea_artifact_intake import fingerprint

EXPECTED_REA_VERSION = "6.9.0"
PINNED_REA_SOURCE = "4491c84c82140a43fa12390b727840a433875ba8"
MAX_ARTIFACT = 512 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
OPERATIONS = {"imports": "inspect-pe-imports", "certificates": "inspect-pe-certificates"}
SHA40 = re.compile(r"^[0-9a-fA-F]{40}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class BridgeBlocked(Exception):
    pass


def execute_json(argv: list[str], seconds: int) -> tuple[int, dict, bytes]:
    """Bounded-time subprocess, no shell; parse JSON only after a size check."""
    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            result = subprocess.run(argv, stdout=stdout, stderr=stderr,
                                    timeout=seconds, check=False)
            if stdout.tell() > MAX_OUTPUT or stderr.tell() > 128 * 1024:
                raise BridgeBlocked("REA output exceeds review limit")
            stdout.seek(0)
            payload = stdout.read()
            if not payload:
                raise BridgeBlocked("REA CLI returned no JSON; check local REA installation")
            try:
                parsed = json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BridgeBlocked("REA CLI produced invalid JSON") from exc
            if not isinstance(parsed, dict):
                raise BridgeBlocked("REA CLI JSON must be an object")
            return result.returncode, parsed, payload
    except subprocess.TimeoutExpired as exc:
        raise BridgeBlocked(f"REA command exceeded {seconds}s timeout") from exc
    except OSError as exc:
        raise BridgeBlocked(f"REA executable could not be started: {exc.__class__.__name__}") from exc


def validate_command(path: Path, entry: Path | None) -> list[str]:
    if not path.is_absolute():
        raise BridgeBlocked("Pass an absolute --rea-bin path")
    if path.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        raise BridgeBlocked("Windows shell shims are forbidden; use node.exe and --rea-entry")
    binary = path.resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise BridgeBlocked("REA executable is not launchable")
    if entry is not None:
        if binary.name.lower() not in {"node", "node.exe"}:
            raise BridgeBlocked("--rea-entry requires a direct Node executable")
        if not entry.is_absolute() or entry.suffix.lower() != ".mjs":
            raise BridgeBlocked("REA entrypoint must be an absolute .mjs file")
        file = entry.resolve(strict=True)
        if not file.is_file():
            raise BridgeBlocked("REA entrypoint is missing")
        return [str(binary), str(file)]
    return [str(binary)]


def run(rea_bin: Path, artifact: Path, output_dir: Path, repository: str,
        source_sha: str, operations: list[str], timeout: int, max_bytes: int,
        rea_entry: Path | None = None) -> dict:
    if not REPO.fullmatch(repository) or not SHA40.fullmatch(source_sha):
        raise BridgeBlocked("Provide repository owner/name and a 40-hex source SHA")
    if not 5 <= timeout <= 180 or not 0 < max_bytes <= MAX_ARTIFACT:
        raise BridgeBlocked("Invalid timeout or file budget")
    if not artifact.is_absolute() or not output_dir.is_absolute():
        raise BridgeBlocked("Artifact and output directory paths must be absolute")
    if not operations or any(op not in OPERATIONS for op in operations):
        raise BridgeBlocked("Unsupported static operation")
    if len(set(operations)) != len(operations):
        raise BridgeBlocked("Duplicate static operation")
    if not stat.S_ISREG(artifact.lstat().st_mode):
        raise BridgeBlocked("Artifact must be a regular file, not a symlink")
    try:
        identity = fingerprint(artifact, max_bytes)
    except (OSError, ValueError) as exc:
        raise BridgeBlocked(f"Artifact intake rejected: {exc}") from exc
    if identity["container"] != "PE":
        raise BridgeBlocked("PE static commands require a confirmed PE header")
    invocation = validate_command(rea_bin, rea_entry)
    if artifact.resolve() in {Path(x) for x in invocation}:
        raise BridgeBlocked("REA executable cannot be the inspected artifact")
    rc, version, _ = execute_json([*invocation, "--version", "--json"], 20)
    if (rc != 0 or version.get("name") != "rea-agents"
            or version.get("version") != EXPECTED_REA_VERSION
            or version.get("supported_runtime", {}).get("satisfied") is not True):
        raise BridgeBlocked("REA version/runtime mismatch; require pinned 6.9.0 and supported Node")
    if output_dir.exists() and output_dir.is_symlink():
        raise BridgeBlocked("Output directory cannot be a symlink")
    output_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not output_dir.is_dir() or output_dir.resolve() == artifact.parent.resolve():
        raise BridgeBlocked("Use a dedicated output directory separate from the artifact")
    receipts = []
    overall = "REA_CLI_STATIC_OBSERVED"
    for operation in operations:
        command = [*invocation, OPERATIONS[operation], str(artifact), "--json"]
        if max_bytes > 64 * 1024 * 1024:
            command.extend(["--max-file-bytes", str(max_bytes)])
        rc, data, payload = execute_json(command, timeout)
        filename = f"rea-{identity['sha256'][:12]}-{operation}.json"
        destination = output_dir / filename
        # Never overwrite a previous evidence file, even across retries.
        if destination.exists():
            if not destination.is_file() or destination.read_bytes() != payload:
                raise BridgeBlocked(f"Evidence collision: {filename}")
        else:
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
        receipts.append({
            "operation": operation,
            "exit_code": rc,
            "evidence_file": filename,
            "evidence_sha256": hashlib.sha256(payload).hexdigest(),
            "evidence_bytes": len(payload),
            "review": "UNVALIDATED_EXTERNAL_OUTPUT",
            "rea_success": rc == 0,
        })
        if rc != 0:
            overall = "REA_CLI_PARTIAL_OR_FAILED"
    # Detect a replaced installer after CLI reads, but do not claim atomic snapshots.
    try:
        after = fingerprint(artifact, max_bytes)
    except (OSError, ValueError) as exc:
        raise BridgeBlocked("Artifact unavailable for post-analysis identity check") from exc
    if identity != after:
        raise BridgeBlocked("Artifact changed during CLI analysis; discard evidence")
    return {
        "schema_version": 1,
        "status": overall,
        "mode": "CLI_ONLY_NO_MCP",
        "engine": {"package": "rea-agents", "version": EXPECTED_REA_VERSION,
                   "source_sha": PINNED_REA_SOURCE},
        "repository": repository,
        "source_sha": source_sha.lower(),
        "artifact": identity,
        "operations": receipts,
        "donor_admission": "RESEARCH_ONLY",
        "runtime_or_visual_certified": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rea-bin", required=True, type=Path)
    p.add_argument("--rea-entry", type=Path, help="Windows: absolute node_modules/rea-agents/scripts/rea.mjs")
    p.add_argument("--artifact", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--repository", required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--operation", choices=sorted(OPERATIONS), action="append")
    p.add_argument("--timeout", type=int, default=45)
    p.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    args = p.parse_args()
    try:
        receipt = run(args.rea_bin, args.artifact, args.output_dir, args.repository,
                      args.source_sha, args.operation or ["imports", "certificates"],
                      args.timeout, args.max_bytes, args.rea_entry)
    except (BridgeBlocked, OSError, ValueError) as exc:
        print(f"REA CLI BRIDGE BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "REA_CLI_STATIC_OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
