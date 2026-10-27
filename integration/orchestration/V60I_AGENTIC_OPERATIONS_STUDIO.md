# AppLab v6.0I — Agentic Operations Studio

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

v6.0I is a read-only projection of durable agent records. It does not become a second control plane.

The optional `.applab-history/agent-operations.jsonl` ledger is projected into Control Center as WorkItems with repository/source identity, state/risk, action and attempt counts, evidence count, repair-budget consumption, changed-line consumption, stop reason, next action, draft PR state, sensor producers, cost/runtime metadata and the active authority envelope.

When no durable agent records exist, the panel explicitly shows `NO AGENT OPERATIONS`; it never synthesizes activity.

The Control Center only renders this evidence. It exposes no merge/release/approval action and the projection records `merge_authority=NONE` and `release_authority=NONE`.

The UI was extracted into `AgentOperationsPanel.tsx` rather than raising the existing ControlCenter growth ceiling.

## Acceptance

- [x] read-only JSONL projection;
- [x] WorkItem/attempt/action/evidence aggregation;
- [x] repair budget and stop reason visibility;
- [x] draft PR and sensor evidence visibility;
- [x] authority envelope visibility;
- [x] Repo Watcher + Production Certification snapshot integration;
- [x] no-evidence truth state;
- [x] no merge/release UI;
- [x] bounded frontend extraction instead of ceiling inflation;
- [x] CI/self-test wiring;
- [ ] exact-head required checks GREEN;
- [ ] real WorkItem ledger populated by the closed-loop pilot.
