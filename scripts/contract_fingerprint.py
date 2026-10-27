#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

CONTRACT_FILES = (
    "scripts/verify_apk.sh",
    "scripts/certification_gate.py",
    "scripts/finalize_external_result.py",
    "scripts/release_reality.py",
    "scripts/physical_evidence.py",
    "scripts/evidence_contract_registry.py",
    "scripts/finalize_certification_matrix.py",
    "scripts/run_external_android_gate.sh",
    "scripts/dismiss_foreign_anr.py",
    "scripts/visual_qa.py",
    "scripts/visual_policy.py",
    "scripts/visual_regression.py",
    "scripts/visual_journey.py",
    "scripts/visual_journey_runtime.py",
    "scripts/prepare_visual_baseline.py",
    "scripts/validate_build_contract.py",
    "scripts/package_build_contract.py",
    "scripts/install_maestro.sh",
    "scripts/interaction_crawler.py",
    "scripts/system_lab.py",
    "scripts/performance_lab.py",
    "scripts/network_lab.py",
    "scripts/persistence_lab.py",
    "scripts/configuration_lab.py",
    "scripts/resource_pressure_lab.py",
    "scripts/background_lab.py",
    "scripts/storage_lab.py",
    "scripts/smart_test_plan.py",
    "scripts/journey_planner.py",
    "scripts/journey_runtime.py",
    "scripts/journey_runtime_support.py",
    "config/journey-runtime-pilots.json",
    "scripts/journey_sharding.py",
    "scripts/journey_sharding_admission.py",
    "scripts/journey_shard_runtime.py",
    "scripts/journey_shard_aggregate.py",
    "scripts/finalize_journey_shard_result.py",
    "scripts/run_journey_shard.sh",
    "config/journey-sharding-pilots.json",
    "scripts/planner_feedback.py",
    "scripts/planner_feedback_contract.py",
    "scripts/restore_planner_feedback.sh",
    "scripts/adaptive_checks.py",
    "scripts/incremental_result.py",
    "scripts/shadow_calibration.py",
    "scripts/delta_calibration.py",
    "scripts/domain_fingerprint.py",
    "scripts/pipeline_metrics.py",
    "scripts/github_run_started_at.py",
    "scripts/history_learning.py",
    "scripts/verification_intelligence.py",
    "scripts/agent_work_graph_v60a.py",
    "scripts/causal_repo_investigator_v60b.py",
    "scripts/bounded_fix_worker_v60c.py",
    "scripts/verify_repair_loop_v60d.py",
    "scripts/self_change_plan_v60g.py",
    "scripts/autonomous_pr_steward_v60e.py",
    "scripts/agent_memory_v60f.py",
    "integration/orchestration/contracts/agent-episodic-memory-v1.json",
    "integration/orchestration/contracts/autonomous-pr-steward-v1.json",
    "scripts/self_evidence_dag_v60g.py",
    "scripts/run_evidence_node_v60g.sh",
    "integration/performance/contracts/self-dogfooding-plan-v1.json",
    ".github/workflows/emulator-self-test.yml",
    ".github/workflows/autonomous-app-review-v31.yml",
    "integration/orchestration/contracts/verify-repair-loop-v1.json",
    "integration/orchestration/contracts/bounded-fix-worker-v1.json",
    "integration/orchestration/contracts/causal-repo-investigator-v1.json",
    "integration/orchestration/contracts/agent-work-graph-v1.json",
    "scripts/verification_reuse_promotion_v57e.py",
    "scripts/build_once_promotion_v59d.py",
    "scripts/warm_runtime_route_v59e.py",
    "config/warm-runtime-production.json",
    "scripts/upgrade_lab.py",
    "scripts/prepare_upgrade_baseline.py",
    "scripts/prepare_performance_baseline.py",
    "scripts/project_autodiscover.py",
    "scripts/project_adapter.py",
    ".github/workflows/external-project-runner.yml",
    ".github/workflows/external-native-android-runner.yml",
    ".github/workflows/universal-project-runner.yml",
    ".github/workflows/trusted-apk-verifier.yml",
    ".github/workflows/production-certification.yml",
)
CONTRACT_VERSION = "1.0.0"

def compute(root: Path) -> str:
    digest = hashlib.sha256()
    digest.update(f"AppLab contract {CONTRACT_VERSION}\0".encode())
    files = list(CONTRACT_FILES)
    profiles = root / "watch-profiles"
    if profiles.is_dir():
        files.extend(
            str(path.relative_to(root))
            for path in sorted(profiles.rglob("*"))
            if path.is_file()
        )
    for relative in files:
        path = root / relative
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--short", action="store_true")
    args = parser.parse_args()
    value = compute(Path(args.root))
    print(value[:16] if args.short else value)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
