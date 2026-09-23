# External Project Runner

AppLab v0.4.1 can verify a public Flutter repository without adding an AppLab
workflow to that repository.

Open **Actions -> External Flutter Project Runner -> Run workflow** in AppLab
and provide:

- `repository`: GitHub `owner/name`;
- `ref`: branch, tag, or exact commit SHA;
- `working_directory`: `.` for a normal Flutter repository, or the Flutter
  subdirectory for a monorepo.

The remaining inputs are optional. AppLab checks out the exact requested ref,
runs Flutter analysis/tests/build, boots Android, installs and launches the APK,
runs Maestro when enabled, scans runtime failures, and publishes the same
evidence contract used by the reusable Project Gate.

## Result contract

The run uploads `external-applab-report-<run id>` containing at least:

- `project.txt` with requested repository/ref and resolved target SHA;
- Flutter analyze/test/build logs;
- APK metadata;
- `summary.md`;
- `result.json`;
- screenshots, UI hierarchy, Logcat and app Logcat when Android verification
  starts.

`result.json` is the stable machine-readable output for later AppLab
automation.

## Scope

v0.4.1 intentionally targets public GitHub Flutter repositories. Private
cross-repository checkout requires a separate credential model and is not
silently granted to the runner.
