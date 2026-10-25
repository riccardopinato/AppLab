# AppLab v5.5B — Reconciliation & Recovery

Status: **IMPLEMENTED AS BOUNDED PROOF / AUTHORITY UNCHANGED**

v5.5B adds a deterministic reconciliation/recovery policy harness over the v5.5A three-repository pilot. It proves the control-plane response to event loss, duplicate delivery, GitHub Actions outage, interrupted operation, Durable Brain restart, expired lease, superseding SHA and hourly watcher recovery.

The proof corpus runs all eight scenarios for AppLab/selftest, CamperBoss and TrailPath (24 proofs). Recovery may re-admit or resume orchestration, but every live dispatch remains delegated to GitHub Actions. An Actions outage holds durable pending work rather than minting a result. Duplicate deliveries reuse the durable operation. Terminal operations are preserved and never re-dispatched.

Authority is unchanged: Smart Test Plan remains the FAST/FULL planning authority; Trusted Verifier remains runtime evidence authority; Release Assurance remains assurance authority; Production Certification remains the only certification authority. `coverage_reduction_enabled=false` and the hourly watcher remains the independent reconciliation path.
