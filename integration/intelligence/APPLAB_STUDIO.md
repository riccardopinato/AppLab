# AppLab v2.0 — AppLab Studio

AppLab Studio is the unified presentation layer for AppLab evidence.

It deliberately keeps two source domains separate:

- **Quality / runtime truth** from Repo Watcher, FAST/FULL and CERTIFICATION;
- **Product intelligence** from Product Analysis, UX/Product, Architecture/Data,
  Market, Cross-App Intelligence and Autonomous Audit Planning.

The UI can display them together, but the evidence contracts remain independent.

## Studio snapshot layout

The Studio snapshot builder expects a directory such as:

```text
evidence/
  project-a/
    app-intelligence.json
    market-intelligence.json
    audit-plan.json
  project-b/
    app-intelligence.json
    audit-plan.json
  cross-app-intelligence.json
```

Run:

```bash
python scripts/studio_snapshot.py \
  --evidence-root evidence \
  --output studio.json
```

The backend reads `/data/studio.json` by default. Override with
`APPLAB_STUDIO_PATH`.

## Control Center

The Control Center fetches:

- `/api/control-center` for build/runtime/certification state;
- `/api/studio` for product-intelligence state.

Studio shows per project:

- detected engine and source confidence;
- capability count;
- UX review signals;
- architecture review signals and local-first assessment;
- competitor count, market-gap review signals and differentiator signals;
- autonomous audit lab count and manual-review requirement;
- longitudinal history depth, finding lifecycle and regression-review candidates;
- autonomous experiment count, next experiment, priority and target labs;
- top selected labs;
- cross-app reusable pattern candidates.

## Safety properties

1. Studio is a presentation layer, not a new source of truth.
2. Market evidence cannot change technical PASS/FAIL.
3. Cross-app recurrence cannot override project-specific evidence.
4. Missing Studio evidence leaves the runtime Control Center usable.
5. No opaque overall app score is generated.
6. Certification remains owned exclusively by the trusted certification pipeline.


## Trusted review integration

True Autonomous Review now packages each target's trusted evidence under a
project directory and runs `studio_snapshot.py` in the same workflow. The review
artifact therefore includes both the source evidence and a ready-to-consume
`studio.json` snapshot. Backend adapters preserve unknown/new summary fields so
producer metrics added by later AppLab versions are not silently discarded.
