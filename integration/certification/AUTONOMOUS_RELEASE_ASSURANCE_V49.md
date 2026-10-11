# AppLab v4.9.0 — Autonomous Release Assurance

## Goal

Close the technical release-assurance chain above the existing AppLab authorities:

Source -> Build -> Static intelligence -> Trusted runtime -> Evidence Graph ->
Risk-based validation -> Physical evidence -> Distribution evidence -> Certification.

v4.9 does not create a new certification authority. It composes already-produced
evidence and states exactly whether the end-to-end release-assurance chain is
PASS, FAIL or BLOCKED.

## Canonical record

The engine is scripts/release_assurance.py and produces:

- release-assurance.json
- release-assurance.md

The record is bound to the Release Reality identity:

- repository;
- immutable resolved source SHA;
- exact APK SHA-256;
- package id;
- version name;
- version code.

The deterministic assurance digest covers the bound identity plus every required
stage state.

## Required assurance stages

1. SOURCE_BUILD_BOUND
2. STATIC_BUILD_ASSURANCE
3. TRUSTED_RUNTIME
4. EVIDENCE_GRAPH
5. RISK_BASED_VALIDATION
6. PHYSICAL_EVIDENCE when required by policy
7. DISTRIBUTION_EVIDENCE when applicable
8. CERTIFICATION

Cross-app evidence remains a separate conditional stage. When a bound pair record
is supplied it must contain the exact current release artifact and must preserve
the independent cross-app authority introduced in v4.8. True Autonomous Review
accepts an optional `cross_app_run_id`, verifies that the successful workflow run
came from `cross-app-verification.yml` on trusted AppLab `main`, downloads the
90-day attestation artifact, verifies its digest/attestation, and only then binds
the record into Release Assurance.

## Fail-closed rules

- Missing required evidence never becomes PASS.
- Evidence identity mismatch is FAIL.
- Exact artifact bytes are mandatory.
- Evidence Graph must match repository/revision/package when those identities are present.
- Adaptive risk plans must use the canonical lane schema and match the exact repository/revision.
- Required physical evidence remains independent from emulator evidence; an attached optional physical FAIL is still a FAIL.
- Distribution is not inferred from certification or from a green build, and only an explicit distribution PASS can satisfy the stage.
- Canonical certification PASS requires an identity-bound `certification.json`; the embedded Release Reality summary is context only.
- Cross-app PASS is not inferred from two individually green apps.
- Release Assurance cannot promote or issue CERTIFIED.
- No numeric release/product score is introduced.

## Trusted integration

True Autonomous App Review copies the trusted Release Reality and other bound
release evidence into its evidence workspace after the Evidence Graph is built,
then generates Release Assurance. A BLOCKED assurance state is evidence, not a
technical workflow failure; certification remains the authority that decides
whether a release is certified.

Studio surfaces the release-assurance state, required-stage coverage, blockers,
failures and the next required stage.

## Distribution evidence contract

When distribution-evidence.json is present it must bind exactly to the same
repository, resolved SHA, APK SHA-256, package id, version name and version code.
It must explicitly state trusted=true and exact_artifact_match=true before it can
satisfy DISTRIBUTION_EVIDENCE.

Until trusted distribution/install-channel evidence exists for the exact artifact,
release assurance remains BLOCKED when distribution is applicable.

## Validation

The v4.9 implementation is protected by:

- release_assurance.py --self-test;
- audit-contract invariants;
- workflow-contract invariants;
- frontend build/type checking through normal AppLab CI;
- existing trusted runtime, CodeQL, Browser E2E, Emulator Self Test and repository-governance gates.
