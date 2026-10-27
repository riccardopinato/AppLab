#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
from typing import Any

PROFILE_VERSION = "1.1"
LABS = (
    "system",
    "performance",
    "network",
    "persistence",
    "configuration",
    "resource_pressure",
    "background",
    "storage",
    "upgrade",
)
ALL_UNITS = (
    "runtime-core",
    "maestro-core",
    "lifecycle",
    "performance",
    "network",
    "persistence",
    "configuration",
    "resource-pressure",
    "background",
    "storage",
    "upgrade",
    "certification-contract",
)

# Changes to these surfaces can alter the verifier/runtime/certification contract
# itself and therefore retain the historical FULL self-test depth.
FULL_PATTERNS = (
    ".github/workflows/emulator-self-test.yml",
    ".github/workflows/runtime-fixture-build.yml",
    ".github/workflows/production-certification.yml",
    "scripts/verify_apk.sh",
    "scripts/install_maestro.sh",
    "scripts/restore_runtime_fixture.sh",
    "scripts/build_runtime_fixture_fallback.sh",
    "scripts/run_emulator_selftest_v60g.sh",
    "scripts/execution_acceleration.py",
    "scripts/certification_gate.py",
    "scripts/package_build_contract.py",
    "scripts/validate_build_contract.py",
    "scripts/trusted_evidence_manifest.py",
    "scripts/project_adapter.py",
    "scripts/project_autodiscover.py",
    "selftest/**",
    ".maestro/**",
    "tests/flows/selftest.yaml",
)

# Specialist producers are independently selectable. A change to one producer
# exercises runtime/maestro sentinels plus that exact lab instead of all labs.
TARGETED_LAB_PATTERNS: dict[str, tuple[str, ...]] = {
    "system": ("scripts/system_lab.py",),
    "performance": (
        "scripts/performance_lab.py",
        "scripts/prepare_performance_baseline.py",
    ),
    "network": ("scripts/network_lab.py",),
    "persistence": ("scripts/persistence_lab.py",),
    "configuration": ("scripts/configuration_lab.py",),
    "resource_pressure": ("scripts/resource_pressure_lab.py",),
    "background": ("scripts/background_lab.py",),
    "storage": ("scripts/storage_lab.py",),
    "upgrade": (
        "scripts/upgrade_lab.py",
        "scripts/prepare_upgrade_baseline.py",
    ),
}
TARGETED_VISUAL_PATTERNS = (
    "scripts/visual_qa.py",
    "scripts/visual_policy.py",
    "scripts/visual_regression.py",
    "scripts/visual_journey.py",
    "scripts/visual_journey_runtime.py",
    "scripts/interaction_crawler.py",
)

# Bounded orchestration/intelligence changes still exercise launch, Maestro,
# interaction and crash/visual sentinels, but do not run unrelated specialist
# labs. These scripts are covered in depth by static/contract CI.
FAST_PATTERNS = (
    "scripts/agent_work_graph_v60a.py",
    "scripts/causal_repo_investigator_v60b.py",
    "scripts/bounded_fix_worker_v60c.py",
    "scripts/verify_repair_loop_v60d.py",
    "scripts/draft_pr_steward_v60e.py",
    "scripts/autonomous_failure_triage_v58a.py",
    "scripts/contract_fingerprint.py",
    "scripts/maintainability_budget.py",
    "scripts/advanced_hardening_v56e.py",
    "scripts/control_center_snapshot.py",
    "scripts/selftest_runtime_profile_v60g.py",
    "scripts/agent_memory_v60f.py",
    "scripts/sensor_mesh_v60h.py",
    "scripts/agent_operations_studio_v60i.py",
    "integration/orchestration/**",
    "integration/performance/**",
)

NON_RUNTIME_PATTERNS = (
    "README.md",
    "ROADMAP.md",
    "docs/**",
    "integration/**/*.md",
    "integration/**/*.json",
    "tests/contracts/**",
)


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _unit_for_lab(lab: str) -> str:
    if lab == "system":
        return "lifecycle"
    if lab == "resource_pressure":
        return "resource-pressure"
    return lab


def plan(changed_files: list[str]) -> dict[str, Any]:
    files = sorted(
        dict.fromkeys(
            str(value).strip().replace("\\", "/")
            for value in changed_files
            if str(value).strip()
        )
    )
    if not files:
        return _report(
            files=[],
            profile="FULL",
            reason="NO_TRUSTED_DIFF",
            full=[],
            fast=[],
            targeted={},
            visual=[],
            unknown=[],
        )

    full = [path for path in files if _matches(path, FULL_PATTERNS)]
    fast = [path for path in files if _matches(path, FAST_PATTERNS)]
    targeted: dict[str, list[str]] = {}
    targeted_paths: set[str] = set()
    for lab, patterns in TARGETED_LAB_PATTERNS.items():
        rows = [path for path in files if _matches(path, patterns)]
        if rows:
            targeted[lab] = rows
            targeted_paths.update(rows)
    visual = [path for path in files if _matches(path, TARGETED_VISUAL_PATTERNS)]
    targeted_paths.update(visual)

    known = set(full) | set(fast) | targeted_paths
    unknown_runtime = [
        path
        for path in files
        if path.startswith("scripts/")
        and path not in known
        and not _matches(path, NON_RUNTIME_PATTERNS)
    ]

    if full:
        profile = "FULL"
        reason = "RUNTIME_OR_CERTIFICATION_SURFACE_CHANGED"
    elif unknown_runtime:
        profile = "FULL"
        reason = "UNKNOWN_SCRIPT_SURFACE_FAIL_CLOSED"
    elif targeted or visual:
        profile = "FAST"
        reason = "TARGETED_RUNTIME_UNITS"
    elif fast:
        profile = "FAST"
        reason = "BOUNDED_ORCHESTRATION_SURFACE"
    else:
        # Outer workflow scope decides whether runtime is applicable. If this
        # planner is called with only non-runtime files, retain bounded smoke
        # rather than inventing a runtime PASS from no execution.
        profile = "FAST"
        reason = "NO_RUNTIME_CRITICAL_SURFACE"

    return _report(
        files=files,
        profile=profile,
        reason=reason,
        full=full,
        fast=fast,
        targeted=targeted,
        visual=visual,
        unknown=unknown_runtime,
    )


