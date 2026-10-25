# AppLab v5.4F — Warm Trusted-Runtime Pilot

Status: **PILOT IMPLEMENTED / NOT PRIMARY EXECUTOR**

v5.4F introduces the first reusable trusted-runtime worker protocol and a bounded KVM/AVD equivalence pilot. It does not change build isolation, verifier authority or certification authority.

## Worker protocol

The durable worker projection stores:

- exact AppLab SHA;
- runtime profiles;
- pristine snapshot digest;
- heartbeat time;
- current lease;
- isolation generation;
- health/quarantine reason.

Only one ACTIVE lease is allowed per worker.

A capability mismatch or unavailable worker fails closed to `GITHUB_ACTIONS`.

## Lease lifecycle

```text
AVAILABLE
  -> LEASED
  -> SCRUBBING
  -> AVAILABLE
```

Uncertain paths terminate in QUARANTINED.

Lost heartbeat during an active lease changes that lease to UNKNOWN and quarantines the worker until explicit recovery/re-registration.

Cleanup must be proven before a worker returns to AVAILABLE.

## Security boundary

The warm protocol never executes:

- target Gradle/Flutter build;
- target prepare commands;
- arbitrary target shell;
- repository dispatch;
- worker-controlled verdict logic.

The warm runtime consumes only a previously built canonical APK fixture and trusted AppLab verifier code.

## KVM/AVD pilot

`.github/workflows/warm-worker-pilot.yml` reuses the same pinned Android emulator action and verifier stack already used by AppLab.

The pilot:

1. restores the canonical self-test APK;
2. creates one API 35 Pixel 7 Pro AVD;
3. verifies the target package is absent;
4. saves named snapshot `applab-pristine` before APK installation;
5. runs the existing FAST verifier;
6. stops the emulator while preserving the AVD;
7. starts the same AVD explicitly from `applab-pristine`;
8. proves the target package is still absent before the second verifier run;
9. runs the same FAST verifier again;
10. compares APK identity, result and wall-clock duration.

The warm path must be faster in the pilot evidence before this milestone is accepted.

## Equivalence evidence

`APPLAB_WARM_WORKER_EQUIVALENCE` records:

- exact APK SHA-256;
- cold/warm verifier result;
- analysis mode;
- clean snapshot restore;
- cold wall time;
- warm wall time;
- measured improvement;
- explicit statement that dispatch authority did not change.

## Promotion boundary

Even a green pilot does not make the warm worker primary.

Primary dispatch remains a future explicit promotion decision after durable event-driven execution is stable. GitHub Actions stays the independent fallback/burst executor.
