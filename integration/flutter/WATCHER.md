# AppLab Portfolio Watchers — source first

## Automatic lane (default, all enabled watchlist entries)

`.github/workflows/source-gate-watcher.yml` runs hourly at minute 17,
on relevant AppLab pushes and on `repository_dispatch: applab-watch`.
It resolves an immutable GitHub commit/tree SHA for each enabled
`watchlist.json` entry and performs **source-structure** checks without
cloning or executing the app, installing Flutter/Gradle, compiling an APK,
starting an emulator or running Maestro.

The output `SOURCE_OK` is limited to file/entrypoint structure. It is **not**
lint/test/CI GREEN, a trusted APK/runtime PASS, a physical-device verification,
or a release/certification verdict. `FAIL` and `BLOCKED` fail the automatic
lane. Unsupported discovered projects are `NOT_VERIFIED` and remain visible.

## Runtime lane (explicit only)

`.github/workflows/repo-watcher.yml` accepts only manual
`workflow_dispatch` with `run_android=true` (default: false). It still
uses `scripts/watch_discover.py` for exact SHA/history/cache planning,
the Flutter/native/universal runners for Android artifacts and
`scripts/watch_aggregate.py` for trusted runtime history. `force=true`
can rerun existing SHA, and `repository=owner/name` limits the run.

FAST/FULL runtime selection, artifact identity, Maestro, physical tests and
Production Certification retain their original independent requirements.
Source checks are never an authority for runtime-cache promotion.

## Inventory and specific app workflows

The central watchlist covers multiple Flutter and native Android repositories,
including Anna's Diary, TrailPath, Battery Guard, Notes-Ecosistema,
CamperBoss and Send-to-pc. Disabled entries remain disabled.

This does **not** rewrite any application's own GitHub workflows. Local
PR source checks and manual Android build triggers remain the responsibility
of the app repository. See
`integration/hardening/SOURCE_GATE_DEFAULT_2026-10-30.md`.

## Key files

- `watchlist.json` — enabled inventory and runtime profiles.
- `scripts/source_gate_watch.py` — read-only source structure inspection.
- `.github/workflows/source-gate-watcher.yml` — automatic default.
- `.github/workflows/repo-watcher.yml` — manual Android runtime.
- `scripts/watch_discover.py` — runtime SHA/cache discovery.
- `scripts/watch_aggregate.py` — runtime history/evidence.
