# AppLab v0.9.0 — Adaptive Impact Analysis & Incremental Verification

AppLab v0.9 moves FAST planning to the beginning of the project gate. The goal is not to skip quality checks blindly: AppLab first measures impact, risk and confidence, then chooses the smallest trustworthy verification lane. Any uncertainty increases coverage.

## Verification lanes

- `NO_RUNTIME`: documentation/non-runtime-only change. No Flutter/Gradle setup, APK build or emulator. The result records the previous verified SHA whose runtime evidence remains applicable.
- `STATIC_ONLY`: tests, lint configuration or CI-only change. Runs targeted static verification and does not rebuild or launch an APK.
- `FAST_RUNTIME`: runtime change with bounded blast radius, acceptable risk and high enough confidence. Builds an APK and always keeps core launch/crash/visual/interaction verification, while specialist labs are selected by impact.
- `FULL_RUNTIME`: explicit FULL, unsafe diff, oversized diff, low confidence or high risk. Runs the complete runtime suite.
- `CERTIFICATION`: production release gate. Existing v0.8.1 release-integrity guarantees remain mandatory.

`SKIPPED` is never converted into `PASS`, and FAST can never publish a production-certified release.

## Trusted diff and baseline identity

FAST uses the most recent matching PASS for the watch entry and compares:

```
last verified SHA .. current SHA
```

The baseline must exist and satisfy `git merge-base --is-ancestor BASELINE HEAD`. A missing, unrelated or unreachable baseline forces FULL.

Diff evidence includes name/status, rename detection, per-file line churn and aggregate churn. More than 500 changed files or more than 20,000 changed lines is treated as an oversized change and escalates to FULL instead of failing the planner.

## Impact model

The planner combines:

1. changed paths;
2. add/delete/rename status;
3. line churn;
4. changed source content;
5. framework/platform signals;
6. a bounded source dependency graph built from Dart/Kotlin/Java imports;
7. transitive blast radius;
8. recent project failure history supplied by Repo Watcher.

Path rules remain as a deterministic fallback, not as the sole decision mechanism.

## Risk

Risk is scored from 0–100. Signals that increase it include schema/migration changes, Manifest and platform-level changes, signing/build configuration, background components, network/sync surfaces, deleted files, large churn, broad dependency blast radius and recent failures.

Risk levels:

- low: <35
- medium: 35–64
- high: 65–84
- critical: >=85

A FAST candidate at risk >=75 escalates to FULL.

## Confidence

Confidence represents how trustworthy AppLab considers its own impact inference. Missing source content, unavailable dependency analysis, generated-code-heavy changes, unsafe baselines and oversized diffs reduce confidence.

A FAST candidate below 0.65 confidence escalates to FULL. The design rule is: uncertainty may increase work, never decrease it.

## Incremental static verification

Flutter FAST/STATIC lanes can narrow analysis and unit tests when confidence is >=0.85 and reliable targets are available. Otherwise they fall back to the full Flutter static suite.

Native Android combines compatible Gradle test/lint/build commands into one task graph. When confidence is high and one module is clearly affected, unqualified Gradle tasks are scoped to that module. Unsupported/custom commands fall back to the original sequential commands.

## Core runtime invariant

For every runtime lane AppLab still performs its trusted Build -> isolated contract -> Trusted Verify boundary. Core launch, crash/ANR checks, Maestro when enabled, Visual Journey and Safe Interaction Crawler remain mandatory for runtime verification. Specialist labs are selective only in FAST_RUNTIME.

## Clean runtime caches

Maestro 2.10.0 is cached by pinned version. Android uses a clean AVD cache keyed by API level, hardware profile, target and architecture. The clean AVD cache is saved before any target APK is installed, so cached emulator state does not contain app-under-test data.

## Shadow FULL calibration

Repo Watcher deterministically samples 10% of scheduled SHAs for an additional FULL verification. The shadow result is compared against FAST. A failing gate that FAST skipped, or FAST PASS paired with FULL FAIL, is recorded as a critical divergence/false negative.

Shadow results are attached to the normal FAST history record and are not treated as an independent project state.

## Telemetry

Central history records:

- lane distribution;
- FAST/FULL mode distribution;
- risk levels;
- average planner confidence;
- shadow sample count;
- shadow false-negative count/rate.

These metrics are written to `.applab-history/adaptive-telemetry.json`.

## Domain contract fingerprints

The verification contract now exposes a core fingerprint plus independent fingerprints for visual, system, performance, network, persistence, configuration, resource-pressure, background, storage and upgrade domains.

For an unchanged target SHA, Repo Watcher can reuse a cached result when an AppLab internal change affects only domains that the latest PASS did not use. With no trustworthy prior PASS it falls back to the full contract fingerprint.

## Fail-safe rules

AppLab escalates to FULL when:

- no trustworthy baseline exists;
- baseline is not an ancestor of HEAD;
- diff discovery fails;
- the change is oversized;
- risk is high enough;
- confidence is too low;
- required runtime baselines are unavailable.

Production certification remains independent and always uses complete release evidence.
