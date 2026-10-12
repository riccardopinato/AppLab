# AppLab v5.3.4 — Evidence Schema Registry & Compatibility Contracts

## Purpose

v5.3.4 introduces one explicit compatibility registry for the evidence artifacts
that cross AppLab producer/consumer boundaries.

The registry is not a new evidence authority. It does not select FAST/FULL,
certify releases, replace trusted runtime verification or convert missing
evidence into PASS.

## Registry contract

The canonical implementation is:

- `scripts/evidence_contract_registry.py`

Each registered artifact declares:

- producer;
- schema version;
- component/version field when the artifact has one;
- consumers;
- fixed identity fields such as record type or authority where applicable;
- evidence class.

Compatibility is exact for the declared schema/version pair. A registered
artifact with a mismatched schema, component version, record type or authority
fails closed.

Unknown evidence is explicitly `NOT_REGISTERED`; it is never promoted to
trusted/compatible merely because it is valid JSON.

## Initial registered surface

The v1 registry covers the high-value planning, trusted-runtime, release and
review chain:

- `analysis-plan.json`;
- `build-contract.json`;
- `trusted-evidence-manifest.json`;
- `evidence-graph.json`;
- `planner-feedback.json`;
- `physical-evidence.json`;
- `release-reality.json`;
- `certification.json`;
- `cross-app-verification.json`;
- `release-assurance.json`;
- `simulated-human-qa.json`;
- `design-system-advisor.json`;
- `competitive-product-intelligence.json`;
- `virtual-product-review-council.json`.

The registry is deliberately bounded. New evidence producers must be added only
when their producer/consumer boundary is stable enough to declare explicitly.

## Production integration

Three critical boundaries consume the registry directly:

1. Evidence Graph validates registered inputs before building graph evidence.
2. Release Assurance validates registered release/planning/certification inputs
   before making release-assurance conclusions.
3. Trusted evidence manifest validation rejects incompatible manifest
   schema/version before binding hashes and runtime evidence.

The autonomous review workflow also runs a directory compatibility preflight
before Studio projection so stale producer output cannot be silently rendered as
current evidence.

## Cache and invalidation semantics

The registry participates in:

- the central AppLab contract fingerprint;
- the core domain fingerprint;
- Repo Watcher invalidation.

A registry-contract change therefore cannot silently reuse a cache produced
under different evidence compatibility semantics.

## Validation

v5.3.4 adds an independent contract test outside the registry implementation:

- `tests/contracts/evidence_schema_registry_test.py`

It verifies:

- required artifact coverage;
- exact schema/version acceptance;
- schema mismatch rejection;
- component-version mismatch rejection;
- producer declaration consistency;
- unknown evidence remaining unregistered;
- directory-level failure detection;
- deterministic registry digest.

The central audit additionally checks production wiring, CI execution,
maintainability ceilings and cache invalidation.

## Authority boundaries preserved

v5.3.4 does not:

- reduce specialist-lab coverage;
- skip runtime because evidence appears unchanged;
- change Smart Test Plan authority;
- change Trusted APK Verifier authority;
- change Release Assurance semantics;
- change Production Certification authority;
- infer physical-device evidence from emulator evidence;
- infer compatibility for unregistered evidence.

Coverage-reducing delta execution remains a separate future step and is still
gated on real multi-project calibration.
