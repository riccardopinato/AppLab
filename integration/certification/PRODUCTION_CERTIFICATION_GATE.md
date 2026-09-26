# AppLab v0.8.0 — Production Certification Gate

AppLab v0.8.0 separates continuous verification from production certification.

## Verification modes

- `fast`: continuous analysis. Core runtime checks always run; specialist labs can be skipped by the Smart Test Planner.
- `full`: complete diagnostic verification. Every specialist lab runs and passing baselines can be refreshed.
- `certification`: production gate. Every specialist lab runs and AppLab applies strict release rules after the trusted Android runtime finishes.

FAST and FULL can prove that a build is healthy. Only CERTIFICATION can authorize publication of the AppLab verified APK.

## Certification verdicts

The final certification status is one of:

- `CERTIFIED`: every mandatory gate is PASS and the tested APK hash matches the isolated build contract.
- `NOT_CERTIFIED`: the trusted runtime, a mandatory gate, or APK integrity failed.
- `BLOCKED`: AppLab could not obtain production-grade evidence, for example because a lab returned WARN/SKIPPED/NO_BASELINE or certification was attempted without the required mode/baseline.

AppLab never converts WARN, SKIPPED or NO_BASELINE into a production PASS.

## Mandatory gates

Production certification requires two evidence layers.

### Build evidence

For Flutter targets:

- static analysis PASS;
- unit tests PASS;
- APK build PASS.

For native Android targets:

- Android lint PASS;
- unit tests PASS;
- APK build PASS.

A required build check reported as `NOT_RUN` blocks certification.

### Runtime evidence

Production certification requires PASS for:

- Maestro acceptance;
- Smart Visual QA;
- Visual Regression;
- Multi-Screen Visual Journey;
- System UI;
- Network & Offline;
- Persistence & Restart;
- Configuration & Lifecycle;
- Resource Pressure & Process Death;
- Background / Doze Recovery;
- Storage & Data Integrity;
- Upgrade & Migration;
- Performance.

Safe Interaction Crawler remains supporting evidence because a conservative crawler can legitimately find no safe interaction target.

## Controlled runtime lane

v0.8.0 records an explicit primary certification lane:

- Android API level;
- emulator hardware profile;
- Android target image;
- CPU architecture.

The default manual certification workflow uses API 35, `pixel_7_pro`, `google_apis`, and x86_64. API level and emulator profile are explicit workflow inputs. This is the minimum controlled production matrix for v0.8.0; wider multi-device matrices can be layered on without changing the certification contract.

## APK integrity and release

The certification gate recomputes SHA-256 from the isolated `app.apk` and compares it with `contract.json`.

The release publisher then verifies the same bytes again. A release artifact is created only when:

1. the trusted runtime result is PASS;
2. effective analysis mode is `certification`;
3. certification status is `CERTIFIED`;
4. the APK SHA-256 matches the build contract.

FULL and FAST runs do not publish the verified installable APK.

## Baselines

FULL runs remain the normal way to seed or refresh Visual, Performance and Upgrade baselines. A successful CERTIFICATION run may also refresh passing baselines.

Certification does not weaken itself to create a missing baseline: missing production evidence produces `BLOCKED`. Run a successful FULL verification first.

## Evidence

A certification run adds:

- `certification.json` — machine-readable verdict, failures, blockers, runtime lane and APK digest;
- `evidence-bundle.json` — complete machine-readable evidence bundle with repository, resolved commit, engine, build-quality checks, APK identity/version/size/hash, AppLab control verdicts, runtime matrix and real-device status;
- `evidence-bundle.md` — readable form of the same evidence bundle;
- `certification.md` — readable production decision;
- `certification_status` and `certification` in `result.json`;
- production certification state in Repo Watcher history and Control Center.

The Control Center preserves the last production certification even if newer FAST checks run afterward.

Physical-device execution is not silently implied by hosted CI. v0.8.0 records `real_device.status=NOT_TESTED` unless separate real-device evidence is attached by the project. This keeps certification evidence honest while allowing projects with hardware-dependent features to impose a stricter release policy.

## Manual workflow

Run **Production Certification** and provide:

- repository;
- ref;
- Android API level;
- emulator profile.

The workflow resolves the watched project's stable history key, runs universal project discovery, forces Maestro, uses `analysis_mode=certification`, records the certification in central history, and publishes a release APK only for `CERTIFIED`.

## Network-lab hardening

v0.8.0 also removes a false-negative source observed on hosted Android emulators. Android may reclaim a process while network capabilities are changing. AppLab no longer treats process disappearance alone as an application crash.

It attempts a clean relaunch and still fails on:

- fatal exception;
- ANR;
- failed offline relaunch;
- failed recovery relaunch.

This keeps application failures strict while separating them from hosted-emulator process churn.

## Release rule

A build is production-certified only from explicit evidence generated by the current certification run. Historical FAST/FULL PASS results are never relabeled as CERTIFIED.
