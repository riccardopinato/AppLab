# AppLab v5.4G — Controlled Event-Driven Pilot

Status: **REPOSITORY-SIDE IMPLEMENTATION PREPARED / LIVE ACTIVATION REQUIRES EXTERNAL HTTPS + SECRETS**

v5.4G connects the Durable Event Gateway, Durable Store, per-repository queue and existing GitHub Actions executor without changing verification authority.

## Runtime path

GitHub push/pull_request -> public HTTPS gateway -> signed persistent Event -> signed repository_dispatch -> exact target SHA checkout -> authoritative Smart Test Plan -> Durable Brain Operation/lease -> existing Universal Project Runner -> signed orchestration callback.

The gateway and Durable Brain are orchestration-only. They cannot mint AppLab PASS or CERTIFIED.

## Scope

Only push and pull_request are live-pilot inputs. workflow_run remains shadow-observable but is not eligible for dispatch, preventing execution loops. Normal webhook traffic can create VERIFICATION only; certification, physical validation and explicit manual diagnostics remain outside this route.

## Identity and planning

The target checkout must equal the immutable SHA from the admitted Event. Smart Test Plan runs after exact target checkout. Operation identity then binds repository, source ref, exact target SHA, exact AppLab SHA, semantic plan digest, operation class and analysis mode. Executor run ID is lease/attempt metadata, not immutable Operation identity.

## Durable dispatch

Event persistence occurs before repository_dispatch. A durable dispatch projection records DISPATCHING, DISPATCHED or FAILED with append-only history and bounded retry. Exact provider replay is idempotent; downstream Operation idempotency and operation-bound queue claim prevent a duplicate logical verification.

## Queue and executor

Workflow concurrency is repository | source_ref | operation_class with cancel-in-progress disabled. The authorization call requests a lease for the exact Operation ID; it cannot accidentally claim another queued Operation. Existing GitHub Actions runners remain the executor.

## Service activation

The gateway container is disabled by default and is available only through the optional v54g compose profile. Live activation requires a stable public HTTPS URL, GitHub source-repository webhooks, webhook secret, dispatch secret, a token scoped for AppLab repository_dispatch, APPLAB_V54G_GATEWAY_URL Actions secret, a pilot repository/ref allowlist, persistent storage and APPLAB_V54G_ENABLED=true.

No secret value is stored in this repository.

## Watchdog and rollback

The hourly Repo Watcher remains active as reconciliation/watchdog. Rollback is: disable APPLAB_V54G_ENABLED, disable pilot webhooks and stop the v54g compose profile. Existing manual/watcher GitHub Actions paths remain available and verification semantics do not change.

## Completion rule

Repository-side implementation and tests are not sufficient to claim a live event-driven pilot. Full v5.4G activation requires observed signed webhook delivery from a configured pilot repository, exact-SHA execution, durable Event/Operation/queue records, successful signed callback and watcher reconciliation through the externally reachable HTTPS endpoint.
