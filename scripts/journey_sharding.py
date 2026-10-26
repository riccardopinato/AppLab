#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

import project_adapter

SCHEMA_VERSION = 1
ENGINE_VERSION = "5.9C"
MAX_PARALLEL_SHARDS = 3


class ShardingDisabled(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShardingDisabled(f"unreadable JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ShardingDisabled(f"JSON object required: {path}")
    return payload


def admitted_repositories(trusted_root: Path) -> dict[str, str]:
    payload = read_json(trusted_root / "config" / "journey-sharding-pilots.json")
    if payload.get("schema_version") != 1:
        raise ShardingDisabled("unsupported journey sharding pilot config")
    values = payload.get("repositories")
    if not isinstance(values, dict) or len(values) > 32:
        raise ShardingDisabled("invalid journey sharding repository map")
    result: dict[str, str] = {}
    for repository, config in values.items():
        if not isinstance(repository, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
        ):
            raise ShardingDisabled("invalid journey sharding repository")
        if not isinstance(config, dict):
            raise ShardingDisabled("journey sharding repository config must be an object")
        mode = str(config.get("mode", "")).strip().lower()
        if mode not in {"shadow", "authoritative"}:
            raise ShardingDisabled("journey sharding mode must be shadow or authoritative")
        result[repository.lower()] = mode
    return result


def build_plan(
    *,
    contract_root: Path,
    trusted_root: Path,
    repository: str,
) -> dict[str, Any]:
    contract = read_json(contract_root / "contract.json")
    plan = read_json(contract_root / "analysis-plan.json")
    repo = repository.strip()
    base = {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "repository": repo,
        "resolved_sha": str(contract.get("resolved_sha", "")),
        "apk_sha256": str((contract.get("apk") or {}).get("sha256", "")),
        "enabled": False,
        "mode": "disabled",
        "authoritative": False,
        "coordinator_journeys": [],
        "shards": [],
        "coverage_union_verified": False,
    }
    if str(contract.get("repository", "")).lower() != repo.lower():
        return {**base, "reason": "contract repository mismatch"}
    admissions = admitted_repositories(trusted_root)
    mode = admissions.get(repo.lower(), "")
    if not mode:
        return {**base, "mode": "disabled", "reason": "repository is not admitted to journey sharding"}
    if str(plan.get("lane", "")) != "FAST_RUNTIME":
        return {**base, "reason": "parallel sharding is FAST-only in v5.9C"}
    selection = plan.get("journey_selection")
    selected = plan.get("selected_journeys")
    if (
        not isinstance(selection, dict)
        or selection.get("enforcement_eligible") is not True
        or selection.get("unmatched_paths")
        or not isinstance(selected, list)
        or len(selected) < 2
    ):
        return {**base, "reason": "journey plan is not safely shardable"}

    evidence = contract_root / "target-evidence"
    try:
        config, _ = project_adapter.load_config(evidence)
        journeys = config.get("journeys", {}) if isinstance(config, dict) else {}
        if not isinstance(journeys, dict):
            raise ValueError("journeys config is invalid")
        catalog = project_adapter.normalize_journey_catalog(
            evidence, journeys.get("catalog", {})
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {**base, "reason": f"invalid journey catalog: {exc}"}

    if any(not isinstance(value, str) or value not in catalog for value in selected):
        return {**base, "reason": "selected journey is absent from trusted catalog"}

    deep = [
        value for value in selected
        if catalog[value].get("risk_class") == "deep"
    ][:MAX_PARALLEL_SHARDS]
    coordinator = [value for value in selected if value not in deep]
    if not deep or not coordinator:
        return {**base, "reason": "no independent deep journey shard available"}

    shards = [
        {
            "id": f"journey-{index + 1}-{journey_id}",
            "journeys": [journey_id],
        }
        for index, journey_id in enumerate(deep)
    ]
    union = set(coordinator)
    for shard in shards:
        union.update(shard["journeys"])
    if union != set(selected):
        return {**base, "reason": "shard union does not cover selected journeys"}

    return {
        **base,
        "enabled": True,
        "mode": mode,
        "authoritative": mode == "authoritative",
        "reason": f"trusted FAST deep-journey sharding admitted in {mode} mode",
        "selected_journeys": selected,
        "coordinator_journeys": coordinator,
        "shards": shards,
        "coverage_union_verified": True,
    }


def write_outputs(path: Path, payload: dict[str, Any]) -> None:
    matrix = {"include": payload.get("shards", [])} if payload.get("enabled") else {"include": []}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"enabled={str(bool(payload.get('enabled'))).lower()}\n")
        handle.write(f"mode={payload.get('mode','disabled')}\n")
        handle.write(f"authoritative={str(bool(payload.get('authoritative'))).lower()}\n")
        handle.write("matrix=" + json.dumps(matrix, separators=(",", ":")) + "\n")
        handle.write(
            "coordinator_journeys="
            + json.dumps(payload.get("coordinator_journeys", []), separators=(",", ":"))
            + "\n"
        )


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        trusted = root / "trusted"
        contract = root / "contract"
        evidence = contract / "target-evidence"
        (trusted / "config").mkdir(parents=True)
        (evidence / ".maestro").mkdir(parents=True)
        (trusted / "config" / "journey-sharding-pilots.json").write_text(
            json.dumps({"schema_version": 1, "repositories": {"owner/app": {"mode": "shadow"}}}),
            encoding="utf-8",
        )
        for name in ("shell.yaml", "vault.yaml"):
            (evidence / ".maestro" / name).write_text("appId: demo\n", encoding="utf-8")
        (evidence / "applab.project.json").write_text(
            json.dumps({
                "schema_version": 1,
                "journeys": {
                    "catalog": {
                        "shell": {
                            "flow": ".maestro/shell.yaml", "paths": ["lib/**"],
                            "labs": [], "surfaces": ["home"], "capabilities": ["navigation"],
                            "risk_class": "core", "always_fast": True,
                        },
                        "vault-deep": {
                            "flow": ".maestro/vault.yaml", "paths": ["lib/security/**"],
                            "labs": [], "surfaces": ["vault"], "capabilities": ["crypto"],
                            "risk_class": "deep", "always_fast": False,
                        },
                    }
                },
            }),
            encoding="utf-8",
        )
        (contract / "contract.json").write_text(
            json.dumps({
                "repository": "owner/app",
                "resolved_sha": "a" * 40,
                "apk": {"sha256": "b" * 64},
            }),
            encoding="utf-8",
        )
        (contract / "analysis-plan.json").write_text(
            json.dumps({
                "lane": "FAST_RUNTIME",
                "selected_journeys": ["shell", "vault-deep"],
                "journey_selection": {
                    "enforcement_eligible": True,
                    "unmatched_paths": [],
                },
            }),
            encoding="utf-8",
        )
        result = build_plan(contract_root=contract, trusted_root=trusted, repository="owner/app")
        assert result["enabled"] is True, result
        assert result["mode"] == "shadow" and result["authoritative"] is False, result
        assert result["coordinator_journeys"] == ["shell"], result
        assert result["shards"][0]["journeys"] == ["vault-deep"], result
        assert result["coverage_union_verified"] is True
        blocked = build_plan(
            contract_root=contract, trusted_root=trusted, repository="owner/other"
        )
        assert blocked["enabled"] is False
    print("AppLab v5.9C journey sharding planner self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-root", default="")
    parser.add_argument("--trusted-root", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.contract_root, args.trusted_root, args.repository)):
        parser.error("contract root, trusted root and repository are required")
    payload = build_plan(
        contract_root=Path(args.contract_root),
        trusted_root=Path(args.trusted_root),
        repository=args.repository,
    )
    if args.output:
        Path(args.output).write_text(
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
