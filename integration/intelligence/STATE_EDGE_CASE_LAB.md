# AppLab v2.8 — State & Edge-Case Lab

State & Edge-Case Lab builds one product-state coverage view from existing AppLab
runtime labs.

It maps normal interaction, offline/recovery, restart/persistence, configuration
changes, process death, storage integrity, background behavior and system permission
evidence. Empty/loading/error/auth/permission-denied observations are detected only
when bounded runtime evidence contains them.

Missing applicable evidence becomes REVIEW, never PASS.

Applicability is capability-driven where possible and remains advisory.
