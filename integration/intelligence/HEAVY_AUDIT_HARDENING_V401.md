# AppLab v4.0.1 — Heavy Audit Hardening

v4.0.1 converts the post-v4.0 heavy-audit findings into enforceable platform
contracts without adding a parallel verification architecture.

## Closed in code

- Live Controller binds to loopback by default in KVM/live mode.
- Maestro is installed from versioned release bytes with a pinned SHA-256; the
  backend image no longer executes a remote installer through `curl | bash`.
- External GitHub Actions are pinned to immutable commit SHAs.
- The Flutter reusable wrapper binds to the same AppLab revision instead of
  floating on `@main`.
- Longitudinal Product Intelligence records branch lineage and PR base SHA.
  Sibling branches are excluded from history comparison; an exact PR base
  snapshot can still act as baseline.
- Longitudinal pruning is lineage-aware.
- True Autonomous Review produces `studio.json` automatically from its trusted
  evidence bundle.
- Control Center and Studio backend adapters preserve forward-compatible summary
  fields instead of silently dropping newer producer metrics.
- Backend, frontend, Studio snapshot and CI health version contracts are aligned
  to 4.0.1.
- `scripts/audit_contract_test.py` makes the hardening invariants part of CI.
- Dependabot covers backend Python, frontend npm and GitHub Actions dependencies.

## Heavy-audit invariant set

Every future heavy audit must explicitly inspect:

1. repository governance and default-branch protection;
2. workflow permissions, immutable action pinning and remote installer supply chain;
3. local privileged-runtime exposure, authentication boundary and host mounts;
4. trusted/untrusted execution boundary and artifact provenance;
5. branch/commit lineage for historical or regression intelligence;
6. producer -> storage -> backend -> frontend schema preservation;
7. automatic generation/transport of Studio and Control Center evidence;
8. version/config/documentation drift;
9. independent tests versus implementation-local self-tests;
10. release artifact identity, signing and deploy/web-preview path;
11. dependency/security maintenance;
12. code concentration, duplicated pipelines, legacy paths and technical debt.

A green build is not evidence that these classes of risks were checked.

## Repository-setting blocker

GitHub branch protection/rulesets are repository settings, not repository files.
The connected repository API used by this automation does not expose a mutation
for branch protection. Until the repository setting is enabled, AppLab must report
the default branch as a governance blocker during heavy audits.

Required target state for `main`:

- require pull requests before merge;
- require the AppLab CI, Live Emulator Browser E2E, Emulator Self Test and True
  Autonomous Review checks for release-significant changes;
- block force pushes and branch deletion;
- require branches to be up to date before merge when practical.

This is the only v4.0.1 audit item that cannot be enforced by the repository
contents themselves.
