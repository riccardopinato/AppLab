#!/usr/bin/env python3
"""Optional REA CLI research adapter: Desktop, managed PE, Android/JADX, Flutter AOT.

Only static, authorized local artifact inspection. No MCP, installer execution,
implicit dependency installation, E3 admission, or trusted runtime proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

from rea_cli_bridge import (BridgeBlocked, EXPECTED_REA_VERSION,
                            PINNED_REA_SOURCE, execute_json, validate_command)

MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 10000
JADX_SHA256 = "6e5eacf500b64292bfb73c49797c1958f6ee44646e43e868039ae7feb573ff75"
SHA = re.compile(r"^[a-f0-9]{64}$", re.I)
SHA40 = re.compile(r"^[a-f0-9]{40}$", re.I)
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COMMANDS = {
    "desktop": {"inventory": "inspect-desktop-application"},
    "managed": {"metadata": "inspect-managed-artifact"},
    "flutter": {"build": "identify-flutter-build", "aot": "inspect-dart-aot"},
    "android": {"package": "inspect-android-package"},
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def identity(path: Path, mode: str, max_bytes: int) -> dict:
    if not path.is_absolute():
        raise BridgeBlocked("Use an absolute artifact or directory path")
    st = path.lstat()  # fail closed on top-level symlinks
    if mode == "desktop":
        if not stat.S_ISDIR(st.st_mode):
            raise BridgeBlocked("desktop inventory requires a real directory")
        seen = 0
        total = 0
        digest = hashlib.sha256()
        for f in sorted(path.rglob("*"), key=lambda q: q.relative_to(path).as_posix()):
            statinfo = f.lstat()
            if stat.S_ISLNK(statinfo.st_mode):
                raise BridgeBlocked("desktop tree contains symlink; reject cross-root ambiguity")
            if f.is_dir():
                continue
            if not stat.S_ISREG(statinfo.st_mode):
                raise BridgeBlocked("desktop tree contains special file")
            seen += 1
            total += statinfo.st_size
            if seen > MAX_FILES or total > max_bytes:
                raise BridgeBlocked("desktop inventory exceeds file/count budget")
            rel = f.relative_to(path).as_posix()
            digest.update(json.dumps([rel, statinfo.st_size, sha256(f)],
                                     ensure_ascii=True, separators=(",", ":")).encode())
        return {"kind": "directory", "count": seen, "bytes": total,
                "sha256": digest.hexdigest()}
    if not stat.S_ISREG(st.st_mode):
        raise BridgeBlocked("requires a regular file, not a directory or symlink")
    if st.st_size <= 0 or st.st_size > max_bytes:
        raise BridgeBlocked("file size outside configured limit")
    with path.open("rb") as fh:
        header = fh.read(4)
    if mode == "managed" and header[:2] != b"MZ":
        raise BridgeBlocked("managed mode requires a PE file (MZ)")
    if mode in {"flutter", "android"} and header[:4] != b"PK\x03\x04":
        raise BridgeBlocked("Android/Flutter mode requires a ZIP/APK header")
    return {"kind": "file", "bytes": st.st_size, "sha256": sha256(path)}


def validate_jadx(jar: Path | None) -> None:
    if jar is None or not jar.is_absolute() or not jar.is_file() or jar.is_symlink():
        raise BridgeBlocked("Android JADX mode requires --jadx-jar absolute regular file")
    if sha256(jar) != JADX_SHA256:
        raise BridgeBlocked("JADX JAR checksum mismatch; no Android analysis started")
    os.environ["REA_JADX_MCP_JAR"] = str(jar)


def run(rea_bin: Path, artifact: Path, output_dir: Path, repository: str,
        source_sha: str, mode: str, operations: list[str] | None = None,
        max_bytes: int = 64 * 1024 * 1024, timeout: int = 120,
        expected_sha256: str | None = None, rea_entry: Path | None = None,
        jadx_jar: Path | None = None) -> dict:
    if mode not in COMMANDS or not REPO.fullmatch(repository) or not SHA40.fullmatch(source_sha):
        raise BridgeBlocked("Invalid operation family, repository or immutable source SHA")
    if not 5 <= timeout <= 180 or not 0 < max_bytes <= MAX_BYTES:
        raise BridgeBlocked("Resource budget outside approved limits")
    chosen = operations or list(COMMANDS[mode])
    if not chosen or len(set(chosen)) != len(chosen) or any(o not in COMMANDS[mode] for o in chosen):
        raise BridgeBlocked("Operation not allowlisted for selected family")
    if not output_dir.is_absolute() or output_dir.is_symlink():
        raise BridgeBlocked("Evidence directory must be absolute and not a symlink")
    before = identity(artifact, mode, max_bytes)
    if expected_sha256 is not None:
        if not SHA.fullmatch(expected_sha256) or before["sha256"] != expected_sha256.lower():
            raise BridgeBlocked("Expected source artifact hash mismatch")
    if mode == "android":
        validate_jadx(jadx_jar)
    invocation = validate_command(rea_bin, rea_entry)
    rc, version, _ = execute_json([*invocation, "--version", "--json"], 20)
    if (rc != 0 or version.get("name") != "rea-agents" or
            version.get("version") != EXPECTED_REA_VERSION or
            version.get("supported_runtime", {}).get("satisfied") is not True):
        raise BridgeBlocked("Wrong REA version or unsupported Node runtime")
    if artifact.resolve() in {Path(x).resolve() for x in invocation}:
        raise BridgeBlocked("Target cannot be REA executable")
    output_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not output_dir.is_dir() or output_dir.resolve() == artifact.resolve() or (
            artifact.is_dir() and output_dir.resolve().is_relative_to(artifact.resolve())):
        raise BridgeBlocked("Evidence directory must be outside inspected tree")
    receipts = []
    for op in chosen:
        argv = [*invocation, COMMANDS[mode][op], str(artifact), "--json"]
        code, response, raw = execute_json(argv, timeout)
        # The tool returns external observations; do not rewrite tool results as certification.
        name = f"rea-{mode}-{before['sha256'][:16]}-{op}.json"
        dest = output_dir / name
        if dest.exists():
            if not dest.is_file() or dest.is_symlink() or sha256(dest) != hashlib.sha256(raw).hexdigest():
                raise BridgeBlocked("Evidence collision / previously changed report")
        else:
            fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
        receipts.append({"operation": op, "command": COMMANDS[mode][op],
                         "exit_code": code, "cli_success": code == 0,
                         "json_file": name, "sha256": hashlib.sha256(raw).hexdigest(),
                         "bytes": len(raw),
                         "review": "UNVALIDATED_EXTERNAL_OUTPUT"})
    after = identity(artifact, mode, max_bytes)
    if after != before:
        raise BridgeBlocked("Input mutated while inspecting it: discard external evidence")
    result = {"schema_version": 1, "status": (
        "REA_CLI_STATIC_OBSERVED" if all(x["cli_success"] for x in receipts)
        else "REA_CLI_PARTIAL_OR_FAILED"), "mode": "CLI_ONLY_NO_MCP",
        "family": mode, "repository": repository, "source_sha": source_sha.lower(),
        "input": before, "rea_version": EXPECTED_REA_VERSION,
        "rea_source_sha": PINNED_REA_SOURCE, "operations": receipts,
        "license_and_source_review": "REQUIRED",
        "admission": "RESEARCH_ONLY_NOT_TRUSTED_RUNTIME_NOT_DONOR",
        "independent_runtime_certified": False}
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rea-bin", type=Path, required=True)
    p.add_argument("--rea-entry", type=Path)
    p.add_argument("--artifact", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--repository", required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--family", choices=sorted(COMMANDS), required=True)
    p.add_argument("--operation", action="append")
    p.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--expected-sha256")
    p.add_argument("--jadx-jar", type=Path)
    args = p.parse_args()
    try:
        result = run(args.rea_bin, args.artifact, args.output_dir, args.repository,
                     args.source_sha, args.family, args.operation, args.max_bytes,
                     args.timeout, args.expected_sha256, args.rea_entry, args.jadx_jar)
    except (BridgeBlocked, OSError, ValueError) as exc:
        print(f"REA BOUNDED RESEARCH BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "REA_CLI_STATIC_OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
