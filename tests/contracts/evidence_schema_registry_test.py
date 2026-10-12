#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import evidence_contract_registry as registry  # noqa: E402


REQUIRED = {
    "analysis-plan.json",
    "build-contract.json",
    "trusted-evidence-manifest.json",
    "evidence-graph.json",
    "planner-feedback.json",
    "physical-evidence.json",
    "release-reality.json",
    "certification.json",
    "cross-app-verification.json",
    "release-assurance.json",
    "simulated-human-qa.json",
    "design-system-advisor.json",
    "competitive-product-intelligence.json",
    "virtual-product-review-council.json",
}


def valid_payload(contract: registry.EvidenceContract) -> dict[str, object]:
    payload: dict[str, object] = {"schema_version": contract.schema_version}
    if contract.version_field:
        current: dict[str, object] = payload
        tokens = contract.version_field.split(".")
        for token in tokens[:-1]:
            child: dict[str, object] = {}
            current[token] = child
            current = child
        current[tokens[-1]] = contract.version
    for dotted, expected in contract.fixed_fields:
        current = payload
        tokens = dotted.split(".")
        for token in tokens[:-1]:
            child = current.get(token)
            if not isinstance(child, dict):
                child = {}
                current[token] = child
            current = child
        current[tokens[-1]] = expected
    return payload


def assert_producer_contracts_are_declared() -> None:
    source_checks = {
        "analysis-plan.json": ('"schema_version": 2', '"planner_version": "1.1.0"'),
        "build-contract.json": ('"schema_version": 1', '"applab_version": "5.3.4"'),
        "trusted-evidence-manifest.json": (
            "SCHEMA_VERSION = 1",
            'MANIFEST_VERSION = "3.0.1"',
        ),
        "evidence-graph.json": (
            "SCHEMA_VERSION = 2",
            'GRAPH_VERSION = "2.0"',
        ),
        "planner-feedback.json": (
            "SCHEMA_VERSION = 1",
            'ENGINE_VERSION = "5.3.3"',
        ),
        "physical-evidence.json": (
            "SCHEMA_VERSION = 1",
            'HUB_VERSION = "4.5.0"',
        ),
        "release-reality.json": (
            "SCHEMA_VERSION = 1",
            'ENGINE_VERSION = "4.5.0"',
        ),
        "certification.json": ('APPLAB_VERSION = "1.0.0"', '"schema_version": 1'),
        "cross-app-verification.json": (
            'APPLAB_VERSION="4.8.0"',
            "SCHEMA_VERSION=1",
        ),
        "release-assurance.json": (
            'APPLAB_VERSION = "4.9.0"',
            "SCHEMA_VERSION = 1",
        ),
        "simulated-human-qa.json": (
            'LAB_VERSION = "5.0.0"',
            "SCHEMA_VERSION = 1",
        ),
        "design-system-advisor.json": (
            'LAB_VERSION = "5.1.0"',
            "SCHEMA_VERSION = 1",
        ),
        "competitive-product-intelligence.json": (
            'LAB_VERSION = "5.2.0"',
            "SCHEMA_VERSION = 1",
        ),
        "virtual-product-review-council.json": (
            'LAB_VERSION = "5.3.0"',
            "SCHEMA_VERSION = 1",
        ),
    }
    for artifact, needles in source_checks.items():
        contract = registry.contract_for(artifact)
        source = (ROOT / contract.producer).read_text(encoding="utf-8")
        for needle in needles:
            assert needle in source, f"{artifact} producer drift: missing {needle}"


def main() -> int:
    assert REQUIRED.issubset(registry.REGISTRY)
    assert registry.REGISTRY_VERSION == "1.0"
    assert registry.COMPATIBILITY_MODE == "EXACT_DECLARED_VERSION"

    for artifact in sorted(REQUIRED):
        contract = registry.contract_for(artifact)
        payload = valid_payload(contract)
        assert registry.require_compatible(artifact, payload) == contract

        broken = json.loads(json.dumps(payload))
        broken["schema_version"] = 999
        state, errors = registry.validate_if_registered(artifact, broken)
        assert state == "INCOMPATIBLE"
        assert any("SCHEMA_VERSION_MISMATCH" in error for error in errors)

        if contract.version_field:
            broken = json.loads(json.dumps(payload))
            current = broken
            tokens = contract.version_field.split(".")
            for token in tokens[:-1]:
                current = current[token]
            current[tokens[-1]] = "999.999"
            state, errors = registry.validate_if_registered(artifact, broken)
            assert state == "INCOMPATIBLE"
            assert any("VERSION_MISMATCH" in error for error in errors)

    state, errors = registry.validate_if_registered("unregistered.json", {})
    assert state == "NOT_REGISTERED"
    assert errors == []

    try:
        registry.require_compatible("unregistered.json", {})
    except registry.EvidenceContractError:
        pass
    else:
        raise AssertionError("unregistered evidence cannot be promoted to compatible")

    assert_producer_contracts_are_declared()

    with tempfile.TemporaryDirectory(prefix="applab-schema-contract-test-") as raw:
        root = Path(raw)
        for artifact in ("analysis-plan.json", "evidence-graph.json", "release-reality.json"):
            (root / artifact).write_text(
                json.dumps(valid_payload(registry.contract_for(artifact))),
                encoding="utf-8",
            )
        result = registry.validate_directory(root)
        assert result["checked"] == 3
        assert result["incompatible"] == 0
        assert len(result["registry_digest_sha256"]) == 64

        bad = valid_payload(registry.contract_for("evidence-graph.json"))
        bad["schema_version"] = 1
        (root / "evidence-graph.json").write_text(json.dumps(bad), encoding="utf-8")
        result = registry.validate_directory(root)
        assert result["incompatible"] == 1

    print("AppLab evidence schema registry contract test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
