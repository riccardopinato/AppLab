# AppLab v5.4C — Event Gateway Shadow

Status: **IMPLEMENTED SHADOW-ONLY / NO PRODUCTION INGESTION / NO DISPATCH**

v5.4C adds the provider-facing normalization boundary required by the Durable Brain while preserving the v5.4B store and all existing AppLab verification authority.

## Delivered

- `integration/orchestration/contracts/event-gateway-shadow-contract-v1.json`
- `scripts/event_gateway_v54c.py`
- `tests/contracts/event_gateway_v54c_test.py`
- CI self-test and independent contract coverage.

## Security boundary

The GitHub adapter requires:

- `X-Hub-Signature-256`;
- `X-GitHub-Delivery`;
- `X-GitHub-Event`;
- a bounded body size;
- a gateway receipt timestamp inside the configured receive window.

The provider signature is verified before JSON normalization.

GitHub does not provide a separately signed webhook timestamp. Therefore v5.4C does **not** invent one. Replay protection is composed from:

1. HMAC SHA-256 payload verification;
2. persistent provider delivery identity;
3. deterministic logical Event dedupe;
4. bounded local receipt-time validation.

## Supported shadow inputs

- push;
- pull request;
- workflow run.

Each accepted payload is normalized to the existing v5.4 Event contract and persisted in the v5.4B durable store before the call returns success.

## Dedupe

The same exact provider delivery is a replay.

A second provider delivery for the same logical repository/ref/SHA becomes one logical Event through the existing deterministic `dedupe_key`.

No duplicate delivery creates an Operation.

## Reconciliation

`compare_reconciliation_snapshot()` compares an independently supplied repository/ref/SHA snapshot against the latest durable admitted Event for that lineage.

It reports:

- MATCHED;
- MISSING;
- STALE.

This is the contract used by the future periodic watcher reconciliation path.

v5.4C does not query GitHub directly and does not alter the existing hourly watcher.

## Explicit non-capabilities

v5.4C has no:

- HTTP server;
- live webhook endpoint;
- GitHub token;
- production secret;
- Operation creation;
- worker dispatch;
- Conductor client;
- verification verdict;
- certification authority;
- coverage reduction.

The CI contract rejects any operational workflow that wires `event_gateway_v54c.py` outside static validation.

## Exit evidence

The deterministic corpus proves:

- valid signed delivery accepted;
- exact redelivery returns REPLAY;
- a different delivery ID for the same logical target change returns DEDUPED;
- invalid signature rejected;
- missing delivery identity rejected;
- unsupported event rejected;
- receive-window violation rejected;
- body limit enforced;
- push/PR/workflow identity normalized deterministically;
- reconciliation detects current, missing and stale lineages;
- durable restart preserves admitted Events;
- zero Operations are created;
- dispatch remains false.

The next step is v5.4D: Conductor-compatible shadow orchestration comparison, still with zero dispatch credentials.
