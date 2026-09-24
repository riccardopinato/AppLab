# AppLab

## v0.7.7 — Resource Pressure & Process Death Lab

AppLab now exercises Android memory-pressure callbacks and background process death before the upgrade gate. It sends validated `trim-memory` levels, backgrounds the target, simulates operating-system-style process death with `am kill`, relaunches the app, captures recovery evidence, and checks target ANRs/fatal exceptions.

Projects can optionally define `.maestro/applab-resource.json` to select safe trim levels, process-death cycles, settling time, and persisted UI assertions. Runtime limitations are advisory by default; crashes, unexpected process loss during trim handling, and failed recovery are hard failures.

See `integration/resources/RESOURCE_PRESSURE_PROCESS_DEATH_LAB.md`.

## v0.7.6 — Configuration & Lifecycle Stress Lab

AppLab now exercises repeated orientation changes and foreground/background transitions before the upgrade gate. It preserves and restores emulator rotation settings, captures per-stage screenshot/UI evidence, verifies process health after each transition, and detects target ANRs or fatal exceptions.

Projects can optionally define `.maestro/applab-configuration.json` to choose rotation/background cycle counts and assert UI state that must survive lifecycle/configuration changes. Unsupported or fixed landscape behaviour is advisory by default; target crashes and failed foreground recovery remain hard failures.

See `integration/configuration/CONFIGURATION_LIFECYCLE_STRESS_LAB.md`.

## v0.7.5 — Upgrade & Migration Lab

AppLab now restores the latest PASS-only APK for each project and exercises a real in-place upgrade to the current candidate. Previous/current APK copies are temporarily re-signed with the same run-local AppLab test key so CI debug-key rotation cannot invalidate the migration test; the original verified APK bytes remain untouched.

The gate verifies previous-version launch, `adb install -r` upgrade, post-upgrade launch, crash/ANR health, screenshot/UI evidence, and optional persisted-state assertions from `.maestro/applab-upgrade.json`. Projects without a previous PASS APK report `NO_BASELINE` and seed one after their first successful verification.

See `integration/upgrade/UPGRADE_MIGRATION_LAB.md`.

## v0.7.4 — Persistence & Restart Lab

The trusted Android gate now force-stops and relaunches the target across repeated lifecycle cycles, captures post-restart screenshot/UI evidence, and fails on relaunch failure, target ANR, or fatal exception. Projects can optionally define persisted-state assertions with `.maestro/applab-persistence.json`, using expected/forbidden UI-text regular expressions after every restart.

Evidence includes `persistence-lab.json`, `persistence-lab.md`, and per-cycle screenshots/UI hierarchies. The verdict is propagated through Repo Watcher history and the Control Center.

See `integration/persistence/PERSISTENCE_RESTART_LAB.md`.

## v0.7.3 — Network & Offline Lab

The trusted Android gate now removes and restores connectivity, verifies that
the target stays healthy while offline, optionally relaunches it without a
network, and checks recovery after connectivity returns. App crashes, ANRs or
failed relaunches fail the gate; emulator network-control limitations are WARN
by default and can be made strict with `.maestro/applab-network.json`.

Evidence includes `network-lab.json`, `network-lab.md`,
`network-offline.png`, and `network-recovered.png`. The verdict is propagated
through Repo Watcher history and the Control Center.

## v0.7.2 — Performance Lab

Trusted verification records cold/warm startup, PSS/RSS, frame jank and
percentiles, CPU snapshot and APK size. Last-known-good performance baselines
are promoted only from eligible passing runs, allowing AppLab to flag startup,
memory and jank regressions without replacing a known-good baseline.

## v0.7.1 — Verified Release Artifact

A successful trusted verification now produces a PASS-only installable APK
artifact. AppLab republishes the exact APK bytes that were exercised by the
trusted emulator gate, verifies the SHA-256 against the isolated build contract,
and records package id, version name/code, size, commit summary, artifact id and
download URL in the final report.

