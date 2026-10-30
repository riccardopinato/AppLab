#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED: dict[str, tuple[str, ...]] = {
    ".github/workflows/external-project-runner.yml": (
        "source_ref:",
        "Plan adaptive verification",
        "adaptive_checks.py",
        "incremental_result.py",
        "run_runtime",
        "analysis-plan-input",
        "--history-key",
        "--source-ref",
        "Cache analysis-only PASS commit",
        "Restore target source before trusted packaging",
        "steps.trusted_target.outputs.apk_file",
        "--history-file",
        "Keep failed SHA retryable",
        "github_run_started_at.py",
        "Restore prior graph planner feedback",
        "restore_planner_feedback.sh",
        "--planner-feedback",
        "${{ inputs.baseline_sha }}",
        "${{ inputs.source_ref != '' && inputs.source_ref || inputs.ref }}",
        '--trusted-root "$GITHUB_WORKSPACE/.applab"',
        "APPLAB_PREPARE_COMMAND: ${{ inputs.prepare_command }}",
        "APPLAB_POST_PUB_GET_COMMAND: ${{ inputs.post_pub_get_command }}",
        '--prepare-command "$APPLAB_PREPARE_COMMAND"',
        '--post-command "$APPLAB_POST_PUB_GET_COMMAND"',
        '--build-input "prepare:$APPLAB_PREPARE_COMMAND"',
        '--build-input "post-pub-get:$APPLAB_POST_PUB_GET_COMMAND"',
    ),
    ".github/workflows/external-native-android-runner.yml": (
        "source_ref:",
        "Plan adaptive verification",
        "adaptive_checks.py",
        "incremental_result.py",
        "run_runtime",
        "analysis-plan-input",
        "--history-key",
        "--source-ref",
        "Cache analysis-only PASS commit",
        "Restore target source before trusted packaging",
        "steps.trusted_target.outputs.apk_file",
        "--history-file",
        "Keep failed SHA retryable",
        "github_run_started_at.py",
        "Restore prior graph planner feedback",
        "restore_planner_feedback.sh",
        "--planner-feedback",
        "${{ inputs.baseline_sha }}",
        "${{ inputs.source_ref != '' && inputs.source_ref || inputs.ref }}",
    ),
    ".github/workflows/universal-project-runner.yml": (
        "source_ref:",
        "baseline_sha:",
        "scripts/project_adapter.py",
        "project-profile.json",
        "resolved_sha:",
        "profile_fingerprint:",
        "physical_evidence_run_id:",
        "ref: ${{ needs.discover.outputs.resolved_sha }}",
    ),
    ".github/workflows/project-adapter-integration.yml": (
        "riccardopinato/CamperBoss",
        "6c866bf8884b78703401db8ce08dbcf97d3f893c",
        "riccardopinato/Battery_Guard",
        "7d3e0b8257628dea65cedcf174357f9bc06d21bc",
        "AppLab v4.4 real-project adapter integration PASS",
    ),
    ".github/workflows/repo-watcher.yml": (
        "source_ref: ${{ matrix.ref }}",
        "baseline_sha: ${{ matrix.previous_verified_sha }}",
        "scripts/domain_fingerprint.py",
        "scripts/planner_feedback.py",
        "scripts/restore_planner_feedback.sh",
        "scripts/pipeline_metrics.py",
    ),
    ".github/workflows/trusted-apk-verifier.yml": (
        "Setup Android SDK tools for resilient image install",
        "android-actions/setup-android@be39fa834029ff78f1a44aa3bb0819b8fc2bd8fd",
        "Restore clean AVD snapshot",
        "Ensure Android system image with retry",
        "scripts/ensure_android_system_image.sh",
        "Create pristine AVD snapshot on cold route",
        "Save pristine AVD snapshot before target execution",
        "force-avd-creation: false",
        "Cache pinned Maestro",
        "runtime-timing.json",
        "pipeline_metrics.py",
        "shadow_calibration.py",
        "Build Release Reality record",
        "scripts/release_reality.py",
        "release-reality.md",
        "physical_evidence_run_id",
        "Verify physical evidence hub run provenance",
        "Download trusted physical evidence attestation",
        "Bind physical evidence to exact APK",
        "--expected-hub-run-attempt",
        "if: always() && steps.verify.outcome == 'success'",
        "physical-evidence.md",
        "AppLab v5.3.5 Trusted APK Verification",
        "BASELINE_FALLBACK",
        "effective FULL fallback",
        "Evaluate verification cache eligibility",
        "Evaluate v5.7E exact-artifact reuse promotion",
        "Enforce v5.7E promotion gate on reused build",
        "steps.reuse_promotion.outputs.promotion_ready == 'true'",
        "github_run_started_at.py",
    ),
    ".github/workflows/autonomous-app-review-v31.yml": (
        "Build Evidence Graph",
        "Build Simulated Human QA",
        "scripts/simulated_human_qa.py",
        "simulated-human-qa.md",
        "Build Design System & UI Library Advisor",
        "scripts/design_system_advisor.py",
        "design-system-advisor.md",
        "Build Competitive Product Intelligence",
        "scripts/competitive_product_intelligence.py",
        "competitive-product-intelligence.md",
        "market_evidence_path:",
        "Build Autonomous Release Assurance",
        "scripts/release_assurance.py",
        "release-assurance.md",
        "Build Virtual Product Review Council",
        "scripts/virtual_product_review_council.py",
        "virtual-product-review-council.md",
        "Build graph-aware planner feedback",
        "scripts/planner_feedback.py",
        "planner-feedback.md",
        ".applab-longitudinal/planner-feedback/",
        "Pin resolved SHA and delta baseline",
        "fetch-depth: 2",
        "AppLab True Autonomous App Review v5.3.5",
        "cross_app_run_id",
        "trusted_cross_app_evidence.py verify-run",
        "Download trusted cross-app verification evidence",
        "trusted_cross_app_evidence.py validate",
        "cross-app-verification.bound.json",
    ),
    ".github/workflows/production-certification.yml": (
        "analysis_mode: certification",
        "source_ref: ${{ inputs.ref }}",
        "production-certification-v1.0.0",
        "Upload certified release bundle",
        "Upload final certification evidence",
        "Upload certification history",
        "retention-days: 90",
    ),
    ".github/workflows/live-emulator-self-test.yml": (
        "Setup Node for browser tooling",
        "Validate frontend dependency graph before runtime work",
        "npm ci --ignore-scripts --no-audit --no-fund --dry-run",
        "frontend-dependency-preflight.txt",
        "retention-days: 7",
    ),
    ".github/workflows/frontend-lock.yml": (
        "pull_request:",
        "applab-frontend-lock-${{ github.ref }}",
        "Validate install graph",
        "Require clean lockfile on pull request",
        "github.event_name != 'pull_request'",
    ),
    ".github/workflows/web-preview.yml": (
        "Detect Pages availability",
        "pages_enabled: ${{ steps.pages_status.outputs.enabled }}",
        "Upload non-deployed preview evidence",
        "if: steps.pages_status.outputs.enabled == 'true'",
        "if: needs.build.outputs.pages_enabled == 'true'",
    ),
    ".github/workflows/physical-evidence-hub.yml": (
        "Require trusted main",
        "refs/heads/main",
        "scripts/physical_evidence.py create",
        "applab-physical-evidence-${{ github.run_id }}-${{ github.run_attempt }}",
        "retention-days: 90",
    ),
}

