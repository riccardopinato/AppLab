# AppLab v0.9.0 — Adaptive Impact Analysis & Incremental Verification

AppLab keeps three user-facing verification modes:

- `fast`: adaptive continuous verification;
- `full`: complete runtime verification and baseline-seeding path;
- `certification`: production release authorization.

FAST is now a **planning request**, not a promise to run a fixed reduced suite. The trusted planner may keep it narrow or escalate it to FULL.

## Preflight-first architecture

The v0.9 pipeline is:

```
checkout target
  -> validate trusted baseline ancestry
  -> inspect full baseline..HEAD diff
  -> build lightweight dependency impact graph
  -> combine change risk + confidence + historical failures
  -> choose verification lane
  -> choose static/test scope
  -> build only if runtime changed
  -> trusted Android runtime only if runtime changed
  -> select specialist labs
  -> evidence + telemetry + history
```

The Build -> isolated contract -> Trusted Verify trust boundary from v0.6.4 remains intact for every runtime lane.

## Trusted changed range

Repo Watcher supplies the latest successful verified SHA. v0.9 requires that SHA to:

1. be a valid 40-hex commit;
2. exist in the target checkout after bounded/deepened fetch;
3. be an ancestor of current HEAD.

The analysis range is `baseline..HEAD`. If ancestry cannot be proven, FAST fails safe to FULL. Intermediate commits therefore cannot hide risky changes behind a later documentation-only commit.

## Impact evidence

The engine consumes:

- `git diff --name-status --find-renames`;
- `git diff --numstat`;
- zero-context changed hunks;
- add/delete/rename status;
- line churn;
- build/dependency/configuration changes;
- path and changed-content domain signals;
- tracked files from `git ls-files`;
- lightweight Dart import relationships;
- lightweight Kotlin/Java package/import relationships;
- recent AppLab failure/WARN history.

The planner does not depend on generative AI. Decisions are deterministic and evidence-preserving.

## Verification lanes

### NO_RUNTIME_CHANGE

Used only when the trusted diff contains documentation/metadata-only changes.

AppLab does not install toolchains, build an APK or start an emulator. The result records:

- `runtime_changed=false`;
- `verification_scope=SOURCE_ONLY`;
- the trusted runtime-evidence baseline SHA;
- all runtime labs as `SKIPPED`.

This is not represented as a new runtime PASS.

### STATIC_ONLY

Used when only tests or supported static-analysis configuration changed.

AppLab runs the necessary static/test path but avoids APK build and emulator runtime. The result explicitly records `STATIC_ONLY`; runtime evidence remains inherited.

### FAST_RUNTIME

Used when runtime code changed but risk/confidence allow selective verification.

Always-on verification remains:

- app install/start and process health;
- crash/ANR detection;
- Maestro acceptance when enabled;
- Visual Journey / Smart Visual QA / Visual Regression;
- Safe Interaction Crawler.

Specialist labs are selected by impact domain:

- System UI;
- Performance;
- Network & Offline;
- Persistence & Restart;
- Configuration & Lifecycle;
- Resource Pressure & Process Death;
- Background / Doze Recovery;
- Storage & Data Integrity;
- Upgrade & Migration.

A skipped lab is always `SKIPPED`, never PASS.

### FULL_RUNTIME

FAST automatically escalates to FULL when any safety condition requires it, including:

- missing/invalid/unavailable baseline;
- baseline that is not an ancestor of HEAD;
- changed-file discovery failure;
- more than 500 changed files;
- critical release/runtime surfaces such as migration/schema/applicationId/signing/permissions;
- high-risk build/dependency changes;
- risk score >= 70;
- planner confidence < 0.65;
- missing trusted visual/upgrade baseline in Trusted Verify.

FULL executes the complete specialist suite.

### CERTIFICATION

Certification is never selected as a side effect of FAST or FULL. It remains an explicit release operation with the production rules documented in `../certification/PRODUCTION_CERTIFICATION_GATE.md`.

## Risk and confidence

