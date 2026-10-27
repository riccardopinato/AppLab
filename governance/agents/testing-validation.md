# Testing and evidence

Run targeted self-tests and existing relevant contracts before proposing a PR,
then validate the exact PR head with required GitHub workflows and external review.
Check fresh evidence after code hygiene; prior CI success does not validate changed
bytes. Keep FAST versus FULL risk selection intact.

Trust ladder: implementation -> tests -> CI -> build/artifact -> trusted runtime
-> real physical-device -> distribution/store. Neither CI nor emulator PASS
implies another level. A v6.1A durable admission or v5.4G runner success alone
does not prove a closed-loop autonomous repair. Live operational evidence must
bind immutable SHA, operation and WorkItem, trusted artifact, real fix, external
review and terminal outcome before counting toward cohort promotion.
Never translate BLOCKED/NOT_VERIFIED into PASS.
