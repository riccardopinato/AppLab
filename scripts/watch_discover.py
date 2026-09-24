#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def api_json(url: str, token: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AppLab-Repo-Watcher/0.5",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def validate_entry(entry: dict[str, Any]) -> None:
    key = str(entry.get("key", "")).strip()
    repository = str(entry.get("repository", "")).strip()
    ref = str(entry.get("ref", "")).strip()
    if not KEY_RE.fullmatch(key):
        raise ValueError(f"Invalid watcher key: {key!r}")
    if not REPO_RE.fullmatch(repository):
        raise ValueError(f"Invalid repository: {repository!r}")
    if not ref or "\n" in ref or "\r" in ref:
        raise ValueError(f"Invalid ref for {repository}: {ref!r}")


def cache_exists(applab_repository: str, cache_key: str, token: str) -> bool:
    encoded = urllib.parse.quote(cache_key, safe="")
    url = (
        f"https://api.github.com/repos/{applab_repository}/actions/caches"
        f"?per_page=1&key={encoded}"
    )
    payload = api_json(url, token)
    return int(payload.get("total_count", 0)) > 0


def resolve_sha(repository: str, ref: str, token: str) -> str:
    encoded_ref = urllib.parse.quote(ref, safe="")
    url = f"https://api.github.com/repos/{repository}/commits/{encoded_ref}"
    payload = api_json(url, token)
    sha = str(payload.get("sha", "")).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise ValueError(f"GitHub returned an invalid SHA for {repository}@{ref}")
    return sha.lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist", required=True)
    parser.add_argument("--applab-repository", default="")
    parser.add_argument("--matrix-output")
    parser.add_argument("--status-output")
    parser.add_argument("--only-repository", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    data = json.loads(Path(args.watchlist).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise SystemExit("Unsupported watchlist schema_version")

    cache_epoch = str(data.get("cache_epoch", "1")).strip() or "1"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", cache_epoch):
        raise SystemExit("watchlist cache_epoch must be alphanumeric/dot/dash")

    entries = data.get("repositories")
    if not isinstance(entries, list):
        raise SystemExit("watchlist repositories must be an array")

    seen_keys: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("watchlist entries must be objects")
        validate_entry(entry)
        key = str(entry["key"])
        if key in seen_keys:
            raise SystemExit(f"Duplicate watcher key: {key}")
        seen_keys.add(key)

    if args.validate_only:
        print(f"Validated {len(entries)} AppLab watcher entries.")
        return 0

    applab_repository = args.applab_repository.strip()
    if not REPO_RE.fullmatch(applab_repository):
        raise SystemExit("--applab-repository must be owner/name")

    token = os.environ.get("GITHUB_TOKEN", "")
    only_repository = args.only_repository.strip()
    matrix: list[dict[str, Any]] = []
    status: list[dict[str, Any]] = []

    for entry in entries:
        if not bool(entry.get("enabled", False)):
            continue
        repository = str(entry["repository"])
        if only_repository and repository != only_repository:
            continue

        item_status: dict[str, Any] = {
            "key": entry["key"],
            "repository": repository,
            "ref": entry["ref"],
        }
        try:
            sha = resolve_sha(repository, str(entry["ref"]), token)
            cache_key = f"applab-v0.5-e{cache_epoch}-{entry['key']}-{sha}"
            cached = False if args.force else cache_exists(
                applab_repository, cache_key, token
            )
            item_status.update(
                {
                    "resolved_sha": sha,
                    "cache_key": cache_key,
                    "cached": cached,
                    "scheduled": args.force or not cached,
                }
            )
            if args.force or not cached:
                matrix.append(
                    {**entry, "resolved_sha": sha, "cache_epoch": cache_epoch}
                )
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            item_status.update({"scheduled": False, "error": str(exc)})
        status.append(item_status)

    matrix_payload = {"include": matrix}
    matrix_text = json.dumps(matrix_payload, separators=(",", ":"))
    status_payload = {
        "schema_version": 1,
        "force": args.force,
        "only_repository": only_repository,
        "scheduled_count": len(matrix),
        "repositories": status,
    }

    if args.matrix_output:
        Path(args.matrix_output).write_text(matrix_text + "\n", encoding="utf-8")
    else:
        print(matrix_text)

    if args.status_output:
        Path(args.status_output).write_text(
            json.dumps(status_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"AppLab watcher configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2)
