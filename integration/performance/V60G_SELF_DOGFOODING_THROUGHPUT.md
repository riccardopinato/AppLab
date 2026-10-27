# AppLab v6.0G — Self-Dogfooding Throughput

Status: **IMPLEMENTED CANDIDATE / REAL TIMING EVIDENCE REQUIRED**

## Goal

Reduce AppLab's own commit-to-green critical path without weakening any existing
required check, trusted runtime boundary or certification authority.

The v5.9.1 before-state is recorded in
`integration/performance/V591_SELF_LOOP_BASELINE_2026-10-27.md`.

The two dominant self-costs were:

- Emulator Self Test: roughly 11m40 wall clock;
- True Autonomous Review: roughly 9m40 when fully applicable.

v6.0G attacks both using existing AppLab principles rather than adding a second
execution system.

## 1. Emulator Self Test — fail-closed FAST/FULL profile

`scripts/selftest_runtime_profile_v60g.py` classifies the exact PR diff.

### FULL

FULL remains mandatory when a change can alter runtime/certification semantics,
including:

- `verify_apk.sh`;
- specialist labs;
- visual verification;
- certification/build-contract/trusted-manifest logic;
- project adapter behavior;
- self-test fixture/application;
- Maestro flows;
- Emulator Self Test / runtime fixture workflows.

Unknown `scripts/**` changes also fall back to FULL.

The existing deep path is retained intact:

- Maestro/full runtime;
- system;
- network;
- persistence;
- configuration;
- resource pressure;
- background;
- storage;
- upgrade;
- no-Maestro canary;
- FAST canary;
- certification gate canary.

### FAST

Bounded orchestration/intelligence changes such as v6 A→I can use FAST.

FAST still executes:

- install/launch;
- Maestro primary self-test;
- crash/ANR/log capture;
- visual launch/post-Maestro evidence;
- interaction sentinel;
- verifier result aggregation.

Specialist labs are explicitly selected as SKIPPED/NO_BASELINE by a frozen FAST
analysis plan.

A FAST result is never represented as FULL.

## 2. Autonomous Review — exact-input Evidence DAG

After Evidence Graph construction, four advisory producers are independent:

- graph-aware planner feedback;
- Simulated Human QA;
- Design System & UI Library Advisor;
- Competitive Product Intelligence.

v6.0G executes them concurrently through
`scripts/review_evidence_dag_v60g.py`.

The DAG is:

```
core autonomous review
  -> Evidence Graph
      -> [planner feedback | simulated human | design advisor | competitive]
          -> release assurance
          -> virtual review council
```

The aggregate remains deterministic because each producer writes its own
canonical output files and downstream aggregation still occurs after all four
complete.

## 3. Content-addressed review reuse

The fan-out cache key binds:

- exact target repository;
- exact target SHA;
- exact AppLab workflow SHA;
- Evidence Graph SHA-256;
- analysis-plan SHA-256;
- market-evidence SHA-256 when present;
- producer script hashes;
- max-files execution contract.

A cache hit restores only the four advisory producer outputs.

Changing source, AppLab implementation, trusted planning evidence, market
evidence or producer code invalidates the cache.

Cache reuse cannot mint runtime PASS/CERTIFIED because these four nodes are
advisory-only.

## 4. Required-check contract

The outer GitHub required checks are unchanged.

v6.0G changes work *inside* Emulator Self Test / Autonomous Review; it does not
remove those checks from branch protection.

The review workflow also keeps an explicit producer preflight so historical
contract tests verify that the canonical producer scripts still physically
exist even though execution moved behind a parallel fan-out coordinator.

## 5. Targets

| Path | v6.0G target p95 |
|---|---:|
| docs/config non-runtime | <2 min |
| localized orchestration script | <5–6 min |
| ordinary AppLab FAST | <6 min |
| runtime-sensitive FULL | <10 min where infrastructure permits |
| FULL depth | unchanged |
| certification | no artificial latency target |

The targets are objectives, not PASS criteria. Real exact-head workflow evidence
must be recorded before declaring them achieved.

## 6. Acceptance

- [x] deterministic self-test FAST/FULL planner;
- [x] unknown runtime scripts fail closed to FULL;
- [x] runtime/certification surfaces force FULL;
- [x] FAST preserves launch/Maestro/crash/visual/interaction sentinels;
- [x] FULL path remains present and unchanged in depth;
- [x] content-addressed review DAG;
- [x] exact AppLab SHA included in review cache identity;
- [x] four advisory producers execute in parallel;
- [x] exact-input cache restore/save;
- [x] incomplete cache fails closed;
- [x] historical producer contract remains explicit;
- [x] CI/contract/fingerprint/maintainability integration;
- [ ] exact-head required checks GREEN;
- [ ] first real FAST self-run timing recorded;
- [ ] first real review fan-out/cache evidence recorded.

## Authority

Smart Test Plan remains FAST/FULL authority for target applications.

v6.0G's self-profile governs only AppLab's own Emulator Self Test depth and is
conservative by construction.

Production Certification, physical-device, distribution/store and cross-app
authority remain unchanged.
