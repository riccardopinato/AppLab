# AppLab v0.9.0 — Adaptive Impact Analysis & Incremental Verification

AppLab v0.9 moves verification planning **before** expensive static analysis, tests, APK builds and emulator work.

## Goals

- make continuous analysis materially faster without treating skipped work as PASS;
- increase accuracy with diff metadata, risk, confidence, module impact and historical failures;
- fail safe to FULL whenever the impact model is uncertain;
- preserve the existing Build -> isolated contract -> Trusted Verify boundary;
- keep production certification separate from FAST/FULL verification.

## Verification lanes

- `NO_RUNTIME_CHANGE`: documentation-only or no effective source change. No toolchain setup, APK build or emulator. Runtime labs are explicitly SKIPPED and previous trusted runtime evidence is referenced.
- `STATIC_ONLY`: tests/static configuration only. Run static/test quality checks, skip APK/emulator, emit a traceable incremental PASS only after those checks succeed.
- `FAST_RUNTIME`: build the APK and run core runtime verification plus selected specialist labs.
- `FULL_RUNTIME`: complete runtime suite. Used for explicit FULL, high/critical risk, low confidence, unsafe baselines, large diffs, and shadow calibration.
- `CERTIFICATION`: production certification contract. v0.8.1 release-integrity guarantees remain mandatory.

## Trusted impact inputs

The engine inspects the trusted range `baseline SHA..HEAD` with:

- `git merge-base --is-ancestor` baseline validation;
- name/status including deletes and renames;
- numstat line churn;
- tracked source paths and lightweight import evidence;
- impacted Flutter/native modules;
- recent AppLab failure count for the same repository/ref/history identity.

A missing, invalid, unavailable or non-ancestor baseline escalates to FULL.

A changed-file set over 500 files escalates to FULL instead of failing the pipeline.

## Risk and confidence

Risk is deterministic. Sensitive areas such as migrations, schema, Manifest, signing, applicationId, Gradle/build configuration, services/workers, permissions and lifecycle-sensitive Android code raise risk.

Confidence is reduced for broad or poorly classified changes. The invariant is:

> Lower confidence can only increase coverage; it can never reduce coverage.

## Incremental static work

Flutter FAST may analyze/test up to a bounded number of impacted scopes when confidence is high. If those scopes are missing, too broad or ambiguous, it falls back to full `flutter analyze` / `flutter test`.

Native Android creates a Gradle execution plan. Compatible Gradle test/lint/build commands are merged into one task graph and test/lint tasks can be module-qualified when exactly one trustworthy module is impacted. Custom shell commands stay sequential.

## Runtime acceleration

Trusted verification preserves clean isolation but caches:

- pinned Maestro 2.10.0;
- clean AVD state keyed by API, profile, target and architecture.

The cached AVD is created before any candidate APK is installed. Verification runs with `-no-snapshot-save`, so app state from a candidate never contaminates the reusable clean snapshot.

## Shadow FULL calibration

A deterministic sample of FAST_RUNTIME commits is selected for shadow calibration.

For those commits AppLab stores:

1. what FAST predicted it would run/skip;
2. the same commit executed as FULL;
3. `shadow-calibration.json/.md` comparing predicted skips with actual FULL outcomes.

If a lab that FAST would have skipped fails under FULL, AppLab records a critical false-negative and the workflow fails.

## Domain-scoped contract fingerprints

v0.9 fingerprints `core + selected specialist domains` rather than treating every specialist script as one monolith.

Each result records:

- `cache_domains`;
- `verification_fingerprint`.

For an already verified target SHA the Repo Watcher recomputes the fingerprint for the same recorded domains. An unrelated specialist-lab implementation change does not invalidate the project; a core or selected-domain change does.

## Evidence and telemetry

The impact plan records:

- verification lane;
- requested/effective mode;
- changed files and change types;
- risk score/label/reasons;
- confidence;
- impacted modules;
- selected labs;
- predicted FAST lab selection for shadow runs;
- historical failure count;
- cache domains/fingerprint;
- planner duration.

Control Center surfaces lane, risk, confidence, shadow status and fingerprint.

## Fail-safe invariants

v0.9 does not change these rules:

- FAST is never production certification.
- SKIPPED is never PASS.
- FAST never publishes a production release artifact.
- certification requires release-profile artifacts and current-run evidence.
- unsafe impact analysis falls back to FULL.
- Build -> contract -> Trusted Verify remains isolated.
