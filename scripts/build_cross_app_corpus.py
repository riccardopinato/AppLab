#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REF_RE = re.compile(r"^[A-Za-z0-9_./-]+$")


def load_watchlist(path: Path) -> list[dict[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read watchlist: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid watchlist JSON: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported watchlist schema")
    raw_repositories = payload.get("repositories")
    if not isinstance(raw_repositories, list):
        raise ValueError("watchlist.repositories must be a list")

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_repositories):
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        key = str(item.get("key") or "").strip()
        repository = str(item.get("repository") or "").strip()
        ref = str(item.get("ref") or "main").strip()
        if not key:
            raise ValueError(f"watchlist entry {index} has no key")
        if key in seen:
            raise ValueError(f"duplicate watchlist key: {key}")
        if not REPOSITORY_RE.fullmatch(repository):
            raise ValueError(f"unsafe/invalid GitHub repository: {repository}")
        if not REF_RE.fullmatch(ref) or ".." in ref:
            raise ValueError(f"unsafe/invalid ref for {repository}: {ref}")
        seen.add(key)
        result.append({"key": key, "repository": repository, "ref": ref})

    if len(result) < 2:
        raise ValueError("Cross-App corpus requires at least two enabled repositories")
    return result


def run(command: list[str], *, cwd: Path | None = None) -> None:
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        stdout=sys.stdout,
        stderr=sys.stderr,
        timeout=300,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}")


def clone_public(entry: dict[str, str], destination: Path) -> None:
    url = f"https://github.com/{entry['repository']}.git"
    run(
        [
            "git",
            "-c",
            "protocol.file.allow=never",
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            entry["ref"],
            "--",
            url,
            str(destination),
        ]
    )


def annotate_report(path: Path, entry: dict[str, str]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Analyzer output is not an object: {path}")
    payload["project_id"] = entry["key"]
    payload["repository"] = entry["repository"]
    payload["ref"] = entry["ref"]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_corpus(
    entries: list[dict[str, str]],
    *,
    analyzer: Path,
    output_dir: Path,
) -> None:
    if not analyzer.is_file():
        raise ValueError(f"App Intelligence analyzer not found: {analyzer}")
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="applab-cross-app-") as raw:
        workspace = Path(raw)
        for entry in entries:
            repo_dir = workspace / entry["key"]
            project_out = output_dir / entry["key"]
            clone_public(entry, repo_dir)
            run(
                [
                    sys.executable,
                    str(analyzer),
                    "--repo-root",
                    str(repo_dir),
                    "--output-dir",
                    str(project_out),
                ]
            )
            annotate_report(project_out / "app-intelligence.json", entry)
            shutil.rmtree(repo_dir, ignore_errors=True)


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "watchlist.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "repositories": [
                        {
                            "key": "one",
                            "enabled": True,
                            "repository": "owner/one",
                            "ref": "main",
                        },
                        {
                            "key": "two",
                            "enabled": True,
                            "repository": "owner/two",
                            "ref": "release/test",
                        },
                        {
                            "key": "disabled",
                            "enabled": False,
                            "repository": "bad value",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        entries = load_watchlist(path)
        assert [item["key"] for item in entries] == ["one", "two"]

        bad = Path(raw) / "bad.json"
        bad.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "repositories": [
                        {
                            "key": "one",
                            "enabled": True,
                            "repository": "owner/one",
                            "ref": "main",
                        },
                        {
                            "key": "two",
                            "enabled": True,
                            "repository": "owner/two",
                            "ref": "../unsafe",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        try:
            load_watchlist(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("Unsafe ref should be rejected")

    print("AppLab Cross-App corpus builder self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist")
    parser.add_argument("--analyzer", default="scripts/app_intelligence.py")
    parser.add_argument("--output-dir", default="applab-cross-app-corpus")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.watchlist:
        raise SystemExit("--watchlist is required unless --self-test is used")

    entries = load_watchlist(Path(args.watchlist))
    if args.validate_only:
        print(json.dumps({"repositories": entries}, indent=2))
        return 0

    build_corpus(
        entries,
        analyzer=Path(args.analyzer).resolve(),
        output_dir=Path(args.output_dir).resolve(),
    )
    print(
        json.dumps(
            {
                "projects": len(entries),
                "output_dir": str(Path(args.output_dir)),
                "execution_policy": "source-only; target code is never executed",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
