# AppLab v6.0G — Promotion Evidence

Date: 2026-10-27  
Status: **PROMOTION EVIDENCE SATISFIED FOR ORDINARY APPLAB FAST**

Factory baseline: `App-Factory-Core@7b84e33df715cf2a48bda7c7495d0690819bff0f` (Master 26.6 / Golden Index 23).  
Immutable comparison baseline: `integration/performance/V591_SELF_LOOP_BASELINE_2026-10-27.md`.

## Scope of this promotion

v6.0G is promoted on the criterion stated in its design: ordinary orchestration/script
changes must show materially improved exact-head latency while FULL depth and
verification authority remain unchanged.

This evidence does **not** claim that every throughput target in the tracking table
has already accumulated sufficient samples. In particular, docs-only <2 min,
runtime-sensitive <10 min and downstream UI FAST remain monitoring targets rather
than inferred achievements.

## Measurement method

- Timing comes from GitHub Actions job-log timestamps for completed exact-head jobs.
- The FAST p95 calculation uses only successful `Emulator Self Test / android-runtime`
  executions whose own logs identify the v6.0G profile as `FAST`.
- Whole-head merge-floor checks use the slowest relevant required job on fully green
  exact heads.
- A head with an unrelated Browser E2E failure is retained only as a FAST runtime
  timing sample and is excluded from whole-head merge-floor claims.
- These are observed engineering samples, not a population SLA.

## Exact-head FAST samples

| Exact head | Job | Result | Observed wall clock |
|---|---:|---|---:|
| `cb5f92d2f0c9b8f328e4061957121eae57b7b7e1` | Emulator Self Test job `122116263325` | PASS / FAST | 205.169 s |
| `ddf514fec43c30406e57e6478570853276c8377d` | Emulator Self Test job `122118250227` | PASS / FAST | 249.054 s |
| `6c5d5f2cac401b9bc9aab380cdcfa822e142da7d` | Emulator Self Test job `122136034562` | PASS / FAST | 248.489 s |

Observed p95 across these three FAST runtime samples:

**248.998 s ≈ 4m09s**, below the v6.0G ordinary AppLab FAST target of **<6 min**.

The immutable v5.9.1 baseline recorded Emulator Self Test at approximately
**11m40s**. The slower promoted FAST observation is therefore roughly 64% below
that historical runtime baseline while preserving the same trusted verifier
authority.

## Fully green exact-head merge-floor checks

### `cb5f92d2f0c9b8f328e4061957121eae57b7b7e1`

| Required lane / job | Observed wall clock |
|---|---:|
| Emulator Self Test | 205.169 s |
| AppLab CI static | 163.682 s |
| CodeQL JavaScript/TypeScript | 65.051 s |
| CodeQL Python | 64.884 s |
| Runtime Fixture | 41.705 s |
| AppLab CI security | 19.867 s |
| Autonomous Review required-check scope | 1.945 s |

Observed required-lane floor: **205.169 s ≈ 3m25s**.

### `ddf514fec43c30406e57e6478570853276c8377d`

| Required lane / job | Observed wall clock |
|---|---:|
| Emulator Self Test | 249.054 s |
| AppLab CI static | 171.817 s |
| CodeQL Python | 59.720 s |
| CodeQL JavaScript/TypeScript | 58.020 s |
| Runtime Fixture | 35.219 s |
| AppLab CI security | 17.681 s |
| Autonomous Review required-check scope | 3.204 s |

Observed required-lane floor: **249.054 s ≈ 4m09s**.

Both fully green exact heads are below the ordinary FAST target of 6 minutes.
The older v5.9.1 effective merge floor was approximately **11m40s**.

## FULL-depth preservation

Throughput promotion does not replace or weaken FULL verification.

Evidence after the FAST samples includes:

- PR #185 runtime-sensitive WebRTC/runtime changes were forced through
  `FULL / RUNTIME_OR_CERTIFICATION_SURFACE_CHANGED` and ultimately reached
  GREEN 8/8 before merge.
- PR #188 preserved the required `android-runtime` check while removing the
  serial scope-job barrier; exact-head required checks were GREEN before merge.
- PR #187, rebased onto the post-#188 `main`, ran the new fail-closed CI scope
  changes through the full gate matrix and reached GREEN 8/8 at
  `99e27ceb1f14c36f09386b97af5fc5ee94af6aba` before merge.
- Unknown/runtime-critical surfaces remain fail-closed to FULL.
- `verify_apk.sh`, Smart Test Plan, trusted evidence and Production Certification
  authorities remain unchanged.

## Promotion decision

**PROMOTE v6.0G ordinary AppLab FAST throughput.**

Reason:

1. exact-head FAST samples are real and successful;
2. observed FAST p95 is below the <6 min target;
3. fully green exact heads show the required-lane merge floor below 6 min;
4. the result materially improves the immutable v5.9.1 baseline;
5. FULL depth and certification authority remain unchanged.

Not promoted by this decision:

- docs/config non-runtime p95 <2 min;
- runtime-sensitive p95 <10 min as a generalized SLA;
- downstream UI FAST 5–10 min;
- certification latency targets.

Those remain evidence-collection targets and cannot be inferred from the samples above.