FORBIDDEN: dict[str, tuple[str, ...]] = {
    ".github/workflows/external-project-runner.yml": (
        "Cache failed resolved commit",
        '--prepare-command "${{ inputs.prepare_command }}"',
        '--post-command "${{ inputs.post_pub_get_command }}"',
        '--build-input "prepare:${{ inputs.prepare_command }}"',
        '--build-input "post-pub-get:${{ inputs.post_pub_get_command }}"',
    ),
    ".github/workflows/external-native-android-runner.yml": (
        "Cache failed resolved commit",
    ),
    ".github/workflows/trusted-apk-verifier.yml": (
        "AppLab v0.8.0 Trusted APK Verification",
        "needs.prepare_avd",
        "if: always() && inputs.cache_verification\n        uses: actions/cache/save",
        'json.dumps(payload, indent=2, sort_keys=True) + "\\\\n"',
    ),
}

def workflow_input_count(text: str, trigger: str) -> int:
    lines = text.splitlines()
    try:
        trigger_index = lines.index(f"  {trigger}:")
    except ValueError:
        return 0
    inputs_index = next(
        (index for index in range(trigger_index + 1, len(lines)) if lines[index] == "    inputs:"),
        -1,
    )
    if inputs_index < 0:
        return 0
    count = 0
    for line in lines[inputs_index + 1:]:
        if line.startswith("  ") and not line.startswith("    "):
            break
        if line.startswith("    ") and not line.startswith("      "):
            break
        if line.startswith("      ") and not line.startswith("        ") and line.endswith(":"):
            count += 1
    return count


