# X10-032 — Physical QA and Play internal testing execution handoff

Factory: Core@c5adc147046beb7024629466d10eeb799c3c2619, Master 27 / Index 29.

This PR adds a **deterministic planning adapter only**: `scripts/x10_physical_play_plan.py`. It accepts a *previously independently verified* APK source SHA, file SHA256, signer fingerprint, versionCode, provenance workflow and a bounded list of native capabilities. It emits scenarios for install/upgrade/no-loss/restart/reinstall and Google Play Internal Testing, plus device-specific native feature checks. All initial results are `NOT_VERIFIED`. Tests are synthetic, not physical.

Do **NOT** use this planner as the source of verification authority. The already-existing canonical `scripts/physical_evidence.py` and its trusted physical evidence hub must confirm identical artifact bytes, real device, signed release and trusted workflow run. Google Play Internal Testing requires independent Play Console track / authorized tester install and version proof. Merely opening an APK on an emulator, seeing green AppLab checks, uploading a fake receipt or sending a signed APK does not close X10-032.

**Recommended real physical matrix:** one Android Samsung and one Xiaomi/Redmi (different OEM battery policies) for notification/permission/upgrade flows, plus any app-specific GPS/background/camera/storage/biometric cases. Inputs must be sourced from the target app release manifest: no blank APK checksums fabricated.

## Pending human evidence
1. Approved final APK/AAB source SHA and actual uploaded artifact SHA/signer.
2. Real devices with OS build and app installation; privacy-safe screenshots/logs per scenario.
3. Same-bytes install and upgrade preserving test data, reboot and restricted-background behaviour.
4. Play Console internal track evidence with package/versionCode and tester-installed receipt.
5. Canonical AppLab physical_evidence verification and independent review after each run.

This does not change CI/workflows, grant Play access, publish, install or remove user data. X10-032 stays HUMAN_GATE/PLANNED until external execution.
