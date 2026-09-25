# AppLab v0.7.10 — Fast Analysis Engine & Smart Test Orchestration

AppLab v0.7.10 adds a safe fast path for continuous project analysis while preserving FULL verification for certification and release.

## Modes

- `full`: runs the complete trusted runtime suite.
- `fast`: always keeps launch, crash/ANR detection, Maestro when enabled, Visual Journey and Safe Interaction Crawler, then runs only specialist labs selected by the trusted Smart Test Planner.

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

Those operations require an effective FULL run. The v0.8.0 Production Certification Gate will always use FULL.

## Evidence

- `contract.json` records the requested analysis mode;
- `analysis-plan.json` records changed files, selected specialist labs and selection reasons;
- `result.json` records the effective `analysis_mode`;
- the Control Center shows FAST/FULL for the latest project result.
