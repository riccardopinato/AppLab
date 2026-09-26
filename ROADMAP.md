# AppLab Roadmap

Current target: **v0.9.0 — Adaptive Impact Analysis & Incremental Verification**

## v0.9.0 — Release candidate

Implementation complete on `feature/v0.9-adaptive-impact`; release becomes complete only after CI/self-tests and pull-request gates pass.

- [x] Move trusted impact planning before expensive static/build/runtime work.
- [x] Preserve last-verified-SHA range and require baseline ancestry.
- [x] Inspect name-status, renames, numstat, changed hunks and churn.
- [x] Add deterministic Risk + Confidence engine with fail-safe FULL escalation.
- [x] Add NO_RUNTIME_CHANGE / STATIC_ONLY / FAST_RUNTIME / FULL_RUNTIME / CERTIFICATION lanes.
- [x] Add bounded Dart and Kotlin/Java dependency-impact graph.
- [x] Add targeted Flutter analysis/tests.
- [x] Add module-aware Android test/lint planning.
- [x] Add safe single-graph Gradle batching for compatible FAST work.
- [x] Treat >500-file/invalid/ambiguous impact analysis as FULL, not planner failure.
- [x] Feed recent domain failures and shadow false negatives into future risk.
- [x] Add deterministic 10% FAST-vs-FULL shadow calibration.
- [x] Add planner regression corpus for high-risk edge cases.
- [x] Add domain-scoped contract fingerprints with global fail-safe fallback.
- [x] Bind exact preflight plan and selected-domain fingerprint into isolated build contract.
- [x] Recompute adaptive contract identity inside Trusted Verify.
- [x] Add source/static-only explicit result semantics; never claim runtime PASS when runtime was skipped.
- [x] Cache pinned Maestro installation.
- [x] Cache only a pristine pre-app-install AVD snapshot; never persist target-app state.
- [x] Prefer `git ls-files` for project discovery.
- [x] Add phase/planner telemetry.
- [x] Surface lane, risk, confidence and shadow state in Control Center and watcher summaries.
- [x] Keep FAST unable to certify/publish releases and preserve SKIPPED != PASS.
- [x] Keep v0.8.1 release-signing, compatibility-matrix and physical-device BLOCKED semantics.
- [ ] CI green on the complete v0.9 branch.
- [ ] PR merged to `main`.

## Post-v0.9 evidence-driven work

These are intentionally not claimed as complete until v0.9 telemetry provides evidence:

- [ ] Establish p50/p95 FAST vs FULL wall-clock baselines per project/engine.
- [ ] Track planner over-selection rate and shadow false-negative rate over a meaningful sample.
- [ ] Tune risk/confidence thresholds only from recorded calibration evidence.
- [ ] Add a trusted physical Android/ARM64 lane for projects with `requires_real_device=true`.
- [ ] Consider transitive dependency graph expansion only if shadow evidence shows direct-import analysis misses relevant impact.
- [ ] Consider test-coverage mapping only where projects publish trustworthy coverage metadata.

## Invariants

- Build -> isolated artifact contract -> Trusted Verify stays mandatory for runtime verification.
- Uncertainty expands coverage.
- `SKIPPED` never means PASS.
- FAST/FULL never imply CERTIFIED.
- Release publication requires the exact bytes covered by a current production-certification matrix.
- README and this roadmap must be updated with every completed feature/fix/audit/release.
