#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_history(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def build_snapshot(
    watchlist: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    configured = {
        str(item.get("repository")): item
        for item in watchlist.get("repositories", [])
        if isinstance(item, dict) and item.get("enabled", True)
    }

    latest: dict[str, dict[str, Any]] = {}
    for item in history:
        repository = str(item.get("repository", "")).strip()
        if not repository:
            continue
        current = latest.get(repository)
        if current is None or str(item.get("recorded_at", "")) >= str(
            current.get("recorded_at", "")
        ):
            latest[repository] = item

    repositories = sorted(set(configured) | set(latest))
    projects: list[dict[str, Any]] = []
    for repository in repositories:
        config = configured.get(repository, {})
        result = latest.get(repository, {})
        projects.append(
            {
                "repository": repository,
                "key": config.get("key", result.get("history_key", "")),
                "engine": config.get("engine", result.get("engine", "unknown")),
                "ref": config.get("ref", result.get("ref", "main")),
                "enabled": bool(config.get("enabled", True)),
                "resolved_sha": result.get("resolved_sha", ""),
                "result": result.get("result", "NOT_RUN"),
                "maestro": result.get("maestro", "—"),
                "visual_qa": result.get("visual_qa", "—"),
                "visual_regression": result.get("visual_regression", "—"),
                "visual_journey": result.get("visual_journey", "—"),
                "interaction_crawl": result.get("interaction_crawl", "—"),
                "system_lab": result.get("system_lab", "—"),
                "applab_version": result.get("applab_version", ""),
                "recorded_at": result.get("recorded_at", ""),
                "watcher_run_id": result.get("watcher_run_id", ""),
                "watcher_run_url": result.get("watcher_run_url", ""),
            }
        )

    pass_count = sum(1 for item in projects if item["result"] == "PASS")
    fail_count = sum(1 for item in projects if item["result"] == "FAIL")
    not_run_count = len(projects) - pass_count - fail_count

    recent = sorted(
        (
            {
                key: value
                for key, value in item.items()
                if key
                in {
                    "recorded_at",
                    "repository",
                    "resolved_sha",
                    "result",
                    "engine",
                    "maestro",
                    "visual_qa",
                    "visual_regression",
                    "visual_journey",
                    "interaction_crawl",
                    "system_lab",
                    "watcher_run_id",
                    "watcher_run_url",
                    "applab_version",
                }
            }
            for item in history
        ),
        key=lambda item: str(item.get("recorded_at", "")),
        reverse=True,
    )[:50]

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "projects": len(projects),
            "pass": pass_count,
            "fail": fail_count,
            "not_run": not_run_count,
        },
        "projects": projects,
        "recent": recent,
    }


def self_test() -> None:
    watchlist = {
        "repositories": [
            {
                "key": "one",
                "repository": "owner/one",
                "engine": "flutter",
                "enabled": True,
            },
            {
                "key": "two",
                "repository": "owner/two",
                "engine": "auto",
                "enabled": True,
            },
        ]
    }
    history = [
        {
            "repository": "owner/one",
            "recorded_at": "2026-01-01T00:00:00Z",
            "result": "FAIL",
            "resolved_sha": "old",
        },
        {
            "repository": "owner/one",
            "recorded_at": "2026-01-02T00:00:00Z",
            "result": "PASS",
            "resolved_sha": "new",
        },
    ]
    snapshot = build_snapshot(watchlist, history)
    assert snapshot["summary"] == {
        "projects": 2,
        "pass": 1,
        "fail": 0,
        "not_run": 1,
    }
    first = next(
        item for item in snapshot["projects"] if item["repository"] == "owner/one"
    )
    assert first["resolved_sha"] == "new"
    print("AppLab Control Center snapshot self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist")
    parser.add_argument("--history-file")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.watchlist or not args.history_file or not args.output:
        raise SystemExit("--watchlist, --history-file and --output are required")

    watchlist = json.loads(Path(args.watchlist).read_text(encoding="utf-8"))
    snapshot = build_snapshot(watchlist, read_history(Path(args.history_file)))
    Path(args.output).write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"AppLab Control Center snapshot: "
        f"{snapshot['summary']['projects']} projects"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
