#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

VERSION = "0.9.0"

def load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": 1, "version": VERSION, "phases": {}, "metrics": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    value.setdefault("schema_version", 1)
    value.setdefault("version", VERSION)
    value.setdefault("phases", {})
    value.setdefault("metrics", {})
    return value

def save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "telemetry.json"
        payload = load(path)
        payload["metrics"]["lane"] = "FAST_RUNTIME"
        save(path, payload)
        assert load(path)["metrics"]["lane"] == "FAST_RUNTIME"
    print("AppLab v0.9 Telemetry self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=False)
    mark = sub.add_parser("mark")
    mark.add_argument("--file", required=True)
    mark.add_argument("--phase", required=True)
    mark.add_argument("--event", choices=("start", "end"), required=True)

    metric = sub.add_parser("metric")
    metric.add_argument("--file", required=True)
    metric.add_argument("--key", required=True)
    metric.add_argument("--value", required=True)

    merge = sub.add_parser("merge")
    merge.add_argument("--file", required=True)
    merge.add_argument("--plan", required=True)

    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    if args.command == "mark":
        path = Path(args.file)
        payload = load(path)
        phase = payload["phases"].setdefault(args.phase, {})
        phase[args.event] = time.time()
        if "start" in phase and "end" in phase:
            phase["duration_seconds"] = round(max(0.0, phase["end"] - phase["start"]), 3)
        save(path, payload)
    elif args.command == "metric":
        path = Path(args.file)
        payload = load(path)
        value: Any = args.value
        if args.value.lower() in {"true", "false"}:
            value = args.value.lower() == "true"
        else:
            try:
                value = float(args.value) if "." in args.value else int(args.value)
            except ValueError:
                pass
        payload["metrics"][args.key] = value
        save(path, payload)
    elif args.command == "merge":
        path = Path(args.file)
        payload = load(path)
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        payload["metrics"].update({
            "lane": plan.get("lane"),
            "risk_score": plan.get("risk_score"),
            "risk_level": plan.get("risk_level"),
            "confidence": plan.get("confidence"),
            "changed_file_count": plan.get("changed_file_count"),
            "churn": plan.get("churn"),
            "shadow_full": plan.get("shadow_full"),
            "planner_duration_ms": plan.get("planner_duration_ms"),
            "fallback_full": plan.get("fallback_full"),
        })
        save(path, payload)
    else:
        raise SystemExit("command required unless --self-test is used")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