The central Repo Watcher history carries this release metadata into the Control
Center, where the latest PASS for each project exposes a direct verified APK
download. FAIL/WARN pipelines never publish a release artifact.

## v0.7 — Control Center

AppLab now exposes the central Repo Watcher snapshot in the browser dashboard,
including the latest verdict and runtime quality gates for every configured
project plus recent verification history.

## v0.6.7 — Permissions, Notifications & System UI Lab

AppLab now validates Android system behaviour after the visual and interaction
gates. The trusted verifier records permission/app-op state, notification
evidence, running/foreground services, battery-idle state, background/foreground
recovery, and force-stop/relaunch behaviour.

Projects can optionally add `.maestro/applab-system.json` to declare runtime
permission grants/revokes, package-scoped deep links, optional biometric
emulator events, and notification requirements. The policy is copied through
the isolated build contract and validated before the trusted emulator runs.

Evidence is published as `system-lab.json` and `system-lab.md`, while
`result.json` and Repo Watcher history expose the aggregated `system_lab`
verdict.

See `integration/system/SYSTEM_UI_LAB.md`.

## v0.6.6 — Safe Interaction Crawler

After launch and scripted visual journeys, AppLab now performs a conservative
runtime exploration pass. It discovers only clearly labelled navigation
controls from the app UI hierarchy, excludes destructive or transactional
actions, relaunches the app before every probe, taps a bounded number of safe
targets, and checks for process death, ANR, or fatal exceptions after each tap.

The report includes `interaction-crawl.json`, `interaction-crawl.md`, and
per-action screenshot/UI evidence. A crawler-detected crash fails the gate;
screens that do not expose a conservative safe candidate are reported as
`SKIPPED` rather than treated as failures.

## v0.6.5 — Visual Regression Pro

Visual Regression is now configurable per checkpoint. Projects can use
`strict`, `standard`, or `dynamic` profiles, define normalized screen masks,
ignore known dynamic text with regular expressions, and let AppLab
automatically mask native dynamic surfaces such as maps, WebViews, camera
previews, SurfaceViews, and TextureViews.

Regression evidence now includes perceptual-difference metrics and a heatmap
per comparable checkpoint. Intentional visual changes can be promoted only
through the explicit `approve_visual_baseline` input; ordinary WARN runs do
not overwrite the last known-good baseline, and FAIL runs remain
non-approvable.

The v0.6.4 trusted Build -> Artifact -> Verify isolation remains in force:
target repositories are never checked out in the emulator verification job.

AppLab is a reusable Android APK verification lab.

## v0.6.3 — Hardening & Architecture Consolidation

v0.6.3 consolidates the verification contract introduced across v0.5–v0.6.2.

Key changes:

- Visual Journey is the single visual verification engine; final-screen
  `visual-qa.*` and `visual-regression.*` files are compatibility views of
  the `final` checkpoint instead of a second analysis pass.
- Visual baselines are promoted only after a full visual `PASS`. A `WARN`
  run never replaces the last known-good baseline.
- Journey manifests are discovered both at repository root and inside the
  configured project `working_directory`; custom flows are skipped cleanly
  when Maestro is disabled.
- External runners restore the pinned AppLab checkout after target build hooks,
  remove persisted GitHub credentials, and restrict Android preparation hooks
  to explicit `pm grant` permission commands before the trusted verifier runs.
- Watcher cache invalidation uses an automatic contract fingerprint plus a
  per-project configuration fingerprint instead of manual cache epochs.
- The reusable Flutter gate delegates to the same external v0.6.3 verifier.
- GitHub Actions were moved to Node-24-ready major versions, Maestro is pinned,
  frontend dependencies are lockfile-driven, and AEMU proto sources are pinned.
- AppLab Live reports v0.6.3, defaults CORS to localhost, binds Docker ports to
  localhost, and streams APK uploads with a configurable size limit.
- The Android self-test now verifies real multi-screen checkpoints
  (`launch`, `final`, `settings`, `dialog`) plus a Maestro-disabled path.

See `integration/HARDENING_0_6_3.md`.

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
