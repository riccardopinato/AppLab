# AppLab

AppLab is a reusable Android APK verification lab.

## v0.6.2 — Multi-Screen Visual Journey

AppLab now validates a sequence of runtime screens instead of only the final
screen. Every verification captures at least `launch` and `final`, runs
Smart Visual QA on each checkpoint, and compares each one with its own last
passing baseline.

Repositories can add `.maestro/applab-journey.json` to define additional
sequential checkpoints such as Settings, detail screens, dialogs or other
critical UI states. Each checkpoint flow is executed in the same emulator
session and AppLab captures screenshot + UI hierarchy after it succeeds.

Visual baseline cache generation is now `v2` and stores one baseline per
checkpoint. The main report exposes an aggregated `visual_journey` verdict.

See `integration/visual-qa/MULTI_SCREEN_JOURNEY.md`.

## v0.6.1 — Visual Regression Baseline

AppLab now preserves the last passing final screen for each watched project in
GitHub Actions cache and compares every new verified screen against it.

The comparison combines normalized screenshot differences with UI hierarchy
changes. Large visual changes accompanied by major structural UI changes fail
the gate; moderate differences are warnings. A project's first passing run
creates the initial baseline automatically.

Baselines are updated only after a successful verification, so a broken commit
cannot replace a known-good reference.

See `integration/visual-qa/VISUAL_REGRESSION.md`.

## v0.6 — Smart Visual QA

The Android verification gate now performs deterministic visual checks after
launch/Maestro using the final screenshot plus the matching uiautomator
hierarchy.

High-confidence anomalies such as blank screens, target app not being in the
foreground, visible crash/ANR dialogs and impossible interactive bounds fail
the gate. Smaller touch targets, partially off-screen controls and likely
permission/system dialogs are reported as warnings.

Every report now includes `visual-qa.json`, `visual-qa.md` and a
`visual_qa` field inside the main `result.json`. Repo Watcher history also
surfaces the visual QA verdict.

See `integration/visual-qa/SMART_VISUAL_QA.md`.

## v0.5.2 — Universal Project Auto-Discovery

AppLab can now start from only `owner/repository + ref`. The Universal Runner
checks out the target, detects whether it is Flutter or native Android/Gradle,
derives the build profile, and routes it to the correct existing verification
engine.

For standard repositories AppLab auto-detects the working directory, Java,
Flutter/Gradle versions, compile SDK, build command, APK path, package id and
common code-generation/build preparation. The inferred profile is uploaded as
`profile.json` for inspection.

The watcher also supports `engine: auto`, so a normal repository entry can be
reduced to its key, repository and ref. Explicit Flutter/native profiles remain
available for exceptional projects that need custom preparation.

See `integration/universal/AUTO_DISCOVERY.md`.

## v0.5.1 — Native Android Project Runner

The central watcher now supports two engines: `flutter` and
`native_android`. Native Gradle/Compose projects receive their own build gate
(Java, Android SDK, Gradle, unit tests, lint, APK build and signature check)
before entering the same AppLab emulator/Maestro/runtime verifier.

`Send-to-pc` is the first native Android repository in the live watchlist.

See `integration/android/NATIVE_RUNNER.md`.

## v0.5 — Automatic Repo Watcher

AppLab watches configured public Android repositories centrally. Every hour
it resolves each target's current SHA, skips commits already verified, and runs
the existing External Project Runner only for new commits.

The live watchlist contains TrailPath, Battery Guard, the Flutter port of
Notes-Ecosistema, and native Android project Send-to-pc. Each repository keeps its own build profile while AppLab
owns the emulator verification contract.

Watcher results are aggregated into a cumulative `history.jsonl` stored in
GitHub Actions cache and published as a 90-day artifact. Both PASS and FAIL
commits are marked as checked; a manual forced run can retry the same SHA.

See `integration/flutter/WATCHER.md`.

## v0.4.1 — External Project Runner

AppLab can also test a public Flutter repository **from AppLab itself**, without
first copying a workflow into the target repository. Run
`External Flutter Project Runner` from GitHub Actions and supply
`owner/repository` plus a branch, tag, or commit SHA.

The runner records the resolved target commit, builds the project, executes the
same Android/ADB/Maestro verification engine as the reusable Project Gate, and
publishes the standard `result.json` + evidence artifact.

For repositories with generated native scaffolding or code generation, v0.4.1 also accepts exact Java/Flutter versions plus `prepare_command`, `post_pub_get_command`, and an ADB-aware `android_prepare_command` hook. These run only in the disposable Actions workspace.

