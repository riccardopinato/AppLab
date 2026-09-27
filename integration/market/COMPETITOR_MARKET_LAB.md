# AppLab v1.4 — Competitor & Market Lab

The Competitor & Market Lab is an **external evidence layer**. It complements
AppLab source/runtime verification but never participates in PASS/FAIL or
CERTIFICATION.

Its purpose is to compare a project's bounded source signals with current market
evidence without turning store pages, reviews or pricing observations into
unverified product truth.

## Evidence contract

Input JSON must use `schema_version: 1` and provide at least one competitor.

Each competitor requires:

- stable `id` and display `name`;
- one or more `source_urls`;
- optional `observed_at`;
- `features[]` with canonical `key`, label and per-feature `source_url`;
- optional pricing with model/currency/period values and `source_url`;
- optional rating with `source_url`;
- optional review themes with key, sentiment, count and `source_url`.

Raw unsourced assertions are rejected where a market fact is used by the
comparison.

## Capability classifications

- `MARKET_PARITY_SIGNAL` — AppLab detected the capability in the project and
  at least half of the supplied competitors expose it.
- `PROJECT_DIFFERENTIATOR_SIGNAL` — AppLab detected the capability in the
  project and fewer than half of competitors expose it.
- `PROJECT_ONLY_SIGNAL` — project source evidence exists but the supplied
  competitor set contains no matching capability.
- `COMMON_MARKET_GAP_REVIEW` — at least half of competitors expose a
  capability for which the bounded project scan found no source signal.
- `NICHE_MARKET_GAP_REVIEW` — fewer than half expose it and no project source
  signal was found.

A gap classification is a **review target**, never proof that the project lacks
the feature.

## Review intelligence

Review themes are supplied as evidence rather than inferred from arbitrary raw
review text. A negative theme becomes `RECURRING_MARKET_PAIN_SIGNAL` only when
it appears across at least two supplied competitors.

This prevents a single review or single competitor from becoming a product
directive.

## Pricing intelligence

AppLab reports:

- observed monetization-model counts;
- comparable min/max ranges grouped by currency and period;
- per-competitor pricing evidence.

AppLab does not convert currencies and does not recommend a price in v1.4.

## Execution

```bash
python scripts/market_intelligence.py \
  --evidence market-evidence.json \
  --app-intelligence applab-intelligence/app-intelligence.json \
  --output-dir applab-market
```

Self-test:

```bash
python scripts/market_intelligence.py --self-test
```

Outputs:

- `market-intelligence.json`
- `market-intelligence.md`

## Trust boundary

Market evidence is intentionally isolated from:

- build identity;
- APK integrity;
- runtime PASS/FAIL;
- FAST/FULL lane selection;
- production certification.

The market layer can inform later product decisions, but it cannot weaken,
override or manufacture trusted verification evidence.
