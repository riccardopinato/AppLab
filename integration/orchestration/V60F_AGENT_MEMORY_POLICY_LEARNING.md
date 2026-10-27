# AppLab v6.0F — Agent Memory & Policy Learning

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

## Goal

Give AppLab useful engineering memory without creating a second canonical
database and without allowing accumulated history to rewrite policy.

v6.0F derives a compressed episodic view from evidence already produced by:

- v5.8A failure triage;
- v6.0B causal investigation;
- v6.0C bounded repair;
- v6.0D verify-repair verdicts.

The source records remain authoritative.

## Memory shape

Each episode keeps only engineering facts useful for future diagnosis:

- repository;
- WorkItem identity;
- failure classifications/signatures;
- causal candidate files;
- files actually changed;
- required regression evidence;
- verified-pass / stopped / incomplete outcome;
- stop reasons;
- exact source references.

The derived view is capped and exposes truncation explicitly.

## Successful repair view

Verified episodes produce a compact `successful_repairs` view compatible with
the v6.0B historical-path signal:

```
failure
 -> prior successful repair files
 -> candidate overlap
 -> higher causal ranking
```

This is a ranking signal only. A past repair never authorizes a new edit.

## Strategy ranking

`rank_strategies` scores prior verified episodes using:

- same repository;
- same failure classification;
- exact prior normalized failure signature;
- candidate-path overlap.

Results contain source references and required regressions so a future agent can
inspect the original evidence rather than trusting a memory summary blindly.

## Policy learning

Repeated stop reasons are counted.

At the third occurrence the memory emits:

`PATTERN_3_REVIEW`

This is only a review observation. It does not:

- modify AGENTS;
- modify App-Factory-Core;
- modify guardrails;
- promote a Golden;
- change verifier coverage;
- authorize code edits.

Any real policy change still follows the normal Factory branch/validation/PR
process.

## No new database

v6.0F scans versioned JSON evidence/history and builds a derived JSON view.

There is no new mutable memory store or hidden truth layer.

That keeps restart/rebuild semantics simple:

`source evidence -> derive memory again`.

## Authority contract

`integration/orchestration/contracts/agent-memory-v1.json` fixes:

- advisory-only authority;
- allowlisted record types;
- maximum episode count;
- Pattern-3 threshold;
- mandatory denials.

## Acceptance

- [x] source-record allowlist;
- [x] deterministic derivation;
- [x] explicit source provenance;
- [x] verified repair extraction;
- [x] exact-signature / classification / path-overlap ranking;
- [x] Pattern-3 observations;
- [x] no automatic policy mutation;
- [x] no automatic code change;
- [x] no PASS/CERTIFIED authority;
- [x] malformed/unrelated records ignored;
- [x] memory truncation explicit;
- [x] CI/fingerprint/maintainability integration;
- [ ] exact-head required checks GREEN;
- [ ] real repair episodes accumulated.

## Boundary

Memory improves ordering and context. It does not change truth.

If source evidence and memory disagree, source evidence wins.
