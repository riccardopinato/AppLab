# AppLab v4.6 — Evidence Graph 2

AppLab v4.6 evolves the v4.2 Evidence Graph from a unified evidence index into
a temporal, freshness-aware and change-impact query layer.

It remains a **derived index**. Source reports, trusted runtime, certification,
Release Reality and Physical Evidence remain authoritative for their domains.

## Version

- Evidence Graph schema: `2`
- Engine: `4.6.0`
- Graph contract: `2.0`

The original v4.2 node model is preserved and extended with two structural node
types:

- `File`
- `Component`

A Component is a deterministic repository-path grouping. It is not an inferred
business architecture or behavioral claim.

## Temporal finding lifecycle

Evidence Graph 2 imports Longitudinal Product Intelligence lifecycle state and
represents findings as:

- `FIRST_OBSERVED`
- `PERSISTENT`
- `RETURNED`
- `RESOLVED`
- `ACTIVE` when no stronger lifecycle classification is available

Resolved findings remain queryable as historical graph nodes.

Temporal relations include:

- `REVISION_FIRST_OBSERVED_FINDING`
- `REVISION_PERSISTS_FINDING`
- `REVISION_RETURNED_FINDING`
- `REVISION_HAD_FINDING`
- `REVISION_OBSERVED_RESOLUTION`

### Non-causal rule

`first_observed_sha` means the first revision where AppLab observed the finding.

`resolution_observed_sha` means the first current comparison where the finding
was observed absent relative to the compatible baseline.

Neither value is proof that the corresponding commit introduced or fixed the
behavior. Evidence Graph explicitly records `causal_attribution=NOT_INFERRED`.

## Evidence freshness

Reference evidence is classified as:

- `CURRENT` — current-revision evidence or a current claim observation;
- `HISTORICAL` — evidence carried from an earlier longitudinal observation;
- `STALE` — evidence explicitly bound to a different revision or already
  classified stale by Evidence Confidence;
- `INVALIDATED` — historical/stale evidence whose referenced file intersects
  the current changed/dependency-impact set.

Selective invalidation is intentional.

A file changing does **not** automatically invalidate a new current-revision
observation of that same file. For example, `lib/auth.dart` can be changed and
simultaneously provide fresh current evidence, while a prior historical
observation of `lib/auth.dart` may be invalidated.

When invalidation occurs the graph records:

`CHANGE_INVALIDATES_EVIDENCE`

with the exact affected file and a non-causal reason.

## Impact graph

The current trusted `analysis-plan.json` supplies the changed and
dependency-impacted file set.

Evidence Graph 2 maps only bounded, observed relationships.

Canonical structural path:

```
File
  ↓ FILE_IN_COMPONENT
Component
  ↓ COMPONENT_SUPPORTS_CAPABILITY
Capability
  ↓ CAPABILITY_OBSERVED_ON_SURFACE
Surface
  ↓ SURFACE_IN_JOURNEY
Journey
  ↓ DERIVED_FROM
Evidence
```

Supporting relations also include:

- `REVISION_CHANGED_FILE`
- `REVISION_IMPACTS_FILE`
- `FILE_SUPPORTS_CAPABILITY`
- `FILE_IMPLEMENTS_SURFACE`
- `COMPONENT_IMPLEMENTS_SURFACE`
- `EVIDENCE_REFERENCES_FILE`

### Bounded derivation rules

- File → Component comes only from deterministic repository-path grouping.
- File → Capability comes from Feature Truth file provenance.
- File → Surface comes from Product Flow surface source/path identity.
- Capability → Surface requires a shared observed source file.
- Surface → Journey requires an exact observed journey-step alias.
- Journey → Evidence reuses the existing authoritative report relation.

No fuzzy semantic similarity is used to manufacture the canonical impact chain.

An impact path means **this observed evidence chain may be affected by the
change**. It is not proof of root cause.

## Queries

Existing v4.2 queries remain supported:

- `unverified-capabilities`
- `recurring-findings`
- `regressions`
- `history`
- `evidence`

v4.6 adds:

- `impact`
- `stale-evidence`
- `lifecycle`
- `subject`

Examples:

```bash
python scripts/evidence_graph.py --graph evidence-graph.json --query impact
python scripts/evidence_graph.py --graph evidence-graph.json --query stale-evidence
python scripts/evidence_graph.py --graph evidence-graph.json --query lifecycle
python scripts/evidence_graph.py --graph evidence-graph.json --query subject --subject settings
```

The `subject` query returns matching graph nodes, directly connected relations,
supporting evidence and finding lifecycle/history where applicable.

## Studio

The Studio projection now exposes:

- changed files mapped;
- dependency-impacted files;
- impact-path count;
- invalidated evidence count;
- stale/historical evidence count;
- finding lifecycle counts;
- top invalidated evidence;
- top impact paths.

Control Center shows these as descriptive evidence signals. v4.6 does not create
a synthetic product-quality score.

## FAST / FULL boundary

Evidence Graph 2 consumes the trusted Smart Test Plan impact set and makes its
product/evidence consequences explicit.

It does **not** replace Smart Test Plan or independently promote/demote a run
between FAST, FULL or CERTIFICATION in v4.6. Graph-aware feedback into a future
planner run can be added only with a separate deterministic contract so that a
derived graph cannot silently become a second test-selection authority.

## Authority boundaries

v4.6 preserves these rules:

- source reports remain authoritative;
- trusted runtime remains the runtime authority;
- Physical Evidence remains the real-device authority;
- Release Reality remains the release-state authority;
- Certification remains the certification authority;
- historical evidence never overrides current trusted evidence;
- missing evidence never becomes PASS;
- finding return/resolution is not causal blame;
- impact paths are not root-cause proof;
- graph output is deterministic query/index infrastructure.

## Validation

v4.6 is protected by:

- `scripts/evidence_graph.py --self-test`;
- independent `tests/intelligence/evidence_graph_test.py`;
- audit-contract invariants;
- Studio projection self-test;
- normal AppLab CI/security/runtime gates.
