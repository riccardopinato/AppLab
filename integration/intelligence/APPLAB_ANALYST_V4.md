# AppLab v4.0 — AppLab Analyst

AppLab Analyst is the deterministic synthesis layer above AppLab's product,
runtime, evidence-confidence, longitudinal and experiment-planning systems.

It does not replace any source report. It reads them, preserves their provenance
and produces a compact product-analysis view whose actionable statements remain
traceable to existing evidence.

No LLM is required.

## Inputs

The Analyst can consume the Studio-ready evidence directory produced by True
Autonomous Review, including:

- App Intelligence;
- Autonomous Review;
- Behavioral Product Lab;
- State & Edge-Case Lab;
- Evidence Calibration;
- Evidence Confidence & Contradiction Engine;
- User Journey Intelligence;
- UX Friction & Discoverability Lab;
- Product Contract Audit;
- Decision Brief;
- Longitudinal Product Intelligence;
- Autonomous Experiment Planner;
- Autonomous Audit Plan;
- Market Intelligence when explicitly available.

Missing optional inputs remain missing. The Analyst never fills those gaps from
general knowledge or external web research.

## Analyst states

The state is descriptive and is not a release verdict:

- `CONFIRMED_ACTION` — at least one evidence-backed FIX_NOW item exists;
- `EVIDENCE_INCOMPLETE` — trusted runtime evidence is unavailable/incomplete;
- `VERIFICATION_REQUIRED` — contradictions, VERIFY_NEXT evidence, regression
  candidates or high-priority experiments require bounded verification;
- `CHANGE_REVIEW` — longitudinal evidence changed without a current regression
  candidate;
- `NO_IMMEDIATE_ACTION` — current bounded evidence contains no immediate
  FIX_NOW or high-priority verification requirement.

FAST/FULL/CERTIFICATION remain authoritative.

## Output structure

### Product context

Summarizes only observed App Intelligence evidence:

- detected engine;
- source-scan confidence/completeness;
- present capabilities;
- entity and surface counts;
- local-first assessment.

### Evidence posture

Summarizes:

- Autonomous Review state;
- Trusted Evidence state;
- confirmed/corroborated/contradicted/unverified claim counts;
- journey observations;
- UX review signals.

### Change context

Consumes v3.5 without reinterpreting it:

- longitudinal state;
- history depth;
- new/returned/persistent/resolved findings;
- regression candidates.

### Experiment context

Consumes v3.6:

- planner state;
- next experiment id;
- total/high-priority experiments;
- existing-lab-ready and bounded-review-only counts.

### Evidence-backed observations

Each observation has:

- stable id;
- category and priority;
- kind and subject;
- human-readable statement;
- explicit basis files;
- evidence state;
- bounded evidence references.

Observations currently originate only from FIX_NOW, longitudinal regression
candidates, explicit Evidence Confidence contradictions, VERIFY_NEXT and the
next planned experiment.

### Next actions

The Analyst does not invent product work. Actions are derived only from:

- Decision Brief FIX_NOW;
- Experiment Planner experiments;
- Decision Brief IMPROVE.

They are classified as:

- `FIX_CONFIRMED_ISSUE`;
- `VERIFY_AFTER_FIX`;
- `RUN_BOUNDED_EXPERIMENT`;
- `CONSIDER_EVIDENCE_BACKED_IMPROVEMENT`.

## Provenance

`analyst-report.json` records the derivation type, Analyst engine/version and
every input report with filename, schema version and source engine/lab/platform
version when available.

The Analyst is a derived view. It never overwrites or replaces original evidence.

## Market boundary

Market Intelligence is included only when a market report already exists.
The Analyst does not perform automatic web research and does not rank competitors.
Market evidence cannot alter technical PASS/FAIL or certification.

## Outputs

- `analyst-report.json`
- `analyst-report.md`

Both are packaged into the same Studio-ready evidence bundle as the underlying
reports.

## Guardrails

1. Deterministic synthesis; no required LLM.
2. No numeric quality or product score.
3. No feature invention.
4. No automatic target-app mutation.
5. Every actionable observation has explicit evidence basis.
6. Current trusted evidence remains authoritative over derived summaries.
7. Missing evidence is reported rather than guessed.
8. Market evidence is descriptive only.
9. Analyst state is not a release/certification verdict.
10. FAST/FULL/CERTIFICATION remain independent.
