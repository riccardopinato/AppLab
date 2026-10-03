# AppLab v4.0.2 — Residual Hardening

v4.0.2 closes the residual P2 items left after the v4.0.1 heavy-audit remediation.

## Longitudinal history retention

True Autonomous Review runs automatically once per month against `main`.
Because every successful trusted review restores and republishes the repository-
scoped longitudinal artifact with 90-day retention, the history is refreshed
well before expiry without introducing a second persistence mechanism.

The 20-snapshot bound and branch-lineage filtering remain unchanged.

## Independent intelligence regression corpus

`integration/intelligence/intelligence-regression-corpus.json` is an external
oracle for the Longitudinal -> Experiment Planner -> Analyst chain.

`tests/intelligence/intelligence_corpus_test.py` imports the production engines
but keeps the input and expected states outside their implementation-local
`--self-test` blocks.

The corpus currently verifies both:
- a returned navigation finding becoming a longitudinal regression candidate,
  high-priority experiment and Analyst VERIFICATION_REQUIRED state;
- a stable trusted product remaining STABLE / NO_EXPERIMENTS_REQUIRED /
  NO_IMMEDIATE_ACTION.

## Security scanning

AppLab CI blocks on:
- `pip-audit 2.10.1` for backend Python requirements;
- `npm audit --audit-level=high` for frontend dependencies.

A separate pinned CodeQL workflow analyzes:
- Python;
- JavaScript/TypeScript.

Dependabot from v4.0.1 remains active for pip, npm and GitHub Actions.

## Maintainability control

Large legacy modules are not rewritten solely because they are large.
`scripts/maintainability_budget.py` instead places explicit growth ceilings on
the highest-cost files. Crossing a ceiling requires extraction/refactor before
additional logic is accepted.

This turns an uncontrolled P2 growth risk into a governed maintenance constraint.

## Legacy workflow naming

Historical filenames are retained only when renaming could break external callers.
`integration/CANONICAL_WORKFLOWS.md` defines current authority and compatibility
status. Current display names/report versions must track the platform even when a
filename contains a historical version.

## Read-only Web Preview

The public Web Preview is a separate security mode:

- `VITE_APPLAB_READ_ONLY=true`;
- static Control Center / Studio preview fixtures;
- no backend controller;
- no Docker socket;
- no KVM;
- no ADB;
- no APK upload;
- no process/device mutation.

`.github/workflows/web-preview.yml` builds and deploys this mode to GitHub Pages.
The normal local frontend remains connected to the localhost-only privileged
controller.

The preview fixtures explicitly identify themselves as non-live evidence and must
never be interpreted as current trusted audit data.

## Repository governance

`.github/workflows/repository-governance-audit.yml` verifies that `main` is
protected and reports failure otherwise.

Actual branch protection is still a GitHub repository setting. Repository files
can detect the missing setting but cannot grant the administration permission
needed to enable it.

## Definition of Done

v4.0.2 is complete only when:
- AppLab CI passes, including dependency audits and independent corpus;
- CodeQL passes;
- Browser E2E passes;
- Emulator Self Test passes;
- True Autonomous Review passes;
- repository governance audit reports protected `main`;
- Web Preview deploy is operational.
