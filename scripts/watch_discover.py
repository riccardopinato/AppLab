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
ENGINES = {"auto", "flutter", "native_android"}


def api_json(url: str, token: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AppLab-Repo-Watcher/0.5.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def validate_relative_path(value: object, field: str, repository: str) -> None:
    raw = str(value or "").strip()
    if not raw:
        return
    if raw.startswith("/") or "\n" in raw or "\r" in raw:
        raise ValueError(f"Invalid {field} for {repository}: {raw!r}")
    parts = raw.replace("\\", "/").split("/")
    if ".." in parts:
        raise ValueError(f"{field} must stay inside repository: {raw!r}")


def validate_entry(entry: dict[str, Any]) -> None:
    key = str(entry.get("key", "")).strip()
    repository = str(entry.get("repository", "")).strip()
    ref = str(entry.get("ref", "")).strip()
    engine = str(entry.get("engine", "flutter")).strip()

    if not KEY_RE.fullmatch(key):
        raise ValueError(f"Invalid watcher key: {key!r}")
    if not REPO_RE.fullmatch(repository):
        raise ValueError(f"Invalid repository: {repository!r}")
    if not ref or "\n" in ref or "\r" in ref:
        raise ValueError(f"Invalid ref for {repository}: {ref!r}")
    if engine not in ENGINES:
        raise ValueError(
            f"Unsupported engine for {repository}: {engine!r}; "
            f"expected one of {sorted(ENGINES)}"
        )

    validate_relative_path(entry.get("working_directory", "."), "working_directory", repository)
    validate_relative_path(entry.get("apk_path", ""), "apk_path", repository)
    validate_relative_path(entry.get("maestro_flow", ""), "maestro_flow", repository)

    if engine != "auto":
        if not str(entry.get("build_command", "")).strip():
            raise ValueError(f"build_command is required for {repository}")
        if not str(entry.get("apk_path", "")).strip():
            raise ValueError(f"apk_path is required for {repository}")


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


def write_matrix(path: str | None, items: list[dict[str, Any]]) -> None:
    if not path:
        return
    payload = {"include": items}
    Path(path).write_text(
        json.dumps(payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist", required=True)
    parser.add_argument("--applab-repository", default="")
    parser.add_argument("--matrix-output")
    parser.add_argument("--flutter-matrix-output")
    parser.add_argument("--native-matrix-output")
    parser.add_argument("--auto-matrix-output")
    parser.add_argument("--status-output")
    parser.add_argument("--only-repository", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    data = json.loads(Path(args.watchlist).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise SystemExit("Unsupported watchlist schema_version")

    global_cache_epoch = str(data.get("cache_epoch", "1")).strip() or "1"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", global_cache_epoch):
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
        counts = {
            engine: sum(
                1
                for entry in entries
                if str(entry.get("engine", "flutter")) == engine
            )
            for engine in sorted(ENGINES)
        }
        print(
            f"Validated {len(entries)} AppLab watcher entries: "
            f"{counts['auto']} auto, "
            f"{counts['flutter']} flutter, "
            f"{counts['native_android']} native_android."
        )
        return 0

    applab_repository = args.applab_repository.strip()
    if not REPO_RE.fullmatch(applab_repository):
        raise SystemExit("--applab-repository must be owner/name")

    token = os.environ.get("GITHUB_TOKEN", "")
    only_repository = args.only_repository.strip()
    matrix: list[dict[str, Any]] = []
    flutter_matrix: list[dict[str, Any]] = []
    native_matrix: list[dict[str, Any]] = []
    auto_matrix: list[dict[str, Any]] = []
    status: list[dict[str, Any]] = []

    for entry in entries:
        if not bool(entry.get("enabled", False)):
            continue

        repository = str(entry["repository"])
        engine = str(entry.get("engine", "flutter"))
        cache_epoch = str(
            entry.get("cache_epoch", global_cache_epoch)
        ).strip() or global_cache_epoch
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", cache_epoch):
            raise ValueError(
                f"Invalid cache_epoch for {repository}: {cache_epoch!r}"
            )
        if only_repository and repository != only_repository:
            continue

        item_status: dict[str, Any] = {
            "key": entry["key"],
            "engine": engine,
            "repository": repository,
            "ref": entry["ref"],
        }

        try:
            sha = resolve_sha(repository, str(entry["ref"]), token)
            cache_key = f"applab-v0.5-e{cache_epoch}-{entry['key']}-{sha}"
            cached = False if args.force else cache_exists(
                applab_repository, cache_key, token
            )
            scheduled = args.force or not cached
            item_status.update(
                {
                    "resolved_sha": sha,
                    "cache_key": cache_key,
                    "cached": cached,
                    "scheduled": scheduled,
                }
            )
            if scheduled:
                resolved = {
                    **entry,
                    "engine": engine,
                    "resolved_sha": sha,
                    "cache_epoch": cache_epoch,
                }
                matrix.append(resolved)
                if engine == "flutter":
                    flutter_matrix.append(resolved)
                elif engine == "native_android":
                    native_matrix.append(resolved)
                elif engine == "auto":
                    auto_matrix.append(resolved)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            item_status.update({"scheduled": False, "error": str(exc)})
        status.append(item_status)

    write_matrix(args.matrix_output, matrix)
    write_matrix(args.flutter_matrix_output, flutter_matrix)
    write_matrix(args.native_matrix_output, native_matrix)
    write_matrix(args.auto_matrix_output, auto_matrix)

    if not args.matrix_output:
        print(json.dumps({"include": matrix}, separators=(",", ":")))

    status_payload = {
        "schema_version": 1,
        "force": args.force,
        "only_repository": only_repository,
        "scheduled_count": len(matrix),
        "flutter_scheduled_count": len(flutter_matrix),
        "native_scheduled_count": len(native_matrix),
        "auto_scheduled_count": len(auto_matrix),
        "repositories": status,
    }

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
