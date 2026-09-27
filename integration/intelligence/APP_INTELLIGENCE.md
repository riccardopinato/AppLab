# AppLab App Intelligence — v1.1 → v1.3

App Intelligence extends AppLab from runtime/build verification into deterministic
product understanding. It is intentionally separate from FAST/FULL/CERTIFICATION:
static product heuristics cannot certify an application and cannot weaken an
existing failure.

## v1.1 — Product Analysis Engine

The engine inventories the target repository and emits bounded source evidence for:

- detected stack and languages;
- screen-like and test-like surfaces;
- authentication;
- local persistence;
- network/API usage;
- background execution;
- notifications;
- monetization;
- analytics;
- AI/ML;
- export/backup;
- media capture;
- maps/location;
- cloud/sync.

Every capability is reported as PRESENT or NOT_DETECTED with concrete file evidence.
NOT_DETECTED never means proven absence.

## v1.2 — UX & Product Lab

The UX layer checks deterministic evidence for:

- loading, error and empty states;
- confirmations and undo;
- accessibility annotations;
- onboarding and search;
- navigation surface;
- delete/remove flows;
- trash/archive/restore lifecycle;
- cleanup of notifications/work/files after destructive actions.

Findings are advisory REVIEW signals. They do not fail runtime verification.

## v1.3 — Architecture & Data Intelligence

The architecture layer inventories:

- repository/data-source patterns;
- view model/controller/BLoC patterns;
- services/clients;
- models/entities/DTOs;
- database/DAO structures;
- local persistence, sync and offline evidence;
- direct remote SDK usage in UI-like files;
- premium-policy scattering;
- secret-like tracked material.

The local-first result is deliberately conservative:

- SUPPORTED_BY_SIGNALS
- LOCAL_PERSISTENCE_ONLY
- REMOTE_SIGNALS_WITHOUT_LOCAL_STORE_EVIDENCE
- UNKNOWN

No architecture claim is treated as ground truth without source evidence.

## Execution

Run locally:

```bash
python scripts/app_intelligence.py \
  --repo-root /path/to/project \
  --output-dir applab-intelligence
```

Run the built-in deterministic regression:

```bash
python scripts/app_intelligence.py --self-test
```

GitHub Actions:

`AppLab App Intelligence` can be started manually or reused through
`workflow_call`. It checks out the target once, runs the three analysis layers
in one bounded pass and uploads:

- `app-intelligence.json`
- `app-intelligence.md`

For private cross-repository analysis, configure the optional
`APPLAB_TARGET_TOKEN` repository secret with read access to the target.

## Guardrails

1. Evidence first; uncertainty is explicit.
2. No opaque quality score.
3. No external AI is required.
4. Source scanning is bounded by file count and file size.
5. Static findings never convert FAIL into PASS.
6. Product/UX/architecture findings are advisory until corroborated.
7. Runtime certification remains exclusively owned by CERTIFICATION.
8. The analyzer does not modify the target repository.
