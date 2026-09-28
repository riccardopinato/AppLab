# AppLab v2.3 — Product Consistency Engine

v2.3 consolidates product-intelligence evidence into one traceable consistency
layer. The engine does not invent a product score and does not convert review
signals into runtime failures.

## Inputs

The consistency engine consumes deterministic evidence already produced by:

- Product Analysis
- Feature Truth
- Deep Product Model
- Product Flow Graph
- UX & Product Lab
- Architecture & Data Intelligence

## Normalized review domains

### Product truth
Documentation/source drift and capabilities supported only by documentation or
test evidence are normalized into explicit review findings.

### Lifecycle
Entity lifecycle gaps are carried forward with subject and source evidence.

### Product flow
Candidate orphan surfaces are exposed as low-confidence review targets because
dynamic routing can create valid runtime links that static analysis cannot see.

### UX
Existing UX review findings are normalized without changing their meaning.

### Architecture
Architecture findings are normalized and high-risk evidence such as possible
embedded secrets remains distinguishable as HIGH_REVIEW.

### Data / coverage
The engine can expose informational consistency signals such as remote/sync
evidence without detected local persistence, and coverage gaps where the product
surface exists but a bounded flow model could not be reconstructed.

## Finding contract

Every normalized finding contains:

- stable deterministic id
- domain
- kind
- severity
- confidence
- optional subject
- message
- bounded evidence paths

The summary reports counts by severity and domain. It deliberately does not
produce a synthetic numeric score.

## Guardrails

1. Findings are advisory review targets, not automatic defects.
2. Missing static evidence never proves missing runtime behavior.
3. Dynamic routing and generated code reduce confidence rather than creating
   false certainty.
4. The engine never changes FAST/FULL/CERTIFICATION decisions.
5. The target repository remains read-only.
6. No feature request is generated automatically from a finding.
