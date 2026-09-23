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

## Non-standard Flutter repositories

The runner exposes build hooks instead of assuming every repository commits the
same native scaffold:

- `flutter_version`: pin an exact Flutter SDK when the project CI requires it;
- `java_version`: select the target JDK;
- `prepare_command`: run setup before `flutter pub get`, for example
  generating `android/` with `flutter create`;
- `post_pub_get_command`: run code generation such as
  `dart run build_runner build`;
- `android_prepare_command`: run an ADB-aware command after a preliminary APK
  install and before the standard AppLab verifier.

These hooks execute only for an explicitly dispatched run and do not write back
to the target repository.

### TrailPath example

TrailPath intentionally generates its native scaffold in CI. A compatible
external run therefore pins Flutter and passes its scaffold/codegen commands
through these hooks rather than requiring AppLab to special-case TrailPath.
