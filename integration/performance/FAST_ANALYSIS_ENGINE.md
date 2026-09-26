# AppLab v0.9.0 — Adaptive Impact Analysis & Incremental Verification

AppLab v0.9 moves selective verification to the beginning of the pipeline. FAST is no longer only a runtime-lab selector: AppLab first determines what changed, how risky the change is, how confident the impact model is, and only then decides which static checks, build work and runtime labs are necessary.

The governing safety rule is:

> Uncertainty can only increase coverage. It must never reduce it.

## Verification lanes

The planner emits exactly one lane:

- `NO_RUNTIME_CHANGE` — changes are documentation-only or otherwise proven not to affect the runtime artifact. No toolchain, APK build or emulator is started.
- `STATIC_ONLY` — changes affect tests/static configuration but not production runtime code. Static checks run; APK build and emulator are skipped.
- `FAST_RUNTIME` — bounded low/medium-risk runtime change with sufficient confidence. AppLab builds the APK and runs core runtime verification plus selected specialist labs.
- `FULL_RUNTIME` — broad, high-risk, low-confidence, oversized or otherwise unsafe-to-select change. The complete runtime suite runs.
- `CERTIFICATION` — explicit production certification. All mandatory release evidence remains required.

FAST remains a request mode. The effective lane may escalate to FULL automatically.

## Trusted baseline

FAST compares the most recent matching trusted PASS to the current target SHA.

The baseline identity is bound to:

- repository;
- ref;
- history key;
- effective project engine where applicable;
- project configuration fingerprint.

The baseline SHA must exist locally and pass:

```
git merge-base --is-ancestor BASELINE HEAD
```

A missing, invalid, unavailable or non-ancestor baseline causes FULL fallback.

## Diff evidence

The planner records more than changed filenames:

- `git diff --name-status --find-renames`;
- `git diff --numstat`;
- bounded zero-context patch evidence;
- additions/deletions;
- adds/deletes/renames;
- total file count;
- diff size/truncation state.

A change set larger than the selective-analysis safety limit or a diff exceeding the inspection budget escalates to FULL rather than failing or silently dropping files.

## Content and dependency impact

Path rules remain as one signal, but they are no longer the sole classifier.

AppLab also inspects bounded source content for signals such as:

- network/API clients;
- Room/SQLite/Drift/Hive persistence;
- permissions, notifications and foreground services;
- WorkManager/alarms/background execution;
- camera/media/memory-sensitive code;
- configuration/lifecycle/UI code.

A bounded dependency graph is built from tracked Dart/Kotlin/Java source files. Imports, exports, package declarations and source identities are used to propagate impact up to two levels. Transitive dependents can therefore activate labs and static targets even when the changed filename itself is generic.

If the dependency scan reaches its safety budget, confidence decreases and can trigger FULL.

## Risk and confidence

Every plan includes a deterministic risk score, risk level and confidence.

High-risk signals include:

- database/schema/migration changes;
- Android manifest, application ID, SDK or signing changes;
- build/dependency configuration;
- background services/workers/alarms;
- network/sync changes;
- broad line churn or many changed files;
- deletions/renames;
- recent failures in affected areas.

Risk levels are `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.

High/critical risk or confidence below the safety threshold escalates to FULL.

## Incremental static verification

For Flutter LOW-risk/high-confidence FAST changes, AppLab can narrow analysis to impacted feature directories and run directly mapped tests when such targets can be proven.

If targets are missing, confidence is insufficient, risk rises, or the change touches broad/global configuration, AppLab runs the complete Flutter analysis/test suite.

For native Android, AppLab builds one safe Gradle task graph when test/lint/build commands are compatible. LOW-risk/high-confidence changes may qualify tasks to impacted modules. If the targeted Gradle task does not exist, AppLab retries the original commands. Genuine test, lint or build failures are never masked.

## Source reuse

The preflight job owns the authoritative source SHA.

After analysis it packages an exact tracked-source tar archive with SHA-256 evidence. Build jobs consume that archive rather than checking out the target again. The Universal Runner can produce the plan and source snapshot once and pass both into the selected Flutter/native runner.

The isolated Build → Artifact → Trusted Verify boundary is unchanged.

## Runtime selection

Core runtime safety remains mandatory for `FAST_RUNTIME`:

- install/launch/process health;
- crash and ANR detection;
- Maestro when enabled;
- Visual Journey / visual QA;
- Safe Interaction Crawler.

Specialist labs are selected by the impact plan:

- System UI;
- Performance;
- Network & Offline;
- Persistence & Restart;
- Configuration & Lifecycle;
- Resource Pressure & Process Death;
- Background / Doze Recovery;
- Storage & Data Integrity;
- Upgrade & Migration.

A skipped specialist lab remains `SKIPPED`, never PASS.

## Runtime acceleration

Trusted verification caches:

- pinned Maestro 2.10.0;
- a clean Android AVD snapshot keyed by API/system image/architecture/device profile.

The verification emulator is started from the clean snapshot with snapshot saving disabled, so target-app state is not persisted back into the reusable AVD.

## Shadow FULL calibration

A deterministic sample of eligible FAST_RUNTIME runs is executed as FULL runtime while preserving the original FAST prediction.

`shadow_calibration.py` compares the skipped/selected specialist labs with the complete result and records:

- MATCH / DIVERGED;
- false-negative count;
- false-negative labs;
- over-selection evidence.

This converts FAST accuracy from an assumption into a measurable property.

## History-aware planning

Recent repository verification failures can increase the risk score of affected domains. Historical evidence only broadens coverage; it cannot be used to suppress a lab.

## Domain-aware cache fingerprints

The verification contract is split into:

- core fingerprint;
- per-specialist-lab fingerprints.

Cache reuse is based on the domains that the latest trusted plan actually exercised. A change to one specialist lab does not invalidate unrelated cached verification, while changes to planner/verifier/workflow core invalidate all relevant results.

Older history without domain metadata is treated conservatively as depending on all specialist domains.

## Telemetry

Each result can include:

- planner elapsed milliseconds;
- preflight seconds;
- build-job seconds;
- trusted-runtime seconds;
- estimated total seconds;
- lane;
- risk/confidence;
- FAST→FULL escalation;
- selected labs;
- shadow calibration.

`analysis_metrics.py` aggregates p50/p95 timing, lane distribution, escalation count and shadow false negatives. The Control Center exposes the latest adaptive state and aggregate health.

## Production safety

FAST does not authorize production release.

Production Certification remains separate and requires the release build profile, signing/integrity checks, primary deep certification lane, compatibility lane and any required real-device evidence. FAST/NO_RUNTIME/STATIC_ONLY results cannot be promoted into CERTIFIED.

## Evidence

Primary v0.9 evidence includes:

- `analysis-plan.json`;
- `contract.json`;
- `result.json`;
- `shadow-calibration.json` when evaluated;
- `timings.json` for runtime lanes;
- phase-specific build/static logs;
- normal AppLab runtime/lab evidence.

The planner regression corpus protects expected lane/lab decisions for documentation, test-only, UI, network, background, manifest, database/migration, storage, camera, notification and build/dependency cases.
