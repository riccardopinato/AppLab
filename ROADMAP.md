# AppLab Roadmap

Current version: **v0.9.0 — Adaptive Impact Analysis & Incremental Verification**

This file is the canonical forward roadmap. Completed release history remains in `README.md`.

## Completed — v0.9.0

- [x] Pre-build Adaptive Impact Engine.
- [x] Trusted baseline identity bound to repository/ref/history key/engine/configuration.
- [x] Baseline ancestry validation with fail-safe FULL fallback.
- [x] Full verified-SHA → current-SHA diff analysis across intermediate commits.
- [x] Name-status, rename/delete, line-churn and bounded patch evidence.
- [x] Content-aware capability detection.
- [x] Bounded Dart/Kotlin/Java dependency impact graph with transitive propagation.
- [x] Deterministic risk and confidence engine.
- [x] `NO_RUNTIME_CHANGE`, `STATIC_ONLY`, `FAST_RUNTIME`, `FULL_RUNTIME`, `CERTIFICATION` lanes.
- [x] Oversized/ambiguous/low-confidence/high-risk changes escalate to FULL.
- [x] Flutter targeted analysis/test execution with conservative complete-suite fallback.
- [x] Native Android unified Gradle task graph and module targeting with safe fallback.
- [x] Exact preflight source snapshot reuse instead of repeated target checkout.
- [x] Universal Runner reuse of auto-discovery plan/source snapshot.
- [x] Build contract binding of lane/risk/confidence/shadow evidence.
- [x] Clean AVD snapshot cache with no target-state persistence.
- [x] Pinned Maestro cache.
- [x] Deterministic FAST shadow FULL sampling and false-negative calibration.
- [x] Historical failure risk broadening.
- [x] Domain-aware verification contract fingerprints.
- [x] Planner regression corpus.
- [x] Planner/preflight/build/runtime timing telemetry.
- [x] p50/p95 adaptive metrics and Control Center exposure.
- [x] `git ls-files` based auto-discovery with filesystem fallback.
- [x] v0.8.1 certification/release safety invariants preserved.
- [x] README, engine documentation and roadmap aligned with the implementation.

## Validation gates for v0.9.0

Before merge/release:

- [ ] AppLab CI.
- [ ] Emulator Self Test.
- [ ] Live Emulator Browser E2E.
- [ ] Workflow syntax and self-tests after final version/documentation commit.
- [ ] Verify FAST shadow evidence can be aggregated without converting `SKIPPED` to PASS.
- [ ] Verify production certification still requires complete release evidence.

The unchecked items are release-validation gates, not missing v0.9 implementation features. They are checked only from real CI/runtime evidence.

## Next — v0.9.x hardening

These items are deliberately post-v0.9 telemetry-driven rather than speculative feature work:

- [ ] Tune risk weights only after enough shadow FULL samples exist.
- [ ] Tune targeted-test thresholds from measured false-negative/over-selection rates.
- [ ] Add more language/framework dependency adapters only where real monitored repositories require them.
- [ ] Evaluate physical-device/ARM64 trusted execution when infrastructure is available.
- [ ] Expand emulator/device matrices only where failure history proves value.
- [ ] Add long-window trend visualization for verification cost and planner calibration.

## Release rule

No roadmap item may weaken these invariants:

1. uncertainty increases coverage;
2. `SKIPPED` is never PASS;
3. FAST is never CERTIFIED;
4. production release bytes must be the exact bytes covered by certification evidence;
5. real-device requirements cannot be satisfied by emulator evidence;
6. baseline/cache reuse must remain identity- and contract-bound.
