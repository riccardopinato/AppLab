> **Legacy note (v3.0.1+):** this v3.0 contract remains valid for static/advisory review, but target-authored runtime evidence is no longer trusted. Use **True Autonomous App Review v3.1** for end-to-end runtime-backed review.\n\n# AppLab v3.0 — Autonomous App Review

Autonomous App Review orchestrates the complete product-intelligence chain:

1. App Intelligence
2. Behavioral Product Lab
3. State & Edge-Case Lab
4. Evidence Calibration
5. Product Contract Audit
6. Decision & Opportunity Brief
7. Autonomous Audit Plan

The review emits ATTENTION_REQUIRED, REVIEW_REQUIRED, EVIDENCE_INCOMPLETE or
READY_FOR_HUMAN_REVIEW. These are advisory review states, not release states.

If runtime evidence is absent, v3.0 explicitly returns EVIDENCE_INCOMPLETE instead
of fabricating runtime success.

The target repository is read-only. FAST/FULL runtime verification and production
CERTIFICATION remain independent and authoritative.
