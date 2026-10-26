#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from autonomous_failure_triage_v58a import build_triage
from fix_candidate_planner_v58b import build_plan
from proposal_pr_package_v58c import build_package


def run_pilot() -> dict[str, Any]:
    plan = {
        "repository": "riccardopinato/AppLab",
        "head_sha": "b" * 40,
        "baseline_sha": "a" * 40,
        "lane": "FAST_RUNTIME",
        "playbook": {"category": "general_code_change"},
        "learning_profile": {"unstable_labs": []},
    }
    failure = {
        "repository": "riccardopinato/AppLab",
        "resolved_sha": "b" * 40,
        "result": "FAIL",
        "pipeline_status": "failure",
        "reason": "unit test failed in bounded self-repo pilot fixture",
        "runtime_executed": False,
    }
    triage = build_triage(failure, plan)
    fix = build_plan(triage)
    package = build_package(triage, fix)
    return {
        "schema_version": 1,
        "record_type": "BOUNDED_SELF_REPO_PILOT_V58E",
        "authority": "PROPOSAL_ONLY",
        "repository": "riccardopinato/AppLab",
        "fixture_only": True,
        "triage": triage,
        "fix_plan": fix,
        "pr_package": package,
        "kill_switch": True,
        "guardrails": {
            "github_write_performed": False,
            "automatic_retry": False,
            "automatic_merge": False,
            "automatic_release": False,
            "exact_head_required_for_any_future_real_fix": True,
        },
    }


def self_test() -> None:
    report = run_pilot()
    assert report["triage"]["classification"] == "BUILD_OR_QUALITY_FAILURE"
    assert report["fix_plan"]["state"] == "FIX_CANDIDATE_READY"
    assert report["pr_package"]["state"] == "READY_FOR_AGENT"
    assert report["pr_package"]["guardrails"]["can_create_pr"] is False
    assert report["guardrails"]["github_write_performed"] is False
    assert report["kill_switch"] is True
    print("AppLab v5.8E bounded self-repo pilot PASS")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    report = run_pilot()
    if a.self_test:
        self_test()
        return 0
    if a.output:
        Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
