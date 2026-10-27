# AppLab v6.0G — Self-Dogfooding Throughput

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD TIMING EVIDENCE REQUIRED**

## Goal

Reduce AppLab's own commit-to-green latency without weakening FULL depth,
trusted-runtime authority, exact-source identity or certification.

v6.0G applies the same principles already used for downstream projects to
AppLab itself:

- path/risk-aware self-test selection;
- bounded FAST runtime smoke for orchestration-only changes;
- targeted specialist-lab execution;
- FULL fallback for unknown or verifier-critical surfaces;
- content-addressed advisory-review fan-out;
- safe exact-input cache reuse;
- dependency-aware parallel execution.

## Emulator Self Test

The required check remains one umbrella check, but its internal runtime depth is
planned deterministically.

Profiles:

- **FULL** — historical self-test depth remains unchanged;
- **FAST** — launch + Maestro + interaction + crash/visual sentinels, plus only
  the specialist labs selected by the v6.0G self-test planner.

FULL is mandatory when the diff touches:

- the self-test/runtime-fixture workflows;
- `verify_apk.sh`;
- build-contract or trusted-manifest boundaries;
- project auto-discovery/adapter semantics;
- the self-test fixture or Maestro flow;
- certification-gate semantics;
- any unclassified script surface.

Specialist producer changes are mapped to independent units:

- lifecycle/system;
- performance;
- network;
- persistence;
- configuration;
- resource-pressure;
- background;
- storage;
- upgrade.

Orchestration-only v6 scripts use the bounded FAST core path. Unknown
`scripts/**` changes fail closed to FULL.

The planner never emits PASS. It only selects runtime work; `verify_apk.sh`
remains the runtime authority.

## Autonomous Review Evidence DAG

After the authoritative Evidence Graph is built, independent advisory producers
are executed as a dependency-aware DAG.

Wave 1 may run in parallel:

- planner feedback;
- simulated-human QA;
- competitive intelligence.

Wave 2 waits for simulated-human output:

- design-system advisor.

This ordering is required because the design advisor reads
`simulated-human-qa.json`; running those two nodes concurrently would make the
result race-dependent.

The downstream release-assurance and virtual-review-council stages remain after
the fan-out.

## Content-addressed cache

The review fan-out cache key binds:

- target repository;
- exact target SHA;
- exact AppLab workflow SHA;
- Evidence Graph SHA-256;
- analysis-plan SHA-256;
- market-evidence SHA-256 when present;
- max-files policy;
- hashes of every fan-out producer script.

Cache restore is accepted only when the exact key matches and every declared
output exists. A producer/input change invalidates the fan-out cache.

The cache contains advisory evidence only and cannot mint PASS or CERTIFIED.

## Safety invariants

- FULL/CERTIFICATION depth is not reduced by missing or unknown planning data.
- Unknown script surfaces select FULL.
- Required-check names remain stable.
- Runtime PASS still comes only from existing trusted verification.
- Review cache reuse is exact-input only.
- Review fan-out is advisory and cannot change release/certification authority.
- No new merge or release authority is introduced.

## Validation

Contract coverage proves:

- FULL fallback for verifier/self-test/unknown script surfaces;
- bounded FAST for orchestration-only changes;
- targeted specialist-lab selection;
- FULL dominance when mixed with a critical surface;
- deterministic Evidence DAG fingerprints;
- AppLab-SHA invalidation;
- Evidence Graph invalidation;
- complete-cache restore requirement;
- dependency-safe review waves.

## Promotion evidence still required

Implementation completion does not by itself claim the throughput target.

Before v6.0G is marked production-complete, exact-head observations must show
that ordinary orchestration/script PRs materially improve from the immutable
v5.9.1 baseline in
`integration/performance/V591_SELF_LOOP_BASELINE_2026-10-27.md`.

Targets remain:

- docs/config non-runtime: p95 < 2 min;
- localized script change: p95 < 5–6 min;
- ordinary AppLab FAST: p95 < 6 min;
- runtime-sensitive change: p95 < 10 min where safely attainable;
- FULL/certification: evidence depth over artificial latency.
