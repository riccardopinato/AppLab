# AppLab v6.1A — Closed-Loop Pilot Admission

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

## Goal

v6.1A admits the already-proven v6 engineering components into one durable self-canary control path. The first mutation canary is AppLab itself. This stage does not grant autonomous edit authority to downstream repositories and does not create a second scheduler, verifier, merge authority or certification authority.

The admitted path is:

failure/evidence -> durable operation -> WorkItem -> causal investigation -> bounded repair -> focused verification -> draft-PR stewardship -> trusted AppLab verification.

v6.1A is an admission and control-plane integration step. The existing v5.4/v5.5 durable store, queue and GitHub Actions fallback remain the execution substrate.

## Self-canary admission

Live mutation admission is fail-closed and requires all of the following:

- repository is exactly `riccardopinato/AppLab`;
- source ref is exactly `refs/heads/main`;
- `resolved_sha` is an exact lowercase 40-hex SHA;
- self-canary identity requires `resolved_sha == applab_sha`;
- global pilot and closed-loop controls are enabled;
- the global kill switch is off;
- LOW or NORMAL risk is required for autonomous code mutation.

HIGH and SECURITY risk may be admitted for investigation, but they do not receive code-edit or draft-PR capabilities.

The durable operation and the v6 WorkItem share the same SQLite control-plane substrate. Duplicate delivery reuses the same durable operation and WorkItem. Terminal WorkItems are never redispatched merely to search for green.

## Authority envelope

v6.1A reuses the v6.0 authority envelope. Autonomous work cannot write main, modify App-Factory-Core, read secrets, edit workflows or branch protection, weaken tests, approve itself, merge itself or release software.

The bounded fix worker remains branch-workspace only. Draft PR stewardship remains draft branch/PR only. Post-gate automatic merge, when repository gates independently allow it, remains a separate repository automation authority. Production Certification remains the only certification authority.

## Kill switch and fallback

`integration/orchestration/v61-closed-loop-pilot.json` contains the single self-canary target and the global kill switch. GitHub Actions remains an explicit fallback.

v6.1A deliberately invokes the existing controlled-event admission in non-dispatch mode. It persists the event/operation/queue state and starts the WorkItem, but it does not install a parallel live dispatcher.

## Post-screen waiting model

The observed repeated `check -> sleep 20/25/30 seconds -> check again` behavior is not adopted as the target architecture.

v6.1A introduces no fixed-interval polling loop. v6.1B must make event-driven state change plus durable waiting the primary progression mechanism, with independent reconciliation/watchdog recovery and bounded polling only as a fallback for missed or unavailable events.

v6.1C then applies queue/backpressure and observation budgets so concurrent GitHub jobs do not create one independent polling loop per job. Already terminal/green gates and immutable identity are retained; pending or changed gates are re-evaluated unless the target SHA changes.

v6.1E will measure GitHub's actual execution time separately from AppLab orchestration/wait overhead.

## Acceptance criteria

- self-repository and main-ref allowlist are exact;
- global kill switch blocks admission before a WorkItem is started;
- self source SHA and AppLab SHA are immutable and equal;
- LOW/NORMAL can receive bounded mutation + draft PR authority;
- HIGH/SECURITY remain investigation-only;
- duplicate delivery reuses durable operation/WorkItem;
- WorkItem is persisted on the existing durable control plane and enters `INVESTIGATING`;
- no parallel scheduler or live dispatcher is introduced;
- no fixed-interval polling is introduced;
- GitHub Actions fallback remains;
- merge/release/certification authority boundaries remain unchanged;
- exact-head CI and contract tests must be green before promotion from candidate to landed.