Risk is an integer 0–100 and maps to LOW/MEDIUM/HIGH/CRITICAL. Signals include affected domains, migrations/build configuration, deletes/renames, diff breadth/churn and recent failures.

Confidence is 0–1. Uncertainty lowers confidence; uncertainty **increases coverage**. A low-confidence plan escalates rather than skipping more tests.

Recent failures are compacted by Repo Watcher. Repeated WARN/FAIL evidence in an affected domain raises future risk. A false negative discovered by shadow calibration carries an additional historical penalty.

## Lightweight dependency impact

For Dart, AppLab indexes tracked `.dart` files and follows direct `package:` and relative imports from changed files.

For Kotlin/Java, AppLab maps package/class identities and direct imports.

This is intentionally bounded and deterministic. If the graph exceeds its safety budget, confidence drops; AppLab never treats a truncated graph as proof that code is unaffected.

## Targeted static analysis and tests

For high-confidence FAST/STATIC changes:

- Flutter can run `dart analyze` against affected feature/file scopes rather than the whole tree;
- Flutter can run directly affected/matched tests;
- Android can scope compatible Gradle test/lint tasks to affected modules;
- compatible Gradle test/lint/build commands can be combined into one task graph in FAST_RUNTIME.

FULL and CERTIFICATION retain complete project checks.

## Domain-scoped cache fingerprints

The global AppLab contract fingerprint remains the fail-safe fallback.

When a verified result contains a trusted selected-lab plan, AppLab can recompute a fingerprint from:

- core verification contract;
- visual/core runtime contract;
- only the specialist domains that were selected.

Therefore a change to an unrelated specialist lab does not automatically invalidate an already verified SHA, while a change to a selected lab does.

The Trusted Verifier recomputes this fingerprint from its own AppLab checkout and rejects a build contract that does not match.

## AVD and Maestro caches

Maestro remains pinned to 2.10.0 and its installation directory is cached by exact version.

A clean Android AVD cache is generated in a dedicated job **before any target APK is installed**. Verification jobs restore that pristine snapshot. They never save the post-test emulator state, preventing project state from contaminating future runs.

A cache miss falls back to normal fresh AVD creation.

## Shadow FULL calibration

A deterministic 10% of eligible FAST_RUNTIME SHAs is selected for shadow calibration.

For those runs the plan remains FAST, but the runtime executes every specialist lab. `shadow_calibration.py` compares labs FAST would have skipped with the FULL observations:

- skipped lab PASS -> safe skip;
- skipped lab WARN -> warning miss;
- skipped lab FAIL/ERROR -> false negative.

False negatives are recorded in central history and increase future domain risk.

Shadow calibration is only counted if the effective runtime mode remains FAST; a missing-baseline FULL fallback is not mislabeled as a calibration sample.

## Telemetry

Evidence records planner and phase metrics, including:

- preflight/planner duration;
- lane;
- risk score/level;
- confidence;
- changed-file count and churn;
- FULL fallback;
- shadow sample;
- static/test/build phase durations where applicable;
- trusted runtime duration.

Control Center exposes lane/risk/confidence/shadow state. These metrics are the basis for measuring p50/p95 FAST vs FULL performance and false-negative/over-selection behavior rather than claiming an unmeasured speedup.

## Regression corpus

CI exercises both unit self-tests and scenario regressions:

- documentation-only;
- test-only;
- UI;
- network;
- worker/background;
- migration;
- manifest/permissions;
- dependency/build changes;
- baseline from a non-ancestor branch;
- >500 changed files;
- indirect Dart dependency impact;
- historical failures forcing FULL;
- directly changed test targeting;
- rename handling;
- destructive database-file deletion.

Planner errors and unsafe ambiguity must fail safe to increased coverage.

## Release safeguards

FAST:

- cannot certify;
- cannot publish a production release APK;
- does not promote Performance/Upgrade baselines merely because selective runtime passed;
- preserves `SKIPPED != PASS`.

Production Certification remains the only authority for a verified release artifact.
