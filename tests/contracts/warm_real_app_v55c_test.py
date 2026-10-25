#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import warm_real_app_v55c as mod

def main()->int:
    proof=mod.self_test()
    assert proof["status"]=="PASS"
    assert proof["repositories"]==list(mod.REAL_APP_REPOSITORIES)
    assert proof["proof_count"]==2
    assert proof["github_actions_fallback"] is True
    assert proof["coverage_reduction_enabled"] is False
    assert proof["target_build_scripts_on_warm_worker"] is False
    for row in proof["proofs"]:
        assert row["equivalence"]["equivalent"] is True
        assert row["target_build_executor"]=="GITHUB_ACTIONS_UNTRUSTED_BUILD_JOB"
        assert row["trusted_runtime_executor"]=="WARM_TRUSTED_ANDROID"
        assert row["fallback_executor"]=="GITHUB_ACTIONS"
    print("v5.5C warm-worker real-app contract PASS")
    return 0
if __name__=="__main__":
    raise SystemExit(main())
