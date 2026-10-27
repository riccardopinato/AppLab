#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# These are growth ceilings, not quality scores. Crossing a ceiling requires
# extraction/refactor justification before more logic is added to the monolith.
LIMITS = {
    "scripts/app_intelligence.py": 1600,
    "scripts/studio_snapshot.py": 950,
    "scripts/verify_apk.sh": 1150,
    "scripts/longitudinal_product_intelligence.py": 1100,
    "scripts/autonomous_app_review.py": 500,
    "scripts/competitive_product_intelligence.py": 750,
    "scripts/studio_competitive_product.py": 350,
    "scripts/virtual_product_review_council.py": 700,
    "scripts/studio_review_council.py": 350,
    "scripts/evidence_retention_contract.py": 180,
    "scripts/evidence_contract_registry.py": 480,
    "scripts/audit_contract_schema.py": 180,
    "scripts/delta_calibration.py": 420,
    "scripts/audit_contract_delta.py": 150,
    "scripts/audit_contract_v59.py": 120,
    "scripts/smart_test_plan.py": 1000,
    "scripts/journey_planner.py": 300,
    "scripts/journey_runtime.py": 360,
    "scripts/journey_runtime_support.py": 300,
    "scripts/journey_sharding.py": 300,
    "scripts/journey_sharding_admission.py": 180,
    "scripts/build_once_promotion_v59d.py": 230,
    "scripts/external_review_watchdog_v59e.py": 220,
    "scripts/watchdog_github_v59e.py": 80,
    "scripts/external_review_support_v59e.py": 250,
    "scripts/external_review_reconcile_v59e.py": 220,
    "scripts/supersession_support_v59e.py": 260,
    "scripts/supersession_watchdog_v59e.py": 220,
    "scripts/audit_contract_v59e.py": 180,
    "scripts/agent_work_graph_v60a.py": 950,
    "scripts/causal_repo_investigator_v60b.py": 650,
    "scripts/bounded_fix_worker_v60c.py": 720,
    "scripts/verify_repair_loop_v60d.py": 980,
    "scripts/draft_pr_steward_v60e.py": 760,
    "scripts/selftest_runtime_profile_v60g.py": 340,
    "scripts/review_evidence_dag_v60g.py": 430,
    "scripts/agent_memory_v60f.py": 720,
    "scripts/sensor_mesh_v60h.py": 430,
    "scripts/agent_operations_studio_v60i.py": 320,
    "frontend/src/AgentOperationsPanel.tsx": 220,
    "scripts/warm_runtime_route_v59e.py": 190,
    "scripts/journey_shard_runtime.py": 180,
    "scripts/journey_shard_aggregate.py": 220,
    "scripts/finalize_journey_shard_result.py": 280,
    "scripts/planner_feedback.py": 280,
    "scripts/planner_feedback_contract.py": 260,
    "scripts/evidence_graph.py": 2400,
    "scripts/audit_contract_test.py": 1300,
    "scripts/audit_contract_hardening.py": 320,
    "scripts/studio_snapshot_self_test.py": 450,
    "scripts/evidence_graph_self_test.py": 320,
    "frontend/src/ControlCenter.tsx": 1750,
    "frontend/src/App.tsx": 850,
    ".github/workflows/external-project-runner.yml": 900,
    ".github/workflows/external-native-android-runner.yml": 900,
}


def logical_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def main() -> int:
    failures: list[str] = []
    for relative, limit in LIMITS.items():
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"missing tracked maintainability file: {relative}")
            continue
        lines = logical_lines(path)
        print(f"{relative}: {lines}/{limit} lines")
        if lines > limit:
            failures.append(
                f"{relative} exceeded maintainability growth ceiling: {lines} > {limit}"
            )
    if failures:
        raise SystemExit("\n".join(failures))
    print("AppLab maintainability growth budget PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
