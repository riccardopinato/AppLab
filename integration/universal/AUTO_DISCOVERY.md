# AppLab v0.5.2 — Universal Project Auto-Discovery

AppLab can now start from only a public GitHub repository and a ref.

Input:

- `repository`: `owner/name`
- `ref`: branch, tag, or commit SHA

The Universal Runner checks out the target in a disposable GitHub Actions
workspace, inspects the repository, produces a machine-readable profile, and
routes the project to the correct AppLab engine.

## What is detected

### Flutter

AppLab searches for the most likely `pubspec.yaml` and detects:

- Flutter project working directory, including common monorepo layouts;
- exact Flutter version when pinned in GitHub Actions;
- Java version;
- whether an Android scaffold already exists;
- whether a temporary `flutter create --platforms=android .` bootstrap is needed;
- build_runner/drift-style code generation;
- Android package id when already present;
- AppLab/Maestro smoke flow when present.

Default Flutter output:

`flutter build apk --debug`

with:

`build/app/outputs/flutter-apk/app-debug.apk`

### Native Android / Gradle

AppLab detects:

- Gradle project root;
- Java version;
- Gradle wrapper or pinned Gradle version;
- compile SDK;
- build-tools version;
- unit-test command from the project's GitHub Actions workflow;
- lint command;
- `assemble*` task;
- expected APK path and variant;
- application id;
- optional Maestro flow.

The detected APK is still verified through `apksigner`, Android Emulator,
ADB, Maestro, screenshots, UI hierarchy and Logcat.

## Watchlist

Watcher entries may now use:

```json
{
  "key": "watch-example",
  "engine": "auto",
  "enabled": true,
  "repository": "owner/repository",
  "ref": "main"
}
```

No Java, Flutter, Gradle, SDK, build command, APK path or package id is
required for a standard repository.

Explicit `flutter` and `native_android` profiles remain supported for
projects that need repository-specific preparation or native overrides.

## Detection evidence

Every Universal Runner execution uploads an `applab-autodiscovery-<run id>`
artifact containing `profile.json`. This makes the inferred build contract
inspectable instead of hiding it inside workflow logic.
