# AppLab v6.0G — Self-Dogfooding Throughput

Status: **IMPLEMENTED CANDIDATE / FULL EXACT-HEAD VALIDATION REQUIRED**

Baseline: `integration/performance/V591_SELF_LOOP_BASELINE_2026-10-27.md`.

## Emulator Self Test

The required workflow now plans its own scope before starting Android:

- `NO_ANDROID_RUNTIME` for explicitly known orchestration/governance scripts and changes with no Android-runtime impact;
- `FAST_RUNTIME` for a bounded specialist-lab or core visual/journey change;
- `FULL_RUNTIME` for the trusted verifier core, Smart Test Plan, journey execution/sharding, certification/build-contract code, fixture/selftest code, the Emulator Self Test workflow itself, and any unknown `scripts/*` path.

Unknown runtime-relevant scripts fail safe to FULL. FAST still executes the trusted core launch/visual path and only selected specialist labs. Push/manual runs remain FULL.

## Internal journey catalog

`runtime-core`, `maestro-core`, `system`, `performance`, `network`, `persistence`, `configuration`, `resource-pressure`, `background`, `storage`, `upgrade`, `certification-contract`.

## Autonomous Review Evidence DAG

Advisory producers are wrapped in an exact-input content-addressed cache. A node fingerprint includes all current evidence inputs except its own outputs, trusted-runtime evidence bytes and exact target-tree bytes. A cache hit is accepted only when node/fingerprint/output hashes all match. Any input-byte change invalidates reuse. Cross-input/semantic reuse remains disabled.

Cached nodes: experiment planner, analyst, simulated-human QA, design advisor, competitive intelligence, evidence graph, planner feedback, release assurance and review council.

## Authority

This step changes self-execution scope only. It does not change downstream Smart Test Plan authority, Production Certification, physical/store/cross-app boundaries or exact-artifact identity. `NO_ANDROID_RUNTIME` is not represented as runtime PASS.

## Targets

- docs/config non-runtime: <2 min p95;
- localized script: <5–6 min p95;
- ordinary AppLab FAST: <6 min p95;
- runtime-sensitive change: <10 min p95;
- FULL depth: unchanged.

These are targets, not claims until measured post-merge evidence exists.

## Acceptance

- [x] path-aware self planner;
- [x] explicit internal journey catalog;
- [x] unknown-script FULL fallback;
- [x] push/manual FULL;
- [x] FAST result-plan validation;
- [x] self workflow remains FULL on its own change;
- [x] content-addressed Evidence DAG cache;
- [x] exact-output hash validation;
- [x] cross-input reuse disabled;
- [x] longitudinal cache persistence;
- [x] CI/self-test wiring;
- [ ] exact-head FULL required checks GREEN;
- [ ] post-merge p50/p95 evidence against v5.9.1 baseline.
