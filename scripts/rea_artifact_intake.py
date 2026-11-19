#!/usr/bin/env python3
"""Read-only local artifact identity intake for REA/AppLab research.

Does not execute software, decompile, invoke REA or certify a donor.
External REA reports are fingerprinted, not trusted or interpreted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import struct
import sys
from pathlib import Path

MAX_ALLOWED = 2 * 1024**3
DEFAULT_LIMIT = 512 * 1024**2
SHA40 = re.compile(r"^[a-fA-F0-9]{40}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MACHINES = {0x014C: "x86", 0x8664: "x86_64", 0xAA64: "arm64"}


def fingerprint(path: Path, limit: int) -> dict:
    if not 0 < limit <= MAX_ALLOWED:
        raise ValueError("max-bytes outside supported bound")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Only regular files; no symlinks or directories")
    if before.st_size > limit:
        raise ValueError("Artifact exceeds max-bytes")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        prefix = handle.read(64)
        handle.seek(0)
        actual = 0
        while chunk := handle.read(1024 * 1024):
            actual += len(chunk)
            if actual > limit:
                raise ValueError("Artifact grew beyond max-bytes")
            digest.update(chunk)
        pe_header = b""
        if len(prefix) >= 64 and prefix.startswith(b"MZ"):
            offset = struct.unpack_from("<I", prefix, 0x3C)[0]
            if offset <= actual - 6:
                handle.seek(offset)
                pe_header = handle.read(6)
    after = path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if identity(before) != identity(after) or actual != before.st_size:
        raise ValueError("Artifact changed while being inspected")
    pe = pe_header.startswith(b"PE\x00\x00")
    machine = struct.unpack_from("<H", pe_header, 4)[0] if pe else None
    return {
        "basename": path.name,
        "bytes": actual,
        "sha256": digest.hexdigest(),
        "container": "PE" if pe else ("MZ_UNCONFIRMED" if prefix.startswith(b"MZ") else "UNKNOWN"),
        "pe_machine": MACHINES.get(machine, f"unknown_0x{machine:04x}") if pe else None,
    }


def intake(artifact: Path, repository: str, source_sha: str,
           rea_commit: str, rea_report: Path | None = None,
           max_bytes: int = DEFAULT_LIMIT) -> dict:
    if not REPO.fullmatch(repository) or not SHA40.fullmatch(source_sha):
        raise ValueError("Repository owner/name and immutable 40-hex source SHA required")
    if not SHA40.fullmatch(rea_commit):
        raise ValueError("Immutable 40-hex REA commit required")
    evidence = fingerprint(artifact, max_bytes)
    external = None
    if rea_report:
        if rea_report.resolve() == artifact.resolve():
            raise ValueError("REA report must be distinct from target artifact")
        report = fingerprint(rea_report, 16 * 1024 * 1024)
        external = {
            "basename": report["basename"],
            "sha256": report["sha256"],
            "bytes": report["bytes"],
            "trust": "UNVALIDATED_EXTERNAL_OUTPUT",
        }
    return {
        "schema_version": 1,
        "report_type": "REVERSE_INTELLIGENCE_STATIC_INTAKE",
        "repository": repository,
        "source_sha": source_sha.lower(),
        "rea_upstream": f"morluto/rea@{rea_commit.lower()}",
        "artifact": evidence,
        "rea_report_reference": external,
        "execution": "NONE",
        "artifact_identity": "LOCALLY_OBSERVED",
        "architecture_inferred_from_binary": "NOT_VERIFIED",
        "observed_functional_behavior": "NOT_VERIFIED",
        "target_license": "NOT_VERIFIED",
        "android_reimplementation": "NOT_VERIFIED",
        "donor_admission": "RESEARCH_ONLY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--rea-commit", required=True)
    parser.add_argument("--rea-report", type=Path)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()
    try:
        output = intake(args.artifact, args.repository, args.source_sha,
                        args.rea_commit, args.rea_report, args.max_bytes)
    except (OSError, ValueError) as exc:
        print(f"STATIC INTAKE BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
