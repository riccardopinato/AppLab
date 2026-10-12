#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


def run_check(namespace: dict[str, Any]) -> None:
    root = namespace["ROOT"]
    require = namespace["require"]

    calibration = (root / "scripts/delta_calibration.py").read_text(encoding="utf-8")
    registry = (root / "scripts/evidence_contract_registry.py").read_text(encoding="utf-8")
    planner = (root / "scripts/smart_test_plan.py").read_text(encoding="utf-8")
    control = (root / "scripts/control_center_snapshot.py").read_text(encoding="utf-8")
    frontend = (root / "frontend/src/ControlCenter.tsx").read_text(encoding="utf-8")
    fingerprint = (root / "scripts/contract_fingerprint.py").read_text(encoding="utf-8")
    domains = (root / "scripts/domain_fingerprint.py").read_text(encoding="utf-8")
    maintainability = (root / "scripts/maintainability_budget.py").read_text(encoding="utf-8")
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    watcher = (root / ".github/workflows/repo-watcher.yml").read_text(encoding="utf-8")
    certification = (root / ".github/workflows/production-certification.yml").read_text(
        encoding="utf-8"
    )

    for path in (
        "scripts/delta_calibration.py",
        "scripts/audit_contract_delta.py",
        "tests/contracts/delta_calibration_test.py",
        "integration/performance/MULTI_PROJECT_DELTA_CALIBRATION_V535.md",
    ):
        require((root / path).is_file(), f"v5.3.5 delta-calibration file missing: {path}")

    for needle in (
        'ENGINE_VERSION = "5.3.5"',
        'RECORD_TYPE = "MULTI_PROJECT_DELTA_CALIBRATION"',
        'AUTHORITY = "APPLAB_DELTA_CALIBRATION_ADVISORY"',
        '"coverage_reduction_enabled": False',
        '"smart_test_plan_remains_single_authority": True',
        '"ready_for_experiment_is_not_permission_to_reduce_coverage": True',
        '"READY_FOR_EXPERIMENT"',
        '"UNSAFE"',
        '"COLLECTING"',
    ):
        require(needle in calibration, f"v5.3.5 calibration guardrail missing: {needle}")

    require(
        '"delta-calibration.json"' in registry
        and '"scripts/delta_calibration.py"' in registry
        and '"5.3.5"' in registry
        and '"MULTI_PROJECT_DELTA_CALIBRATION"' in registry
        and '"APPLAB_DELTA_CALIBRATION_ADVISORY"' in registry,
        "delta calibration must have an exact registered evidence contract",
    )
    require(
        "import delta_calibration" not in planner
        and "from delta_calibration" not in planner
        and "coverage_reduction_enabled" not in planner,
        "calibration must not become a coverage-reducing Smart Test Plan input in v5.3.5",
    )
    require(
        "import delta_calibration" in control
        and '"delta_calibration": delta_calibration.build_report(history)' in control,
        "Control Center must expose deterministic multi-project calibration",
    )
    require(
        "Delta readiness" in frontend
        and "Coverage reduction" in frontend
        and "DISABLED" in frontend,
        "Control Center UI must surface readiness without implying coverage reduction",
    )
    require(
        '"scripts/delta_calibration.py"' in fingerprint
        and '"scripts/delta_calibration.py"' in domains,
        "delta calibration semantics must invalidate the core contract fingerprint",
    )
    require(
        '"scripts/delta_calibration.py": 420' in maintainability
        and '"scripts/audit_contract_delta.py": 150' in maintainability,
        "v5.3.5 calibration modules must have maintainability ceilings",
    )
    require(
        "scripts/delta_calibration.py" in ci
        and "tests/contracts/delta_calibration_test.py" in ci
        and "python scripts/delta_calibration.py --self-test" in ci
        and "python tests/contracts/delta_calibration_test.py" in ci,
        "CI must execute implementation-local and independent calibration contracts",
    )

    for workflow in (watcher, certification):
        require(
            "delta_calibration.py" in workflow
            and "delta-calibration.json" in workflow
            and "delta-calibration.md" in workflow,
            "central history workflows must publish durable delta calibration evidence",
        )
    require(
        '"scripts/delta_calibration.py"' in watcher,
        "Repo Watcher must invalidate when calibration semantics change",
    )
