# AppLab Roadmap

Current development baseline: **v0.9.0 candidate — Adaptive Impact Analysis & Incremental Verification Engine**.

## v0.9.0 — Adaptive Impact Analysis & Incremental Verification Engine

Status: **IMPLEMENTED ON FEATURE BRANCH — CI/PR gate pending before main merge**.

### Completed implementation

- pre-build Adaptive Impact Engine;
- lanes: NO_RUNTIME_CHANGE, STATIC_ONLY, FAST_RUNTIME, FULL_RUNTIME, CERTIFICATION;
- trusted baseline identity: repository/ref/history key/engine/config fingerprint;
- baseline ancestry verification with fail-safe FULL fallback;
- name-status, numstat, hunk/content and churn-aware Git impact evidence;
- large/unsupported diff escalation to FULL;
- Dart/Kotlin/Java reverse-dependency impact graph;
- risk score, risk level and confidence engine;
- historical lab/pipeline failure risk;
- targeted Flutter analyzer/test execution with conservative fallback;
- impacted-module Android test/lint probing with safe full Gradle fallback;
- single Gradle task graph reuse where compatible;
- source-only verification semantics without fake APK/runtime PASS;
- deterministic shadow FULL sampling and false-negative detection;
- planner regression corpus/self-tests;
- `git ls-files` first auto-discovery;
- clean AVD snapshot cache;
- pinned Maestro cache;
- selected-domain verification fingerprints;
- planner/build/emulator/runtime timing telemetry;
- lane/skip/cache/confidence/shadow telemetry aggregation;
- Control Center adaptive lane/risk/time/shadow exposure;
- v0.8.1 release-integrity/certification safeguards retained.

### Release gate

Before merge to `main`:

1. AppLab CI must pass.
2. Adaptive planner/self-tests must pass.
3. Backend health/frontend build/container checks must pass.
4. Workflow YAML must be accepted by GitHub Actions.
5. Any CI or contract regression is fixed on this branch and rerun.
6. README and this roadmap are updated to the final merged state.

## Completed foundations

- v0.8.1 — Certification Integrity & Release Artifact Hardening.
- v0.8.0 — Production Certification Gate.
- v0.7.10 — Fast Analysis Engine & Smart Test Orchestration.
- v0.7.9 — Storage & Data Integrity Lab.
- v0.7.8 — Background Execution, Doze & Recovery Lab.
- v0.7.7 — Resource Pressure & Process Death Lab.
- v0.7.6 — Configuration & Lifecycle Stress Lab.
- v0.7.5 — Upgrade & Migration Lab.
- v0.7.4 — Persistence & Restart Lab.
- v0.7.3 — Network & Offline Lab.
- v0.7.2 — Performance Lab.
- v0.7.1 — Verified Release Artifact.
- v0.7 — Control Center.
- v0.6.x — System UI, Interaction Crawler, Visual Regression, Multi-Screen Journey and architecture hardening.
- v0.5.x — Watcher, native Android runner and universal auto-discovery.
- v0.4.x — external/reusable project gates.
- v0.3.x — managed emulator/browser E2E runtime.

## Post-v0.9 evidence-driven work

Future tuning is intentionally based on measured v0.9 telemetry rather than arbitrary reductions in coverage. Candidate work is promoted only after observing p50/p95 duration, FAST/FULL shadow divergence, false-negative rate, over-selection, lane distribution and cache effectiveness.
