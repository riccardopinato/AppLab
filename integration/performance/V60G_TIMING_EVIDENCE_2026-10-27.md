# AppLab v6.0G — Timing Evidence

Status: **COLLECTION ACTIVE / PROMOTION NOT YET PROVEN**

Evidence date: 2026-10-27

## Purpose

This record tracks exact-head, real GitHub Actions observations for the v6.0G
self-dogfooding throughput gate. It does not promote v6.0G by itself.

The immutable before-state remains
`integration/performance/V591_SELF_LOOP_BASELINE_2026-10-27.md`.
The target contract remains
`integration/performance/V60G_SELF_DOGFOODING_THROUGHPUT.md`.

## Admission rules

A timing observation is admitted only when:

- it belongs to the exact PR head being evaluated;
- the relevant workflow completed successfully;
- the changed surface was classified by the corrected v6.0G routing contract;
- the sample is not a cancelled/superseded run;
- runtime-sensitive surfaces are not counted as FAST merely because an older
  planner version misclassified them;
- the observed timing is recorded as evidence, never converted into PASS by
  this report.

Runs that predate a routing correction remain historical diagnostics but are
excluded from the promoted p95 population when the old routing was wrong.

## Immutable pre-v6 baseline

v5.9.1 recorded an effective self-loop merge floor of approximately **11m40s**.
That figure is the comparison baseline, not a v6 sample.

## Ordinary AppLab FAST — admitted observations

| Exact head | Surface | Emulator Self Test |
|---|---|---:|
| `cb5f92d2f0c9b8f328e4061957121eae57b7b7e1` | v6.0F bounded orchestration | 4m54s |
| `ddf514fec43c30406e57e6478570853276c8377d` | v6.0F bounded orchestration | 4m23s |
| `6c5d5f2cac401b9bc9aab380cdcfa822e142da7d` | early clean v6.0I without runtime transport surfaces | 5m49s |
| `3a54550660161a54a01e99d7a40b18c7ccecbc6e` | early clean v6.0I without runtime transport surfaces | 6m00s |

Current admitted sample size: **n=4**.

The strict target is **p95 <6m**. This population is too small for a robust
promotion claim, and its observed maximum is exactly 6m rather than below 6m.
Therefore the ordinary FAST timing gate remains **OPEN**.

## Runtime-sensitive / FULL observations

| Exact head | Reason | Emulator Self Test |
|---|---|---:|
| `566655d9e5ae0a04ff6c7ebaade53287182649be` | execution-acceleration surface; explicit FULL | 9m29s |
| `fa7b6bf59d606254c7b4a2fce52303e28c97bcf7` | runtime transport surfaces after fail-closed routing correction | 10m43s |
| `d235bd00270853967663ff16e2971dfb238423cf` | runtime transport surfaces after fail-closed routing correction | 10m11s |

The runtime-sensitive target is **p95 <10m where safely attainable**, while FULL
depth remains unchanged. These observations show the target is not yet proven.
The v6.0G critical-path remediation in PR #188 removes runner/scope
serialization only; it does not remove or weaken FULL verification.

## Docs/config non-runtime observation before remediation

PR #186 exact head
`f8d62091dfac7bc504d62b463cfbc948b0a8a561` was a documentation-only truth
refresh. Its AppLab CI run took approximately **2m50s**, above the **<2m** target.

Inspection showed that the old CI path still ran PostgreSQL smoke, frontend
build and backend/frontend container work even though only Markdown changed.

PR #187 addresses that measured gap with a fail-closed docs-only CI path.
Post-remediation exact-head samples are required before the target can be
promoted.

## Explicitly excluded FAST samples

The following successful v6.0I runs are **not** admitted into the FAST timing
population:

- `fc0db12aa85f721e5ffb86366251e98b23749672`;
- `b74b6d9640d463c699af36eaad12b13269a18da1`;
- `3d49b7e1c784c2688d42fe41591bad8c3b4e4115`.

Their diffs included WebRTC/runtime transport surfaces that were later
recognized as requiring FULL. Counting those timings as FAST would preserve a
known routing error in the performance evidence.

Cancelled and superseded workflow runs are also excluded.

## Localized script target

The target remains **p95 <5–6m**. The current real-history set does not yet
contain a sufficiently isolated, correctly classified population to make a
defensible p95 claim. No synthetic code change is created solely to manufacture
samples.

## Promotion state

| Path | Target | Current evidence state |
|---|---:|---|
| docs/config non-runtime | p95 <2m | **OPEN** — pre-remediation sample 2m50s; PR #187 remediation pending |
| localized script | p95 <5–6m | **OPEN** — insufficient isolated population |
| ordinary AppLab FAST | p95 <6m | **OPEN** — n=4; insufficient and one sample at exactly 6m |
| runtime-sensitive | p95 <10m where safely attainable | **OPEN** — corrected-routing observations include 10m11s and 10m43s |
| FULL/certification | depth unchanged | **PRESERVED** — no timing optimization may reduce authority/depth |

v6.0G remains **TIMING PROMOTION OPEN** until real post-remediation observations
support the stated targets without weakening verification.
