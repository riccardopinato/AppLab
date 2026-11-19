#!/usr/bin/env python3
"""Verify already-extracted desktop payload against a publisher's file manifest.

Does not execute installers or extract archives. Run extraction separately in
an isolated environment; this comparator only verifies regular local files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from pathlib import Path, PurePosixPath

HASH = re.compile(r"^[a-f0-9]{64}$")
MAX_MANIFEST = 5000
MAX_FILE_BYTES = 512 * 1024 * 1024


def compare(root: Path, manifest: Path) -> dict:
    if not root.is_absolute() or not manifest.is_absolute():
        raise ValueError("Paths must be absolute")
    if root.is_symlink() or not root.is_dir() or manifest.is_symlink() or not manifest.is_file():
        raise ValueError("Input directory/manifest must be actual regular objects")
    if manifest.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Oversized manifest")
    rows = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_MANIFEST:
        raise ValueError("Manifest must be a bounded nonempty array")
    seen = set()
    evidence = []
    for entry in rows:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("Malformed manifest row")
        rel = entry["path"].replace("\\", "/")
        parsed = PurePosixPath(rel)
        if parsed.is_absolute() or ".." in parsed.parts or not rel or "\x00" in rel:
            raise ValueError("Unsafe manifest relative path")
        key = rel.casefold()
        if key in seen:
            raise ValueError("Duplicate manifest path")
        seen.add(key)
        expected = entry.get("sha256")
        if not isinstance(expected, str) or not HASH.fullmatch(expected.lower()):
            raise ValueError("Invalid manifest SHA-256")
        path = root.joinpath(*parsed.parts)
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Missing or unsafe manifest payload: " + rel)
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
            raise ValueError("Unacceptable payload: " + rel)
        digest = hashlib.sha256()
        with path.open("rb") as data:
            while chunk := data.read(1024 * 1024):
                digest.update(chunk)
        after = path.lstat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("Payload changed during SHA-256 calculation")
        actual = digest.hexdigest()
        evidence.append({"path": rel, "bytes": after.st_size,
                         "expected_sha256": expected.lower(),
                         "actual_sha256": actual, "match": actual == expected.lower()})
    return {"schema_version": 1, "report_type": "PUBLICATION_MANIFEST_PAYLOAD_CHECK",
            "entries": len(rows), "matched": sum(e["match"] for e in evidence),
            "mismatched": [e["path"] for e in evidence if not e["match"]],
            "files": evidence, "status": "PASS" if all(e["match"] for e in evidence) else "FAIL",
            "no_execution": True, "binary_runtime_verified": False}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    args = p.parse_args()
    try:
        result = compare(args.root, args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"MANIFEST CHECK BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
