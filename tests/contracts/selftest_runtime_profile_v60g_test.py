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

    execution_contract = planner.plan(["scripts/execution_acceleration.py"])
    assert execution_contract["profile"] == "FULL"
    assert execution_contract["reason"] == "RUNTIME_OR_CERTIFICATION_SURFACE_CHANGED"

    runtime_transport = planner.plan([
        "backend/app/runtime.py",
        "backend/app/gateway_wrapper.py",
        "frontend/e2e/live-webrtc.spec.mjs",
    ])
    assert runtime_transport["profile"] == "FULL"
    assert runtime_transport["reason"] == "RUNTIME_OR_CERTIFICATION_SURFACE_CHANGED"
    assert set(runtime_transport["full_trigger_files"]) == {
        "backend/app/runtime.py",
        "backend/app/gateway_wrapper.py",
        "frontend/e2e/live-webrtc.spec.mjs",
    }

    fast = planner.plan([
        "scripts/agent_work_graph_v60a.py",
        "tests/contracts/agent_work_graph_v60a_test.py",
    ])
    assert fast["profile"] == "FAST"
    assert "launch" in fast["fast_core_sentinels_required"]
    assert "maestro" in fast["fast_core_sentinels_required"]

    operations = planner.plan(["scripts/agent_operations_studio_v60i.py"])
    assert operations["profile"] == "FAST"
    assert operations["reason"] == "BOUNDED_ORCHESTRATION_SURFACE"

    unknown = planner.plan(["scripts/future_unclassified_runtime.py"])
    assert unknown["profile"] == "FULL"
    assert unknown["unknown_runtime_files"] == [
        "scripts/future_unclassified_runtime.py"
    ]

    network = planner.plan(["scripts/network_lab.py"])
    assert network["profile"] == "FAST"
    assert network["selected_labs"] == ["network"]
    assert "network" in network["units"]

    mixed = planner.plan([
        "scripts/draft_pr_steward_v60e.py",
        "scripts/network_lab.py",
    ])
    assert mixed["profile"] == "FAST"
    assert mixed["selected_labs"] == ["network"]

    workflow = (
        ROOT / ".github" / "workflows" / "emulator-self-test.yml"
    ).read_text(encoding="utf-8")
    runner = (ROOT / "scripts" / "run_emulator_selftest_v60g.sh").read_text(
        encoding="utf-8"
    )
    assert "needs: scope" not in workflow
    assert "\n  android-runtime:\n    runs-on: ubuntu-latest" in workflow
    assert "name: Android runtime / required-check scope" not in workflow
    assert "steps.scope.outputs.run == 'true'" in workflow
    assert "fetch-depth: 0" in workflow

    for required in (
        "Plan v6.0G self-test runtime depth",
        "selftest_runtime_profile_v60g.py",
        "SELFTEST_PROFILE='${{ steps.profile.outputs.profile }}'",
        "SELFTEST_SELECTED_LABS='${{ steps.profile.outputs.selected_labs }}'",
        "bash scripts/run_emulator_selftest_v60g.sh",
    ):
        assert required in workflow, required

    # The emulator runner executes each workflow script line independently, so
    # FAST/FULL control flow must live inside one repository shell process.
    assert 'if [[ "$SELFTEST_PROFILE" == "FAST" ]]' in runner
    assert 'test "$SELFTEST_PROFILE" = "FULL"' in runner
    assert "V60G_TARGETED_SELFTEST_UNIT" in runner
    assert "RUN_MAESTRO=true" in runner
    assert 'assert result["maestro"] == "PASS"' in runner
    assert "applab-report-certification" in runner

    # FAST is additive selection, not a replacement of the legacy FULL
    # contract. All deep specialist/certification assertions remain in the
    # repository runner script.
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
        assert evidence in runner, evidence

    planner.self_test()
    print("AppLab v6.0G self-test throughput contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
