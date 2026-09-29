# AppLab v3.1 — True Autonomous App Review

v3.1 turns Autonomous App Review into an end-to-end workflow.

## Pipeline

```
target ref
  -> resolve immutable SHA
  -> universal project auto-discovery
  -> build
  -> isolated APK contract
  -> Trusted APK Verifier
  -> Trusted Evidence Manifest
  -> download evidence from the same workflow run
  -> manifest validation
  -> App Intelligence
  -> Behavioral Product Lab
  -> State & Edge-Case Lab
  -> Evidence Calibration
  -> Product Contract Audit
  -> Decision & Opportunity Brief
  -> Studio-ready review evidence
```

The target ref is resolved once. Every later stage uses that exact SHA.

## Runtime evidence policy

Runtime evidence is consumed only when `trusted-evidence-manifest.json` validates
against the expected repository, SHA and workflow run id.

Untrusted runtime is ignored by the library API and rejected by strict workflow
callers.

## Review hardening

v3.1 also reduces false positives:

- product-surface matching uses observed UI hierarchy, not the label of the tapped
  control;
- empty/loading/error/auth/permission UI states require UI hierarchy evidence,
  not incidental words in logs or JSON;
- Product Contract claims are classified as PROMISED, EXCLUDED, FUTURE,
  MENTION_ONLY or CONTRADICTORY;
- evidence calibration requires an exact subject, relation key or shared evidence
  path instead of loose lexical overlap;
- FIX_NOW requires direct HIGH-confidence runtime evidence with a concrete
  evidence path;
- Product Contract and lifecycle findings remain VERIFY_NEXT unless independently
  confirmed at runtime.

## Studio

Studio exposes runtime trust state, bound SHA/package/run id and top action evidence
paths alongside the autonomous review state.

## Authority

Autonomous Review is advisory. FAST/FULL verification and production
CERTIFICATION remain the authoritative technical/release gates.
