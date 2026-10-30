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


def full_shadow_opted_in(trusted_root: Path, repository: str) -> bool:
    """An explicit trusted-repository opt-in; never an authority escalation."""
    payload = read_json(trusted_root / "config" / "journey-sharding-pilots.json")
    items = payload.get("repositories", {})
    entry = items.get(repository.lower()) if isinstance(items, dict) else None
    return (
        isinstance(entry, dict)
        and entry.get("mode") == "shadow"
        and entry.get("full_shadow") is True
    )


def full_shadow_groups(selected: list[str], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Disjoint UI / diary / deep groups, each run on its own isolated emulator."""
    if len(set(selected)) != len(selected) or set(selected) != set(catalog):
        return []
    ui: list[str] = []
    diary: list[str] = []
    deep: list[str] = []
    for journey_id in selected:
        item = catalog[journey_id]
        surfaces = item.get("surfaces", [])
        if item.get("risk_class") == "deep":
            deep.append(journey_id)
        elif any(surface in {"memories", "diary"} for surface in surfaces):
            diary.append(journey_id)
        else:
            ui.append(journey_id)
    if not ui or not diary or not deep:
        return []
    return [
        {"id": "full-ui-navigation", "journeys": ui},
        {"id": "full-diary-memories", "journeys": diary},
        {"id": "full-deep-security", "journeys": deep},
    ]


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
    lane = str(plan.get("lane", ""))
    full_shadow = (
        lane == "FULL_RUNTIME"
        and mode == "shadow"
        and full_shadow_opted_in(trusted_root, repo)
    )
    if lane != "FAST_RUNTIME" and not full_shadow:
        return {**base, "reason": "FULL sharding requires trusted shadow opt-in; certification is excluded"}
    selection = plan.get("journey_selection")
    selected = plan.get("selected_journeys")
    if not isinstance(selection, dict) or not isinstance(selected, list) or len(selected) < 2:
        return {**base, "reason": "journey plan is not safely shardable"}
    if not full_shadow and (
        selection.get("enforcement_eligible") is not True
        or selection.get("unmatched_paths")
    ):
        return {**base, "reason": "FAST journey plan is not safely shardable"}

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

    if full_shadow:
        shards = full_shadow_groups(selected, catalog)
        if len(shards) != MAX_PARALLEL_SHARDS:
            return {**base, "reason": "FULL shadow needs complete disjoint UI/diary/deep coverage"}
        return {
            **base,
            "enabled": True,
            "mode": "shadow",
            "authoritative": False,
            "lane": "FULL_RUNTIME",
            "selected_journeys": selected,
            "coordinator_journeys": [],
            "shards": shards,
            "coverage_union_verified": True,
            "reason": "advisory FULL parallel shadow; canonical FULL remains sole PASS authority",
        }

    deep = [
        value for value in selected
        if catalog[value].get("risk_class") == "deep"
    ][: max(1, MAX_PARALLEL_SHARDS - 1)]
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

        # FULL never shards without explicit shadow-only opt-in.
        config_path = trusted / "config" / "journey-sharding-pilots.json"
        current = read_json(config_path)
        current["repositories"]["owner/app"]["full_shadow"] = True
        config_path.write_text(json.dumps(current), encoding="utf-8")
        (evidence / ".maestro" / "memory.yaml").write_text("appId: demo\n", encoding="utf-8")
        project_path = evidence / "applab.project.json"
        project = read_json(project_path)
        project["journeys"]["catalog"]["memory"] = {
            "flow": ".maestro/memory.yaml", "paths": ["lib/diary/**"],
            "labs": [], "surfaces": ["memories"], "capabilities": ["diary"],
            "risk_class": "normal", "always_fast": False,
        }
        project_path.write_text(json.dumps(project), encoding="utf-8")
        analysis_path = contract / "analysis-plan.json"
        analysis = read_json(analysis_path)
        analysis.update({
            "lane": "FULL_RUNTIME",
            "selected_journeys": ["shell", "memory", "vault-deep"],
            "journey_selection": {"enforcement_eligible": False,
                                  "unmatched_paths": ["lib/unmapped_runtime.dart"]},
        })
        analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
        full = build_plan(contract_root=contract, trusted_root=trusted, repository="owner/app")
        assert full["enabled"] and full["mode"] == "shadow" and not full["authoritative"], full
        assert len(full["shards"]) == 3 and full["coordinator_journeys"] == [], full
        assert set().union(*(set(s["journeys"]) for s in full["shards"])) == set(analysis["selected_journeys"])
        assert full["coverage_union_verified"] is True
        analysis["selected_journeys"] = ["shell", "vault-deep"]
        analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
        assert not build_plan(contract_root=contract, trusted_root=trusted, repository="owner/app")["enabled"]
        analysis["selected_journeys"] = ["shell", "memory", "vault-deep"]
        analysis["lane"] = "CERTIFICATION"
        analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
        assert not build_plan(contract_root=contract, trusted_root=trusted, repository="owner/app")["enabled"]
        analysis["lane"] = "FULL_RUNTIME"
        analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
        current["repositories"]["owner/app"]["mode"] = "authoritative"
        config_path.write_text(json.dumps(current), encoding="utf-8")
        assert not build_plan(contract_root=contract, trusted_root=trusted, repository="owner/app")["enabled"]
    print("AppLab v6.3D shadow FULL three-way sharding planner self-test PASS")


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
