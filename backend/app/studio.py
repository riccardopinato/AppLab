from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_STUDIO_PATH = Path(
    os.getenv("APPLAB_STUDIO_PATH", "/data/studio.json")
)


def empty_studio_snapshot() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": "",
        "summary": {
            "projects": 0,
            "with_market": 0,
            "manual_review": 0,
            "recurrent_patterns": 0,
        },
        "projects": [],
        "portfolio": {},
        "available": False,
    }


def load_studio_snapshot(path: Path | None = None) -> dict[str, Any]:
    source = path or DEFAULT_STUDIO_PATH
    if not source.is_file():
        return empty_studio_snapshot()

    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_studio_snapshot()

    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return empty_studio_snapshot()

    projects = payload.get("projects")
    portfolio = payload.get("portfolio")
    summary = payload.get("summary")
    if not isinstance(projects, list):
        projects = []
    if not isinstance(portfolio, dict):
        portfolio = {}
    if not isinstance(summary, dict):
        summary = {}

    normalized_summary = dict(summary)
    normalized_summary.update(
        {
            "projects": int(summary.get("projects", len(projects)) or 0),
            "with_market": int(summary.get("with_market", 0) or 0),
            "manual_review": int(summary.get("manual_review", 0) or 0),
            "recurrent_patterns": int(summary.get("recurrent_patterns", 0) or 0),
        }
    )

    return {
        "schema_version": 1,
        "generated_at": str(payload.get("generated_at", "")),
        "summary": normalized_summary,
        "projects": projects[:100],
        "portfolio": portfolio,
        "available": True,
    }
