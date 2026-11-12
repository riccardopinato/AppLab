# X10-045 — Failure → donor feedback with Pattern-3 reuse

Factory pinned: App-Factory-Core@c5adc147046beb7024629466d10eeb799c3c2619 · Master v27 / Golden Index 29.

**Existing AppLab owners, never duplicated:** `pattern3_discovery_v57c.queue_observations/build_report` and `factory_feedback_packager_v58d.build_packages`. The new `x10_failure_donor_loop.analyze` is only a source/run/evidence admission and replay-plan facade. It requires **three distinct failed CI run/test identities** with identical normalized pattern (not three duplicate copies of one failure), independently verified source SHA, run id, evidence hash and failure state. Keeps output free of original log text, secrets, raw code or personal payloads.

Output is `PROPOSAL_ONLY`: canonical Pattern-3 suggested classification, complete bounded source references, candidates with replay plans marked `NOT_EXECUTED`. No test retry executed, no Donor promotion, no Golden admission, no source edit, no unapproved Core write and no AI scheduler. Re-running the verified failing test on the actual consumer at the pinned source SHA and cross-app review are explicit later gates.

Acceptance for this PR is SOURCE+CI + independent Codex review; fixture responses are NOT trusted independent failure evidence and do not count as live replay. The existing Factory Core provenance/reuse ledger remains the only canonical admission registry.
