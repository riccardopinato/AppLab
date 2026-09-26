# AppLab Roadmap

Current version: **v0.9.0 — Adaptive Impact Analysis & Incremental Verification**

## Completed

- [x] v0.5 Automatic Repo Watcher
- [x] v0.6 Smart Visual QA and Visual Regression
- [x] v0.6.2 Multi-Screen Visual Journey
- [x] v0.6.6 Safe Interaction Crawler
- [x] v0.6.7 Permissions / Notifications / System UI Lab
- [x] v0.7 Control Center
- [x] v0.7.1 Verified Release Artifact
- [x] v0.7.2 Performance Lab
- [x] v0.7.3 Network & Offline Lab
- [x] v0.7.4 Persistence & Restart Lab
- [x] v0.7.5 Upgrade & Migration Lab
- [x] v0.7.6 Configuration & Lifecycle Stress Lab
- [x] v0.7.7 Resource Pressure & Process Death Lab
- [x] v0.7.8 Background Execution / Doze / Recovery Lab
- [x] v0.7.9 Storage & Data Integrity Lab
- [x] v0.7.10 FAST Analysis Engine
- [x] v0.8.0 Production Certification Gate
- [x] v0.8.1 Certification Integrity & Release Artifact Hardening
- [x] v0.9.0 Adaptive Impact Analysis & Incremental Verification

## v0.9.0 delivered

- [x] Early impact planning before static/build/runtime work
- [x] NO_RUNTIME / STATIC_ONLY / FAST_RUNTIME / FULL_RUNTIME / CERTIFICATION lanes
- [x] Baseline ancestor validation
- [x] name-status / rename / numstat / churn-aware diff
- [x] large-diff fail-safe FULL escalation
- [x] content-aware classification
- [x] Dart/Kotlin/Java dependency blast-radius analysis
- [x] risk and confidence engine
- [x] historical watcher failure risk bias
- [x] targeted Flutter analysis/tests with confidence fallback
- [x] combined/scoped native Gradle execution planning
- [x] clean AVD snapshot cache
- [x] pinned Maestro cache
- [x] core + per-domain contract fingerprints
- [x] deterministic 10% shadow FULL sampling
- [x] FAST/FULL false-negative calibration
- [x] adaptive telemetry
- [x] Control Center lane/risk/confidence/shadow evidence
- [x] expanded planner regression corpus
- [x] Git-index-based project auto-discovery
- [x] corrected watcher result artifact discovery
- [x] README and roadmap synchronization

## Next hardening candidates

- [ ] Calibrate risk weights from accumulated shadow evidence rather than changing them manually.
- [ ] Add real-device execution provider for projects that set `requires_real_device=true`.
- [ ] Expand dependency analysis with Gradle module dependency metadata and Dart package graph when the project exposes them.
- [ ] Add wall-clock phase timing to history once enough v0.9 runs exist, then optimize based on measured p50/p95 rather than estimates.
- [ ] Evaluate a third compatibility lane only for projects whose minSdk/targetSdk or hardware profile justify it.

## Non-negotiable invariants

FAST is never certification. SKIPPED is never PASS. Unknown or unsafe analysis escalates to FULL. Release artifacts must remain byte-identical to certified evidence. README and this roadmap must be updated with every completed feature, fix, audit or release.
