# AppLab v2.2 — Product Flow & Feature Truth

v2.2 improves the precision of AppLab's product understanding. It separates
capability evidence by provenance and reconstructs a bounded static graph between
detected product surfaces.

The layer remains advisory. It does not alter FAST/FULL, runtime PASS/FAIL or
production CERTIFICATION.

## Feature Truth

Existing Product Analysis signals are classified by evidence provenance:

- `CODE_CONFIRMED` — at least one bounded implementation-code signal;
- `CONFIG_SIGNAL` — configuration/manifest/package evidence only;
- `TEST_ONLY_SIGNAL` — test evidence only;
- `DOC_ONLY_SIGNAL` — documentation evidence only;
- `NOT_DETECTED` — no bounded evidence.

This distinction prevents a README, roadmap or configuration file from being
presented with the same evidentiary strength as implementation code.

Feature Truth does not prove behavioral correctness. A code-confirmed capability
can still be incomplete or broken at runtime.

## Product Flow Graph

AppLab uses the surfaces reconstructed by the Deep Product Model and searches for
bounded static references between them.

The report contains:

- surface nodes;
- bounded reference edges;
- route/path literals found in navigation-like sources;
- candidate orphan surfaces with no detected incoming surface reference.

Candidate orphans are review signals only. Dynamic routing, dependency injection,
reflection, generated routes and platform navigation can create valid runtime
edges that static heuristics do not see.

## Output

`app-intelligence.json` remains schema version 1 and gains optional:

- `feature_truth`
- `product_flow_graph`

AppLab Studio summarizes:

- code-confirmed capability count;
- documentation-only capability count;
- flow node/edge counts;
- orphan-surface review count.

## Guardrails

1. Provenance strength is descriptive, not a quality score.
2. Documentation-only does not mean fake; it means implementation was not found
   in the bounded scan.
3. Orphan candidates do not prove unreachable UI.
4. Dynamic navigation ambiguity must broaden review, never create false certainty.
5. Runtime/certification evidence remains authoritative for behavioral claims.
6. Target repositories remain read-only.
