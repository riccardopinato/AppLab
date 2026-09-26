# AppLab Roadmap

Current version: **v0.9.0**

## Completed

### v0.9.0 — Adaptive Impact Analysis & Incremental Verification

- [x] Impact analysis moved before expensive build/static/runtime work.
- [x] Trusted baseline ancestry validation.
- [x] Multi-commit diff with status, rename/delete and churn evidence.
- [x] Risk + confidence engine.
- [x] Verification lanes: NO_RUNTIME_CHANGE, STATIC_ONLY, FAST_RUNTIME, FULL_RUNTIME, CERTIFICATION.
- [x] Safe FULL fallback for missing/untrusted baseline, low confidence, high risk and >500 changed files.
- [x] Targeted Flutter analysis/tests with full fallback.
- [x] Native Gradle unified task graph and module targeting when safe.
- [x] Historical failure risk signal scoped to repository/ref/history identity.
- [x] Deterministic FAST -> FULL shadow calibration.
- [x] False-negative detection against FULL shadow results.
- [x] Maestro cache.
- [x] Clean AVD/snapshot cache with no candidate-state persistence.
- [x] Domain-scoped contract fingerprints.
- [x] Explicit non-runtime result contract; runtime labs remain SKIPPED.
- [x] Cache already-verified non-runtime commits.
- [x] Git tracked-file auto-discovery fast path.
- [x] Planner regression corpus.
- [x] Planner telemetry.
- [x] Control Center lane/risk/confidence visibility.
- [x] README / roadmap / technical documentation updated.

### v0.8.1 — Certification Integrity & Release Artifact Hardening

- [x] Release-only certification identity/signing hardening.
- [x] FAST range based on last verified SHA.
- [x] Multi-lane production certification.
- [x] Exact certified APK/evidence binding.
- [x] Current vs stale certification state.

### v0.8.0 — Production Certification Gate

- [x] Dedicated certification mode and evidence bundle.
- [x] Production release publication only from certified bytes.

### v0.7.10 and earlier

- [x] FAST/FULL smart specialist selection.
- [x] Storage, background, resource-pressure, lifecycle, persistence, upgrade, network and performance labs.
- [x] Safe interaction crawler and visual-regression journey.
- [x] Universal Flutter/native project runner.
- [x] Repo Watcher and Control Center.

## Next hardening candidates

These are not required to call v0.9 complete; they are future extensions:

- [ ] Expand dependency graph from import/module heuristics to compiler/build-system symbol graph where supported.
- [ ] Add physical-device farm lanes for projects that require hardware evidence.
- [ ] Persist long-term p50/p95 phase-duration analytics beyond the current run/history window.
- [ ] Tune risk weights using accumulated shadow-calibration evidence once enough samples exist.
