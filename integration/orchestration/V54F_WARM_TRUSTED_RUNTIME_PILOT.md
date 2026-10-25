# AppLab v5.4F — Warm Trusted-Runtime Pilot

Status: **PILOT IMPLEMENTED / NOT PRIMARY EXECUTOR**

v5.4F adds a trusted-runtime worker control plane and an isolated KVM equivalence pilot. It does not move target builds onto warm hosts and does not change verification authority.

## Worker lifecycle

```text
STARTING -> AVAILABLE -> LEASED -> SCRUBBING -> AVAILABLE
                      \-> QUARANTINED
```

Additional operational states are UNHEALTHY, DRAINING and OFFLINE.

## Trust boundary

A warm worker may contain:

- pinned AppLab trusted runtime code;
- Android SDK/platform tools;
- KVM;
- pristine AVD templates;
- evidence capture tooling.

It must never execute:

- target repository build scripts;
- arbitrary target shell commands;
- Gradle/Flutter target builds;
- untrusted prepare commands;
- target PR source outside installed APK runtime.

The pilot restores a canonical already-built APK fixture.

## Durable worker identity

Worker identity binds:

- worker ID;
- class `WARM_TRUSTED_ANDROID`;
- exact AppLab SHA;
- normalized capability digest;
- pristine snapshot digest.

Re-registering a worker ID with different immutable identity is rejected.

## Lease protocol

Lease eligibility requires:

- state AVAILABLE;
- no current lease;
- fresh heartbeat;
- exact AppLab SHA;
- matching runtime profile;
- mandatory KVM/runtime/disposable-AVD/evidence capabilities.

No eligible worker produces a structured GitHub Actions fallback; no weaker capability match is accepted.

Only one active trust-sensitive lease exists per worker.

## Cleanup / quarantine

After runtime, the worker enters SCRUBBING.

Return to AVAILABLE requires all cleanup attestations:

- emulator destroyed;
- target processes absent;
- app data discarded;
- snapshot digest verified;
- evidence hashes verified.

Missing attestation, stale heartbeat or expired lease causes fail-closed quarantine.

## PostgreSQL persistence

`integration/orchestration/sql/postgres-v54f-workers.sql` persists:

- warm workers;
- worker leases;
- append-only worker history.

The schema enforces immutable worker identity, one active lease per worker, worker delete rejection and append-only history.

## KVM equivalence pilot

`.github/workflows/warm-worker-pilot.yml` runs on an isolated GitHub runner and compares:

1. a cold control emulator created from scratch;
2. a warm emulator restored from a pristine template.

Both paths:

- use the same canonical APK fixture;
- use the same trusted verifier;
- use the same FAST pilot plan;
- verify exact result/lab evidence identity.

The control writes target private app state. The warm path is restored from the pristine template and must start with the target package absent, proving prior operation state did not cross the boundary.

The clone is destroyed after use.

## Promotion evidence

The pilot record requires:

- repository/source/AppLab/APK/package/mode identity match;
- exact lab outcome match;
- verdict match;
- clean isolation;
- positive measured emulator-ready startup improvement.

A faster result alone is insufficient.

The workflow produces `APPLAB_WARM_WORKER_PILOT` evidence with authority `NONE_PILOT_EVIDENCE`.

## Fallback and rollback

GitHub Actions remains the independent executor and fallback.

A quarantined/offline/mismatched warm worker simply becomes ineligible. No verifier semantics or certification rule changes are needed for rollback.

## Exit gate

v5.4F can be marked complete only when:

- worker lifecycle/lease/quarantine contract tests pass;
- PostgreSQL worker schema smoke passes;
- KVM pilot passes exact-artifact/lab/verdict equivalence;
- cross-run state isolation passes;
- measurable warm-start improvement is observed;
- normal AppLab CI/runtime/security/governance gates are green.

The next step is v5.4G controlled event-driven execution.
