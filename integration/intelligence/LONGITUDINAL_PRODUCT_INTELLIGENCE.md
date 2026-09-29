# AppLab v3.5 — Longitudinal Product Intelligence

Longitudinal Product Intelligence compares successive trusted Autonomous Review
snapshots for the same repository and explains how product evidence evolves over
time.

It complements Change Intelligence v2.4 rather than replacing it:

- Change Intelligence compares two App Intelligence snapshots.
- Longitudinal Product Intelligence tracks findings, evidence claims and product
  changes across a bounded review history.

## Inputs

Each run consumes:

- the current `autonomous-review.json`;
- up to 20 prior review snapshots for the same repository;
- repository, resolved SHA and workflow run metadata.

The v3.1 trusted autonomous-review workflow restores the latest repository-scoped
history from GitHub Actions cache, runs the v3.5 engine, then saves the new
snapshot only after the trusted product review succeeds.

## Finding identity

A finding is tracked with a deterministic identity based on its evidence source
plus stable id when available, otherwise:

`source + domain + category + kind + subject`.

Messages and evidence paths are not part of identity because they may legitimately
change between revisions.

## Lifecycle states

For the immediately previous snapshot, AppLab classifies findings as:

- **new** — present now, absent from every available prior snapshot;
- **returned** — present now, absent in the immediately previous snapshot, but
  observed earlier;
- **persistent** — present in both current and previous snapshot;
- **resolved** — present previously but absent now.

"Resolved" means only that the current bounded evidence no longer emits the
finding. It is not proof that runtime behavior was fixed.

Persistent findings also expose severity transitions. A transition toward
`HIGH_REVIEW` or `REVIEW` is surfaced as a severity escalation.

## Evidence claim transitions

Evidence Confidence claims keep their deterministic identity across snapshots.
v3.5 reports status changes such as:

- UNVERIFIED → CORROBORATED;
- CORROBORATED → CONFIRMED;
- CONFIRMED → CONTRADICTED;
- any state → STALE.

The engine reports the transition without assigning a synthetic probability.

## Product change reuse

When a previous snapshot exists, v3.5 calls the existing Change Intelligence
engine on the two App Intelligence snapshots. Capability, entity, surface and
consistency deltas therefore retain the existing v2.4 semantics.

A disappeared capability is only a **regression candidate**. Intentional product
removal remains possible and requires review.

## Longitudinal state

The engine emits one advisory state:

- `INSUFFICIENT_HISTORY` — first usable snapshot;
- `STABLE` — no tracked movement;
- `CHANGED` — evidence changed without a regression candidate;
- `REGRESSION_REVIEW` — a finding returned, a persistent finding escalated, or
  previously detected capability evidence disappeared.

This state never changes runtime PASS/FAIL, FAST/FULL selection or CERTIFICATION.

## Outputs

The autonomous review artifact adds:

- `longitudinal-intelligence.json`
- `longitudinal-intelligence.md`

The rolling cache stores review snapshots separately from the artifact and keeps
at most 20 per repository.

AppLab Studio surfaces history depth, baseline SHA, new/returned/persistent/
resolved counts, severity escalations and top regression candidates.

## Guardrails

1. No numeric product or quality score.
2. Historical evidence never overrides current trusted evidence.
3. Regression candidates require review; they are not automatic defects.
4. Resolved findings are not proof of a runtime fix.
5. Capability removal is not automatically a regression.
6. History is repository-scoped and bounded.
7. Release verdicts and production certification remain independent.
