#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

ENGINE_VERSION = "5.9C"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read sharding plan: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError("sharding plan must be a JSON object")
    return value


def reconcile(
    plan: dict[str, Any],
    *,
    visual_baseline_ready: bool,
    upgrade_baseline_ready: bool,
) -> dict[str, Any]:
    result = dict(plan)
    result["baseline_ready"] = bool(visual_baseline_ready and upgrade_baseline_ready)
    result["baseline_evidence"] = {
        "visual_ready": bool(visual_baseline_ready),
        "upgrade_ready": bool(upgrade_baseline_ready),
    }
    if not bool(plan.get("enabled")):
        return result
    if result["baseline_ready"]:
        result["admission_state"] = "ADMITTED"
        return result

    result.update(
        {
            "enabled": False,
            "mode": "disabled",
            "authoritative": False,
            "coordinator_journeys": [],
            "shards": [],
            "coverage_union_verified": False,
            "admission_state": "DISABLED_MISSING_RUNTIME_BASELINE",
            "reason": (
                "missing trusted runtime baseline; sharding disabled before "
                "effective FULL fallback"
            ),
        }
    )
    return result


def write_outputs(path: Path, payload: dict[str, Any]) -> None:
    matrix = (
        {"include": payload.get("shards", [])}
        if payload.get("enabled")
        else {"include": []}
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"enabled={str(bool(payload.get('enabled'))).lower()}\n")
        handle.write(f"mode={payload.get('mode','disabled')}\n")
        handle.write(
            f"authoritative={str(bool(payload.get('authoritative'))).lower()}\n"
        )
        handle.write("matrix=" + json.dumps(matrix, separators=(",", ":")) + "\n")
        handle.write(
            "coordinator_journeys="
            + json.dumps(payload.get("coordinator_journeys", []), separators=(",", ":"))
            + "\n"
        )
        handle.write(
            f"baseline_ready={str(bool(payload.get('baseline_ready'))).lower()}\n"
        )


def self_test() -> None:
    plan = {
        "enabled": True,
        "mode": "authoritative",
        "authoritative": True,
        "coordinator_journeys": ["shell"],
        "shards": [{"id": "journey-1-vault", "journeys": ["vault"]}],
        "coverage_union_verified": True,
    }
    blocked = reconcile(
        plan,
        visual_baseline_ready=False,
        upgrade_baseline_ready=True,
    )
    assert blocked["enabled"] is False
    assert blocked["authoritative"] is False
    assert blocked["shards"] == []
    assert blocked["admission_state"] == "DISABLED_MISSING_RUNTIME_BASELINE"

    admitted = reconcile(
        plan,
        visual_baseline_ready=True,
        upgrade_baseline_ready=True,
    )
    assert admitted["enabled"] is True
    assert admitted["authoritative"] is True
    assert admitted["admission_state"] == "ADMITTED"

    disabled = reconcile(
        {"enabled": False, "mode": "disabled", "authoritative": False},
        visual_baseline_ready=False,
        upgrade_baseline_ready=False,
    )
    assert disabled["enabled"] is False
    print("AppLab v5.9C sharding admission self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="")
    parser.add_argument("--visual-baseline-dir", default="")
    parser.add_argument("--upgrade-baseline-apk", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.plan:
        parser.error("--plan is required")

    visual_dir = Path(args.visual_baseline_dir) if args.visual_baseline_dir else Path()
    visual_ready = bool(
        args.visual_baseline_dir
        and visual_dir.is_dir()
        and any(path.is_file() for path in visual_dir.rglob("*"))
    )
    upgrade = Path(args.upgrade_baseline_apk) if args.upgrade_baseline_apk else Path()
    upgrade_ready = bool(
        args.upgrade_baseline_apk and upgrade.is_file() and upgrade.stat().st_size > 0
    )
    payload = reconcile(
        read_json(Path(args.plan)),
        visual_baseline_ready=visual_ready,
        upgrade_baseline_ready=upgrade_ready,
    )
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.github_output:
        write_outputs(Path(args.github_output), payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
