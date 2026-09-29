# AppLab v3.2 — Evidence Confidence & Contradiction Engine

v3.2 adds a single evidence graph above App Intelligence, Product Contract,
trusted runtime, UI hierarchy, state coverage and calibrated findings.

The engine does not create a numeric quality/confidence score.

## Claim states

Every normalized product claim is classified as one of:

- `CONFIRMED` — independent strong evidence or direct trusted runtime supports it;
- `CORROBORATED` — multiple compatible bounded sources agree, but direct runtime
  confirmation is incomplete;
- `CONTRADICTED` — strong bounded evidence sources disagree about the same
  product subject;
- `UNVERIFIED` — evidence is missing, weak or incomplete;
- `STALE` — the evidence is explicitly bound to a different source revision.

## Evidence domains

The first v3.2 graph normalizes:

- product capabilities and Feature Truth provenance;
- Product Contract claim status;
- trusted runtime verification state;
- static Product Flow surfaces;
- surfaces observed through trusted UI hierarchy;
- applicable runtime states;
- calibrated static/runtime findings.

## Deterministic contradictions

Examples include:

- capability promised by the Product Contract but not detected in implementation;
- capability explicitly excluded by the Product Contract but confirmed in code;
- static orphan-surface candidate directly observed at runtime;
- calibrated static finding explicitly contradicted by trusted runtime.

Contradiction means "the evidence sources disagree". It is not itself a release
failure and never overrides FAST/FULL/CERTIFICATION.

## Stale evidence

Where a source revision is explicitly available, evidence bound to a SHA different
from the current trusted target is classified `STALE`.

Missing revision metadata is never silently treated as stale or current.

## Studio

AppLab Studio exposes:

- total evidence claims;
- confirmed / corroborated / contradicted / unverified / stale counts;
- explicit contradiction count;
- top contradiction subjects.

## Guardrails

1. No synthetic numeric score.
2. Missing evidence never becomes PASS.
3. Contradictions preserve all source evidence.
4. Trusted runtime has the strongest direct observational authority, without
   deleting contradictory static/documentary evidence.
5. A contradiction produces review work, not an automatic product decision.
6. Production certification remains independent and authoritative.
