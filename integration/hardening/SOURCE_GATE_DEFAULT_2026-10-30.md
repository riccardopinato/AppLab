# AppLab — Source Gate default across the portfolio (30 October 2026)

## Runtime execution policy

**Automatic portfolio surveillance = source-only.** The scheduled hourly watcher,
watchlist-change push and `repository_dispatch: applab-watch` now target
`.github/workflows/source-gate-watcher.yml`. It reads the enabled
`watchlist.json` entries, resolves each exact GitHub SHA and inspects source
structure (Flutter/Gradle). It **does not clone/execute target code**, install
toolchains, build APKs, start an emulator or run Maestro.

This is intentionally a cheap **source-structure gate**, not a replacement for
per-app lint, tests or static analysis. Results are `SOURCE_OK`, `FAIL`,
`BLOCKED` or `NOT_VERIFIED` and include an immutable source identity.
`SOURCE_OK` must **never** be translated to an AppLab trusted-runtime PASS.
The evidence explicitly reports APK not built and runtime/certification not
verified. Unsupported auto-discovery remains `NOT_VERIFIED`.

## Explicit Android verification

The original `.github/workflows/repo-watcher.yml` is manual-only.
To run Android verification across the watchlist or on one app, dispatch
**AppLab Repo Watcher (manual Android verification)** with
`run_android=true` and optionally select `repository=owner/name`.
The unchecked/default state cannot start APK jobs.

The external Flutter/native/universal runners, Maestro, APK signing,
trusted verifier and Production Certification remain available via their
existing explicit workflows and required release paths. Their FAST/FULL
analysis modes are **runtime modes**, not an alias for the source gate.
Source-only evidence cannot satisfy exact-artifact, physical-device, store,
release or certification requirements.

## Boundaries and adoption

App-specific PR checks are repository-owned: this central change does not
silently edit or disable existing app workflows, and those must be audited
individually when their migration is authorized. Anna's Diary commit
`7c0ad8c` already adopts a local source gate. This change prevents
AppLab's **central default watcher** from scheduling APKs for all enabled
applications, including Anna.

Contract regression: `python scripts/workflow_contract_test.py` and
`python scripts/source_gate_watch.py --self-test`.
