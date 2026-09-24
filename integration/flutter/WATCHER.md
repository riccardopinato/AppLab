# AppLab v0.5 Repo Watcher

The watcher centralizes automatic APK verification for configured public Flutter
repositories.

## How it works

1. `AppLab Repo Watcher` runs hourly at minute 17.
2. `scripts/watch_discover.py` resolves the current commit for every enabled
   watchlist entry.
3. AppLab checks its own Actions cache for
   `applab-v0.5-<watch-key>-<sha>`.
4. Only uncached commits enter the verification matrix.
5. Each changed repository is tested through the existing External Project
   Runner.
6. PASS and FAIL commits are both cached as checked, so an unchanged broken
   commit does not consume another emulator run every hour.
7. `watch_aggregate.py` appends the run to a cumulative `history.jsonl`
   stored in a rolling GitHub Actions cache and uploads a 90-day history
   artifact.

A manual watcher run can set `force=true` to retry the same SHA. It can also
limit execution to one configured `owner/name`.

The workflow accepts `repository_dispatch` type `applab-watch` as an
immediate trigger for a future cross-repository signal integration. The hourly
poll remains the credential-free fallback.

## Initial watchlist

v0.5 enables:

- `riccardopinato/TrailPath`
- `riccardopinato/Battery_Guard`
- `riccardopinato/Notes-Ecosistema` (Flutter project in `flutter_app/`)

Each profile reproduces the target repository's required build preparation.

`Agenda-per-Anna` is intentionally not enabled yet because its current Android
pipeline performs app-specific Firebase/native/release preparation.
`Send-to-pc` is a native Gradle Android project rather than Flutter and will
use the native project runner instead of being forced through the Flutter gate.

## Files

- `watchlist.json`: central repository configuration.
- `.github/workflows/repo-watcher.yml`: scheduled/dispatched orchestrator.
- `watch-profiles/`: target-specific disposable build preparation.
- `scripts/watch_discover.py`: SHA/cache discovery.
- `scripts/watch_aggregate.py`: current-run and cumulative history.
- `scripts/finalize_external_result.py`: stable external-result metadata.
