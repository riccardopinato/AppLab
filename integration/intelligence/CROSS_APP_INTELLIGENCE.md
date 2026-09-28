# AppLab v1.5 — Cross-App Intelligence

Cross-App Intelligence turns multiple **project-scoped App Intelligence reports**
into a portfolio-level evidence view.

It does not copy features, architecture or code between projects. Its purpose is
to identify recurrence so that a human or later AppLab orchestration layer can
decide whether a pattern is worth standardizing.

## Inputs

The core engine consumes a directory containing at least two
`app-intelligence.json` reports.

The optional corpus builder can create these reports from the enabled public
repositories in AppLab's `watchlist.json`.

Important safety property: the corpus builder only clones and **reads** target
source. It never runs target build scripts, package managers, tests or hooks.

## Outputs

- `cross-app-intelligence.json`
- `cross-app-intelligence.md`

Each project record includes the SHA-256 of the exact App Intelligence report
that contributed to the portfolio conclusion.

## Pattern classes

### REPEATED_CAPABILITY_PATTERN

A capability source signal appears in at least the configured recurrence
threshold, default two projects.

This makes it a candidate for reusable-design or reusable-engineering review.
It is not permission to create a shared library automatically.

### PROJECT_SPECIFIC_SIGNAL

A capability appears in exactly one project in the current corpus.

AppLab keeps it project-scoped. It must not be generalized merely because
another app could theoretically use it.

### RECURRENT_REVIEW_SIGNAL

The same UX/Product or Architecture/Data review finding appears in at least the
configured recurrence threshold.

This is a candidate for a software-house rule, checklist or common hardening
pattern.

## Portfolio profile

The report also records descriptive distributions for:

- detected app engines;
- local-first assessments;
- scan confidence.

No overall portfolio score is generated.

## Watchlist corpus workflow

`AppLab Cross-App Intelligence` can build a fresh source-only corpus from the
enabled repositories in `watchlist.json`, then aggregate the results in the
same run.

This path currently targets public GitHub repositories. Private-repository
credential routing is intentionally not hidden inside v1.5.

## Guardrails

1. Project evidence remains authoritative.
2. Recurrence can propose review, never automatic feature transfer.
3. No automatic code extraction or shared-library creation.
4. No target source is executed by the corpus builder.
5. Cross-app evidence cannot affect runtime PASS/FAIL or CERTIFICATION.
6. Missing projects reduce corpus scope; the workflow fails rather than silently
   presenting an incomplete corpus as complete.
