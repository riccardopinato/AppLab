# AppLab v5.1.0 — Design System & UI Library Advisor

## Goal

Evaluate whether an application's visual language and component-library choices fit the product context and interaction style. The advisor exists to prevent one-size-fits-all UI decisions: it does not assume Material, Cupertino, custom UI or a third-party library is universally superior.

## Authority boundary

- Record type: `DESIGN_SYSTEM_UI_LIBRARY_ADVISOR`
- Authority: `APPLAB_DESIGN_SYSTEM_ADVISOR_ADVISORY`
- Classification: `DESIGN SYSTEM ADVISORY`
- Allowed recommendations: `KEEP`, `ADAPT`, `REPLACE_CANDIDATE`, `EVIDENCE_INCOMPLETE`

The advisor is product/design evidence only. It cannot mint PASS, FAIL or CERTIFIED; cannot override FAST/FULL/CERTIFICATION; and cannot turn aesthetic preference into a defect.

## Evidence and identity

The advisor runs against the exact immutable target checkout used by True Autonomous Review and consumes the current evidence directory. It requires Evidence Graph v2 and binds its record to:

- repository;
- immutable source SHA;
- trusted workflow run;
- package id;
- exact APK SHA-256;
- version name;
- version code.

Malformed or mismatched identity fails closed.

The source scan is bounded and deterministic. Missing source evidence becomes `EVIDENCE_INCOMPLETE`; it is never interpreted as proof that a design capability is absent.

## Product context first

Before judging visual-system fit, AppLab infers a bounded product category and interaction style from App Intelligence plus tracked source evidence. Current categories include general utility, productivity, journal/lifestyle, map/outdoor, media/creative and developer/pro-tool patterns.

This context is descriptive, not a permanent product label. Its purpose is to avoid applying the same density, expressiveness or platform conventions to every app.

## UI-system detection

The advisor can identify bounded evidence for:

- Flutter Material / Material 3;
- Flutter Cupertino;
- Compose Material 3 / Android Material;
- common web libraries including MUI, Ant Design, Chakra, Mantine, Radix/shadcn, Tailwind and Bootstrap;
- custom token/component layers.

Detection means evidence was found. Non-detection does not prove absence.

## Review dimensions

Every record contains the canonical twelve dimensions:

1. hierarchy;
2. typography;
3. spacing;
4. density;
5. component consistency;
6. feedback;
7. empty/loading/error states;
8. interaction affordances;
9. accessibility;
10. responsive behavior;
11. dark mode;
12. localization.

Each dimension is `FIT`, `REVIEW`, `EVIDENCE_INCOMPLETE` or `NOT_APPLICABLE`, with traceable source evidence.

The review deliberately evaluates accessibility, responsive behavior, dark mode and localization together with visual fit rather than treating them as post-design checks.

## Recommendation semantics

### KEEP

No concrete mismatch justifies a library change. Preserve the current system and avoid style churn.

### ADAPT

The current system remains viable, but evidence supports targeted changes to tokens, density, components, states, responsive behavior or product expression.

### REPLACE_CANDIDATE

Replacement may be evaluated only when AppLab sees a concrete product-fit concern together with meaningful UI-system fragmentation. This is a candidate for investigation, not an automatic migration request.

### EVIDENCE_INCOMPLETE

There is not enough trustworthy evidence to recommend a change.

A different library is never considered an improvement merely because it is different or newer.

## App Factory alignment

For Flutter products, Material 3 remains a strong default baseline where appropriate, but v5.1 explicitly treats it as a baseline rather than a universal aesthetic answer. Consumer, creative or high-density products can require adaptation while retaining accessibility, responsiveness, localization resilience and platform fit.

App Factory Golden UI rules remain evidence inputs and constraints; the advisor does not convert a Golden into a mandatory cross-product visual style.

## Studio

`studio_design_advisor.py` validates the record, deterministic digest, canonical dimensions, guardrails and exact Evidence Graph identity before projection.

Invalid or identity-mismatched records become `EVIDENCE_INCOMPLETE`. Studio exposes:

- product context and interaction style;
- primary detected UI system;
- recommendation;
- fit/review/incomplete dimension counts;
- top advisory findings;
- record validation errors.

## True Autonomous Review integration

The trusted review pipeline builds the advisor after Evidence Graph and Simulated Human QA while the exact reviewed source checkout is still available. It writes:

- `design-system-advisor.json`;
- `design-system-advisor.md`.

The markdown report is included in the workflow summary and the JSON record enters the normal Studio-ready evidence bundle.

## Guardrails

v5.1 guarantees:

- advisory-only output;
- no release verdict;
- no numeric aesthetic score;
- no automatic library replacement;
- no style churn by novelty;
- recommendations require observed evidence;
- missing evidence fails closed;
- source evidence remains authoritative;
- deterministic core with no external AI dependency.

## Validation

The milestone is protected by:

- `design_system_advisor.py --self-test`;
- `studio_design_advisor.py` self-test;
- AppLab CI compile/self-test gates;
- audit-contract invariants;
- workflow-contract invariants;
- frontend build/type validation;
- normal trusted runtime and repository-governance checks.
