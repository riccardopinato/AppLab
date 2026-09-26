#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * p
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    lanes = Counter(str(row.get("analysis_lane", row.get("lane", "UNKNOWN"))) for row in rows)
    confidence = [
        float((row.get("risk") or {}).get("confidence"))
        for row in rows
        if isinstance(row.get("risk"), dict)
        and isinstance((row.get("risk") or {}).get("confidence"), (int, float))
    ]
    timings: dict[str, list[float]] = {}
    for key in ("planner_seconds", "build_seconds", "emulator_seconds", "runtime_seconds", "total_seconds"):
        timings[key] = [
            float((row.get("timings") or {}).get(key))
            for row in rows
            if isinstance(row.get("timings"), dict)
            and isinstance((row.get("timings") or {}).get(key), (int, float))
        ]

    selected = skipped = 0
    false_negatives = selected_clean = shadow_runs = 0
    cache_hits = cache_total = 0
    for row in rows:
        labs = row.get("selected_labs")
        if isinstance(labs, dict):
            selected += sum(1 for value in labs.values() if value)
            skipped += sum(1 for value in labs.values() if not value)
        shadow = row.get("shadow_calibration")
        if isinstance(shadow, dict) and shadow.get("performed"):
            shadow_runs += 1
            false_negatives += int(shadow.get("false_negatives", 0) or 0)
            selected_clean += int(shadow.get("selected_clean", 0) or 0)
        cache = row.get("cache")
        if isinstance(cache, dict):
            for value in cache.values():
                if isinstance(value, bool):
                    cache_total += 1
                    cache_hits += int(value)

    timing_summary = {
        key: {
            "samples": len(values),
            "p50": round(percentile(values, 0.50), 3),
            "p95": round(percentile(values, 0.95), 3),
            "mean": round(statistics.fmean(values), 3) if values else 0.0,
        }
        for key, values in timings.items()
    }
    return {
        "schema_version": 1,
        "samples": len(rows),
        "lane_distribution": dict(sorted(lanes.items())),
        "lab_skip_ratio": round(skipped / max(1, selected + skipped), 4),
        "cache_hit_ratio": round(cache_hits / max(1, cache_total), 4),
        "confidence": {
            "samples": len(confidence),
            "p50": round(percentile(confidence, 0.50), 3),
            "p95": round(percentile(confidence, 0.95), 3),
        },
        "shadow": {
            "runs": shadow_runs,
            "false_negatives": false_negatives,
            "selected_clean": selected_clean,
            "over_selection_observable": False,
            "false_negative_rate": round(false_negatives / max(1, shadow_runs), 4),
        },
        "timings": timing_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-file")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        payload = summarize([
            {"analysis_lane": "FAST_RUNTIME", "risk": {"confidence": 0.9}, "selected_labs": {"a": True, "b": False}, "timings": {"total_seconds": 10}},
            {"analysis_lane": "NO_RUNTIME_CHANGE", "risk": {"confidence": 0.99}, "selected_labs": {"a": False, "b": False}, "timings": {"total_seconds": 1}},
        ])
        assert payload["samples"] == 2
        assert payload["lane_distribution"]["FAST_RUNTIME"] == 1
        assert payload["lab_skip_ratio"] == 0.75
        print("AppLab telemetry summary self-test PASS")
        return 0
    if not args.history_file or not args.output:
        raise SystemExit("--history-file and --output are required")
    rows: list[dict[str, Any]] = []
    path = Path(args.history_file)
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    payload = summarize(rows[-1000:])
    Path(args.output).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
