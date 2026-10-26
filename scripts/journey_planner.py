#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import json
import tempfile
from pathlib import Path
from typing import Any, Callable

import project_adapter

RUNTIME_LANES = {"FAST_RUNTIME", "FULL_RUNTIME", "CERTIFICATION"}


def normalize_repo_path(path: str) -> str:
    value = path.replace("\\", "/").lower()
    while value.startswith("./"):
        value = value[2:]
    return value.lstrip("/")


def select_journeys(
    repo_root: Path,
    plan: dict[str, Any],
    *,
    is_static_only_path: Callable[[str], bool],
) -> dict[str, Any]:
    enriched = dict(plan)
    lane = str(plan.get("lane", ""))
    runtime_lane = lane in RUNTIME_LANES
    try:
        config, config_path = project_adapter.load_config(repo_root)
        journeys = config.get("journeys", {}) if isinstance(config, dict) else {}
        if journeys is None:
            journeys = {}
        if not isinstance(journeys, dict):
            raise ValueError("journeys must be an object")
        catalog = project_adapter.normalize_journey_catalog(
            repo_root,
            journeys.get("catalog", {}),
        )
    except Exception as exc:
        enriched["selected_journeys"] = []
        enriched["journey_selection"] = {
            "state": "INVALID_CATALOG_FAIL_SAFE",
            "config_path": "",
            "catalog_count": 0,
            "selected_count": 0,
            "unmatched_paths": [],
            "coverage_reduction_enabled": False,
            "enforcement_eligible": False,
            "reason": str(exc)[:300],
        }
        return enriched

    if not catalog:
        enriched["selected_journeys"] = []
        enriched["journey_selection"] = {
            "state": "LEGACY_PRIMARY",
            "config_path": config_path,
            "catalog_count": 0,
            "selected_count": 0,
            "unmatched_paths": [],
            "coverage_reduction_enabled": False,
            "enforcement_eligible": False,
            "reason": (
                "No journey catalog declared; legacy primary Maestro behavior remains authoritative."
            ),
        }
        return enriched

    paths = [
        normalize_repo_path(value)
        for value in list(plan.get("changed_files", [])) + list(plan.get("impacted_files", []))
        if isinstance(value, str) and value
    ]
    for row in plan.get("changes", []) if isinstance(plan.get("changes"), list) else []:
        if isinstance(row, dict) and row.get("previous_path"):
            previous = normalize_repo_path(str(row["previous_path"]))
            if previous and previous not in paths:
                paths.append(previous)

    selected_labs = {
        key
        for key, value in (plan.get("selected_labs") or {}).items()
        if isinstance(value, bool) and value
    }
    selected: list[str] = []
    matched_paths: set[str] = set()
    reasons: dict[str, list[str]] = {key: [] for key in catalog}

    for journey_id, item in catalog.items():
        path_hits: list[str] = []
        for pattern in item.get("paths", []):
            normalized_pattern = normalize_repo_path(pattern)
            for path in paths:
                if fnmatch.fnmatch(path, normalized_pattern):
                    matched_paths.add(path)
                    if path not in path_hits:
                        path_hits.append(path)

        choose = False
        if lane in {"FULL_RUNTIME", "CERTIFICATION"}:
            choose = True
            reasons[journey_id].append(f"{lane} selects all declared journeys")
        elif lane == "FAST_RUNTIME":
            if item.get("risk_class") == "core" or item.get("always_fast") is True:
                choose = True
                reasons[journey_id].append("core/always_fast journey")
            if path_hits:
                choose = True
                reasons[journey_id].extend(f"path:{path}" for path in path_hits)
            lab_hits = sorted(set(item.get("labs", [])) & selected_labs)
            if lab_hits:
                choose = True
                reasons[journey_id].append("labs:" + ",".join(lab_hits))

        if choose and runtime_lane:
            selected.append(journey_id)

    runtime_paths = [path for path in paths if not is_static_only_path(path)]
    unmatched = sorted(set(runtime_paths) - matched_paths)
    state = "CATALOG_SELECTED"
    if lane in {"NO_RUNTIME_CHANGE", "STATIC_ONLY"}:
        state = "NO_RUNTIME"
    elif lane == "FAST_RUNTIME" and unmatched:
        state = "CATALOG_PARTIAL_UNMATCHED"

    enriched["selected_journeys"] = selected
    enriched["journey_reasons"] = reasons
    enriched["journey_selection"] = {
        "state": state,
        "config_path": config_path,
        "catalog_count": len(catalog),
        "selected_count": len(selected),
        "unmatched_paths": unmatched[:100],
        "coverage_reduction_enabled": False,
        "enforcement_eligible": bool(
            lane == "FAST_RUNTIME" and selected and not unmatched
        ),
        "reason": (
            "v5.9A plans journeys only; runtime reduction is intentionally disabled until v5.9B."
        ),
    }
    return enriched


