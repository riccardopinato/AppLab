#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REGISTRY_VERSION = "1.0"
COMPATIBILITY_MODE = "EXACT_DECLARED_VERSION"


class EvidenceContractError(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceContract:
    artifact: str
    producer: str
    schema_version: int
    version_field: str
    version: str
    consumers: tuple[str, ...]
    fixed_fields: tuple[tuple[str, str], ...] = ()
    evidence_class: str = "ADVISORY"


_CONTRACTS = (
    EvidenceContract(
        "analysis-plan.json",
        "scripts/smart_test_plan.py",
        2,
        "planner_version",
        "1.1.0",
        (
            "scripts/package_build_contract.py",
            "scripts/evidence_graph.py",
            "scripts/release_assurance.py",
        ),
        evidence_class="PLANNING",
    ),
    EvidenceContract(
        "build-contract.json",
        "scripts/package_build_contract.py",
        1,
        "applab_version",
        "5.3.4",
        (
            "scripts/validate_build_contract.py",
            "scripts/trusted_evidence_manifest.py",
            "scripts/release_reality.py",
            "scripts/evidence_graph.py",
        ),
        evidence_class="TRUST_BOUNDARY",
    ),
    EvidenceContract(
        "trusted-evidence-manifest.json",
        "scripts/trusted_evidence_manifest.py",
        1,
        "manifest_version",
        "3.0.1",
        ("scripts/evidence_graph.py",),
        (("producer", "trusted-apk-verifier"),),
        "TRUSTED_RUNTIME",
    ),
    EvidenceContract(
        "evidence-graph.json",
        "scripts/evidence_graph.py",
        2,
        "graph_version",
        "2.0",
        (
            "scripts/release_assurance.py",
            "scripts/simulated_human_qa.py",
            "scripts/design_system_advisor.py",
            "scripts/competitive_product_intelligence.py",
            "scripts/virtual_product_review_council.py",
        ),
        evidence_class="EVIDENCE_MODEL",
    ),
    EvidenceContract(
        "planner-feedback.json",
        "scripts/planner_feedback.py",
        1,
        "engine_version",
        "5.3.3",
        ("scripts/smart_test_plan.py", "scripts/package_build_contract.py"),
        (("record_type", "EVIDENCE_GRAPH_PLANNER_FEEDBACK"),),
        "PLANNING_ADVISORY",
    ),
    EvidenceContract(
        "physical-evidence.json",
        "scripts/physical_evidence.py",
        1,
        "hub_version",
        "4.5.0",
        ("scripts/release_reality.py",),
        (
            ("record_type", "PHYSICAL_DEVICE_EVIDENCE"),
            ("attestation.authority", "APPLAB_PHYSICAL_EVIDENCE_HUB"),
        ),
        "PHYSICAL",
    ),
    EvidenceContract(
        "release-reality.json",
        "scripts/release_reality.py",
        1,
        "engine_version",
        "4.5.0",
        (
            "scripts/release_assurance.py",
            "scripts/certification_studio.py",
        ),
        evidence_class="RELEASE_REALITY",
    ),
    EvidenceContract(
        "certification.json",
        "scripts/finalize_certification_matrix.py",
        1,
        "applab_version",
        "1.0.0",
        ("scripts/release_assurance.py",),
        evidence_class="CERTIFICATION",
    ),
    EvidenceContract(
        "cross-app-verification.json",
        "scripts/cross_app_verification.py",
        1,
        "applab_version",
        "4.8.0",
        ("scripts/release_assurance.py",),
        (
            ("record_type", "CROSS_APP_VERIFICATION"),
            ("authority", "APPLAB_CROSS_APP_VERIFICATION"),
        ),
        "CROSS_APP",
    ),
    EvidenceContract(
        "release-assurance.json",
        "scripts/release_assurance.py",
        1,
        "applab_version",
        "4.9.0",
        (
            "scripts/studio_release_assurance.py",
            "scripts/virtual_product_review_council.py",
        ),
        (
            ("record_type", "AUTONOMOUS_RELEASE_ASSURANCE"),
            ("authority", "APPLAB_RELEASE_ASSURANCE"),
        ),
        "RELEASE_ASSURANCE",
    ),
    EvidenceContract(
        "simulated-human-qa.json",
        "scripts/simulated_human_qa.py",
        1,
        "lab_version",
        "5.0.0",
        (
            "scripts/studio_simulated_human.py",
            "scripts/virtual_product_review_council.py",
        ),
        (
            ("record_type", "SIMULATED_HUMAN_QA"),
            ("authority", "APPLAB_SIMULATED_HUMAN_QA_ADVISORY"),
        ),
        "ADVISORY",
    ),
    EvidenceContract(
        "design-system-advisor.json",
        "scripts/design_system_advisor.py",
        1,
        "lab_version",
        "5.1.0",
        (
            "scripts/studio_design_advisor.py",
            "scripts/virtual_product_review_council.py",
        ),
        (
            ("record_type", "DESIGN_SYSTEM_UI_LIBRARY_ADVISOR"),
            ("authority", "APPLAB_DESIGN_SYSTEM_ADVISOR_ADVISORY"),
        ),
        "ADVISORY",
    ),
    EvidenceContract(
        "competitive-product-intelligence.json",
        "scripts/competitive_product_intelligence.py",
        1,
        "lab_version",
        "5.2.0",
        (
            "scripts/studio_competitive_product.py",
            "scripts/virtual_product_review_council.py",
        ),
        (
            ("record_type", "COMPETITIVE_PRODUCT_INTELLIGENCE"),
            ("authority", "APPLAB_COMPETITIVE_PRODUCT_INTELLIGENCE_ADVISORY"),
        ),
        "ADVISORY",
    ),
    EvidenceContract(
        "virtual-product-review-council.json",
        "scripts/virtual_product_review_council.py",
        1,
        "lab_version",
        "5.3.0",
        ("scripts/studio_review_council.py",),
        (
            ("record_type", "VIRTUAL_PRODUCT_REVIEW_COUNCIL"),
            ("authority", "APPLAB_VIRTUAL_PRODUCT_REVIEW_COUNCIL_ADVISORY"),
        ),
        "ADVISORY",
    ),
)

REGISTRY = {contract.artifact: contract for contract in _CONTRACTS}


def contract_for(artifact: str) -> EvidenceContract:
    name = Path(artifact).name
    contract = REGISTRY.get(name)
    if contract is None:
        raise EvidenceContractError(f"unregistered evidence artifact: {name}")
    return contract


def _lookup(payload: dict[str, Any], dotted: str) -> Any:
    current: Any = payload
    for token in dotted.split("."):
        if not isinstance(current, dict) or token not in current:
            return None
        current = current[token]
    return current


def _assign(payload: dict[str, Any], dotted: str, value: Any) -> None:
    current = payload
    tokens = dotted.split(".")
    for token in tokens[:-1]:
        child = current.get(token)
        if not isinstance(child, dict):
            child = {}
            current[token] = child
        current = child
    current[tokens[-1]] = value


def compatibility_errors(artifact: str, payload: Any) -> list[str]:
    contract = contract_for(artifact)
    if not isinstance(payload, dict):
        return ["PAYLOAD_NOT_OBJECT"]

    errors: list[str] = []
    if payload.get("schema_version") != contract.schema_version:
        errors.append(
            f"SCHEMA_VERSION_MISMATCH:{payload.get('schema_version')!r}!={contract.schema_version!r}"
        )

    if contract.version_field:
        observed = _lookup(payload, contract.version_field)
        if str(observed or "").strip() != contract.version:
            errors.append(
                f"VERSION_MISMATCH:{contract.version_field}:{observed!r}!={contract.version!r}"
            )

    for field, expected in contract.fixed_fields:
        observed = _lookup(payload, field)
        if str(observed or "").strip() != expected:
            errors.append(f"FIELD_MISMATCH:{field}:{observed!r}!={expected!r}")

    return errors


def require_compatible(artifact: str, payload: Any) -> EvidenceContract:
    errors = compatibility_errors(artifact, payload)
    if errors:
        raise EvidenceContractError(
            f"{Path(artifact).name} is incompatible with AppLab evidence registry "
            f"v{REGISTRY_VERSION}: " + "; ".join(errors)
        )
    return contract_for(artifact)


def validate_if_registered(artifact: str, payload: Any) -> tuple[str, list[str]]:
    name = Path(artifact).name
    if name not in REGISTRY:
        return "NOT_REGISTERED", []
    errors = compatibility_errors(name, payload)
    return ("COMPATIBLE" if not errors else "INCOMPATIBLE"), errors


def registry_snapshot() -> dict[str, Any]:
    contracts = []
    for contract in sorted(_CONTRACTS, key=lambda row: row.artifact):
        row = asdict(contract)
        row["consumers"] = list(contract.consumers)
        row["fixed_fields"] = [
            {"field": field, "value": value}
            for field, value in contract.fixed_fields
        ]
        contracts.append(row)
    return {
        "registry_version": REGISTRY_VERSION,
        "compatibility_mode": COMPATIBILITY_MODE,
        "contracts": contracts,
        "guardrails": {
            "compatibility_registry_is_not_evidence_authority": True,
            "unknown_artifacts_are_not_implicitly_trusted": True,
            "schema_or_declared_version_mismatch_fails_closed": True,
            "registry_does_not_change_fast_full_certification_authority": True,
            "registry_change_must_invalidate_core_contract_fingerprint": True,
        },
    }


def registry_digest() -> str:
    raw = json.dumps(
        registry_snapshot(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_directory(root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    incompatible = 0
    checked = 0
    for artifact in sorted(REGISTRY):
        path = root / artifact
        if not path.is_file():
            continue
        checked += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        state, errors = validate_if_registered(artifact, payload)
        if state == "INCOMPATIBLE":
            incompatible += 1
        records.append(
            {
                "artifact": artifact,
                "state": state,
                "errors": errors,
            }
        )

    present_json = {
        path.name
        for path in root.glob("*.json")
        if path.is_file()
    }
    unregistered = sorted(present_json - set(REGISTRY))
    return {
        "registry_version": REGISTRY_VERSION,
        "registry_digest_sha256": registry_digest(),
        "root": str(root),
        "checked": checked,
        "incompatible": incompatible,
        "unregistered_present": unregistered,
        "records": records,
    }


def self_test() -> None:
    assert REGISTRY_VERSION == "1.0"
    assert len(REGISTRY) == len(_CONTRACTS)
    assert len(REGISTRY) >= 10
    assert registry_digest() == registry_digest()

    for contract in _CONTRACTS:
        payload: dict[str, Any] = {"schema_version": contract.schema_version}
        if contract.version_field:
            _assign(payload, contract.version_field, contract.version)
        for field, expected in contract.fixed_fields:
            _assign(payload, field, expected)
        assert not compatibility_errors(contract.artifact, payload)
        require_compatible(contract.artifact, payload)

        wrong_schema = json.loads(json.dumps(payload))
        wrong_schema["schema_version"] = contract.schema_version + 100
        assert compatibility_errors(contract.artifact, wrong_schema)

        if contract.version_field:
            wrong_version = json.loads(json.dumps(payload))
            _assign(wrong_version, contract.version_field, "incompatible")
            assert compatibility_errors(contract.artifact, wrong_version)

    try:
        contract_for("unknown-evidence.json")
    except EvidenceContractError:
        pass
    else:
        raise AssertionError("unknown evidence must not be implicitly trusted")

    with tempfile.TemporaryDirectory(prefix="applab-schema-registry-") as raw:
        root = Path(raw)
        contract = REGISTRY["evidence-graph.json"]
        payload = {
            "schema_version": contract.schema_version,
            contract.version_field: contract.version,
        }
        (root / contract.artifact).write_text(json.dumps(payload), encoding="utf-8")
        result = validate_directory(root)
        assert result["checked"] == 1
        assert result["incompatible"] == 0

    print("AppLab Evidence Schema Registry v1.0 self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("self-test")
    sub.add_parser("snapshot")

    validate = sub.add_parser("validate")
    validate.add_argument("--artifact", required=True)
    validate.add_argument("--path", required=True)

    validate_dir = sub.add_parser("validate-dir")
    validate_dir.add_argument("--root", required=True)

    args = parser.parse_args()

    if args.command == "self-test":
        self_test()
        return 0
    if args.command == "snapshot":
        print(json.dumps(registry_snapshot(), indent=2, sort_keys=True))
        return 0
    if args.command == "validate":
        path = Path(args.path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvidenceContractError(f"unable to read JSON evidence: {path}") from exc
        require_compatible(args.artifact, payload)
        print(f"{Path(args.artifact).name}: COMPATIBLE")
        return 0
    if args.command == "validate-dir":
        result = validate_directory(Path(args.root))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1 if result["incompatible"] else 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
