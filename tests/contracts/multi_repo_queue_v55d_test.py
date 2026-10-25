#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/"scripts"))
import multi_repo_queue_v55d as mod
def main()->int:
    p=mod.self_test()
    assert p["status"]=="PASS" and p["operations"]==12
    assert p["fairness"]["all_repositories_in_first_six"] is True
    assert set(p["fairness"]["claims_per_repository"].values())=={4}
    assert p["priority"]["highest_priority_claimed_first"] is True
    assert p["priority"]["aging_order_change_proven"] is True
    assert p["backpressure"]["deferred_observed"] is True
    assert p["backpressure"]["global_pending_overflow_rejected"] is True
    assert p["backpressure"]["per_repo_pending_overflow_rejected"] is True
    assert p["repository_isolation"]["overlapping_cross_repo_leases"] is True
    assert p["repository_isolation"]["same_repo_second_lease_blocked"] is True
    assert p["repository_isolation"]["global_active_limit_observed"] is True
    assert p["repository_isolation"]["integrity_ok"] is True
    assert p["coverage_reduction_enabled"] is False
    assert p["github_actions_fallback"] is True
    assert p["production_certification_authority"]=="UNCHANGED"
    assert p["telemetry"]["queue_start_seconds"]["p95"]>=p["telemetry"]["queue_start_seconds"]["p50"]
    assert p["telemetry"]["runtime_seconds"]["p95"]>=p["telemetry"]["runtime_seconds"]["p50"]
    print("v5.5D multi-repo queue contract PASS"); return 0
if __name__=="__main__": raise SystemExit(main())
