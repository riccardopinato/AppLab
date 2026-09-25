# AppLab v0.7.10 — Fast Analysis Engine & Smart Test Orchestration

AppLab v0.7.10 adds a safe fast path for continuous project analysis. AppLab v0.8.0 keeps FULL as the complete diagnostic path and adds a distinct CERTIFICATION mode for production release.

## Modes

- `full`: runs the complete trusted runtime suite and can seed/refresh trusted baselines.
- `fast`: always keeps launch, crash/ANR detection, Maestro when enabled, Visual Journey and Safe Interaction Crawler, then runs only specialist labs selected by the trusted Smart Test Planner.
- `certification`: runs every specialist lab and then applies the v0.8.0 Production Certification Gate.

Manual project runs default to `full`. Repo Watcher runs default to `fast`.

If FAST is requested but AppLab cannot find a previous trusted visual and upgrade baseline, the verifier automatically falls back to FULL. This prevents first-time projects from receiving a reduced test pass.

## Smart Test Planner

The build phase records the files changed by the target commit and creates `analysis-plan.json`. The file is packaged inside the isolated build contract and validated by the trusted verifier before use.

Examples:

- documentation-only change: specialist labs can all be skipped;
- UI/Compose/Flutter screen change: Configuration + Performance;
- networking/API/sync change: Network, Background and Performance as applicable;
- Room/database/migration change: Persistence, Storage and Upgrade;
- service/worker/background change: Background + Resource Pressure;
- manifest/permissions/notification change: System UI and related lifecycle labs.

If the changed-file set cannot be determined reliably, the planner falls back to FULL.

## Release safety

FAST results are explicit: skipped labs remain `SKIPPED`; they are never converted to PASS.

FAST runs do not:

- promote the Performance baseline;
- promote the Upgrade baseline;
- publish the verified release APK.

Performance and Upgrade baseline promotion requires FULL or a successful CERTIFICATION run. Publishing the verified installable APK requires `CERTIFIED`; FULL no longer publishes a production release artifact.

## Evidence

- `contract.json` records the requested analysis mode;
- `analysis-plan.json` records changed files, selected specialist labs and selection reasons;
- `result.json` records the effective `analysis_mode`;
- the Control Center shows FAST/FULL/CERTIFICATION for the latest project result and preserves the most recent production certification separately.
