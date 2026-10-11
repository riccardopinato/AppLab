# AppLab v5.2.0 — Competitive Product Intelligence

## Goal

Use competitor evidence to improve product decisions without turning AppLab into a
feature-copying engine.

Competitive Product Intelligence is an advisory layer built on top of the
source-traceable Competitor & Market Lab. It combines current market evidence
with the exact product source revision, Product Bible/product-contract context
and target-user context.

## Authority boundary

- Record type: `COMPETITIVE_PRODUCT_INTELLIGENCE`
- Authority: `APPLAB_COMPETITIVE_PRODUCT_INTELLIGENCE_ADVISORY`
- Classification: `COMPETITIVE PRODUCT INTELLIGENCE`
- States: `READY`, `EVIDENCE_INCOMPLETE`, `STALE_EVIDENCE`

This layer cannot emit PASS, FAIL or CERTIFIED and cannot change FAST, FULL,
Release Assurance or Production Certification.

## Competitor-set contract

A target repository may maintain a `market-evidence.json` file. The existing
schema remains backward compatible. v5.2 additionally understands:

- `project.category`;
- `project.target_user` / `target_users` / `audience`;
- `project.competitor_set_id`;
- per-competitor `workflows[]`;
- per-competitor `onboarding[]`;
- per-competitor `visual_patterns[]`.

Every workflow, onboarding or visual-pattern observation must include a stable
key/label and an http(s) `source_url`. Existing capability, pricing, rating and
review-theme evidence keeps the v1.4 source-traceability rules.

The competitor set is project/category scoped. AppLab records its stable set id,
category, members and source URLs in the v5.2 record.

## Comparison dimensions

v5.2 compares:

1. product capabilities;
2. workflows;
3. onboarding;
4. pricing;
5. visual patterns;
6. recurring user pain points.

No opaque competitive score or ranked winner is generated.

## Common expectations

A capability/pattern becomes a common market expectation only when at least two
competitors are present and at least half of the supplied competitor set exposes
the same normalized signal.

This threshold is descriptive evidence, not a mandate.

## Relevant parity

A common competitor capability missing from bounded project source evidence is
not automatically a product gap.

It becomes `RELEVANT_PARITY_REVIEW` only when both are true:

- Product Bible/product-contract documentation mentions or promises the
  capability; and
- target-user context is explicitly declared in market evidence or bounded
  product documentation.

Otherwise AppLab records either
`NOT_PRODUCT_CONTRACT_RELEVANT` or
`TARGET_USER_CONTEXT_INCOMPLETE` and does not treat the capability as a product
requirement.

## Differentiation

Project capabilities observed in fewer than half of the competitor set become
bounded differentiation opportunities. The route is
`PROTECT_DIFFERENTIATOR`: verify the value before standardizing it away.

## Competitor weaknesses

A negative review theme becomes a market weakness only through the existing
cross-competitor recurring-pain rule. v5.2 converts that signal into a
`MARKET_WEAKNESS_OPPORTUNITY` with route `CONSIDER`.

The intended interpretation is: avoid or simplify the recurring weakness.
AppLab never recommends copying the competitor implementation.

## Freshness

Market evidence is evaluated against an explicit `as_of` date and a default
maximum age of 120 days.

States:

- `FRESH`: all dated evidence is within the freshness window;
- `PARTIAL_STALE`: at least one observation is stale or lacks a date;
- `STALE_EVIDENCE`: all known dated evidence exceeds the window;
- `EVIDENCE_INCOMPLETE`: no usable observation date exists.

Stale evidence stays visible but must be refreshed before product decisions rely
on it.

## Exact product identity

The competitive record is bound to Evidence Graph v2 and therefore to:

- repository;
- immutable source SHA;
- trusted workflow run;
- package id;
- exact APK SHA-256;
- version name;
- version code.

Studio rejects stale/mismatched records and projects them as
`EVIDENCE_INCOMPLETE`.

## Trusted-review behavior

True Autonomous Review looks for the configured target-relative market evidence
path (default `market-evidence.json`).

If the file exists, it is consumed. If it does not exist, v5.2 still emits a
valid `EVIDENCE_INCOMPLETE` advisory record so lack of market research never
breaks technical verification.

The trusted review does not scrape the web. External research must first be
captured as source-traceable market evidence.

Outputs:

- `competitive-product-intelligence.json`;
- `competitive-product-intelligence.md`.

## Guardrails

v5.2 guarantees:

- advisory-only output;
- no release verdict;
- no automatic feature addition;
- no competitor feature copying;
- parity requires product-contract and target-user relevance;
- source URLs are required for competitive facts;
- freshness remains explicit;
- missing market evidence fails closed as `EVIDENCE_INCOMPLETE`;
- technical verification authorities remain independent.