def validate() -> None:
    for relative, needles in REQUIRED.items():
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            assert needle in text, f"{relative}: missing {needle!r}"
    for relative, needles in FORBIDDEN.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for needle in needles:
            assert needle not in text, f"{relative}: forbidden stale contract {needle!r}"

    flutter_runner = (ROOT / ".github/workflows/external-project-runner.yml").read_text(encoding="utf-8")
    native_runner = (ROOT / ".github/workflows/external-native-android-runner.yml").read_text(encoding="utf-8")
    gradle_action = "gradle/actions/setup-gradle@3f5f9adaf7d9fecd50b5935e54106014257a94e6"
    gradle_setup = flutter_runner.index("- name: Setup Gradle build cache for Flutter")
    gradle_end = flutter_runner.index("- name: Adaptive Flutter checks and build", gradle_setup)
    gradle_block = flutter_runner[gradle_setup:gradle_end]
    assert f"uses: {gradle_action}" in gradle_block and gradle_action in native_runner, (
        "Flutter and native external build runners must both cache Gradle safely"
    )
    assert flutter_runner.index("- name: Post dependency preparation") < gradle_setup < gradle_end
    assert "if: steps.impact.outputs.run_build == 'true' && steps.build_reuse.outputs.hit != 'true'" in gradle_block, (
        "Gradle setup must not run for analysis-only or exact-APK cache reuse"
    )

    trusted = (ROOT / ".github/workflows/trusted-apk-verifier.yml").read_text(encoding="utf-8")
    promotion_index = trusted.index("Evaluate v5.7E exact-artifact reuse promotion")
    assert promotion_index < trusted.index("Prepare PASS-only visual baseline"), (
        "reuse promotion must fail before PASS-only baselines can be promoted"
    )
    assert promotion_index < trusted.index("Finalize trusted result contract"), (
        "reuse promotion must affect job.status before aggregate PASS finalization"
    )


    # Cross-app automation must never spawn APK builders implicitly.
    watcher = (ROOT / ".github/workflows/repo-watcher.yml").read_text(encoding="utf-8")
    auto = (ROOT / ".github/workflows/source-gate-watcher.yml").read_text(encoding="utf-8")
    watcher_triggers = watcher.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    for trigger in ("  schedule:", "  push:", "  repository_dispatch:"):
        assert trigger not in watcher_triggers, "Android watcher must be manual-only"
    assert "run_android:" in watcher_triggers and "default: false" in watcher_triggers
    assert "if: ${{ inputs.run_android == true }}" in watcher
    assert "always() && inputs.run_android == true" in watcher
    assert "  schedule:" in auto and "  repository_dispatch:" in auto
    assert "scripts/source_gate_watch.py --self-test" in auto
    for forbidden in ("external-project-runner.yml", "external-native-android-runner.yml",
                      "trusted-apk-verifier.yml", "flutter build apk", "assembleDebug"):
        assert forbidden not in auto, f"Source watcher starts a runtime path: {forbidden}"
    assert "SOURCE_STRUCTURE_ONLY" in (ROOT / "scripts/source_gate_watch.py").read_text(encoding="utf-8")
    import subprocess
    import sys
    subprocess.run([sys.executable, str(ROOT / "scripts/source_gate_watch.py"), "--self-test"],
                   check=True, timeout=10)

    for relative in (
        ".github/workflows/external-project-runner.yml",
        ".github/workflows/external-native-android-runner.yml",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for trigger in ("workflow_dispatch", "workflow_call"):
            count = workflow_input_count(text, trigger)
            assert count <= 25, (
                f"{relative}: {trigger} exposes {count} inputs; AppLab keeps reusable/manual "
                "workflow contracts within GitHub's 25-input envelope"
            )

def main() -> int:
    validate()
    print("AppLab adaptive workflow contract self-test PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
