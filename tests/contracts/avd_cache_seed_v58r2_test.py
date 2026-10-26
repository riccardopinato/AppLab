#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/seed-android-avd-cache.yml"
TRUSTED = ROOT / ".github/workflows/trusted-apk-verifier.yml"


def main() -> int:
    seed = WORKFLOW.read_text(encoding="utf-8")
    trusted = TRUSTED.read_text(encoding="utf-8")
    key = "applab-clean-avd-schema1-google_apis-api${{ inputs.api_level }}-x86_64-${{ inputs.emulator_profile }}"

    assert "workflow_call:" in seed
    assert "Require caller default branch" in seed
    assert "CURRENT_REF: ${{ github.ref_name }}" in seed
    assert "DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}" in seed
    assert "repository: riccardopinato/AppLab" in seed
    assert "ref: ${{ job.workflow_sha }}" in seed
    assert key in seed
    assert key in trusted
    assert "Create pristine AVD on cache miss" in seed
    assert "actions/cache/save@" in seed
    assert "caller default branch" in seed
    print("AppLab v5.8R2 AVD cache seed contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
