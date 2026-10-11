# AppLab v5.3.0 — Virtual Product Review Council

## Goal

Combine technical QA, simulated-user, UX, accessibility, product, design and
competitive evidence into a review-meeting-like output without collapsing their
authority, uncertainty or provenance.

The Council reduces manual triage. It does not become a new certification
authority and it does not replace product ownership.

## Record contract

- Record type: `VIRTUAL_PRODUCT_REVIEW_COUNCIL`
- Authority: `APPLAB_VIRTUAL_PRODUCT_REVIEW_COUNCIL_ADVISORY`
- Classification: `VIRTUAL PRODUCT REVIEW COUNCIL`
- States: `REVIEW_REQUIRED`, `EVIDENCE_INCOMPLETE`,
  `NO_STRONG_SIGNAL`

The record is bound to Evidence Graph v2 and therefore to repository, immutable
source SHA, trusted run id, package id, exact APK SHA-256, version name and
version code.

## Canonical reviewers

The Council always runs six bounded reviewers in a stable order:

1. `QA` — technical correctness, trusted runtime evidence, contradictions and
   release-assurance blockers.
2. `UX` — observed/simulated usability friction, discoverability and journey
   risks.
3. `ACCESSIBILITY` — accessibility-specific UI evidence and evidence gaps.
4. `PRODUCT` — product-contract consistency, product risks and bounded
   opportunities.
5. `DESIGN` — design-system fit and adaptation questions.
6. `MARKET` — source-traceable parity, differentiation and recurring market
   weakness opportunities.

Each reviewer preserves:

- explicit scope;
- source records and their availability/identity state;
- missing or invalid sources;
- reviewer-level uncertainty;
- independent findings and evidence.

No numeric reviewer score or overall consensus score is produced.

## Product Review Brief

The Council emits five priority buckets:

- `FIX_NOW` — existing high-confidence technical/runtime action only;
- `VERIFY_NEXT` — contradictions, missing evidence, blocked assurance or
  uncertain risks requiring verification;
- `IMPROVE` — bounded usability, accessibility, design or product improvement;
- `CONSIDER` — product/market/design opportunities that require owner judgment;
- `NO_ACTION` — evidence explicitly supports leaving the item unchanged.

A non-QA reviewer can never create a `FIX_NOW` item. If an advisory finding
would otherwise be escalated there, the Council demotes it to
`VERIFY_NEXT`.

## Cross-review reasoning

Findings are grouped by normalized subject.

`CROSS_REVIEW_AGREEMENT` is emitted when at least two different reviewers
independently raise an actionable item about the same subject.

`CROSS_REVIEW_ACTION_CONTRADICTION` is emitted when one reviewer recommends
action while another has `NO_ACTION` for the same subject.

Contradicted subjects are never left in `FIX_NOW`, `IMPROVE` or
`CONSIDER`; they are routed to `VERIFY_NEXT` until the contradiction is
resolved.

All contributing reviewer positions and evidence remain visible.

## Evidence classes that stay separate

The Council exposes but does not merge these evidence classes:

### Real-user validation

Simulated Human QA is never relabeled as real-user evidence. Unless explicit
real-user evidence is introduced by a future governed contract, this class is
`NOT_PROVIDED`.

### Physical-device validation

Physical evidence is projected separately from `physical-evidence.json` when
available. Emulator or simulated evidence cannot substitute for it.

### Release certification

Certification/release state is projected separately from certification or
Release Reality evidence. Council state cannot change certification.

## Reviewer inputs

The Council reuses existing AppLab evidence instead of duplicating labs:

- `decision-brief.json`
- `evidence-confidence.json`
- `release-assurance.json`
- `simulated-human-qa.json`
- `ux-friction.json`
- `design-system-advisor.json`
- `product-contract-audit.json`
- `competitive-product-intelligence.json`
- `physical-evidence.json`
- `release-reality.json`
- `certification.json`

Inputs carrying an exact-artifact identity must match the current Evidence
Graph. Identity mismatch becomes missing/invalid reviewer evidence.

## Missing evidence

Missing evidence is not a passing result.

If the Council has no actionable findings but one or more reviewer scopes lack
their required evidence, the overall state is `EVIDENCE_INCOMPLETE`, not
`NO_STRONG_SIGNAL`.

## Studio

`studio_review_council.py` validates:

- record schema/version/type/authority/classification;
- deterministic record digest;
- exact Evidence Graph identity;
- canonical reviewer set and order;
- reviewer scope and uncertainty;
- canonical Product Review Brief buckets;
- QA-only `FIX_NOW` authority;
- all authority-separation guardrails.

Invalid or stale records fail closed in Studio as `EVIDENCE_INCOMPLETE`.

The Control Center surfaces:

- Council state;
- reviewer/evidence coverage;
- cross-review agreement and contradiction counts;
- FIX_NOW / VERIFY_NEXT / IMPROVE / CONSIDER counts;
- top prioritized items.

## Trusted review

True Autonomous Review builds the Council only after:

- Evidence Graph;
- Simulated Human QA;
- Design System & UI Library Advisor;
- Competitive Product Intelligence;
- trusted release evidence binding;
- Autonomous Release Assurance.

This ordering lets the Council consume the complete governed evidence set for
the exact reviewed artifact.

Outputs:

- `virtual-product-review-council.json`
- `virtual-product-review-council.md`

## Guardrails

v5.3 guarantees:

- advisory-only Council output;
- no release verdict;
- no opaque numeric consensus score;
- preserved reviewer scope and uncertainty;
- FIX_NOW only from existing technical/runtime evidence;
- simulated users never become real-user evidence;
- physical-device validation stays independent;
- release certification stays independent;
- missing evidence fails closed;
- Council output reduces triage but never replaces final product ownership.
