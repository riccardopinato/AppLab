# AppLab Flutter Project Gate

Copy `applab.yml.example` to the Flutter application's repository as:

```
.github/workflows/applab.yml
```

On each push to `main`, the reusable AppLab workflow performs:

```
flutter pub get
-> flutter analyze
-> flutter test
-> build APK
-> boot Android emulator
-> install APK
-> launch app
-> Maestro smoke
-> screenshot + UI hierarchy
-> Logcat/crash/ANR scan
-> PASS/FAIL report
```

The run publishes both a GitHub Actions job summary and an
`applab-report-<commit>` artifact. The artifact includes `result.json`, so
automated clients can consume the verification result without scraping logs.

## Monorepos

Set `working_directory` to the Flutter project directory. `apk_path` is
resolved relative to that directory.

## App-specific interaction

Set `maestro_flow` to a flow in the application repository. If omitted,
AppLab generates its generic launch/home/relaunch smoke flow.

The caller remains intentionally small: AppLab owns the verification logic, so
future gate improvements apply to connected repositories without duplicating
scripts in each app.
