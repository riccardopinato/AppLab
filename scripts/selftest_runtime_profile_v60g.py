#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
from typing import Any

PROFILE_VERSION = "1.0"

# Changes to these surfaces can alter runtime/certification semantics and must
# preserve the complete self-test depth.
FULL_PATTERNS = (
    ".github/workflows/emulator-self-test.yml",
    ".github/workflows/runtime-fixture-build.yml",
    "scripts/verify_apk.sh",
    "scripts/install_maestro.sh",
    "scripts/restore_runtime_fixture.sh",
    "scripts/build_runtime_fixture_fallback.sh",
    "scripts/system_lab.py",
    "scripts/performance_lab.py",
    "scripts/network_lab.py",
    "scripts/persistence_lab.py",
    "scripts/configuration_lab.py",
    "scripts/resource_pressure_lab.py",
    "scripts/background_lab.py",
    "scripts/storage_lab.py",
    "scripts/upgrade_lab.py",
    "scripts/visual_qa.py",
    "scripts/visual_policy.py",
    "scripts/visual_regression.py",
    "scripts/visual_journey.py",
    "scripts/certification_gate.py",
    "scripts/package_build_contract.py",
    "scripts/validate_build_contract.py",
    "scripts/trusted_evidence_manifest.py",
    "scripts/project_adapter.py",
    "selftest/**",
    ".maestro/**",
    "tests/flows/selftest.yaml",
)

# Bounded orchestration/intelligence changes still exercise core launch, Maestro,
# crash/visual sentinels and the FAST verifier, but do not need nine specialist
# labs + duplicate no-Maestro + certification canary on every PR.
FAST_PATTERNS = (
    "scripts/agent_work_graph_v60a.py",
    "scripts/causal_repo_investigator_v60b.py",
    "scripts/bounded_fix_worker_v60c.py",
    "scripts/verify_repair_loop_v60d.py",
    "scripts/draft_pr_steward_v60e.py",
    "scripts/selftest_runtime_profile_v60g.py",
    "scripts/agent_memory_v60f.py",
    "scripts/sensor_mesh_v60h.py",
    "scripts/agentic_operations_snapshot_v60i.py",
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


def plan(changed_files: list[str]) -> dict[str, Any]:
    files = sorted(dict.fromkeys(str(x).strip().replace("\\", "/") for x in changed_files if str(x).strip()))
    if not files:
        return {
            "schema_version": 1,
            "profile_version": PROFILE_VERSION,
            "profile": "FULL",
            "reason": "NO_TRUSTED_DIFF",
            "changed_files": [],
            "full_trigger_files": [],
            "fast_trigger_files": [],
            "unknown_runtime_files": [],
        }

    full = [path for path in files if _matches(path, FULL_PATTERNS)]
    fast = [path for path in files if _matches(path, FAST_PATTERNS)]
    unknown_runtime = [
        path
        for path in files
        if path.startswith("scripts/")
        and path not in full
        and path not in fast
        and not _matches(path, NON_RUNTIME_PATTERNS)
    ]

    if full:
        profile = "FULL"
        reason = "RUNTIME_OR_CERTIFICATION_SURFACE_CHANGED"
    elif unknown_runtime:
        profile = "FULL"
        reason = "UNKNOWN_SCRIPT_SURFACE_FAIL_CLOSED"
    elif fast:
        profile = "FAST"
        reason = "BOUNDED_ORCHESTRATION_SURFACE"
    else:
        # The workflow's outer scope decides whether runtime runs at all. If it
        # called this planner with only non-runtime files, keep FAST as a safe
        # bounded smoke rather than inventing a runtime PASS.
        profile = "FAST"
        reason = "NO_RUNTIME_CRITICAL_SURFACE"

    return {
        "schema_version": 1,
        "profile_version": PROFILE_VERSION,
        "profile": profile,
        "reason": reason,
        "changed_files": files,
        "full_trigger_files": full,
        "fast_trigger_files": fast,
        "unknown_runtime_files": unknown_runtime,
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
    assert plan(["scripts/network_lab.py"])["profile"] == "FULL"
    assert plan(["selftest/app/src/main/java/Foo.kt"])["profile"] == "FULL"
    assert plan(["scripts/agent_work_graph_v60a.py"])["profile"] == "FAST"
    assert plan(["scripts/draft_pr_steward_v60e.py"])["profile"] == "FAST"
    unknown = plan(["scripts/new_unknown_runtime_engine.py"])
    assert unknown["profile"] == "FULL"
    assert unknown["reason"] == "UNKNOWN_SCRIPT_SURFACE_FAIL_CLOSED"
    mixed = plan([
        "scripts/agent_memory_v60f.py",
        "scripts/configuration_lab.py",
    ])
    assert mixed["profile"] == "FULL"
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
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
