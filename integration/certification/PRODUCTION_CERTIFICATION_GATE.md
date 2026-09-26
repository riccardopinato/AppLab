# AppLab v0.9.0 — Production Certification Gate

v0.9 keeps the release-integrity contract from v0.8.x and routes certification
through the adaptive pipeline only as the explicit `CERTIFICATION` lane.
Adaptive FAST decisions can never reduce production-certification coverage.


AppLab separates continuous verification from production certification. FAST and FULL are quality-verification modes; only an explicit CERTIFICATION run can authorize the AppLab verified release artifact.

## Verdicts

The final status is one of:

- `CERTIFIED`: all mandatory build/runtime gates and every required certification lane passed;
- `NOT_CERTIFIED`: a hard runtime, build, artifact-integrity, signing or compatibility failure occurred;
- `BLOCKED`: AppLab lacks production-grade evidence, for example WARN/SKIPPED/NO_BASELINE, an unknown artifact variant, missing signing evidence, a missing compatibility lane, or required real-device evidence that was not executed.

WARN, SKIPPED, NO_BASELINE and unknown evidence are never converted into a production PASS.

## Release-only artifact policy

Auto-discovery exposes separate development and certification profiles.

For Flutter, CERTIFICATION uses:

```
flutter build apk --release
build/app/outputs/flutter-apk/app-release.apk
```

For native Android/Gradle, AppLab derives the corresponding release assemble task where possible and otherwise uses `assembleRelease`.

The certification gate rejects an artifact whose detected build variant is DEBUG. An unknown variant blocks rather than passes.

AppLab also records the signer certificate SHA-256. An Android Debug certificate is rejected. Projects may pin the expected production signing certificate in `.maestro/applab-certification.json`; a mismatch is `NOT_CERTIFIED`.

## Project certification policy

Optional policy at repository root or project working directory:

```json
{
  "schema_version": 1,
  "requires_real_device": false,
  "expected_signing_certificate_sha256": "",
  "max_apk_bytes": 629145600
}
```

A working-directory policy may override repository defaults.

- `requires_real_device=true` deliberately returns BLOCKED in hosted CI until a trusted physical-device lane supplies evidence.
- `expected_signing_certificate_sha256` accepts the expected 64-hex SHA-256 certificate fingerprint.
- `max_apk_bytes` is an absolute release-artifact ceiling.

Performance Lab separately flags material APK-size regressions versus the passing baseline (currently at least 35% and 1 MiB growth); because Performance is mandatory in CERTIFICATION, such a WARN blocks certification.

## Mandatory build evidence

Flutter targets require PASS for static analysis, unit tests and APK build.

Native Android targets require PASS for Android lint, unit tests and APK build.

A required check reported as NOT_RUN blocks certification.

## Mandatory runtime evidence

The primary certification lane requires PASS for:

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

Safe Interaction Crawler remains supporting evidence because a conservative crawler can legitimately find no safe action.

## Certification matrix

v0.9.0 uses two Android lanes:

1. **Primary** — deep CERTIFICATION lane, default API 35 / `pixel_7_pro` / `google_apis` / x86_64.
2. **Compatibility** — release-profile FULL verification on a second API. With `compatibility_api_level=auto`, AppLab derives a representative API from minSdk while keeping it below the primary API when possible.

The final matrix verdict is generated only after both lanes finish. Compatibility FAIL produces NOT_CERTIFIED; missing/non-conclusive compatibility evidence produces BLOCKED.

The installable release APK is not published by either individual lane. Only the matrix-finalization job may publish it, and it copies the exact APK bytes from the **primary** isolated build contract after the aggregate status remains CERTIFIED.

## APK integrity and identity

The isolated contract records:

- repository and resolved commit SHA;
- package id;
- versionName/versionCode;
- release/debug variant;
- APK size;
- APK SHA-256;
- signer subject and certificate SHA-256;
- build-quality evidence;
- certification policy.

The certification gate recomputes SHA-256 from `app.apk`. Release publication recomputes it again and refuses any byte mismatch.

## Architecture boundary

Hosted certification currently runs Android Emulator x86_64. A universal RELEASE APK that contains compatible x86_64 code can therefore be certified byte-for-byte and published unchanged.

An ARM64-only distribution artifact cannot honestly receive byte-identical runtime certification on this x86_64 lane. Projects that require ARM64-only or hardware-specific final validation should set `requires_real_device=true`; v0.9.0 will remain BLOCKED until a trusted physical/ARM64 device path is available. AppLab does not label emulator evidence as real-device evidence.

## Real-device evidence

Hosted CI records physical-device state explicitly. If real-device validation is not required, the Evidence Bundle still says `NOT_TESTED` rather than implying otherwise. If policy requires it, CERTIFICATION blocks.

This is especially appropriate for sensor-, camera-, Bluetooth-, OEM-background-, biometric- or other hardware-dependent applications.

## Evidence Bundle

A certification produces and retains:

- `result.json`;
- `certification.json/.md`;
- `evidence-bundle.json/.md`;
- `certification-matrix.md`;
- compatibility result;
- build contract and analysis plan;
- runtime screenshots/logs and lab evidence from the trusted verification artifact.

The final release bundle places the exact certified APK beside an `evidence/` directory with the essential production evidence. Final certification/release artifacts are retained for 90 days in GitHub Actions.

## Control Center

The last historical certification is preserved, but its relationship to the latest verified SHA is explicit:

- `CERTIFIED_CURRENT`: certified SHA equals the latest project SHA known to AppLab;
- `CERTIFIED_STALE`: a newer verified SHA exists and the older certification is retained only as history;
- `BLOCKED` / `NOT_CERTIFIED`: latest certification attempt did not authorize release.

A newer FAST PASS never silently upgrades itself to CERTIFIED.

## Baselines

FULL is the normal baseline-seeding path. Missing production evidence does not get weakened during CERTIFICATION: a missing required baseline yields BLOCKED. Passing certification lanes may promote eligible baselines under their own stable history keys.

## Release rule

A public AppLab release artifact must be the exact primary APK bytes covered by the final CERTIFIED matrix. Build success, a FAST PASS, a FULL PASS, or a historical certification on an older SHA is insufficient.
