# AppLab Roadmap

Current production baseline: **v0.9.0 — Adaptive Impact Analysis & Incremental Verification Engine**

## Product rule

AppLab optimizes for the shortest verification path that preserves trustworthy
evidence. Reduced work is allowed only when impact evidence is sufficiently
strong. Missing, contradictory, oversized or low-confidence evidence must
increase coverage and may never silently become PASS.

The security boundary remains:

```
Target source -> Build job -> isolated APK contract -> Trusted verifier
```

FAST/FULL results are not production certification. Only CERTIFICATION can
publish a certified release artifact.

## Completed

### v0.9.0 — Adaptive Impact Analysis & Incremental Verification

- [x] Move impact planning before expensive analyze/test/build/runtime work.
- [x] Add five lanes: NO_RUNTIME_CHANGE, STATIC_ONLY, FAST_RUNTIME,
  FULL_RUNTIME and CERTIFICATION.
- [x] Analyze trusted `baseline..HEAD` using name-status, rename/delete
  information, numstat churn and bounded changed-hunk evidence.
- [x] Validate baseline SHA existence and ancestry; progressively deepen shallow
  clones and fall back to FULL if ancestry still cannot be proven.
- [x] Scope watcher baselines by repository + history key + ref.
- [x] Convert oversized diffs and planner uncertainty into FULL rather than a
  planner failure.
- [x] Add deterministic risk score and confidence calculation.
- [x] Add bounded reverse-import dependency impact analysis for Dart/Kotlin/Java.
- [x] Add historical specialist-lab failure risk from central watcher history,
  scoped by repository + history key + source ref.
- [x] Add targeted Flutter analyze/test execution with conservative fallback.
- [x] Add native Gradle task consolidation and safe single-module targeting.
- [x] Preserve core launch/crash/visual/interaction checks for runtime lanes.
- [x] Add deterministic shadow FULL calibration while retaining the original
  FAST prediction.
- [x] Record shadow divergence and potential false-negative labs.
- [x] Add planner regression corpus/self-tests for docs, static-only, database,
  oversized diff, dependency impact, missing baseline and non-ancestor baseline.
- [x] Add clean AVD cache preparation isolated from target app state.
- [x] Add pinned Maestro cache.
- [x] Add per-domain verification fingerprints.
- [x] Cache successful NO_RUNTIME_CHANGE/STATIC_ONLY resolved SHAs so unchanged
  analysis-only commits are not rescheduled by the hourly watcher.
- [x] Add adaptive metrics: planner latency, changed/impacted files, selected
  labs, quality/runtime timings, AVD/Maestro cache hits and shadow divergence.
- [x] Aggregate p50/p95 planner, quality, runtime and observed pipeline latency
  from central history and expose them in Control Center.
- [x] Surface lane/risk/confidence in watcher history and Control Center.
- [x] Prefer `git ls-files` for project auto-discovery.
- [x] Keep Universal Runner discovery checkout separate from target build
  checkout intentionally: merging them would couple auto-discovery and build
  trust boundaries for a small network-only saving.
- [x] Update backend/frontend/runtime identity to v0.9.0.
- [x] Update README and canonical ROADMAP.

### v0.8.1 — Certification Integrity & Release Artifact Hardening

- [x] Last verified SHA range planning.
- [x] Release build identity/signing validation.
- [x] Primary + compatibility production certification lanes.
- [x] Byte-identical certified release publication.
- [x] Current versus stale certification state.
- [x] Real-device-required projects remain BLOCKED when hosted CI cannot provide
  trusted physical-device evidence.

### v0.8.0 — Production Certification Gate

- [x] Explicit CERTIFICATION mode.
- [x] Evidence bundle and APK identity integrity.
- [x] Release publication restricted to certified evidence.

### v0.7.x — Runtime specialist labs and FAST foundation

- [x] Performance.
- [x] Network/offline.
- [x] Persistence/restart.
- [x] Upgrade/migration.
- [x] Configuration/lifecycle stress.
- [x] Resource pressure/process death.
- [x] Background/Doze/recovery.
- [x] Storage/data integrity.
- [x] FAST/FULL smart specialist-lab orchestration.

### v0.6.x and earlier — Trusted Android verification platform

- [x] Smart Visual QA and visual regression.
- [x] Multi-screen visual journeys.
- [x] Safe interaction crawler.
- [x] Permissions/notifications/system UI lab.
- [x] Build -> Artifact -> Trusted Verify isolation.
- [x] Universal Flutter/native Android project runners.
- [x] Repo Watcher and Control Center.
- [x] Browser-controlled live emulator stack.

## v0.9 evidence contract

Every adaptive plan records:

- requested and effective mode;
- execution lane;
- baseline and target SHA;
- diff trust state;
- file status, additions and deletions;
- dependency-impacted files;
- selected specialist labs and reasons;
- risk score and confidence;
- targeted source/test/module scope;
- FULL fallback reason;
- shadow FULL decision.

A reduced lane is never represented as a fake runtime PASS. NO_RUNTIME_CHANGE
and STATIC_ONLY explicitly record `runtime_executed=false` and the SHA whose
trusted runtime evidence is being reused.

## Current hardening limits

These are explicit engineering boundaries, not hidden assumptions:

1. The dependency graph is a bounded static import heuristic, not compiler-level
   whole-program analysis. Ambiguity lowers confidence or broadens coverage.
2. Historical risk is available when central watcher history is restored;
   standalone manual runs remain valid without it and simply omit that boost.
3. A new AVD cache key has one cold creation run before later jobs benefit from
   reuse.
4. Universal auto-discovery still performs a lightweight source checkout before
   the build runner performs its own checkout. This duplication is retained to
   preserve reusable-job boundaries and source/build isolation.
5. Physical-hardware-only behavior is not inferred from emulator evidence.
   Projects declaring `requires_real_device=true` remain BLOCKED for production
   certification until trusted device evidence exists.

## Next validation targets

- Accumulate enough real watcher samples for statistically meaningful p50/p95.
- Measure shadow false-negative and over-selection rates over a meaningful sample.
- Tune risk thresholds only from measured calibration evidence.
- Expand dependency adapters when real projects demonstrate a repeatable blind
  spot; do not add speculative complexity.
- Evaluate trusted physical ARM64/device lanes independently from emulator FAST
  optimization.
