#!/usr/bin/env python3
"""Read-only, non-blocking diff metrics for Lean Engineering pilot PRs.

Does not infer code reuse, test success, quality, speed, cost or coverage.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def parse_numstat(raw: bytes) -> list[dict]:
    """Parse 'git diff --numstat -z --no-renames' without shell interpolation."""
    result = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        cols = record.decode("utf-8", errors="replace").split("\t", 2)
        if len(cols) != 3:
            raise ValueError("Malformed git numstat record")
        added, deleted, path = cols
        if not path:
            raise ValueError("Empty changed path")
        if (added == "-") != (deleted == "-"):
            raise ValueError("Inconsistent binary numstat record")
        binary = added == "-"
        if not binary and (not added.isdecimal() or not deleted.isdecimal()):
            raise ValueError("Non-numeric line change")
        result.append({
            "path": path,
            "added": None if binary else int(added),
            "deleted": None if binary else int(deleted),
            "binary": binary,
        })
    return result


def classify(path: str) -> set[str]:
    p = path.replace("\\", "/").lower()
    name = p.rsplit("/", 1)[-1]
    tags = set()
    if p.startswith(("test/", "tests/", "selftest/")) or "/test/" in p or name.endswith(("_test.dart", "_test.py", ".test.ts", ".spec.ts")):
        tags.add("test")
    if name in ("pubspec.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "cargo.lock", "poetry.lock", "uv.lock") or "/generated/" in p or name.endswith((".g.dart", ".freezed.dart")):
        tags.add("generated_or_lockfile")
    if name in ("pubspec.yaml", "package.json", "pyproject.toml", "requirements.txt", "build.gradle", "build.gradle.kts", "pom.xml", "cargo.toml"):
        tags.add("dependency_manifest_touched")
    return tags


def report(entries: list[dict], base: str, head: str) -> dict:
    substantive = [e for e in entries if "generated_or_lockfile" not in classify(e["path"])]
    return {
        "schema_version": 1,
        "evidence_type": "ADVISORY_DIFF_ONLY",
        "base": base,
        "head": head,
        "files_changed": len(entries),
        "files_excluding_generated_and_lock": len(substantive),
        "added_lines": sum(e["added"] or 0 for e in substantive),
        "deleted_lines": sum(e["deleted"] or 0 for e in substantive),
        "binary_files": sum(bool(e["binary"]) for e in entries),
        "test_files_touched": [e["path"] for e in entries if "test" in classify(e["path"])],
        "dependency_manifests_touched": [e["path"] for e in entries if "dependency_manifest_touched" in classify(e["path"])],
        "reuse": "NOT_INFERABLE_FROM_DIFF",
        "test_results": "NOT_VERIFIED",
        "regression_status": "NOT_VERIFIED",
        "runtime_performance": "NOT_MEASURED",
        "tokens_time_cost": "NOT_MEASURED",
        "note": "Churn is not quality. Add manual reuse evidence and trusted test receipts separately.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Existing trusted base git ref/SHA")
    parser.add_argument("--head", required=True, help="Existing candidate git ref/SHA")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()
    # Git validates refs. '--' ends revisions/options; no shell expansion.
    cmd = ["git", "diff", "--numstat", "-z", "--no-renames", f"{args.base}...{args.head}", "--"]
    output = subprocess.run(cmd, check=True, stdout=subprocess.PIPE).stdout
    payload = json.dumps(report(parse_numstat(output), args.base, args.head), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
