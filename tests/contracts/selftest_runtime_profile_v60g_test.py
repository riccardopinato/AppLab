#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import selftest_runtime_profile_v60g as planner  # noqa: E402


def main() -> int:
    full = planner.plan(["scripts/verify_apk.sh"])
    assert full["profile"] == "FULL"
    assert full["full_depth_unchanged"] is True

    fast = planner.plan([
        "scripts/agent_work_graph_v60a.py",
        "tests/contracts/agent_work_graph_v60a_test.py",
    ])
    assert fast["profile"] == "FAST"
    assert "launch" in fast["fast_core_sentinels_required"]
    assert "maestro" in fast["fast_core_sentinels_required"]

    unknown = planner.plan(["scripts/future_unclassified_runtime.py"])
    assert unknown["profile"] == "FULL"
    assert unknown["unknown_runtime_files"] == [
        "scripts/future_unclassified_runtime.py"
    ]

    mixed = planner.plan([
        "scripts/draft_pr_steward_v60e.py",
        "scripts/network_lab.py",
    ])
    assert mixed["profile"] == "FULL"

    workflow = (
        ROOT / ".github" / "workflows" / "emulator-self-test.yml"
    ).read_text(encoding="utf-8")
    for required in (
        "Plan v6.0G self-test runtime depth",
        "selftest_runtime_profile_v60g.py",
        'SELFTEST_PROFILE="${{ needs.scope.outputs.profile }}"',
        'if [[ "$SELFTEST_PROFILE" == "FAST" ]]',
        'test "$SELFTEST_PROFILE" = "FULL"',
        "V60G_ORCHESTRATION_FAST",
        "RUN_MAESTRO=true",
        'assert result["maestro"] == "PASS"',
        "applab-report-certification",
    ):
        assert required in workflow, required

    # FAST is additive selection, not a replacement of the legacy FULL
    # contract. All deep specialist/certification assertions remain in workflow.
    for evidence in (
        "network-lab.json",
        "persistence-lab.json",
        "configuration-lab.json",
        "resource-pressure-lab.json",
        "background-lab.json",
        "storage-lab.json",
        "upgrade-lab.json",
        "certification_gate.py",
    ):
        assert evidence in workflow, evidence

    planner.self_test()
    print("AppLab v6.0G self-test throughput contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
