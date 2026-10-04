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
    ),
    ".github/workflows/universal-project-runner.yml": (
        "source_ref:",
        "source_ref: ${{ inputs.source_ref }}",
        "baseline_sha:",
    ),
    ".github/workflows/repo-watcher.yml": (
        "source_ref: ${{ matrix.ref }}",
        "baseline_sha: ${{ matrix.previous_verified_sha }}",
        "scripts/domain_fingerprint.py",
        "scripts/pipeline_metrics.py",
    ),
    ".github/workflows/trusted-apk-verifier.yml": (
        "Restore clean AVD snapshot",
        "Create pristine AVD snapshot on cache miss",
        "Save pristine AVD snapshot before target execution",
        "force-avd-creation: false",
        "Cache pinned Maestro",
        "runtime-timing.json",
        "pipeline_metrics.py",
        "shadow_calibration.py",
        "AppLab v4.2.0 Trusted APK Verification",
        "BASELINE_FALLBACK",
        "effective FULL fallback",
        "Evaluate verification cache eligibility",
        "github_run_started_at.py",
    ),
    ".github/workflows/production-certification.yml": (
        "analysis_mode: certification",
        "source_ref: ${{ inputs.ref }}",
        "production-certification-v1.0.0",
    ),
}

FORBIDDEN: dict[str, tuple[str, ...]] = {
    ".github/workflows/external-project-runner.yml": (
        "Cache failed resolved commit",
    ),
    ".github/workflows/external-native-android-runner.yml": (
        "Cache failed resolved commit",
    ),
    ".github/workflows/trusted-apk-verifier.yml": (
        "AppLab v0.8.0 Trusted APK Verification",
        "needs.prepare_avd",
        "if: always() && inputs.cache_verification\n        uses: actions/cache/save",
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
