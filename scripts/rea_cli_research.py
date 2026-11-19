#!/usr/bin/env python3
"""Opt-in REA CLI research for extracted desktop trees, managed PE, Android APK, Flutter APK.

No MCP, no target execution, no donor promotion and no trusted runtime evidence.
Use private output storage: raw REA output may disclose strings or package metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from rea_artifact_intake import fingerprint
from rea_cli_bridge import BridgeBlocked, execute_json, validate_command, EXPECTED_REA_VERSION, PINNED_REA_SOURCE

OPERATIONS = {
    "desktop": ("inspect-desktop-application",),
    "managed": ("inspect-managed-artifact", "inspect-managed-members"),
    "android": ("inspect-android-package",),
    "flutter": ("identify-flutter-build", "inspect-dart-aot"),
}
MAX_BYTES = 512 * 1024 * 1024
MAX_DIRECTORY_BYTES = 1024 * 1024 * 1024
MAX_FILES = 4000
SHA40 = re.compile(r"^[a-fA-F0-9]{40}$")
SHA64 = re.compile(r"^[a-fA-F0-9]{64}$")
REPO = re.compile(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")


def inspect_local_file(path: Path, budget: int) -> dict:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise BridgeBlocked("Input must be a regular file, not a symlink")
    identity = fingerprint(path, budget)
    return {"type": "file", **identity}


def inspect_apk(path: Path, budget: int) -> dict:
    if path.suffix.lower() != ".apk":
        raise BridgeBlocked("Android/Flutter input must be an .apk, not an AAB or split set")
    ident = inspect_local_file(path, budget)
    try:
        with zipfile.ZipFile(path) as apk:
            members = apk.infolist()
            if len(members) > 20000:
                raise BridgeBlocked("APK ZIP entry count exceeds limit")
            if "AndroidManifest.xml" not in {m.filename for m in members}:
                raise BridgeBlocked("APK missing AndroidManifest.xml")
            names = set()
            for member in members:
                posix = PurePosixPath(member.filename)
                if (posix.is_absolute() or ".." in posix.parts or "\\" in member.filename
                        or ((member.external_attr >> 16) & 0o170000) == stat.S_IFLNK):
                    raise BridgeBlocked("APK has unsafe ZIP entry")
                if member.filename in names:
                    raise BridgeBlocked("APK ZIP duplicate entry")
                names.add(member.filename)
            ident["zip_entries"] = len(members)
            ident["flutter_aot_libraries"] = sorted(
                x for x in names if re.fullmatch(r"lib/[^/]+/libapp\.so", x))
    except (zipfile.BadZipFile, OSError) as exc:
        raise BridgeBlocked("APK not a readable ZIP archive") from exc
    return ident


def inspect_tree(root: Path) -> dict:
    if not root.is_dir() or root.is_symlink():
        raise BridgeBlocked("Desktop root must be a real directory")
    sha = hashlib.sha256()
    count = 0
    total = 0
    root_real = root.resolve()
    def reject_walk_error(error: OSError) -> None:
        raise BridgeBlocked("Desktop tree contains inaccessible directory") from error
    for parent, dirs, files in os.walk(
            root, topdown=True, followlinks=False, onerror=reject_walk_error):
        for name in sorted(dirs):
            child = Path(parent, name)
            if child.is_symlink():
                raise BridgeBlocked("Directory contains symlink")
        dirs.sort()
        for name in sorted(files):
            path = Path(parent, name)
            st = path.lstat()
            if stat.S_ISLNK(st.st_mode):
                raise BridgeBlocked("Directory contains symlink")
            if not stat.S_ISREG(st.st_mode):
                raise BridgeBlocked("Directory contains nonregular entry")
            count += 1
            total += st.st_size
            if count > MAX_FILES or total > MAX_DIRECTORY_BYTES:
                raise BridgeBlocked("Directory exceeds file count/byte limit")
            if not path.resolve().is_relative_to(root_real):
                raise BridgeBlocked("Directory traversal blocked")
            rel = path.relative_to(root).as_posix()
            before = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    digest.update(block)
            last = path.lstat()
            if before != (last.st_dev, last.st_ino, last.st_size, last.st_mtime_ns):
                raise BridgeBlocked("Desktop tree changed during hashing")
            sha.update(json.dumps([rel, st.st_size, digest.hexdigest()],
                                  ensure_ascii=True, separators=(",", ":")).encode())
            sha.update(b"\n")
    if count == 0:
        raise BridgeBlocked("Desktop inventory is empty")
    return {"type": "directory", "basename": root.name, "sha256": sha.hexdigest(),
            "bytes": total, "files": count}


def write_proof(directory: Path, name: str, payload: bytes) -> dict:
    dest = directory / name
    if dest.is_symlink():
        raise BridgeBlocked("Evidence path must not be a symlink")
    if dest.exists():
        if not dest.is_file() or dest.read_bytes() != payload:
            raise BridgeBlocked("Evidence collision / divergent immutable report")
    else:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
    return {"file": name, "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload)}


def invoke(rea_bin: Path, entry: Path | None, target: Path, output_dir: Path,
           mode: str, operations: list[str], repository: str, source_sha: str,
           expected_sha: str | None = None, max_bytes: int = 64 * 1024 * 1024,
           timeout: int = 90) -> dict:
    if mode not in OPERATIONS:
        raise BridgeBlocked("Unknown research mode")
    if not REPO.fullmatch(repository) or not SHA40.fullmatch(source_sha):
        raise BridgeBlocked("Repository and immutable 40-hex source SHA required")
    if expected_sha and not SHA64.fullmatch(expected_sha):
        raise BridgeBlocked("Invalid expected SHA-256")
    if not target.is_absolute() or not output_dir.is_absolute():
        raise BridgeBlocked("Target and output paths must be absolute")
    if not 0 < max_bytes <= MAX_BYTES or not 5 <= timeout <= 240:
        raise BridgeBlocked("File budget or timeout outside supported bounds")
    allowed = OPERATIONS[mode]
    if not operations or any(op not in allowed for op in operations) or len(set(operations)) != len(operations):
        raise BridgeBlocked("Unsupported or duplicate REA operation")
    if mode == "desktop":
        ident = inspect_tree(target)
        if output_dir.resolve() == target.resolve() or output_dir.resolve().is_relative_to(target.resolve()):
            raise BridgeBlocked("Evidence output must be outside the desktop target tree")
    elif mode in ("android", "flutter"):
        ident = inspect_apk(target, max_bytes)
    else:
        ident = inspect_local_file(target, max_bytes)
        if ident["container"] != "PE":
            raise BridgeBlocked("Managed inspection requires PE/CLI candidate")
    if expected_sha and expected_sha.lower() != ident["sha256"]:
        raise BridgeBlocked("Input SHA-256 mismatch: expected specific immutable artifact")
    invocation = validate_command(rea_bin, entry)
    engine_paths = {Path(p).resolve() for p in invocation}
    real_target = target.resolve()
    if mode != "desktop" and real_target in engine_paths:
        raise BridgeBlocked("REA executable/entry cannot equal the inspected artifact")
    if mode == "desktop" and any(p.is_relative_to(real_target) for p in engine_paths):
        raise BridgeBlocked("REA executable/entry cannot reside inside inspected desktop tree")
    rc, version, _ = execute_json([*invocation, "--version", "--json"], 20)
    if (rc != 0 or version.get("name") != "rea-agents"
            or version.get("version") != EXPECTED_REA_VERSION
            or version.get("supported_runtime", {}).get("satisfied") is not True):
        raise BridgeBlocked("REA version/runtime mismatch")
    if output_dir.is_symlink():
        raise BridgeBlocked("Output directory cannot be symlink")
    if target.is_file() and output_dir.resolve() == target.parent.resolve():
        raise BridgeBlocked("Use private output outside artifact directory")
    output_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    receipts = []
    status = "REA_RESEARCH_OBSERVED"
    for operation in operations:
        if mode == "flutter" and operation == "inspect-dart-aot" and not ident["flutter_aot_libraries"]:
            receipts.append({"operation": operation, "status": "NOT_APPLICABLE_NO_LIBAPP_SO"})
            continue
        command = [*invocation, operation, str(target), "--json"]
        bundle = None
        if operation == "inspect-android-package":
            # JADX can produce very large source graphs. Require a retained
            # complete report for the compact package summary.
            # Dart AOT uses its bounded direct JSON mode instead; older
            # releases may refuse compact AOT request/retention options.
            with tempfile.TemporaryDirectory(prefix="rea-bundle-", dir=output_dir) as tempdir:
                raw_path = Path(tempdir) / "full-evidence.json"
                command.extend(["--detail", "summary", "--evidence_output", str(raw_path)])
                rc, data, payload = execute_json(command, timeout)
                if rc == 0:
                    if (not raw_path.is_file() or raw_path.is_symlink()
                            or raw_path.stat().st_size > 256 * 1024 * 1024):
                        raise BridgeBlocked("REA did not produce bounded full evidence bundle")
                    bundle = write_proof(output_dir,
                        f"{ident['sha256'][:14]}-{operation}-full.json",
                        raw_path.read_bytes())
        else:
            rc, data, payload = execute_json(command, timeout)
        evidence = write_proof(output_dir, f"{ident['sha256'][:14]}-{operation}.json", payload)
        result = data.get("normalized_result")
        normalized_keys = sorted(result) if isinstance(result, dict) else []
        op_status = "OBSERVED" if rc == 0 else "REA_FAILED"
        receipts.append({"operation": operation, "status": op_status, "exit_code": rc,
                         "evidence": evidence, "full_bundle": bundle,
                         "normalized_keys": normalized_keys,
                         "review": "UNVALIDATED_EXTERNAL_OUTPUT"})
        if rc != 0:
            status = "REA_RESEARCH_PARTIAL_OR_FAILED"
    if mode == "desktop":
        after = inspect_tree(target)
    elif mode in ("android", "flutter"):
        after = inspect_apk(target, max_bytes)
    else:
        after = inspect_local_file(target, max_bytes)
    if after != ident:
        raise BridgeBlocked("Target changed during REA research; discard receipt")
    return {
        "schema_version": 1, "type": "REA_RESEARCH_CLI_RECEIPT",
        "mode": mode, "status": status, "engine": {"version": EXPECTED_REA_VERSION,
        "source_sha": PINNED_REA_SOURCE}, "repository": repository,
        "source_sha": source_sha.lower(), "artifact": ident, "operations": receipts,
        "donor_admission": "RESEARCH_ONLY", "trusted_runtime": False,
        "automatic_goldens": False, "execution_of_target": "NONE",
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=sorted(OPERATIONS), required=True)
    p.add_argument("--rea-bin", type=Path, required=True)
    p.add_argument("--rea-entry", type=Path)
    p.add_argument("--artifact", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--repository", required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--expected-sha256")
    p.add_argument("--operation", choices=sorted({op for ops in OPERATIONS.values() for op in ops}), action="append")
    p.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    p.add_argument("--timeout", type=int, default=90)
    args = p.parse_args()
    try:
        receipt = invoke(args.rea_bin, args.rea_entry, args.artifact, args.output_dir,
                         args.mode, args.operation or (["inspect-managed-artifact"] if args.mode == "managed" else list(OPERATIONS[args.mode])),
                         args.repository, args.source_sha, args.expected_sha256,
                         args.max_bytes, args.timeout)
    except (BridgeBlocked, OSError, ValueError, KeyError) as exc:
        print(f"REA RESEARCH BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if receipt["status"] == "REA_RESEARCH_OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
