#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import warm_worker_v54f as warm

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "integration" / "orchestration" / "v55-pilot.json"

REAL_APP_REPOSITORIES = ("riccardopinato/CamperBoss", "riccardopinato/TrailPath")
TRUSTED_RUNTIME_PROFILE = "android-default"


class WarmRealAppPilotError(ValueError):
    pass


def load_targets() -> dict[str, dict[str, Any]]:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    targets = {item["repository"]: item for item in payload["pilot_targets"]}
    for repository in REAL_APP_REPOSITORIES:
        target = targets.get(repository)
        if target is None or target.get("engine") not in {"flutter", "native_android", "auto"}:
            raise WarmRealAppPilotError(f"real-app target has unsupported Universal Project Runner engine: {repository}")
    return targets


def evaluate_pair(
    repository: str,
    control: dict[str, Any],
    warm_result: dict[str, Any],
    *,
    isolation_clean: bool,
) -> dict[str, Any]:
    if repository not in REAL_APP_REPOSITORIES:
        raise WarmRealAppPilotError("repository is outside the v5.5C real-app pilot")
    if control.get("repository") != repository or warm_result.get("repository") != repository:
        raise WarmRealAppPilotError("equivalence evidence repository does not match requested pilot target")
    report = warm.compare_equivalence(
        control,
        warm_result,
        isolation_clean=isolation_clean,
        minimum_improvement_percent=0.0,
    )
    return {
        "repository": repository,
        "runtime_profile": TRUSTED_RUNTIME_PROFILE,
        "target_build_executor": "GITHUB_ACTIONS_UNTRUSTED_BUILD_JOB",
        "trusted_runtime_executor": warm.WORKER_CLASS,
        "fallback_executor": warm.FALLBACK_EXECUTOR,
        "target_build_scripts_on_warm_worker": False,
        "smart_test_plan_authority": "UNCHANGED",
        "trusted_verifier_authority": "UNCHANGED",
        "release_assurance_authority": "UNCHANGED",
        "production_certification_authority": "UNCHANGED",
        "coverage_reduction_enabled": False,
        "equivalence": report,
    }


def self_test() -> dict[str, Any]:
    load_targets()
    rows = []
    for index, repository in enumerate(REAL_APP_REPOSITORIES, start=1):
        identity = {
            "repository": repository,
            "resolved_sha": str(index) * 40,
            "applab_sha": "a" * 40,
            "apk_sha256": f"pilot-apk-digest-{index}",
            "package_id": f"pilot.realapp.{index}",
            "analysis_mode": "full",
            "result": "PASS",
            "labs": {"launch": "PASS", "visual": "PASS", "interaction": "PASS"},
        }
        control = dict(identity, startup_seconds=90.0)
        warm_result = dict(identity, startup_seconds=60.0)
        row = evaluate_pair(repository, control, warm_result, isolation_clean=True)
        assert row["equivalence"]["equivalent"] is True
        assert row["equivalence"]["promotion_candidate"] is True
        assert row["target_build_scripts_on_warm_worker"] is False
        assert row["fallback_executor"] == "GITHUB_ACTIONS"
        rows.append(row)

        mismatch = evaluate_pair(
            repository,
            control,
            dict(warm_result, apk_sha256="pilot-apk-digest-mismatch"),
            isolation_clean=True,
        )
        assert mismatch["equivalence"]["equivalent"] is False
        assert mismatch["equivalence"]["promotion_candidate"] is False

    return {
        "schema_version": 1,
        "record_type": "APPLAB_V55C_WARM_REAL_APP_PILOT",
        "status": "PASS",
        "repositories": list(REAL_APP_REPOSITORIES),
        "proof_count": len(rows),
        "proofs": rows,
        "authority": "NONE_PILOT_EVIDENCE",
        "github_actions_fallback": True,
        "coverage_reduction_enabled": False,
        "target_build_scripts_on_warm_worker": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLab v5.5C warm-worker real-app pilot proof")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test:
        parser.error("--self-test is required")
    print(json.dumps(self_test(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
