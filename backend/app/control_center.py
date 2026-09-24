from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_PATH = Path(
    os.getenv("APPLAB_CONTROL_CENTER_PATH", "/data/control-center.json")
)


def empty_snapshot() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": "",
        "summary": {
            "projects": 0,
            "pass": 0,
            "fail": 0,
            "not_run": 0,
        },
        "projects": [],
        "recent": [],
        "available": False,
    }


def load_snapshot(path: Path | None = None) -> dict[str, Any]:
    source = path or DEFAULT_PATH
    if not source.is_file():
        return empty_snapshot()

    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_snapshot()

    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return empty_snapshot()

    projects = payload.get("projects")
    recent = payload.get("recent")
    summary = payload.get("summary")
    if not isinstance(projects, list):
        projects = []
    if not isinstance(recent, list):
        recent = []
    if not isinstance(summary, dict):
        summary = {}

    return {
        "schema_version": 1,
        "generated_at": str(payload.get("generated_at", "")),
        "summary": {
            "projects": int(summary.get("projects", len(projects)) or 0),
            "pass": int(summary.get("pass", 0) or 0),
            "fail": int(summary.get("fail", 0) or 0),
            "not_run": int(summary.get("not_run", 0) or 0),
        },
        "projects": projects[:100],
        "recent": recent[:100],
        "available": True,
    }
