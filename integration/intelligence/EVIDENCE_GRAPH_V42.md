# AppLab v4.2 — Evidence Graph

## Purpose

Evidence Graph is the deterministic query/index layer above AppLab's existing
evidence engines. It does **not** replace App Intelligence, Evidence Confidence,
Longitudinal Product Intelligence, Autonomous Experiment Planner, AppLab Analyst,
Trusted Runtime or FAST/FULL/CERTIFICATION.

The graph unifies the current trusted review into a common model:

- Project
- Revision
- BuildArtifact
- Capability
- Surface
- Journey
- Finding
- Claim
- Evidence
- Experiment
- Result

The source reports remain authoritative. Evidence Graph only normalizes identity,
relationships and provenance so the same evidence can be interrogated without
reimplementing product or release logic.

## Inputs

The canonical v4.2 build consumes:

- `app-intelligence.json`
- `evidence-confidence.json`
- `user-journey.json`
- `ux-friction.json`
- `longitudinal-intelligence.json`
- `experiment-plan.json`
- `analyst-report.json`

When available, trusted-runtime provenance is added from:

- `trusted-evidence-manifest.json`
- `build-contract.json`
- `result.json`

The graph is bound to repository, resolved SHA, workflow run and package/build
identity whenever those fields are available.

## Core relations

Examples of canonical relations:

- Project -> Revision: `PROJECT_HAS_REVISION`
- Revision -> BuildArtifact: `REVISION_BUILT_AS`
- Revision -> Capability: `REVISION_HAS_CAPABILITY`
- Revision -> Surface: `REVISION_HAS_SURFACE`
- Revision -> Journey: `REVISION_OBSERVED_JOURNEY`
- Revision -> Finding: `REVISION_HAS_FINDING`
- Revision -> Claim: `REVISION_HAS_CLAIM`
- Revision -> Experiment: `REVISION_PLANS_EXPERIMENT`
- Revision -> Result: `REVISION_HAS_RESULT`
- Claim -> subject: `CLAIM_ABOUT`
- Finding -> subject: `FINDING_ABOUT`
- Claim/Finding/Experiment -> Evidence: evidence/provenance relations
- Experiment -> target: `EXPERIMENT_TARGETS`
- current Revision -> baseline Revision: `REVISION_COMPARED_TO`

Every derived node also retains report provenance.

## Queries

`scripts/evidence_graph.py` supports deterministic queries over a generated
`evidence-graph.json`:

```bash
python scripts/evidence_graph.py --graph evidence-graph.json --query unverified-capabilities
python scripts/evidence_graph.py --graph evidence-graph.json --query recurring-findings
python scripts/evidence_graph.py --graph evidence-graph.json --query regressions
python scripts/evidence_graph.py --graph evidence-graph.json --query history --subject save
python scripts/evidence_graph.py --graph evidence-graph.json --query evidence --subject authentication
```

This enables bounded questions such as:

- Which capabilities still lack strong verification?
- Which findings recur across trusted revisions?
- What evidence supports a claim or finding?
- At which revision was a finding first observed?
- Which current regression candidates have a planned experiment?

## Longitudinal semantics

Evidence Graph imports Longitudinal Product Intelligence's bounded historical
statistics.

`first_observed_sha` means the first SHA where the finding was observed in the
available trusted history. It is **not** proof that the commit introduced the
underlying defect.

A causal "introducing commit" would require an explicit bisect/experiment and is
not inferred by v4.2.

## Authority and guardrails

Evidence Graph is not a new verification engine.

It cannot:

- turn missing evidence into PASS;
- change a trusted runtime result;
- change FAST/FULL/CERTIFICATION;
- convert a regression candidate into an automatic defect;
- convert a first-observed SHA into a causal blame claim;
- generate a numeric product-quality score;
- overwrite source evidence.

AppLab Analyst remains the descriptive synthesis layer. Evidence Graph includes
the Analyst result as a node so its conclusions can be traced back to the same
underlying reports.

## Outputs

Canonical trusted review artifact adds:

- `evidence-graph.json`
- `evidence-graph.md`

AppLab Studio exposes a compact graph summary while the full graph remains
inspectable in the evidence artifact.

## Version

- Engine: `4.2.0`
- Graph schema: `1`
- Graph model: `1.0`
