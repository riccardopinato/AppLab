# AppLab v5.9D — Build Once Promotion

## Goal

Reduce repeated Android build work on the commit-to-green path without
weakening exact-artifact identity or treating different release variants as the
same artifact.

v5.9D promotes the existing v5.7E content-addressed build contract into a
production-ready runtime carrier for explicitly admitted downstream pilots.

## Production carrier contract

A `build_once_pilot` is READY only when all of the following are true:

- the repository is already an exact-artifact `reuse_pilot`;
- the Flutter toolchain version is pinned;
- generated-platform preparation is owned by immutable AppLab
  `watch-profiles/*.sh` hooks;
- post-dependency generation is owned by an immutable AppLab hook;
- the AppLab runtime build produces one emulator-compatible Android x64 APK;
- the runtime build does not use `--split-per-abi`;
- the expected runtime artifact is exactly
  `build/app/outputs/flutter-apk/app-release.apk`.

The source SHA, config fingerprint, AppLab contract fingerprint, pinned
toolchain, locked dependency material and trusted hook bytes remain part of the
execution identity. A cache hit is accepted only after the existing isolated
build contract is revalidated.

## Anna's Diary pilot

`riccardopinato/Agenda-per-Anna` is the first v5.9D carrier.

AppLab owns two immutable hooks:

- `watch-profiles/agenda_per_anna_prepare.sh`
- `watch-profiles/agenda_per_anna_post_pub_get.sh`

The runtime artifact is built once for `android-x64`, matching the trusted
hosted emulator lane. The previous AppLab `--split-per-abi` command generated
three ABI variants even though the trusted runtime consumes only one Android
artifact.

The target repository remains responsible for its versioned
`tool/prepare_android_platform.py`; target-source changes are still bound to the
resolved source SHA, so changing that script cannot reuse an older build
contract.

## What v5.9D does not merge

Build Once means **build once per compatible artifact identity**, not build once
for every Android purpose.

The following remain separate when their build inputs or trust boundaries
differ:

- production-equivalent size audit with obfuscation and disposable release
  signing;
- stable sideload/store artifacts with production signing;
- Play App Bundle generation;
- certification or physical-device artifacts that require a different build
  variant.

Those lanes may consume the same source SHA but do not share an APK unless
their complete build identity is proven identical.

## Safety invariants

- `coverage_reduction_enabled=false` remains unchanged.
- Build cache reuse never mints trusted runtime evidence.
- Trusted runtime still verifies the restored exact APK.
- v5.7E promotion evidence must be READY for a reused build to contribute a
  PASS result.
- Certification authority is unchanged.
- A missing or mutable scaffold hook makes build reuse ineligible and falls
  back to a fresh build.

## Expected impact

For repeated verification of the same source/config identity, Flutter setup,
platform generation, dependency generation and APK compilation can be skipped
on a validated build-contract hit.

For a fresh Anna runtime build, replacing `--split-per-abi` with a single x64
runtime artifact removes unnecessary ABI compilation from the AppLab lane.
Production size/release workflows remain intentionally independent.
