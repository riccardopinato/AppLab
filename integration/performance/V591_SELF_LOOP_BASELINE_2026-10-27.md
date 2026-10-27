# AppLab v5.9.1 — Self-Loop Performance Baseline

Date: 2026-10-27  
Purpose: immutable before-state for the v6.0G Self-Dogfooding Throughput program.

This record captures the exact-head v5.9E baseline measured before the v6
program. It is a comparison baseline, not a new performance claim.

| Required / important lane | Observed duration |
|---|---:|
| Repository Governance | ~6 s |
| Project Adapter | ~10 s |
| Live Browser E2E | ~11 s |
| v5.9E watchdog validation | ~32 s |
| Runtime Fixture | ~57 s |
| CodeQL | ~1m58 |
| AppLab CI | ~3m32 |
| Autonomous Review | ~9m40 |
| Emulator Self Test | ~11m40 |

The effective merge floor on that exact head was therefore approximately
**11m40** when all lanes were healthy.

## v6.0G target comparison

| Path | Target p95 |
|---|---:|
| docs/config non-runtime | <2 min |
| localized script change | <5–6 min |
| ordinary AppLab FAST | <6 min |
| runtime-sensitive change | <10 min |
| FULL self verification | depth unchanged |

The target is to reduce unnecessary work through path-aware execution,
journey/lab selection, Evidence DAG reuse and safe parallelism. Required
verification authority, exact-artifact identity, physical/store boundaries and
FULL/certification depth are not weakened to meet latency targets.
