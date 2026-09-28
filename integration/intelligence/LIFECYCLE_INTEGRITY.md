# AppLab v2.5 — Lifecycle Integrity

Lifecycle Integrity deepens the entity model introduced by the Deep Product
Model. The goal is not to assume that every entity must support deletion; it is
to make destructive semantics and side-effect cleanup explicit and reviewable.

## Entity-level checks

For every bounded domain entity AppLab evaluates:

- delete evidence
- archive / trash evidence
- restore / recovery evidence
- cascade / relationship cleanup evidence
- media / attachment associations and cleanup
- reminder / alarm / notification scheduling and cancellation
- remote / cloud / sync participation and delete propagation
- ownership / membership / workspace semantics

## Review signals

Examples include:

- `HARD_DELETE_WITHOUT_REVERSIBLE_PATH`
- `POSSIBLE_MEDIA_CLEANUP_GAP`
- `POSSIBLE_SCHEDULER_CLEANUP_GAP`
- `POSSIBLE_REMOTE_DELETE_GAP`
- `SHARED_DELETE_SEMANTICS_REVIEW`

These are bounded static review targets. They do not prove that cleanup or policy
is missing at runtime.

## Why this exists

A product can expose a visible Delete action while still leaving orphaned media,
scheduled work, notifications, remote records or ambiguous shared-content
ownership. Lifecycle Integrity makes those dependencies inspectable at the same
entity granularity as the product model.

## Studio

AppLab Studio exposes:

- entities checked
- entities with lifecycle review
- lifecycle review-signal count
- lifecycle findings are also normalized into Product Consistency

## Guardrails

1. No universal delete policy is assumed.
2. Hard delete is not automatically considered incorrect.
3. Missing static cleanup evidence is not proof of missing runtime cleanup.
4. Shared-content semantics require product-specific review.
5. Findings remain advisory and cannot alter trusted runtime PASS/FAIL.
6. Production CERTIFICATION remains independent.
