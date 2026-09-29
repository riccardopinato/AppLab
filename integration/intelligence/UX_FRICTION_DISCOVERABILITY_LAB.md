# AppLab v3.4 — UX Friction & Discoverability Lab

v3.4 interprets trusted journey evidence as UX review signals without producing a
synthetic UX score.

## Inputs

The lab consumes:

- trusted User Journey Intelligence;
- Product Flow roles and surfaces;
- State & Edge-Case coverage.

## Runtime-backed friction signals

### Feedback

`STABLE_SIGNATURE_AFTER_ACTION_CANDIDATE` is emitted when a safe trusted-runtime
interaction leaves the crawler's reduced stable signature unchanged.

The signature normalizes digits and does not encode every visual/accessibility
state (for example selected/checked state), so this remains a REVIEW candidate
and never means that user-visible feedback is proven absent.

Repeated no-change actions can produce
`REPEATED_STABLE_SIGNATURE_PATTERN`.

### Navigation

A repeated target is exposed as `NAVIGATION_LOOP_CANDIDATE` only when the
observed successful-transition graph contains a path from that target back to
the source, establishing an actual observed cycle rather than mere convergence.

Observed journeys of depth three or greater may produce
`DEEP_JOURNEY_CANDIDATE`, except obvious settings/profile/help-style paths.
Depth alone is never treated as a defect.

### Density

An observed UI hierarchy with twelve or more clickable nodes produces
`HIGH_CLICKABLE_DENSITY_CANDIDATE`.

This is an inspectable heuristic only; clickable-node count does not prove visual
clutter.

### Discoverability

If the same visible safe-action label from one observed state leads to multiple
runtime states, AppLab emits `AMBIGUOUS_RUNTIME_ACTION_LABEL`.

Core-role static surfaces (home/search/editor/onboarding) that remain unmatched in
bounded journey evidence produce
`CORE_SURFACE_DISCOVERABILITY_UNVERIFIED`.

This does not mean the screen is unreachable.

### Recovery / edge states

Applicable empty, error or permission-denied UX states that were not observed are
surfaced as `UX_EDGE_STATE_UNVERIFIED`.

## Decision Brief

UX friction findings never auto-escalate to FIX_NOW.

REVIEW findings enter VERIFY_NEXT. Informational candidates enter IMPROVE.

A true runtime crash remains owned by the runtime/journey evidence chain and can
still become FIX_NOW through the existing high-confidence runtime rules.

## Metrics

The lab exposes measurable evidence such as runtime transition count,
no-change-action count and no-change share. These are diagnostics, not quality
scores.

## Guardrails

1. No numeric UX score.
2. No-change action means review, not defect.
3. Clickable density and journey depth are candidate heuristics only.
4. Unobserved core surfaces are not declared unreachable.
5. UX findings cannot override FAST/FULL/CERTIFICATION.
