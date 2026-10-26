#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import journey_runtime


SCHEMA_VERSION = 1
ENGINE_VERSION = "5.9C"


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_ids(raw: str) -> list[str]:
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("journey ids must be JSON") from exc
    if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
        raise ValueError("journey ids must be a non-empty string array")
    if len(values) != len(set(values)):
        raise ValueError("journey ids must be unique")
    return values


def execute(args: argparse.Namespace) -> int:
    report_dir = Path(args.report_dir).resolve()
    output = report_dir / "journey-runtime.json"
    target_root = Path(args.target_root).resolve()
    trusted_root = Path(args.trusted_root).resolve()
    plan = journey_runtime.read_json(Path(args.plan).resolve())
    try:
        requested = parse_ids(args.journey_ids_json)
        journeys = journey_runtime.selected_catalog(
            target_root=target_root,
            plan=plan,
            repository=args.repository,
            trusted_root=trusted_root,
            requested_journeys=requested,
        )
    except (ValueError, journey_runtime.LegacyFallback) as exc:
        write_report(output, {
            "schema_version": SCHEMA_VERSION,
            "engine_version": ENGINE_VERSION,
            "result": "FAIL",
            "repository": args.repository,
            "shard_id": args.shard_id,
            "selected_journeys": [],
            "coverage_reduction_enabled": False,
            "reason": str(exc),
            "journeys": [],
        })
        return 2

    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    for journey_id, flow in journeys:
        row = journey_runtime.run_journey(
            journey_id=journey_id,
            flow=flow,
            package_id=args.package_id,
            report_dir=report_dir,
            max_attempts=args.max_attempts,
        )
        rows.append(row)
        if row.get("result") != "PASS":
            write_report(output, {
                "schema_version": SCHEMA_VERSION,
                "engine_version": ENGINE_VERSION,
                "result": "FAIL",
                "repository": args.repository,
                "shard_id": args.shard_id,
                "selected_journeys": [value for value, _ in journeys],
                "coverage_reduction_enabled": True,
                "journeys": rows,
                "seconds": round(time.monotonic() - started, 3),
            })
            return 1

    write_report(output, {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "result": "PASS",
        "repository": args.repository,
        "shard_id": args.shard_id,
        "selected_journeys": [value for value, _ in journeys],
        "coverage_reduction_enabled": True,
        "journeys": rows,
        "seconds": round(time.monotonic() - started, 3),
    })
    return 0


def self_test() -> None:
    assert parse_ids('["shell","vault"]') == ["shell", "vault"]
    for raw in ('[]', '["shell","shell"]', '{}'):
        try:
            parse_ids(raw)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid shard ids accepted: {raw}")
    print("AppLab v5.9C shard runtime self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-root", default="")
    parser.add_argument("--trusted-root", default="")
    parser.add_argument("--plan", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--package-id", default="")
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--journey-ids-json", default="")
    parser.add_argument("--shard-id", default="")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    required = (
        args.target_root, args.trusted_root, args.plan, args.repository,
        args.package_id, args.report_dir, args.journey_ids_json, args.shard_id,
    )
    if not all(required):
        parser.error("all shard runtime arguments are required")
    if not 1 <= args.max_attempts <= 3:
        parser.error("--max-attempts must be between 1 and 3")
    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
