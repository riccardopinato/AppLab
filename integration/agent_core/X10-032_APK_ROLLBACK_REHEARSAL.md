# X10-032 — APK rollback rehearsal on a disposable Android emulator

Factory baseline: `App-Factory-Core@c5adc147046beb7024629466d10eeb799c3c2619` (Master v27; Golden Index v29).

## What this tests

[`x10-android-apk-rollback.yml`](../../.github/workflows/x10-android-apk-rollback.yml) builds two actual **debug** APKs (`versionCode 101` and `102`) from the existing `dev.applab.selftest` **fixture**, using the same CI debug signer and exact PR source tree. It runs an isolated API 35 emulator and checks:

1. APK package, version codes, distinct SHA-256 digests and identical verified signer.
2. Initial 101 install; synthetic file in app-private storage written by the debuggable app's `run-as`.
3. Normal `adb install -r` upgrade to 102, synthetic private file unchanged.
4. Ordinary 102 → 101 `adb install -r` rejected with `INSTALL_FAILED_VERSION_DOWNGRADE`, current 102 and file intact.
5. **Debug fixture only**: explicit `adb install -r -d` goes back to 101; private test file still intact.

The script refuses any device except an Android emulator (`ro.kernel.qemu=1`, serial `emulator-*`) and **hardcodes the synthetic AppLab package**. No real user or consumer app can be installed/uninstalled by this script. It produces a run-bound JSON receipt with exact APK fingerprints and explicit `physical_device_verified=false`, `signed_release_rollback_verified=false`, `real_app_data_verified=false`, `play_verified=false`, `golden_admission=false`.

## Hard stop: this is NOT Anna's Diary release rollback

For `riccardopinato/Agenda-per-Anna` the current main remains `1.0.0-rc.6+129`. [Auto-signed workflow #43339886230](https://github.com/riccardopinato/Agenda-per-Anna/actions/runs/43339886230) had `signed-apk: SKIPPED` because the versionCode was not increased by the profile dependency-only merge. It did **not** mint a new signed APK. The old +128 artifact is not a 0.1.1 consumer; never call an old APK a verified restore of the new code.

On production/non-debuggable Android packages, lower-version installation can be rejected and using `-d` must never be assumed to preserve actual app data or work for Store APKs. Do not uninstall Anna's Diary to force a rollback; uninstall can destroy private storage. Migration-forward releases must not assume irreversible schema changes can be downgraded. A safe recovery requires independent encrypted data backup, full restore plan, verified **same signing certificate**, exact APK hash/version chain, physical QA on a spare device and independent Play authorization where applicable.

## Authority and follow-up

- Result may at most be `EMULATOR_DEBUG_ROLLBACK_PASS`; it is **not** an AppLab Physical Evidence Hub receipt or device/store certification.
- X10-026 remains **VERIFIED SOURCE+CI** as previously accepted. This rehearsal adds a distinct runtime tier, not an upgrade to Golden.
- X10-032 remains **PLANNED / HUMAN_GATE** pending real device, signed release, same-bytes artifacts, retained data and Play internal testing evidence through canonical `scripts/physical_evidence.py`.
- Any failure, especially a missing emulator/ADB device, is a failed CI run. Never convert it into PASS by disabling the device test.
