# AppLab v2.4 — Change Intelligence

Change Intelligence compares two App Intelligence snapshots and reports how the
product evidence moved between them.

It is deliberately separate from runtime regression testing. Runtime behavior is
still owned by FAST/FULL/CERTIFICATION; Change Intelligence explains product-level
evidence changes.

## Inputs

- baseline `app-intelligence.json`
- current `app-intelligence.json`

Both snapshots remain authoritative evidence sources. The engine does not mutate
or reinterpret them.

## Compared dimensions

### Feature Truth

For each capability AppLab records provenance transitions such as:

- DOC_ONLY_SIGNAL → CODE_CONFIRMED
- NOT_DETECTED → CODE_CONFIRMED
- CODE_CONFIRMED → NOT_DETECTED

Added and removed capabilities are reported explicitly.

### Domain model

Entity candidates added or removed between snapshots are listed.

### Product flow

Detected surface nodes added or removed between snapshots are listed.

### Product Consistency

Normalized consistency findings are separated into:

- new findings
- resolved findings
- persistent finding ids

New HIGH_REVIEW / REVIEW findings influence only the advisory `review_state`.

## Review state

The engine exposes one descriptive state:

- `HIGH_REVIEW` — at least one new HIGH_REVIEW finding
- `REVIEW` — at least one new REVIEW finding
- `CHANGED` — product evidence changed without new review findings
- `NO_MATERIAL_CHANGE` — no tracked evidence movement

This is not a quality score and is not a release verdict.

## Outputs

```bash
python scripts/change_intelligence.py \
  --baseline previous/app-intelligence.json \
  --current current/app-intelligence.json \
  --output-dir applab-change-intelligence
```

Outputs:

- `change-intelligence.json`
- `change-intelligence.md`

AppLab Studio can consume `change-intelligence.json` from a project evidence
directory and surface feature, entity, surface and finding deltas.

## Guardrails

1. A new static finding is not automatically a runtime regression.
2. A resolved static finding is not automatically proof of a runtime fix.
3. Baseline/current snapshots retain their original confidence.
4. No synthetic numeric score is generated.
5. Change Intelligence cannot change FAST/FULL/CERTIFICATION outcomes.
6. Target repositories remain read-only.
