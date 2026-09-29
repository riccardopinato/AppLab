# AppLab v3.3 — User Journey Intelligence

v3.3 adds trusted, bounded multi-step journey evidence.

## Safe Journey Crawler

The Trusted Verifier runs a bounded BFS-style crawler during non-FAST runtime
verification.

The crawler:

- reuses the Safe Interaction Crawler allow/deny policy;
- never selects destructive, purchase, send, publish or account-removal actions;
- resolves runtime states from UI hierarchy signatures;
- replays previously observed safe paths before exploring the next transition;
- bounds depth, state count, transition count and actions per state;
- stores screenshot/UI-hierarchy evidence for observed target states;
- marks no-change transitions, repeat targets and safe dead-end candidates;
- fails the runtime gate only when a safe action causes a real app runtime failure.

A state with no eligible safe action is only a
`SAFE_JOURNEY_DEAD_END_CANDIDATE`. It does not prove that the product has no
valid outgoing action because unsafe/unknown controls are intentionally excluded.

## User Journey Intelligence

The analysis layer reconciles:

- bounded static Product Flow nodes/edges;
- runtime states and transitions from the Safe Journey Crawler;
- runtime surface matches from Behavioral Product Lab.

Outputs include:

- observed journeys and action sequences;
- observed state/transition counts;
- maximum observed journey depth;
- no-change actions;
- loop candidates;
- safe dead-end candidates;
- static surfaces not matched in bounded runtime evidence;
- static shortest-path distances where a bounded entry root can be inferred.

## Review signals

High-confidence runtime crashes remain `HIGH_REVIEW`.

No-change safe actions and absence of runtime transitions despite a multi-surface
static graph are `REVIEW`.

Loop candidates, safe dead-end candidates and unmatched static surfaces remain
informational/low-confidence because bounded exploration cannot prove the absence
of alternate navigation.

## Trust boundary

Journey evidence is created inside the Trusted Verifier and is covered by the
Trusted Evidence Manifest before Autonomous Review consumes it.

FAST mode skips the multi-step crawler to preserve the shortest trustworthy
verification path.

No journey metric is a release verdict and no numeric UX/product score is
generated.
