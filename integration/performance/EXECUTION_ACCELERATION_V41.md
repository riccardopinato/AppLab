# AppLab v4.1 — Execution Acceleration Engine

v4.1 accelerates AppLab by consolidating mechanisms that already existed in
Adaptive Impact Analysis instead of creating a second planner.

The v0.9/v1.0 Smart Test Plan remains the authority for **what must be tested**.
The v4.1 Execution Acceleration Engine decides **how to execute that plan with
less duplicated work**.

## Architecture

```text
target revision
      |
      v
Smart Test Plan
(change-aware lane + selected labs)
      |
      v
Execution Acceleration Engine
      |
      +--> stable execution key
      +--> content-addressed build contract
      +--> execution DAG
      +--> cache/reuse policy
      |
      v
Build Once
      |
      +--> trusted runtime
      +--> selected specialist labs
      +--> certification / evidence
```

## 1. Build Once / Verify Many

External Flutter and native Android runners already separated the untrusted build
from trusted runtime verification. v4.1 makes the build contract reusable.

The stable build identity includes:

- target repository;
- immutable target SHA;
- engine;
- working directory;
- build command;
- APK path;
- AppLab contract fingerprint;
- project configuration fingerprint;
- resolved toolchain identity (including the concrete Temurin Java patch);
- build-affecting prepare/post/test/lint commands;
- the semantic Smart Test Plan, excluding volatile planner timing.

A matching previous build contract can be restored for seven days.

Floating Flutter channels (for example `stable` without an exact
`flutter_version`) deliberately do **not** reuse build contracts because the
channel can move during the retention window. Java major/range inputs are
resolved to the concrete installed Temurin patch before the key is computed.

Historical learning statistics, timing percentiles and verification-budget
telemetry are excluded from the content key. Only decision-affecting plan state
(mode/lane/run flags, baseline/change set, selected labs and targets) participates.

A cache hit **does not mean runtime PASS**. The restored contract is validated
again against repository, SHA, engine and analysis mode, re-published into the
current run, then consumed by the normal Trusted APK Verifier.

Artifacts from another AppLab workflow revision are rejected.

## 2. Canonical AppLab Runtime Fixture

Before v4.1, Browser E2E and Emulator Self Test independently built the same
`selftest` APK.

Now:

```text
Canonical Runtime Fixture Build
          |
          +----> Browser E2E
          |
          +----> Emulator Self Test
```

The canonical artifact contains:

- source SHA;
- APK SHA-256;
- byte size;
- build command;
- workflow run identity.

Consumers wait for the artifact, verify source SHA and SHA-256, and use exactly
the same APK bytes.

## 3. Change-aware execution

v4.1 does not duplicate the existing Smart Test Plan.

Existing lanes remain authoritative:

- `NO_RUNTIME_CHANGE`;
- `STATIC_ONLY`;
- `FAST_RUNTIME`;
- `FULL_RUNTIME`;
- `CERTIFICATION`.

The Execution Acceleration Engine consumes those lanes and emits a deterministic
DAG with explicit RUN / SKIP / RESTORE_OR_BUILD nodes.

## 4. Parallelism and cancellation

Independent GitHub workflow gates remain parallel and every same-ref workflow
uses cancellation for stale runs.

Stateful specialist labs intentionally remain serial inside a shared emulator.
Parallelizing them would multiply AVD cold starts and destroy the state isolation
that several lifecycle/persistence labs rely on.

The policy is therefore:

- independent workflow gates: **parallel**;
- stale same-ref work: **cancel**;
- shared-emulator specialist labs: **serial**.

## 5. Content-addressed build reuse guardrails

Build reuse is allowed only when:

1. the deterministic execution key matches;
2. the artifact was produced by the same AppLab workflow SHA;
3. the build contract passes the existing trusted contract validator;
4. the target repository/SHA/engine/mode match.

Failed builds never produce a reusable build contract.

Runtime or certification evidence is never reused merely because the build was
reused.

## 6. Metrics

`pipeline-metrics.json` now records:

- `build_cache_applicable`;
- `build_cache_hit` (`null` when no lookup is applicable);
- `build_cache_reason`;
- `execution_key`;
- `execution_lane`;
- `build_once_verify_many`;
- `cached_quality_timings_ignored` when producer-run quality timings are deliberately excluded from current-run duration metrics.

This lets future audits compare cache hit-rate and wall-clock savings against
the pre-v4.1 baseline.

## 7. AppLab Doctor

`scripts/applab_doctor.py` provides deterministic environment preflight:

```bash
python scripts/applab_doctor.py --profile core
python scripts/applab_doctor.py --profile android
python scripts/applab_doctor.py --profile flutter
python scripts/applab_doctor.py --profile full
```

Profiles report missing required and optional tooling before a long pipeline is
started.

Doctor is diagnostic only. It never modifies the host.

## Trust boundary

v4.1 does not weaken:

- source SHA binding;
- build/trusted-runtime separation;
- APK SHA-256 validation;
- FAST/FULL/CERTIFICATION authority;
- release byte identity;
- branch protection;
- heavy-audit contracts.
