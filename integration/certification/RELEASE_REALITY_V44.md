# AppLab v4.4 — Release Reality Engine

AppLab v4.4 adds a canonical release-evidence record that answers one question:

> How far has this exact release artifact really progressed?

The engine does not create a product score and does not promote a release by
inference. Every stage is represented independently and is bound to evidence.

## Canonical ladder

```
IMPLEMENTED
  ↓
STATICALLY_CHECKED
  ↓
TESTED
  ↓
CI_GREEN
  ↓
ARTIFACT_BUILT
  ↓
TRUSTED_RUNTIME_VERIFIED
  ↓
PHYSICAL_DEVICE_VERIFIED
  ↓
DISTRIBUTION_VERIFIED
  ↓
STORE_READY
  ↓
PRODUCTION_RELEASED
```

Applicable stages use `PASS`, `FAIL`, `BLOCKED` or `NOT_VERIFIED`.
A stage that is genuinely not required by policy may be `N/A`.

## Output

The Trusted APK Verifier now writes:

- `release-reality.json`
- `release-reality.md`

The JSON record contains:

The engine also cross-checks repository, immutable SHA, engine, workflow run and
trusted AppLab SHA across the sealed build contract and finalized runtime result.
A provenance mismatch fails closed instead of producing a release-state record.

- repository and immutable source SHA;
- engine/ref;
- package id;
- version name and version code;
- exact APK SHA-256 and byte size;
- signing certificate SHA-256 and signing subject;
- workflow run id and trusted AppLab revision;
- analysis mode and pipeline state;
- every release-reality stage;
- current contiguous verified level;
- next unresolved gate;
- exact certification blockers/failures when certification was attempted;
- same-artifact guardrails.

## Same-artifact semantics

Release identity is byte-bound.

AppLab recomputes SHA-256 from the actual APK available to the Trusted Verifier
and compares it with the build contract. Size and canonical identity are checked
as well.

A rebuilt APK with different bytes is a new artifact even when repository,
source SHA, package and human-readable version labels are unchanged. Evidence
from the previous APK is not silently inherited.

ARTIFACT_BUILT proves that the exact APK bytes, size, package and version/build
identity are bound. It does **not** require release-signing proof merely to
acknowledge that the artifact exists and was the artifact tested. Signing
identity is recorded separately as VERIFIED or NOT_VERIFIED and remains a
certification/store concern when policy requires it. This prevents a debug or
internal test artifact from erasing truthful build/runtime evidence while still
preventing it from being mistaken for a store-ready release.

## Current evidence authority

v4.4 can prove the existing AppLab stages through trusted runtime:

- IMPLEMENTED from repository/SHA/engine binding;
- STATICALLY_CHECKED from the bound build quality evidence;
- TESTED from the bound unit-test evidence;
- CI_GREEN from the required static/test/build checks in the sealed build
  contract; runtime and certification outcomes remain separate stages;
- ARTIFACT_BUILT from the exact APK bytes and canonical artifact identity;
- TRUSTED_RUNTIME_VERIFIED from runtime PASS on those exact bytes.

The record is generated inside the Trusted Verifier before the Trusted Evidence
Manifest. The manifest therefore hashes and covers the Release Reality record
when trusted runtime succeeds.

The finalizer also preserves the original Android verifier verdict as
`runtime_result` before any later certification/pipeline failure can rewrite the
aggregate `result`. Release Reality therefore keeps a successful trusted-runtime
stage as PASS even when a downstream certification gate is BLOCKED.

## Post-runtime stages

v4.4 deliberately does **not** pretend to have evidence that does not yet exist.

- If the certification policy requires a real device, physical-device status is
  `BLOCKED` until a future trusted physical record exists.
- If the policy does not require physical testing, that stage is `N/A`.
- Distribution, store readiness and production release remain
  `NOT_VERIFIED` until separate trusted evidence is implemented.

The v4.5 Physical Evidence Hub will provide the first of those post-runtime
evidence classes.

## Certification

`certification.json`, when present, is imported without changing its authority.

Release Reality records the exact certification failures/blockers but does not
convert CERTIFICATION into distribution/store/production proof.

Therefore:

- CERTIFIED is not the same as DISTRIBUTION_VERIFIED;
- emulator PASS is not PHYSICAL_DEVICE_VERIFIED;
- a green CI build is not ARTIFACT or runtime proof unless the bound bytes are
  actually verified;
- STORE_READY and PRODUCTION_RELEASED require their own future evidence.

## Risk-based validation

Release Reality preserves the existing AppLab risk model. A project is not
forced through irrelevant hardware validation merely to advance the ladder.
Policy-driven non-applicable stages remain visible as `N/A`, while genuinely
missing required evidence stays BLOCKED or NOT_VERIFIED.

## Downstream use

Autonomous Review now preserves `release-reality.json` inside Studio-ready
project evidence. Detailed Release Cockpit UI remains planned for v4.7; v4.4
establishes the canonical data contract first.