See `integration/flutter/EXTERNAL_RUNNER.md`.

## v0.4 — Automatic Project Gate

AppLab can be attached to a Flutter repository as a reusable GitHub Actions
quality gate. A push can now be verified end-to-end without manually uploading
the APK:

```
code -> analyze -> tests -> APK -> Android emulator -> install -> launch
     -> Maestro -> screenshot/UI hierarchy -> Logcat/crash scan -> report
```

Copy `integration/flutter/applab.yml.example` into the target repository as
`.github/workflows/applab.yml`. The run publishes a visible Actions summary
plus an `applab-report-<commit>` artifact containing screenshots, logs and the
machine-readable `result.json`.

The reusable workflow also supports Flutter projects inside monorepos through
the `working_directory` input and optional app-specific Maestro flows.

## v0.3.1 — Live Android Emulator + Browser E2E

AppLab can now own the Android runtime instead of requiring an emulator to be
started manually.

The v0.3 Live stack:

```
Browser / AppLab UI
        |
        | HTTP + WebSocket
        v
AppLab Controller + WebRTC Gateway
        |
        | gRPC :8554
        v
Google Android Emulator container
        |
        +--> ADB :5555
        +--> /dev/kvm
```

From the dashboard you can:

- start the managed Android emulator;
- wait for Android boot automatically;
- start the Google WebRTC signaling gateway;
- view and control Android in the browser;
- restart or stop the complete live runtime;
- upload/install APKs;
- launch/restart/stop/clear/uninstall apps;
- run Maestro flows;
- inspect screenshots, filtered Logcat and PASS/FAIL diagnostics;
- keep controller history across restarts.

## Requirements for Live mode

Live Emulator requires a **Linux host with KVM**. Docker Desktop on Windows and
macOS does not provide the KVM setup required by Google's Android Emulator
containers.

Check the host first:

```bash
chmod +x scripts/check_live_host.sh
./scripts/check_live_host.sh
```

Bare-metal Linux is preferred. Cloud VMs can work when nested virtualization is
enabled.

## Start AppLab v0.3.1 Live

```bash
cp .env.example .env
docker compose -f docker-compose.live.yml up --build
```

Then open:

```
http://localhost:5173
```

The browser frontend talks to:

- AppLab backend: `http://localhost:8000`
- WebRTC gateway: `localhost:8080`
- Android ADB: `127.0.0.1:5555`
- Android Emulator gRPC/WebRTC: `127.0.0.1:8554`

Press **Start emulator** in the Live Runtime panel. AppLab will pull/start the
configured Android Emulator image, connect ADB, wait for
`sys.boot_completed=1`, then launch the WebRTC gateway.

The default v0.3.1 runtime image is `applab-emulator-runtime:0.3.1`. AppLab
builds it automatically from Google's published API 30 x86_64 base image and
upgrades the Android Emulator binary to the WebRTC-capable runtime used by the
browser E2E gate.

Override `APPLAB_EMULATOR_IMAGE` or `APPLAB_EMULATOR_BASE_IMAGE` in
`.env` when testing a compatible custom runtime.

## Standard Control Center

The non-KVM control plane remains available:

```bash
docker compose up --build
```

This mode controls an existing ADB target and does not manage the emulator
lifecycle itself.

## Quality Gate

```
code -> analyze -> tests -> APK -> emulator -> install -> launch
     -> Maestro -> screenshot -> Logcat -> crash scan -> report
```

## Main API

```
GET  /api/runtime
POST /api/runtime/start
POST /api/runtime/restart
POST /api/runtime/stop

GET  /api/device
GET  /api/apps
GET  /api/app/status?package_id=...
POST /api/apk/install
POST /api/app/launch
POST /api/app/restart
POST /api/app/stop
POST /api/app/clear
POST /api/app/uninstall
GET  /api/screenshot
GET  /api/logcat?package_id=...
GET  /api/report?package_id=...
GET  /api/tests
POST /api/tests/run
GET  /api/history
```

## CI verification

```bash
chmod +x scripts/*.sh
./scripts/verify_apk.sh path/to/app.apk com.example.app
```

For Flutter repositories, use
`.github/workflows/verify-flutter.yml` as the reusable AppLab runtime gate.

## Upstream foundations

- Google Android Emulator / android-emulator-container-scripts
- Google android-emulator-webrtc
- ReactiveCircus android-emulator-runner
- Maestro

See `NOTICE.md`.