def _report(
    *,
    files: list[str],
    profile: str,
    reason: str,
    full: list[str],
    fast: list[str],
    targeted: dict[str, list[str]],
    visual: list[str],
    unknown: list[str],
) -> dict[str, Any]:
    selected_labs = list(LABS) if profile == "FULL" else sorted(targeted)
    if profile == "FULL":
        units = list(ALL_UNITS)
    else:
        units = ["runtime-core", "maestro-core"]
        units.extend(_unit_for_lab(lab) for lab in selected_labs)
        units = list(dict.fromkeys(units))

    return {
        "schema_version": 1,
        "profile_version": PROFILE_VERSION,
        "profile": profile,
        "reason": reason,
        "changed_files": files,
        "full_trigger_files": full,
        "fast_trigger_files": fast,
        "targeted_lab_files": targeted,
        "visual_trigger_files": visual,
        "unknown_runtime_files": unknown,
        "selected_labs": selected_labs,
        "units": units,
        "run_maestro": True,
        "full_depth_unchanged": True,
        "fast_core_sentinels_required": [
            "launch",
            "maestro",
            "crash_anr_scan",
            "visual_qa",
            "interaction",
        ],
        "certification_authority": "UNCHANGED",
    }


def self_test() -> None:
    assert plan(["scripts/verify_apk.sh"])["profile"] == "FULL"
    assert plan(["scripts/execution_acceleration.py"])["profile"] == "FULL"
    assert plan([".github/workflows/production-certification.yml"])["profile"] == "FULL"
    network = plan(["scripts/network_lab.py"])
    assert network["profile"] == "FAST"
    assert network["selected_labs"] == ["network"]
    assert "network" in network["units"]
    assert plan(["selftest/app/src/main/java/Foo.kt"])["profile"] == "FULL"
    orchestration = plan(["scripts/agent_work_graph_v60a.py"])
    assert orchestration["profile"] == "FAST"
    assert orchestration["selected_labs"] == []
    visual = plan(["scripts/visual_qa.py"])
    assert visual["profile"] == "FAST"
    assert visual["selected_labs"] == []
    unknown = plan(["scripts/new_unknown_runtime_engine.py"])
    assert unknown["profile"] == "FULL"
    assert unknown["reason"] == "UNKNOWN_SCRIPT_SURFACE_FAIL_CLOSED"
    mixed = plan([
        "scripts/agent_memory_v60f.py",
        "scripts/configuration_lab.py",
    ])
    assert mixed["profile"] == "FAST"
    assert mixed["selected_labs"] == ["configuration"]
    operations = plan(["scripts/agent_operations_studio_v60i.py"])
    assert operations["profile"] == "FAST"
    assert operations["reason"] == "BOUNDED_ORCHESTRATION_SURFACE"
    f_delta = plan([
        "scripts/agent_memory_v60f.py",
        "scripts/autonomous_failure_triage_v58a.py",
        "scripts/contract_fingerprint.py",
        "scripts/maintainability_budget.py",
    ])
    assert f_delta["profile"] == "FAST"
    assert f_delta["reason"] == "BOUNDED_ORCHESTRATION_SURFACE"
    h_delta = plan([
        "scripts/sensor_mesh_v60h.py",
        "scripts/advanced_hardening_v56e.py",
        "scripts/contract_fingerprint.py",
        "scripts/maintainability_budget.py",
    ])
    assert h_delta["profile"] == "FAST"
    assert h_delta["reason"] == "BOUNDED_ORCHESTRATION_SURFACE"
    docs = plan(["integration/performance/NOTE.md"])
    assert docs["profile"] == "FAST"
    empty = plan([])
    assert empty["profile"] == "FULL"
    print("AppLab v6.0G self-test runtime profile planner PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--changed-files", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.changed_files:
        raise SystemExit("--changed-files is required")
    path = Path(args.changed_files)
    files = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    report = plan(files)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"profile={report['profile']}\n")
            handle.write(f"reason={report['reason']}\n")
            handle.write(f"selected_labs={','.join(report['selected_labs'])}\n")
            handle.write(f"units={','.join(report['units'])}\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
