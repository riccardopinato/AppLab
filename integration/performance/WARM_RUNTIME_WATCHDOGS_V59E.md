# AppLab v5.9E — Warm Runtime + Watchdogs

## Scope

v5.9E reduces orchestration latency and wasted work without moving verification
authority away from the existing trusted runner.

### 1. Bounded warm runtime routing

The trusted verifier now records one runtime route for every primary runtime and
journey shard:

- `WARM_TRUSTED_AVD` when the repository/profile is centrally admitted and the
  pristine AVD cache is an exact cache hit;
- `GITHUB_ACTIONS_COLD` for cache miss, non-admitted repository/profile or kill
  switch.

The warm route reuses only the pristine pre-target AVD. Target APK installation,
Maestro, specialist labs, visual evidence and final verdict still execute in the
same trusted verifier. A cache hit never mints PASS by itself.

Initial production admission is intentionally bounded to:

- `riccardopinato/AppLab`
- `riccardopinato/Agenda-per-Anna`

GitHub Actions remains the cold fallback. No persistent self-hosted worker is
required by this production step.

### 2. Proven supersession cancellation

The Supersession Watchdog may cancel an older active run only when all of these
conditions are true:

- workflow name is explicitly allowlisted;
- event and head branch match the newer run;
- the older run is still queued/in progress;
- GitHub compare proves the newer SHA is `ahead` of the older SHA;
- per-run cancellation cap is not exceeded.

`Production Certification` is explicitly protected and cannot appear in the
cancellable set. Cross-repository cancellation is not supported.

### 3. External review watchdog

Every 15 minutes the review reconciler checks open non-draft AppLab PRs.

- clean exact-head Codex review: satisfied;
- stale/missing/timed-out review: bounded `@codex review` retrigger;
- unresolved exact-head findings: BLOCKED and never auto-resolved;
- retries exhausted: BLOCKED.

Review-state markers are accepted only from
`chatgpt-codex-connector[bot]`; watchdog retry markers only from
`github-actions[bot]`.

## Authority boundaries

- Smart Test Plan remains FAST/FULL authority.
- Trusted APK Verifier remains runtime evidence authority.
- Release Assurance remains release-assurance authority.
- Production Certification remains the only certification authority.
- `coverage_reduction_enabled=false` for warm routing/watchdogs.
- Watchdogs may request review or cancel proven stale orchestration only; they
  cannot resolve findings, mint PASS or certify an artifact.

## Rollback

Warm runtime routing has a global kill switch and per-repository admission.
Disabling it falls back to cold GitHub Actions without changing verification
coverage. Both watchdog workflows can be disabled independently without changing
the trusted verifier.
