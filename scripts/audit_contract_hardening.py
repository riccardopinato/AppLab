#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


def run_check(name: str, namespace: dict[str, Any]) -> None:
    globals().update(namespace)
    check = globals().get(name)
    if not callable(check):
        raise AssertionError(f"unknown hardening audit check: {name}")
    check()


def check_v531_technical_hardening_contract() -> None:
    live_spec = (ROOT / "frontend/e2e/live-webrtc.spec.mjs").read_text(encoding="utf-8")
    live_workflow = (ROOT / ".github/workflows/live-emulator-self-test.yml").read_text(
        encoding="utf-8"
    )
    preview = (ROOT / ".github/workflows/web-preview.yml").read_text(encoding="utf-8")
    lock = (ROOT / ".github/workflows/frontend-lock.yml").read_text(encoding="utf-8")
    production = (ROOT / ".github/workflows/production-certification.yml").read_text(
        encoding="utf-8"
    )
    retention = (ROOT / "scripts/evidence_retention_contract.py").read_text(
        encoding="utf-8"
    )
    maintainability = (ROOT / "scripts/maintainability_budget.py").read_text(
        encoding="utf-8"
    )

    for needle in (
        "async function videoDiagnostics",
        "async function attachFrameRecoveryDiagnostics",
        "async function waitForDecodedFrame",
        "webrtc-frame-recovery-attempt-",
        "for (let attempt = 1; attempt <= 2; attempt += 1)",
        "if (attempt === 2) throw error",
        "WebRTC connected but no decoded Android video frame arrived",
        "WebRTC connected but no non-black Android frame was decoded",
        "Android UI did not react to the WebRTC pointer input",
    ):
        require(needle in live_spec, f"v5.3.1 WebRTC hardening missing invariant: {needle}")

    for needle in (
        "Setup Node for browser tooling",
        'node-version: "22"',
        "Validate frontend dependency graph before runtime work",
        "npm ci --ignore-scripts --no-audit --no-fund --dry-run",
        "frontend-dependency-preflight.txt",
        "retention-days: 7",
    ):
        require(needle in live_workflow, f"v5.3.1 live workflow hardening missing: {needle}")

    for needle in (
        "pull_request:",
        "applab-frontend-lock-${{ github.ref }}",
        "Validate install graph",
        "Require clean lockfile on pull request",
        "github.event_name != 'pull_request'",
    ):
        require(needle in lock, f"v5.3.1 frontend lock hardening missing: {needle}")

    for needle in (
        "Detect Pages availability",
        "pages_enabled: ${{ steps.pages_status.outputs.enabled }}",
        "Upload non-deployed preview evidence",
        "if: steps.pages_status.outputs.enabled == 'true'",
        "if: needs.build.outputs.pages_enabled == 'true'",
        "GitHub Pages is not configured for this repository",
    ):
        require(needle in preview, f"v5.3.1 preview hardening missing: {needle}")

    for needle in (
        'POLICY_VERSION = "1.0"',
        '"RELEASE_CRITICAL", 90',
        '"LONGITUDINAL", 90',
        '"INFRA_DIAGNOSTIC", 7',
        "Upload certified release bundle",
        "Upload final certification evidence",
        "Upload certification history",
        "Upload physical evidence attestation",
        "Upload paired verification evidence",
        "Upload repository-wide longitudinal history",
        "Upload live browser evidence",
        "AppLab evidence retention policy v",
    ):
        require(needle in retention, f"v5.3.1 retention contract missing invariant: {needle}")

    require(
        production.count("retention-days: 90") >= 3,
        "production certification release-critical artifacts must retain 90 days",
    )
    require(
        '"scripts/evidence_retention_contract.py": 180' in maintainability,
        "retention contract must have a maintainability ceiling",
    )
    require(
        (ROOT / "integration/hardening/TECHNICAL_HARDENING_V531.md").is_file(),
        "v5.3.1 technical hardening documentation is required",
    )


