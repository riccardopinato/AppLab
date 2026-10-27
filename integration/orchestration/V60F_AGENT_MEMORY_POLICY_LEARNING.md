# AppLab v6.0F — Agent Memory & Policy Learning

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

## Goal

Give AppLab useful engineering memory without creating a second canonical database and without allowing accumulated history to rewrite policy or manufacture present-tense causal evidence.

v6.0F derives a compressed, rebuildable episodic view from v5.8A failure triage and v6.0B/v6.0C/v6.0D causal, repair, and verification evidence. Source records remain authoritative.

## Safety model

Memory authority is **ADVISORY_RANKING_ONLY**. Historical evidence may reorder candidates that already exist in the current investigation, but it cannot add a causal candidate, raise autonomous-edit eligibility, mutate policy/Core/guardrails, weaken verification, mint PASS/CERTIFIED, or trigger an automatic code change.

The v6.0B integration keeps historical score separate from current evidence. Candidate admission and confidence are computed from current evidence only; the historical boost is exposed independently for auditability.

## Exact successful-repair binding

A repair is remembered as successful only when a v6.0D COMPLETE / VERIFIED_PASS verdict carries a `repair_identity_sha256` that exactly matches the identity recomputed from a concrete v6.0C repair result.

This matters for multi-attempt repair loops: an earlier failed patch cannot be credited merely because a later attempt passed.

## Strategy ranking

Strategy lookup can score same-repository, classification, normalized-signature, and path-overlap history, but output is restricted to `matched_current_candidates`. Historical paths that are absent from the current causal candidate set are not introduced.

## Pattern-3 learning

Repeated stop reasons can emit a `PATTERN_3_REVIEW` observation at the configured threshold. It is a review signal only and never a policy promotion.

## Storage and provenance

There is no hidden mutable memory database. The view is deterministically derived from allowlisted versioned JSON records, capped at the contract limit, carries source references, and can be rebuilt from source evidence.

## Contract and validation

`integration/orchestration/contracts/agent-memory-v1.json` fixes advisory authority, source types, limits, Pattern-3 threshold, mandatory denials, exact repair identity binding, current-candidate-only strategy output, and the prohibition on history raising autonomy.

Contract coverage includes two-attempt repair identity binding, unbound COMPLETE verdict rejection, malformed/unrelated input rejection, weak historical-only candidate denial, strong current-evidence admission, candidate-overlap strategy ranking, and Pattern-3 observation behavior.

CI compiles and self-tests the producer and executes `tests/contracts/agent_memory_v60f_test.py`. The producer and authority contract are fingerprinted, and maintainability budget is explicitly bounded.

## Acceptance

- [x] deterministic derived/rebuildable memory;
- [x] allowlisted source records and explicit provenance;
- [x] exact final repair-identity binding;
- [x] multi-attempt success attribution;
- [x] current-candidate-only strategy ranking;
- [x] historical score separated from current causal evidence;
- [x] history cannot create candidates or raise autonomy;
- [x] Pattern-3 review observation without policy mutation;
- [x] no automatic code change or PASS/CERTIFIED authority;
- [x] CI, fingerprint, maintainability, contract tests;
- [ ] exact-head required checks GREEN;
- [ ] real repair episodes accumulated.

## Boundary

Memory improves ordering and context. It does not change truth. If source evidence and derived memory disagree, source evidence wins.
