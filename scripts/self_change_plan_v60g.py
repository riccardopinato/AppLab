#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = ROOT / "integration" / "performance" / "contracts" / "self-dogfooding-plan-v1.json"
LABS = (
    "system", "performance", "network", "persistence", "configuration",
    "resource_pressure", "background", "storage", "upgrade",
)


class SelfPlanError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise SelfPlanError("unsupported self-dogfooding contract version")
    if payload.get("contract_name") != "APPLAB_SELF_DOGFOODING_PLAN":
        raise SelfPlanError("unexpected self-dogfooding contract")
    return payload


def _matches(path: str, rule: str) -> bool:
    return path == rule or (rule.endswith("/") and path.startswith(rule))


def changed_files(repo_root: Path, base_sha: str, head_sha: str) -> list[str]:
    if not base_sha or not head_sha:
        raise SelfPlanError("base and head SHA are required")
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--name-only", base_sha, head_sha],
        capture_output=True, text=True, check=False, timeout=20,
    )
    if proc.returncode != 0:
        raise SelfPlanError("unable to compute exact self diff")
    return sorted({line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()})


def build_plan(paths: list[str], contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract()
    paths = sorted(set(paths))
    selected = {lab: False for lab in LABS}
    reasons = {lab: [] for lab in LABS}
    journeys = {"runtime-core": False, "maestro-core": False, "certification-contract": False}
    full_reasons: list[str] = []
    runtime_relevant = False
    no_runtime_only = True

    for path in paths:
        if any(_matches(path, rule) for rule in contract["full_runtime_paths"]):
            full_reasons.append(path)
            runtime_relevant = True
            no_runtime_only = False
            continue

        mapped = False
        for lab, rules in contract["fast_lab_paths"].items():
            if any(_matches(path, rule) for rule in rules):
                key = lab.replace("-", "_")
                selected[key] = True
                reasons[key].append(path)
                runtime_relevant = True
                no_runtime_only = False
                mapped = True
        if mapped:
            continue

        if any(_matches(path, rule) for rule in contract["fast_core_paths"]):
            runtime_relevant = True
            no_runtime_only = False
            journeys["runtime-core"] = True
            if path.startswith(".maestro/") or "journey" in Path(path).name or "crawler" in Path(path).name:
                journeys["maestro-core"] = True
            continue

        if path.startswith("scripts/"):
            if any(path.startswith(prefix) for prefix in contract["no_android_runtime_prefixes"]):
                continue
            # A runtime-relevant script unknown to the bounded catalog falls back
            # to FULL rather than being silently skipped.
            full_reasons.append(f"UNKNOWN_SCRIPT:{path}")
            runtime_relevant = True
            no_runtime_only = False
            continue

        # Current Emulator Self Test is not applicable to docs/frontend/backend
        # unless one of the explicit runtime paths above is also touched.

    if full_reasons:
        mode = "FULL_RUNTIME"
        journeys.update({
            "runtime-core": True,
            "maestro-core": True,
            "certification-contract": True,
        })
        selected = {lab: True for lab in LABS}
        reasons = {lab: list(full_reasons) for lab in LABS}
    elif runtime_relevant:
        mode = "FAST_RUNTIME"
        journeys["runtime-core"] = True
    elif no_runtime_only:
        mode = "NO_ANDROID_RUNTIME"
    else:
        mode = "NO_ANDROID_RUNTIME"

    return {
        "schema_version": 1,
        "record_type": "APPLAB_SELF_DOGFOODING_PLAN_V60G",
        "authority": "SELF_VERIFICATION_SCOPE_ONLY",
        "mode": mode,
        "changed_files": paths,
        "selected_labs": selected,
        "reasons": reasons,
        "selected_journeys": journeys,
        "run_android_runtime": mode != "NO_ANDROID_RUNTIME",
        "run_maestro": bool(journeys["maestro-core"]),
        "full_reasons": full_reasons,
        "coverage_reduction_authority": "SELF_REPO_ONLY",
        "certification_authority": "UNCHANGED",
        "physical_store_authority": "UNCHANGED",
    }


def validate_runtime_result(plan: dict[str, Any], result: dict[str, Any]) -> None:
    if plan.get("mode") != "FAST_RUNTIME":
        raise SelfPlanError("FAST result validation requires FAST_RUNTIME plan")
    if str(result.get("result", "")).upper() != "PASS":
        raise SelfPlanError("FAST runtime result is not PASS")
    if str(result.get("analysis_mode", "")).lower() != "fast":
        raise SelfPlanError("FAST runtime result did not record fast analysis mode")
    expected_maestro = "PASS" if plan.get("run_maestro") else "SKIPPED"
    if str(result.get("maestro", "")).upper() != expected_maestro:
        raise SelfPlanError("Maestro result does not match self plan")
    mapping = {
        "system": "system_lab",
        "performance": "performance_lab",
        "network": "network_lab",
        "persistence": "persistence_lab",
        "configuration": "configuration_lab",
        "resource_pressure": "resource_pressure_lab",
        "background": "background_lab",
        "storage": "storage_lab",
        "upgrade": "upgrade_lab",
    }
    for lab, result_key in mapping.items():
        value = str(result.get(result_key, "")).upper()
        if plan["selected_labs"][lab]:
            if value not in {"PASS", "WARN"}:
                raise SelfPlanError(f"selected lab {lab} did not execute successfully: {value}")
        elif value not in {"SKIPPED", "NO_BASELINE"}:
            raise SelfPlanError(f"unselected lab {lab} unexpectedly executed: {value}")


def write_outputs(path: str, plan: dict[str, Any]) -> None:
    if not path:
        return
    compact = json.dumps(plan, separators=(",", ":"), sort_keys=True)
    encoded = base64.b64encode(compact.encode("utf-8")).decode("ascii")
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(f"run={str(bool(plan['run_android_runtime'])).lower()}\n")
        handle.write(f"mode={plan['mode']}\n")
        handle.write(f"run_maestro={str(bool(plan['run_maestro'])).lower()}\n")
        handle.write(f"plan_b64={encoded}\n")


def self_test() -> None:
    contract = load_contract()
    no_runtime = build_plan(["scripts/external_review_watchdog_v59e.py"], contract)
    assert no_runtime["mode"] == "NO_ANDROID_RUNTIME"

    fast = build_plan(["scripts/network_lab.py"], contract)
    assert fast["mode"] == "FAST_RUNTIME"
    assert fast["selected_labs"]["network"] is True
    assert sum(bool(x) for x in fast["selected_labs"].values()) == 1

    visual = build_plan(["scripts/visual_qa.py"], contract)
    assert visual["mode"] == "FAST_RUNTIME"
    assert visual["selected_journeys"]["runtime-core"] is True

    full = build_plan(["scripts/verify_apk.sh"], contract)
    assert full["mode"] == "FULL_RUNTIME"
    assert all(full["selected_labs"].values())
    assert full["selected_journeys"]["certification-contract"] is True

    unknown_script = build_plan(["scripts/new_runtime_thing.py"], contract)
    assert unknown_script["mode"] == "FULL_RUNTIME"
    assert unknown_script["full_reasons"][0].startswith("UNKNOWN_SCRIPT:")

    docs = build_plan(["README.md", "integration/foo.md"], contract)
    assert docs["mode"] == "NO_ANDROID_RUNTIME"

    result = {
        "result": "PASS",
        "analysis_mode": "fast",
        "maestro": "SKIPPED",
        "system_lab": "SKIPPED",
        "performance_lab": "SKIPPED",
        "network_lab": "PASS",
        "persistence_lab": "SKIPPED",
        "configuration_lab": "SKIPPED",
        "resource_pressure_lab": "SKIPPED",
        "background_lab": "SKIPPED",
        "storage_lab": "SKIPPED",
        "upgrade_lab": "SKIPPED",
    }
    validate_runtime_result(fast, result)
    print("AppLab v6.0G self-dogfooding plan self-test PASS")


def _read_json(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SelfPlanError("JSON root must be object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--head-sha", default="")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--output", default="")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--validate-result", default="")
    parser.add_argument("--plan", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.validate_result:
        if not args.plan:
            raise SystemExit("--plan is required with --validate-result")
        validate_runtime_result(_read_json(args.plan), _read_json(args.validate_result))
        print("VALID")
        return 0
    paths = list(args.changed_file)
    if not paths:
        paths = changed_files(Path(args.repo_root), args.base_sha, args.head_sha)
    plan = build_plan(paths)
    rendered = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    write_outputs(args.github_output, plan)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
