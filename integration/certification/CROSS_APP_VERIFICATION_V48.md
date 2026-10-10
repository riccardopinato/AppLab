# AppLab v4.8 — Cross-App Verification

AppLab v4.8 adds a dedicated **pair verification authority** for interactions that
cannot be proven by certifying each application independently.

It is deliberately separate from the existing **Cross-App Intelligence** engine:
portfolio recurrence remains advisory, while this verifier evaluates one exact
producer/consumer pair and one explicit executed scenario matrix.

## Authority boundary

Cross-app verification never promotes either app's single-app Release Reality or
CERTIFICATION status. The inverse is also true: two individually CERTIFIED apps
do **not** imply a cross-app PASS.

The pair output is one of:

- `PASS` — all required cross-app semantics and required paired physical evidence pass;
- `FAIL` — an executed semantic or physical assertion failed;
- `BLOCKED` — required pair identity, scenario coverage, or paired physical evidence is missing/invalid;
- `NOT_VERIFIED` — the required scenarios exist but at least one was not actually verified.

`cross_app_round_trip.independent_from_single_app_pass` is therefore always true.

## Paired artifact identity

Both sides are bound independently to:

- repository (`owner/name`);
- immutable 40-character source SHA;
- exact APK SHA-256;
- Android package id;
- version name/code;
- canonical Shared Ecosystem Core app id.

The producer and consumer cannot collapse to the same exact app/artifact identity.
The CLI can additionally consume each side's `release-reality.json`; when supplied,
repository, source SHA, APK hash, package and version must reconcile exactly or the
pair verification is BLOCKED.

## Shared Ecosystem Core v1

For App Factory ecosystem transfers, v4.8 reuses the canonical **Shared Ecosystem
Core v1**. It does not invent a parallel payload.

The verifier enforces the Golden contract invariants that can be evaluated from
the executed session evidence:

- `schemaVersion = 1` and `privacyScope = explicitShare`;
- canonical `bridgeId` and `bridgeId + revision + transferMode` idempotency key;
- COPY/LINK remain separate deliveries while keeping the same canonical owner;
- provenance owner/revision cannot be silently replaced by the destination;
- LINK requires a canonical deep link and known app schemes must match;
- local transport `transportVersion = 1` and target app must match;
- media handoff supports `omitted`, `shareToken`, `cloudObject` while private/local
  references (`file://`, `content://`, `media://`, `/data/`, `/private/`) fail closed.

The session must identify the Golden/contract source through `protocol.contract_ref`.

## Required scenario matrix

A complete pair verification covers these semantic scenarios:

- `COPY`
- `LINK`
- `IDEMPOTENCY`
- `PROVENANCE`
- `OWNERSHIP`
- `FAIL_CLOSED`

It must also cover at least one explicit transport scenario:

- `DEEP_LINK_HANDOFF`, or
- `FALLBACK_TRANSPORT`.

Scenario assertions are explicit rather than represented by a numeric score. For
example, idempotency PASS requires duplicate no-op behavior, a stable bridge id
and mode-specific idempotency keys. FAIL_CLOSED requires incompatible-version
rejection, no domain mutation, and private-media rejection.

## Transport and physical-device evidence

Protocol and transport stay separate. Each scenario declares its transport. Both
the pair-level transport and every scenario transport must use a supported
`deep_link` / `android_intent` / `clipboard` / `fallback` value. AppLab derives
the installed-app requirement from that validated transport class; the submitted
boolean cannot weaken the requirement.

When `requires_installed_apps=true`, **paired physical-device evidence is required**.
Emulator evidence or two independent single-app physical sessions cannot be
silently substituted for the cross-app round trip.

The paired physical record binds:

- both exact artifact SHA-256 values;
- physical device manufacturer/model/OS/build;
- every installed-app-dependent scenario id;
- PASS/FAIL/BLOCKED result;
- **at least one** hashed screenshot/log/video/file/trace/report reference.

The v4.8 workflow is an operator-attested evidence path, following the existing
Physical Evidence Hub trust model. Evidence-reference hashes are recorded, but
external referenced bytes are not downloaded/re-hashed by this workflow. The
attestation states this explicitly and never claims stronger evidence integrity.

## Fail-closed rules

Cross-app PASS is impossible when any of these applies:

- producer/consumer identity is incomplete or contradictory;
- a supplied Release Reality identity disagrees with the pair session;
- the Shared Ecosystem Core contract is malformed/incompatible;
- required semantic or transport scenarios are missing;
- the selected transport is unsupported or its physical-requirement declaration is contradictory;
- COPY/LINK/idempotency/provenance/ownership observations do not share one coherent lineage;
- producer and consumer claim identical APK bytes;
- required assertions are absent/false in a claimed PASS scenario;
- installed-app transport lacks paired physical evidence;
- paired physical evidence does not bind both exact APK hashes;
- required physical scenario coverage is incomplete;
- the physical or semantic run reports a failure.

No missing evidence is converted into PASS.

## CLI

```bash
python scripts/cross_app_verification.py \
  --session pair-session.json \
  --producer-release-reality producer-release-reality.json \
  --consumer-release-reality consumer-release-reality.json \
  --output-dir applab-cross-app-verification
```

Outputs:

- `cross-app-verification.json`
- `cross-app-verification.md`

Self-tests:

```bash
python scripts/ecosystem_core_contract.py --self-test
python scripts/cross_app_verification.py --self-test
```

## Trusted GitHub workflow

`AppLab Cross-App Verification v4.8.0` is manually dispatched from AppLab `main`.
It records the submitted executed pair session under a trusted AppLab workflow
identity and publishes the verifier outputs for 90 days.

This workflow **attests and evaluates** the executed pair evidence; it does not
claim to autonomously operate arbitrary third-party app UIs or re-hash external
screenshots/videos. When real installed-app behavior is required, the physical
operator/device remains the execution source and AppLab remains the contract and
evidence-verification authority.
