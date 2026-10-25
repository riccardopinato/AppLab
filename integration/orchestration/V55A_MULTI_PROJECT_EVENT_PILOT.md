# AppLab v5.5A — Multi-Project Event-Driven Pilot Set

Status: **IMPLEMENTED AS BOUNDED PILOT / AUTHORITY UNCHANGED**

v5.5A expands the v5.4G control plane from the AppLab/selftest canary to a bounded three-repository pilot set: AppLab/selftest, CamperBoss and TrailPath.

## Safety boundary

- Durable Brain remains orchestration-only.
- Smart Test Plan remains the sole FAST/FULL planning authority.
- Existing Universal Project Runner performs target discovery/build and delegates to the existing trusted Flutter/native runners.
- Production Certification remains the only certification authority.
- `coverage_reduction_enabled=false` remains unchanged.
- GitHub Actions remains the executor and fallback.
- The hourly Repo Watcher remains an independent watchdog for every pilot target.
- A global kill switch can force admission to dry-run without deleting Event/Operation evidence.

## Event ingress

The self-repository canary continues to admit AppLab `main` pushes. External pilot repositories are admitted through an explicit `repository_dispatch` payload or bounded manual dispatch carrying repository and immutable target SHA. This avoids granting the Durable Brain broad cross-repository credentials.

A later v5.5 milestone may install narrowly scoped target-side emitters. v5.5A does not require or create a PAT and does not let a target repository mint verification or certification evidence.

## Pilot set

1. `riccardopinato/AppLab` / `main` / selftest.
2. `riccardopinato/CamperBoss` / `main`.
3. `riccardopinato/TrailPath` / `main`.

CamperBoss and TrailPath intentionally exercise real Flutter projects through the existing Universal Project Runner. Their watcher entries remain enabled, so event loss or pilot failure is independently reconciled by the hourly watcher.

## Promotion gate

v5.5A is not permission to make event-driven orchestration the sole scheduler. Promotion requires multi-project evidence for dedupe, restart recovery, repository isolation, failure recovery and watcher reconciliation with no authority-boundary regression.