def check_v532_graph_aware_planning_feedback_contract() -> None:
    feedback = (ROOT / "scripts/planner_feedback.py").read_text(encoding="utf-8")
    feedback_contract = (ROOT / "scripts/planner_feedback_contract.py").read_text(encoding="utf-8")
    feedback_surface = feedback + "\n" + feedback_contract
    planner = (ROOT / "scripts/smart_test_plan.py").read_text(encoding="utf-8")
    packager = (ROOT / "scripts/package_build_contract.py").read_text(encoding="utf-8")
    graph = (ROOT / "scripts/evidence_graph.py").read_text(encoding="utf-8")
    flutter = (ROOT / ".github/workflows/external-project-runner.yml").read_text(encoding="utf-8")
    native = (ROOT / ".github/workflows/external-native-android-runner.yml").read_text(encoding="utf-8")
    review = (ROOT / ".github/workflows/autonomous-app-review-v31.yml").read_text(encoding="utf-8")
    watcher = (ROOT / ".github/workflows/repo-watcher.yml").read_text(encoding="utf-8")
    fingerprint = (ROOT / "scripts/contract_fingerprint.py").read_text(encoding="utf-8")
    maintainability = (ROOT / "scripts/maintainability_budget.py").read_text(encoding="utf-8")
    acceleration = (ROOT / "scripts/execution_acceleration.py").read_text(encoding="utf-8")
    restore = (ROOT / "scripts/restore_planner_feedback.sh").read_text(encoding="utf-8")
    learning = (ROOT / "scripts/history_learning.py").read_text(encoding="utf-8")

    for needle in (
        'ENGINE_VERSION = "5.3.3"',
        'RECORD_TYPE = "EVIDENCE_GRAPH_PLANNER_FEEDBACK"',
        'GRAPH_SCHEMA_VERSION = 2',
        'GRAPH_VERSION = "2.0"',
        'MAX_RISK_BOOST = 20',
        "def build_feedback(",
        "def evaluate_feedback(",
        '"advisory_input_only": True',
        '"smart_test_plan_remains_single_authority": True',
        '"cannot_reduce_coverage": True',
        '"current_run_graph_cannot_retroactively_change_lane": True',
        '"exact_baseline_sha_required": True',
        '"missing_invalid_or_truncated_feedback_is_ignored": True',
        "BASELINE_SHA_MISMATCH",
        "LINEAGE_MISMATCH",
        "SOURCE_ANALYSIS_TRUNCATED",
        "IMPACT_PATH_CAP_REACHED",
        "DIGEST_MISMATCH",
        "AppLab Graph-aware Planner Feedback v5.3.3 self-test PASS",
        'key not in plan for key in ("analysis_truncated", "semantic_diff_truncated", "dependency_analysis")',
        "except (TypeError, ValueError)",
    ):
        require(needle in feedback_surface, f"v5.3.2 planner-feedback contract missing: {needle}")

    for needle in (
        'from planner_feedback import evaluate_feedback',
        '"planner_version": "1.1.0"',
        "def apply_graph_planner_feedback(",
        '"coverage_reduced": False',
        "APPLIED_ESCALATION_ONLY",
        "prior trusted Evidence Graph risk escalation to FULL",
        'parser.add_argument("--planner-feedback"',
        "planner_feedback_path",
        "refresh_lane_telemetry",
        'plan["analysis_truncated"] = bool(',
    ):
        require(needle in planner, f"v5.3.2 Smart Test Plan integration missing: {needle}")

    require(
        'planner_feedback_path=args.planner_feedback' in packager
        and '"planner_feedback",' in packager
        and 'output / "planner-feedback.json"' in packager,
        "trusted build-contract recomputation must bind planner feedback immutably",
    )
    require(
        '"graph_does_not_retroactively_change_current_fast_full_certification": True' in graph
        and '"graph_does_not_change_fast_full_certification": True' not in graph,
        "Evidence Graph must express future-feedback vs current-run authority precisely",
    )

    for workflow in (flutter, native):
        for needle in (
            "Restore prior graph planner feedback",
            "restore_planner_feedback.sh",
            '${{ inputs.baseline_sha }}',
            '${{ inputs.source_ref != \'\' && inputs.source_ref || inputs.ref }}',
            '--planner-feedback "$RUNNER_TEMP/applab-planner-feedback.json"',
        ):
            require(needle in workflow, f"v5.3.2 external runner integration missing: {needle}")

    for needle in (
        "Build graph-aware planner feedback",
        "scripts/planner_feedback.py",
        "planner-feedback.md",
        ".applab-longitudinal/planner-feedback/",
        "Pin resolved SHA and delta baseline",
        "fetch-depth: 2",
        "HEAD^",
        "AppLab True Autonomous App Review v5.3.3",
    ):
        require(needle in review, f"v5.3.2 autonomous review integration missing: {needle}")

    require(
        '"scripts/planner_feedback.py"' in fingerprint
        and '"scripts/planner_feedback_contract.py"' in fingerprint
        and '"scripts/restore_planner_feedback.sh"' in fingerprint,
        "planner feedback producer/restore helper must invalidate core contract fingerprints",
    )
    require(
        '"scripts/planner_feedback.py"' in watcher
        and '"scripts/planner_feedback_contract.py"' in watcher
        and '"scripts/restore_planner_feedback.sh"' in watcher,
        "Repo Watcher must react to planner-feedback contract changes",
    )
    require(
        '"scripts/smart_test_plan.py": 1000' in maintainability
        and '"scripts/planner_feedback.py": 280' in maintainability
        and '"scripts/planner_feedback_contract.py": 260' in maintainability,
        "v5.3.2 planner modules must have maintainability ceilings",
    )
    require(
        '"planner_feedback",' in acceleration,
        "execution identity must include planner-feedback provenance",
    )
    require(
        "def refresh_lane_telemetry(" in learning
        and 'LANE_BUDGETS.get(lane, 1800)' in learning,
        "FAST-to-FULL planner promotion must refresh lane telemetry",
    )
    for needle in (
        'baseline_sha="${2:-}"',
        'source_ref="${3:-}"',
        '--hostname "$gh_host"',
        "GH_ENTERPRISE_TOKEN",
        "mapfile -t artifact_ids",
        "select_matching_feedback",
        "No compatible planner feedback found across recent longitudinal artifacts",
    ):
        require(needle in restore, f"v5.3.2 planner-feedback restore hardening missing: {needle}")
    require(
        (ROOT / "integration/hardening/GRAPH_AWARE_PLANNING_FEEDBACK_V532.md").is_file(),
        "v5.3.2 graph-aware planning feedback documentation is required",
    )

