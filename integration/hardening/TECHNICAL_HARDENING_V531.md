# AppLab v5.3.1 — Evidence-Driven Technical Hardening

## Scope

v5.3.1 is a patch release for the ongoing v5.x hardening track. It does not
introduce a new product-intelligence authority and it does not alter
FAST/FULL/CERTIFICATION semantics.

The changes in this patch are justified by concrete GitHub Actions evidence
observed after v5.3.0.

## Observed failure signatures

### Browser WebRTC: connected signaling, no decoded frame

Live Emulator Browser E2E run `#682` on the v5.3.0 main commit reached:

- managed Android runtime `live_ready=true`;
- ADB ready;
- Android boot complete;
- gateway ready;
- WebRTC state `connected`.

The Playwright gate then failed because no decoded Android frame arrived within
the existing 30-second assertion window.

This is treated as a bounded infrastructure recovery candidate, not as PASS.

### Dependency graph failures reached the expensive live stack

Several dependency-update PR runs failed while Docker was already building the
live stack because the proposed frontend dependency graph was invalid. A
concrete observed case attempted Vite 8 with `@vitejs/plugin-react@4.7.0`,
whose declared peer range stopped at Vite 7.

v5.3.1 therefore validates the frontend dependency graph before Playwright,
Docker and emulator runtime work.

### GitHub Pages was not enabled

The read-only preview push workflow failed at `actions/configure-pages` with a
404 because the repository did not have GitHub Pages configured.

This is configuration absence, not a product/build defect.

## WebRTC recovery contract

The browser test keeps the original decoded-frame assertion.

When all of the following are true:

1. the managed runtime is live;
2. the gateway is ready;
3. the browser reports WebRTC `connected`;
4. no decoded video frame arrives within 30 seconds;

the test may reload the browser exactly once to recreate the browser-side peer
connection.

The second attempt runs the same frame assertions. If it also fails, the test
fails normally.

The recovery path never converts missing video evidence into PASS.

Before each recovery the test attaches:

- video ready/network state;
- video dimensions/current time;
- playback frame/drop counters when available;
- MediaStream track state/settings;
- AppLab runtime status;
- emulator gateway status;
- browser console/page errors.

The existing non-black-frame and real WebRTC input assertions still run after a
decoded frame is obtained.

## Dependency fail-fast contract

Live Browser E2E now pins Node 22 for browser tooling and executes a frontend
`npm ci --dry-run` dependency/lock validation before expensive live-runtime
work.

`Frontend Lock Consistency` now also runs on pull requests that modify the
frontend dependency manifests. Pull requests must leave the generated lockfile
clean and must pass the install-graph validation. The workflow never commits
back into a pull request.

## Read-only preview behavior

The preview workflow first queries the repository Pages state.

When Pages is configured:

- `actions/configure-pages` runs;
- the read-only Studio is built with the configured base path;
- the Pages artifact is uploaded;
- deployment runs normally.

When Pages is not configured:

- the build still runs;
- a deterministic repository base path is used;
- the static preview is uploaded as an ordinary 7-day CI artifact;
- the Pages deployment job is skipped;
- the workflow stays green and explicitly states that no public deployment was
  performed.

A missing Pages configuration is therefore no longer represented as an AppLab
failure.

## Evidence retention / garbage collection

GitHub artifact retention is the bounded evidence garbage-collection mechanism.

The enforced policy is:

| Evidence class | Minimum retention |
| --- | ---: |
| certified release bundle | 90 days |
| final certification evidence | 90 days |
| certification history | 90 days |
| physical-device attestation | 90 days |
| trusted cross-app verification | 90 days |
| repository longitudinal history | 90 days |
| transient Live WebRTC diagnostics | 7 days |

The three production-certification artifacts previously retained for seven
days are raised to 90 days.

`scripts/evidence_retention_contract.py` fails CI if a governed upload step is
removed, ceases to be an `upload-artifact` step, loses a numeric TTL, or drops
below its evidence-class minimum.

## Authority boundaries

v5.3.1 does not:

- weaken browser/runtime assertions;
- treat a retry as evidence;
- turn missing Pages configuration into a deployed site;
- alter certification verdict rules;
- infer physical-device evidence from emulator evidence;
- extend release evidence indefinitely without a bounded retention policy.

The Factory baseline remains unchanged from the v5.3 implementation sequence.
