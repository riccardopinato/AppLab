# AppLab v5.3.5 — Multi-Project Calibration & Delta Readiness

## Purpose

v5.3.5 measures whether AppLab has enough real, diverse evidence to consider a
future controlled delta-execution experiment. It does **not** reduce verification
coverage.

The release reuses existing central watcher history, deterministic shadow FULL
runs and shadow-calibration records instead of inventing a second execution
planner.

## Inputs

Only observed central-history rows with a valid shadow FULL calibration are
eligible. The engine records:

- repository diversity;
- shadow FULL sample volume;
- change-category diversity;
- false negatives and missed warnings;
- missing baselines and over-selection;
- per-lab outcomes for work that FAST predicted could be skipped.

A normal FAST prediction alone is never evidence that a skipped lab was safe.
The corresponding FULL execution must have actually observed the lab.

## Readiness states

- `COLLECTING`: evidence volume or diversity is insufficient.
- `UNSAFE`: at least one predicted skip hid a WARN, FAIL or ERROR.
- `READY_FOR_EXPERIMENT`: minimum diversity/sample gates are met with no
  observed false negative or missed warning.

`READY_FOR_EXPERIMENT` is intentionally weaker than permission to reduce
coverage. It only means that a later release may design a bounded experiment.

## Initial thresholds

- at least 4 repositories with at least 3 shadow samples each;
- at least 20 total shadow FULL samples;
- at least 3 observed non-unknown change categories;
- per-lab candidate evidence requires at least 8 safe skip observations across
  at least 3 repositories.

These thresholds are calibration policy, not release/certification criteria.

## Guardrails

The emitted `delta-calibration.json` declares:

- `advisory_only = true`;
- `coverage_reduction_enabled = false`;
- Smart Test Plan remains the sole FAST/FULL selection authority;
- FAST/FULL/CERTIFICATION authority is unchanged;
- shadow FULL evidence remains mandatory for calibration;
- READY_FOR_EXPERIMENT is not permission to reduce coverage.

The v5.3.5 engine is not imported by `smart_test_plan.py`.

## Outputs and visibility

Repo Watcher and Production Certification regenerate from the cumulative central
history:

- `.applab-history/delta-calibration.json`;
- `.applab-history/delta-calibration.md`.

Control Center independently projects the same deterministic report so current
readiness, qualified project count, shadow sample volume and the hard-disabled
coverage-reduction state are visible.

## Next boundary

A later release may propose controlled coverage-reduction experiments only after
real App Factory history reaches READY_FOR_EXPERIMENT. Any such release requires
its own explicit policy, independent contract tests and fail-closed rollback
criteria. v5.3.5 itself changes no selected lab, build, runtime or certification
decision.