def check_v533_structural_hardening_contract() -> None:
    maintainability = (ROOT / "scripts/maintainability_budget.py").read_text(encoding="utf-8")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    registry = (ROOT / "integration/CANONICAL_WORKFLOWS.md").read_text(encoding="utf-8")
    wrapper = (ROOT / ".github/workflows/verify-flutter.yml").read_text(encoding="utf-8")
    fingerprint = (ROOT / "scripts/contract_fingerprint.py").read_text(encoding="utf-8")
    domains = (ROOT / "scripts/domain_fingerprint.py").read_text(encoding="utf-8")

    for path in (
        "scripts/planner_feedback_contract.py",
        "scripts/studio_snapshot_self_test.py",
        "scripts/evidence_graph_self_test.py",
        "scripts/audit_contract_hardening.py",
        "tests/contracts/planning_feedback_pipeline_test.py",
        "tests/contracts/workflow_structure_test.py",
    ):
        require((ROOT / path).is_file(), f"v5.3.3 structural hardening file missing: {path}")

    for needle in (
        '"scripts/planner_feedback.py": 280',
        '"scripts/planner_feedback_contract.py": 260',
        '"scripts/studio_snapshot.py": 950',
        '"scripts/evidence_graph.py": 2400',
        '"scripts/audit_contract_test.py": 1300',
        '"frontend/src/ControlCenter.tsx": 1750',
        '".github/workflows/external-project-runner.yml": 900',
        '".github/workflows/external-native-android-runner.yml": 900',
    ):
        require(needle in maintainability, f"v5.3.3 structural ceiling missing: {needle}")

    for needle in (
        "tests/contracts/planning_feedback_pipeline_test.py",
        "tests/contracts/workflow_structure_test.py",
        "python tests/contracts/planning_feedback_pipeline_test.py",
        "python tests/contracts/workflow_structure_test.py",
        "scripts/planner_feedback_contract.py",
        "scripts/audit_contract_hardening.py",
        "scripts/studio_snapshot_self_test.py",
        "scripts/evidence_graph_self_test.py",
    ):
        require(needle in ci, f"v5.3.3 CI contract missing: {needle}")

    require("verify-flutter.yml" in registry and "public compatibility wrapper" in registry.lower(),
            "Flutter compatibility wrapper must be classified in canonical registry")
    require("apk-emulator-smoke.yml" in registry and "diagnostic" in registry.lower(),
            "APK smoke workflow must be classified as diagnostic-only")
    require("v0.6.3 Unified Flutter Gate" not in wrapper,
            "Flutter compatibility wrapper must not expose stale v0.6.3 naming")
    require(not (ROOT / ".github/workflows/camperboss-16c-build-once.yml").exists(),
            "project-specific CamperBoss one-off workflow must be removed from AppLab core")
    require('"scripts/planner_feedback_contract.py"' in fingerprint,
            "extracted planner contract must invalidate build-contract fingerprints")
    require('"scripts/planner_feedback_contract.py"' in domains,
            "extracted planner contract must remain in core domain fingerprint")
    require((ROOT / "integration/hardening/STRUCTURAL_HARDENING_V533.md").is_file(),
            "v5.3.3 structural hardening documentation is required")

