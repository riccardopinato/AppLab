#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def find_json(root: Path | None, names: Iterable[str]) -> tuple[Path | None, dict[str, Any] | None]:
    if root is None or not root.exists():
        return None, None
    wanted = {name.lower() for name in names}
    for path in sorted(root.rglob("*.json")):
        if path.name.lower() in wanted:
            value = load_json(path)
            if value is not None:
                return path, value
    return None, None


def result_state(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "NOT_OBSERVED"
    raw = str(payload.get("result", "UNKNOWN")).upper()
    if raw == "PASS":
        return "OBSERVED_PASS"
    if raw == "FAIL":
        return "OBSERVED_FAIL"
    if raw in {"WARN", "WARNING"}:
        return "OBSERVED_WARN"
    if raw in {"SKIPPED", "NOT_RUN", "N/A"}:
        return "NOT_OBSERVED"
    return "OBSERVED_UNKNOWN"


def write_report(output_dir: Path, stem: str, payload: dict[str, Any], markdown: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{stem}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / f"{stem}.md").write_text(markdown.rstrip() + "\n", encoding="utf-8")


def bounded_text_files(root: Path, names: Iterable[str], max_bytes: int = 400_000) -> list[tuple[Path, str]]:
    result: list[tuple[Path, str]] = []
    wanted = {name.lower() for name in names}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.lower() not in wanted:
            continue
        try:
            if path.stat().st_size > max_bytes:
                continue
            result.append((path, path.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    return result
