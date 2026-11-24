# Lean Engineering — AppLab advisory metrics

**Status:** opt-in pilot, read-only, not a new certification gate.
**Factory policy:** `App-Factory-Core/docs/process/LEAN_ENGINEERING_v1.md`.

## Run

From the AppLab checkout, with both refs locally available:

```bash
python3 scripts/lean_pr_report.py --base <base-sha> --head <head-sha> --output lean-report.json
python3 -m unittest discover -s tests -p 'test_lean_pr_report.py'
```

The report summarizes deterministic Git diff data only: changed files,
added/deleted lines excluding obvious generated or lock files, binary count,
test paths touched and dependency manifest paths touched. It does **not**
claim code reuse, reduction of technical debt, test success, coverage, release
readiness, performance, tokens, elapsed time or development costs.

For each selected pilot PR, a reviewer separately records:
- approved product requirement and exact base/head SHA;
- actual reused app components / Golden / Donors with source evidence;
- whether new dependencies and abstractions were necessary;
- exact trusted CI/AppLab checks and regression outcomes;
- missing device/store tests and limitations.

Compare two similarly scoped tasks or before/after implementations only if
the baseline and measurement conditions are sufficiently comparable.
Churn is not a target to minimize blindly. Never block a PR solely for these
advisory figures, and never infer performance from shorter code.

This script does not access paid providers, private user data, telemetry,
tokens, or app databases. It is not wired to automatic CI; adoption requires
an explicit review after pilots.
