# AppLab v1.6 — Autonomous Audit Orchestrator

The Autonomous Audit Orchestrator converts current App Intelligence evidence into
a deterministic audit plan.

It does **not** replace FAST/FULL/CERTIFICATION and does not execute arbitrary
product changes. Its job is to decide which AppLab specialist domains deserve
attention for a given project.

## Inputs

Required:
- current `app-intelligence.json`.

Optional:
- explicit traceable market-evidence JSON.

No market search is performed automatically.

## Selection principles

Every audit contains Product Analysis, UX/Product and Architecture/Data.

Additional labs are selected from observed evidence:

- persistence -> storage, restart and upgrade/migration;
- network/cloud -> network/offline;
- background work -> Doze/recovery and process-death review;
- notifications/location/media -> system/permission review;
- authentication -> safe interaction exploration;
- monetization -> monetization review;
- AI/ML -> AI governance review;
- export/backup -> data lifecycle review;
- detected UX/architecture findings -> manual specialist review;
- Flutter/native Android -> core runtime, visual regression, lifecycle and performance.

Low/unknown source confidence adds broader source review rather than reducing
coverage.

## Output

- `audit-plan.json`
- `audit-plan.md`

Each selected lab includes priority and explicit reason evidence.

## Guardrails

1. The plan is advisory and cannot override certification requirements.
2. Uncertainty can only broaden coverage.
3. No hidden feature creation.
4. No automatic competitor data acquisition.
5. No target mutation.
6. No opaque product score.
