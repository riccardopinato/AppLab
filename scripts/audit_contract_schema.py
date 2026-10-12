#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


def run_check(namespace: dict[str, Any]) -> None:
    root = namespace["ROOT"]
    require = namespace["require"]

    registry = (root / "scripts/evidence_contract_registry.py").read_text(encoding="utf-8")
    evidence_graph = (root / "scripts/evidence_graph.py").read_text(encoding="utf-8")
    assurance = (root / "scripts/release_assurance.py").read_text(encoding="utf-8")
    manifest = (root / "scripts/trusted_evidence_manifest.py").read_text(encoding="utf-8")
    fingerprint = (root / "scripts/contract_fingerprint.py").read_text(encoding="utf-8")
    domains = (root / "scripts/domain_fingerprint.py").read_text(encoding="utf-8")
    maintainability = (root / "scripts/maintainability_budget.py").read_text(encoding="utf-8")
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    watcher = (root / ".github/workflows/repo-watcher.yml").read_text(encoding="utf-8")
    review = (root / ".github/workflows/autonomous-app-review-v31.yml").read_text(
        encoding="utf-8"
    )

    for path in (
        "scripts/evidence_contract_registry.py",
        "scripts/audit_contract_schema.py",
        "tests/contracts/evidence_schema_registry_test.py",
        "integration/hardening/EVIDENCE_SCHEMA_REGISTRY_V534.md",
    ):
        require((root / path).is_file(), f"v5.3.4 schema-contract file missing: {path}")

    for needle in (
        'REGISTRY_VERSION = "1.0"',
        'COMPATIBILITY_MODE = "EXACT_DECLARED_VERSION"',
        '"analysis-plan.json"',
        '"build-contract.json"',
        '"trusted-evidence-manifest.json"',
        '"evidence-graph.json"',
        '"planner-feedback.json"',
        '"physical-evidence.json"',
        '"release-reality.json"',
        '"certification.json"',
        '"cross-app-verification.json"',
        '"release-assurance.json"',
        '"virtual-product-review-council.json"',
        '"compatibility_registry_is_not_evidence_authority": True',
        '"unknown_artifacts_are_not_implicitly_trusted": True',
        '"schema_or_declared_version_mismatch_fails_closed": True',
        '"registry_does_not_change_fast_full_certification_authority": True',
        "def require_compatible(",
        "def validate_directory(",
        "AppLab Evidence Schema Registry v1.0 self-test PASS",
    ):
        require(needle in registry, f"v5.3.4 registry invariant missing: {needle}")

    require(
        "evidence_contract_registry.validate_if_registered" in evidence_graph
        and "INCOMPATIBLE" in evidence_graph,
        "Evidence Graph must reject incompatible registered producer evidence",
    )
    require(
        "evidence_contract_registry.require_compatible" in assurance
        and "def read_registered_json(" in assurance,
        "Release Assurance must validate registered evidence before consumption",
    )
    require(
        "evidence_contract_registry.require_compatible" in manifest,
        "trusted manifest validation must enforce the registry contract",
    )

    require(
        '"scripts/evidence_contract_registry.py"' in fingerprint,
        "registry changes must invalidate central contract fingerprints",
    )
    require(
        '"scripts/evidence_contract_registry.py"' in domains,
        "registry must remain in the core domain fingerprint",
    )
    require(
        '"scripts/evidence_contract_registry.py": 360' in maintainability
        and '"scripts/audit_contract_schema.py": 180' in maintainability,
        "v5.3.4 schema modules must have maintainability ceilings",
    )
    require(
        "tests/contracts/evidence_schema_registry_test.py" in ci
        and "python scripts/evidence_contract_registry.py self-test" in ci
        and "python tests/contracts/evidence_schema_registry_test.py" in ci,
        "CI must run independent schema-registry contracts",
    )
    require(
        '"scripts/evidence_contract_registry.py"' in watcher,
        "Repo Watcher must invalidate on registry contract changes",
    )
    require(
        "Validate registered evidence contracts" in review
        and "evidence_contract_registry.py validate-dir" in review
        and "evidence_contract_registry" in review,
        "autonomous review must validate registered evidence before Studio projection",
    )
