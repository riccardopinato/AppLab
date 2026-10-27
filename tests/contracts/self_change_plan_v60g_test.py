#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import self_change_plan_v60g as mod  # noqa: E402


def main() -> int:
    contract = mod.load_contract()

    cases = [
        (["README.md"], "NO_ANDROID_RUNTIME"),
        (["scripts/external_review_watchdog_v59e.py"], "NO_ANDROID_RUNTIME"),
        (["scripts/agent_work_graph_v60a.py"], "NO_ANDROID_RUNTIME"),
        (["scripts/network_lab.py"], "FAST_RUNTIME"),
        (["scripts/visual_regression.py"], "FAST_RUNTIME"),
        ([".maestro/selftest.yaml"], "FAST_RUNTIME"),
        (["scripts/verify_apk.sh"], "FULL_RUNTIME"),
        (["scripts/smart_test_plan.py"], "FULL_RUNTIME"),
        ([".github/workflows/emulator-self-test.yml"], "FULL_RUNTIME"),
        (["scripts/unknown_runtime_path.py"], "FULL_RUNTIME"),
    ]
    for paths, expected in cases:
        plan = mod.build_plan(paths, contract)
        assert plan["mode"] == expected, (paths, plan)

    network = mod.build_plan(["scripts/network_lab.py"], contract)
    assert network["selected_labs"]["network"] is True
    assert all(
        value is (name == "network")
        for name, value in network["selected_labs"].items()
    )
    assert network["selected_journeys"]["runtime-core"] is True
    assert network["selected_journeys"]["certification-contract"] is False

    maestro = mod.build_plan([".maestro/selftest.yaml"], contract)
    assert maestro["run_maestro"] is True

    mixed = mod.build_plan(
        ["scripts/external_review_watchdog_v59e.py", "scripts/storage_lab.py"],
        contract,
    )
    assert mixed["mode"] == "FAST_RUNTIME"
    assert mixed["selected_labs"]["storage"] is True

    escalation = mod.build_plan(
        ["scripts/network_lab.py", "scripts/verify_apk.sh"],
        contract,
    )
    assert escalation["mode"] == "FULL_RUNTIME"
    assert all(escalation["selected_labs"].values())

    mod.self_test()
    print("AppLab v6.0G self-change planner contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
