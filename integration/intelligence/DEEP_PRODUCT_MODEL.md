# AppLab v2.1 — Deep Product Model

The Deep Product Model extends App Intelligence from capability detection into a
bounded reconstruction of the product's domain surface.

It remains advisory and source-evidence based. It never changes FAST/FULL,
runtime PASS/FAIL or production CERTIFICATION.

## What it reconstructs

### Product entities

AppLab inspects tracked source in model/domain/data/database/schema-like areas
and extracts bounded entity candidates from class, data-class, struct, interface
and enum declarations.

For every candidate it records declaration evidence and searches for lifecycle
signals:

- create / insert / add / save / upsert;
- update / edit / modify;
- delete / remove;
- archive / trash / soft-delete;
- restore / recover;
- ownership / sharing / ACL.

A mutable entity with create/update evidence but no bounded delete/archive/
restore evidence emits `ENTITY_LIFECYCLE_DELETE_GAP`.

This is a review target, not proof that deletion is impossible.

### Product surfaces

Screen/page/view/activity/fragment/route-like files are inventoried and assigned
light roles when the path supports them, such as onboarding, home, search,
settings, profile, detail or editor.

The surface map is descriptive. It does not infer a complete navigation graph.

### Documentation drift

AppLab compares bounded product documentation signals with deterministic source
capabilities already detected by Product Analysis.

Two evidence classes are emitted:

- `DOC_CLAIM_WITHOUT_SOURCE_SIGNAL` — documentation mentions a capability but
  the bounded source scan did not find matching implementation evidence;
- `SOURCE_SIGNAL_WITHOUT_DOC_CLAIM` — implementation evidence exists but the
  bounded product documentation does not mention it.

Only the first is counted as a review-level documentation drift signal.

## Output contract

`app-intelligence.json` keeps schema version 1 for backward compatibility and
adds the optional `deep_product_model` object:

- `entity_count`
- `entities[]`
- `surface_count`
- `surfaces[]`
- `lifecycle_findings[]`
- `documentation_drift[]`
- `summary.lifecycle_review_signals`
- `summary.documentation_drift_signals`

AppLab Studio v2.1 surfaces the aggregate entity and review counts without
turning them into an opaque score.

## Guardrails

1. Missing static evidence never proves absence.
2. Entity names are bounded heuristics, not a canonical domain model.
3. Findings never mutate the target repository.
4. Product intelligence stays separate from trusted runtime evidence.
5. Uncertainty produces review targets, never automatic feature requests.
6. Existing v1.x App Intelligence consumers remain compatible.
