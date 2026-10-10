#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


def _safe_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def history_presence(
    key: str,
    historical_indexes: list[dict[str, dict[str, Any]]],
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    seen_positions = [
        index
        for index, values in enumerate(historical_indexes)
        if key in values
    ]
    if not seen_positions:
        return {
            "seen_count": 0,
            "consecutive_seen": 0,
            "first_seen_sha": "",
            "last_seen_sha": "",
        }

    consecutive = 0
    for values in reversed(historical_indexes):
        if key in values:
            consecutive += 1
        else:
            break

    first = snapshots[seen_positions[0]]
    last = snapshots[seen_positions[-1]]
    return {
        "seen_count": len(seen_positions),
        "consecutive_seen": consecutive,
        "first_seen_sha": _safe_text(first.get("resolved_sha")),
        "last_seen_sha": _safe_text(last.get("resolved_sha")),
    }


def inherited_resolved_tombstones(
    history: list[dict[str, Any]],
    current_keys: set[str],
) -> dict[str, dict[str, Any]]:
    inherited: dict[str, dict[str, Any]] = {}

    # v4.6 snapshots store the complete tombstone set. The newest snapshot that
    # carries this field is authoritative even when the array is empty, so a
    # returned finding can retire an older tombstone deterministically.
    for snapshot in reversed(history):
        if "resolved_tombstones" not in snapshot:
            continue
        rows = (
            snapshot.get("resolved_tombstones")
            if isinstance(snapshot.get("resolved_tombstones"), list)
            else []
        )
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = _safe_text(row.get("key"))
            if key:
                inherited[key] = dict(row)
        break

    # A returned/current finding is active again and must not retain a resolved
    # tombstone.
    for key in current_keys:
        inherited.pop(key, None)

    return inherited


def resolved_history(
    *,
    history: list[dict[str, Any]],
    current_keys: set[str],
    resolved_keys: list[str],
    previous_findings: dict[str, dict[str, Any]],
    historical_indexes: list[dict[str, dict[str, Any]]],
    current_snapshot: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result = inherited_resolved_tombstones(history, current_keys)

    for key in resolved_keys:
        row = dict(previous_findings[key])
        row.update(history_presence(key, historical_indexes, history))
        row["resolution_observed_sha"] = _safe_text(
            current_snapshot.get("resolved_sha")
        )
        row["resolution_observed_at"] = _safe_text(
            current_snapshot.get("recorded_at")
        )
        row["causal_attribution"] = "NOT_INFERRED"
        result[key] = row

    return result
