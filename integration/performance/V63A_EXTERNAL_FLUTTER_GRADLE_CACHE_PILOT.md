# AppLab v6.3A — external Flutter Gradle cache pilot

Factory baseline: App-Factory-Core@174a05e165076c9e4b2d61a20acd85ca6b215f12 (v27).
AppLab starting SHA: 636490e58d38c3910eb168197cde72adb9cdb3f9.
Status: CODE PILOT / NOT YET PERFORMANCE-PROVEN.

## Verified 2026-10-29 baseline

- Anna's Diary AppLab Production Gate run 40847530142, SHA 0c52b170b25ab82f0d7e5e7938f82dd19e0642f3:
  - build job 671 s, adaptive Flutter checks/build 616 s;
  - trusted verification job 1297 s, emulator verification step 1192 s;
  - workflow approximately 33m10s.
- Another Anna gate at run 40855755420 completed analysis-only in 18 s (NOT the same verification coverage).
- In-Cucina-con-gli-Anime development run 40693810374 Android build step 217 s, run 40674954584 Android build step 1158 s. Different repository workflow; not a direct AppLab-runner speed claim.
- AppLab native Android external runner already invokes pinned gradle/actions/setup-gradle, Flutter external runner did not.
- Anna currently pins AppLab@730dfafecc59871365812f4d7d138b43151fdcc5 (v5.9E); central v6.3 implementation does not change existing per-app pins.

## Scoped change

Use the same pinned Gradle cache action in the external Flutter runner after dependency preparation and before adaptive quality/build. Only run it when a fresh Android APK build is actually needed and exact APK reuse did not hit. It must not mutate target source, bypass tests, reuse a mismatched APK, change app signing, or infer a trusted runtime PASS.

This is an infrastructure cache (Gradle downloads, transforms, task outputs). It is independent from the SHA- and contract-bound AppLab APK artifact cache; produced APK identity remains computed from the actual output bytes.

## Acceptance / next pilot

1. Exact-head AppLab workflow checks and independent review green.
2. Pin a downstream pilot to the reviewed new AppLab SHA in a separate PR; never silently move a consuming app's pin.
3. Measure at least three successful matched build trials per condition, with Gradle cache hit/miss and phase timings (including first cold run). Record median/p95 without equating setup cache hit to APK reuse.
4. Analyze separately the longer Anna LEGACY_FALLBACK Maestro path; do not weaken its Vault/security or FULL coverage.
5. Revert the added setup action if a reproducible build regression or sustained net slowdown occurs.

Performance savings are not asserted until downstream measurements support them.
