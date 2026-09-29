# AppLab v3.6 — Autonomous Experiment Planner

The Autonomous Experiment Planner converts unresolved AppLab evidence into an
ordered, inspectable verification plan. It does not invent product features and
it does not mutate the target application.

The planner consumes evidence already produced by AppLab:

- Decision Brief `FIX_NOW` and `VERIFY_NEXT`;
- Longitudinal Product Intelligence regression candidates;
- Evidence Confidence contradictions.

It maps those signals to existing AppLab verification capabilities rather than
creating a second test framework.

## Purpose

v3.6 answers one bounded question:

> Given the evidence AppLab already has, what is the next smallest experiment
> that can support, contradict, or leave the hypothesis unverified?

The output is advisory. It never changes FAST/FULL/CERTIFICATION results.

## Experiment contract

Each experiment records:

- deterministic experiment id;
- priority;
- source trigger(s);
- kind and subject;
- explicit hypothesis;
- reason and evidence basis;
- experiment type;
- existing AppLab labs to reuse;
- preconditions;
- actions;
- observations;
- sufficient-evidence criteria;
- supported / contradicted / unverified outcome semantics.

No numeric confidence or product score is produced.

## Experiment types

### SPECIALIST_RUNTIME

Routes a bounded hypothesis to an existing specialist runtime lab such as:

- network;
- persistence;
- storage;
- upgrade;
- configuration;
- resource pressure;
- background;
- system;
- performance.

### TARGETED_JOURNEY

Uses the existing safe interaction crawler and/or visual journey evidence for
navigation, discoverability, loop, ambiguity and state-change hypotheses.

### EVIDENCE_RECONCILIATION

Used when bounded evidence sources explicitly contradict each other. All sources
remain visible; the planner never resolves contradictions by majority vote.

### STATIC_EVIDENCE_REVIEW

Used for product-contract, documentation and implementation provenance questions
that do not yet justify a runtime claim.

### POST_FIX_VERIFICATION

A runtime-confirmed FIX_NOW signal is not delayed by the planner. The experiment
defines how to reproduce the original evidence path and repeat it after the fix.

## Ordering

Experiments are ordered deterministically:

1. FIX_NOW post-fix verification;
2. longitudinal regression candidates;
3. evidence contradictions;
4. VERIFY_NEXT evidence gaps.

Within those groups, HIGH priority precedes NORMAL and LOW.

Equivalent signals for the same kind, subject and target labs are merged, while
preserving all trigger sources and bounded evidence references.

## Studio

AppLab Studio exposes:

- planner state;
- number of experiments;
- high/normal priority counts;
- existing-lab-ready count;
- bounded-review-only count;
- next experiment id;
- top experiments with target labs.

## Guardrails

1. The planner is advisory.
2. It cannot change product code.
3. It cannot weaken certification coverage.
4. Missing evidence never becomes PASS.
5. Existing labs are reused before new test machinery is considered.
6. FIX_NOW findings are not delayed waiting for an experiment.
7. Experiment outcomes are evidence inputs, not release verdicts.
8. No synthetic quality score is generated.
