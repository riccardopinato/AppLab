# AppLab v6.0F — Agent Memory & Policy Learning

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

v6.0F adds no generic memory database. It builds a rebuildable episodic view from triage, causal investigation, repair attempts, v6.0D decisions and immutable evidence references.

Each episode preserves repository/source SHA, failure signature/class, surfaces, candidate files, successful and failed repair patterns, regression targets, evidence refs and digests of source records.

Query ranking prefers exact failure signatures, same repository, failure class, surface/file overlap and successful prior repairs. Cross-repository retrieval is disabled by default and is explicitly marked advisory when enabled.

Memory authority is `ADVISORY_STRATEGY_RANKING_ONLY`: it cannot mint verification results, change policy, modify guardrails or block verification when missing/stale.

## Acceptance

- [x] versioned episodic contract;
- [x] derived/rebuildable memory;
- [x] successful and failed approaches retained;
- [x] source/evidence provenance retained;
- [x] repository-local retrieval by default;
- [x] explicit cross-repo advisory mode;
- [x] zero policy/guardrail/verdict authority;
- [x] CI/self-test wiring;
- [ ] exact-head required checks GREEN;
- [ ] real repair history accrues episodes.
