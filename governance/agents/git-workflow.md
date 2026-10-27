# Git workflow

Pin AppLab repository, branch and commit SHA once; do not repeatedly refresh
unless source changes or user requests it. All non-emergency changes use a branch.

Create independently reviewable PRs. Exact-head checks, required reviewers, code
review findings, contract fingerprint, immutable artifact identity and branch
protection must be satisfied. Never self-approve, bypass gate, auto-merge a red/
pending PR, or infer merge authority from the v6 draft PR steward. The separate
post-gate executor may merge only after every applicable independent gate.

Autonomous repair remains bounded to 5 files, 250 changed lines, 2 attempts;
main and governance/release/security-sensitive paths remain protected. Store
rejected and STOP outcomes, do not retry until green.