def self_test() -> None:
    labs = (
        "system", "performance", "network", "persistence", "configuration",
        "resource_pressure", "background", "storage", "upgrade",
    )
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / ".maestro").mkdir()
        (root / ".maestro" / "shell.yaml").write_text("appId: demo\n", encoding="utf-8")
        (root / ".maestro" / "vault.yaml").write_text("appId: demo\n", encoding="utf-8")
        (root / "applab.project.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "journeys": {
                        "catalog": {
                            "shell": {
                                "flow": ".maestro/shell.yaml",
                                "paths": ["lib/**"],
                                "labs": ["configuration"],
                                "surfaces": ["home"],
                                "capabilities": ["navigation"],
                                "risk_class": "core",
                                "always_fast": True,
                            },
                            "vault-deep": {
                                "flow": ".maestro/vault.yaml",
                                "paths": ["lib/**/vault*.dart", "lib/security/**"],
                                "labs": ["persistence", "storage"],
                                "surfaces": ["vault"],
                                "capabilities": ["crypto"],
                                "risk_class": "deep",
                                "always_fast": False,
                            },
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        is_static = lambda path: path.startswith("test/") or path.endswith(".md")
        selected = select_journeys(
            root,
            {
                "lane": "FAST_RUNTIME",
                "changed_files": ["lib/features/capture.dart"],
                "impacted_files": [],
                "selected_labs": {lab: False for lab in labs},
            },
            is_static_only_path=is_static,
        )
        assert selected["selected_journeys"] == ["shell"], selected
        assert selected["journey_selection"]["coverage_reduction_enabled"] is False

        vault = select_journeys(
            root,
            {
                "lane": "FAST_RUNTIME",
                "changed_files": ["lib/security/vault_crypto.dart"],
                "impacted_files": [],
                "selected_labs": {**{lab: False for lab in labs}, "persistence": True},
            },
            is_static_only_path=is_static,
        )
        assert "vault-deep" in vault["selected_journeys"], vault

        renamed = select_journeys(
            root,
            {
                "lane": "FAST_RUNTIME",
                "changed_files": ["lib/new/helper.dart"],
                "impacted_files": [],
                "changes": [
                    {
                        "path": "lib/new/helper.dart",
                        "previous_path": "lib/security/vault_crypto.dart",
                        "status": "R",
                    }
                ],
                "selected_labs": {lab: False for lab in labs},
            },
            is_static_only_path=is_static,
        )
        assert "vault-deep" in renamed["selected_journeys"], renamed

        full = select_journeys(
            root,
            {
                "lane": "FULL_RUNTIME",
                "changed_files": ["lib/features/capture.dart"],
                "impacted_files": [],
                "selected_labs": {lab: True for lab in labs},
            },
            is_static_only_path=is_static,
        )
        assert sorted(full["selected_journeys"]) == ["shell", "vault-deep"], full
        assert full["journey_selection"]["unmatched_paths"] == [], full


if __name__ == "__main__":
    self_test()
    print("AppLab v5.9A journey planner self-test PASS")
