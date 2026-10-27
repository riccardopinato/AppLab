type AgentOperationRow = {
  work_item_id: string;
  repository: string;
  resolved_sha: string;
  state: string;
  risk: string;
  attempts: number;
  actions: number;
  evidence_count: number;
  stop_reason: string;
  next_action: string;
  pr_state: string;
  pr_number?: number | null;
  pr_url: string;
  authority_envelope: {
    allowed_capabilities?: string[];
    denied_capabilities?: string[];
  };
  sensor_producers?: string[];
  budget: {
    repair_attempts?: { used?: number; max?: number };
    files?: { max?: number };
    changed_lines?: { used?: number; max?: number };
  };
};

export type AgentOperationsSnapshot = {
  available: boolean;
  summary: {
    work_items: number;
    active: number;
    complete: number;
    stopped_or_blocked: number;
    draft_prs: number;
    evidence_records: number;
  };
  work_items: AgentOperationRow[];
  production_operations?: {
    available: boolean;
    production_status: string;
    active_stage: string;
    operation_count: number;
    promotion: string;
    operations_gate: string;
    rollback: string;
    recommended_stage: string;
    latency_alert_count: number;
    repeated_signature_stops: number;
    covered_waits: number;
    external_queries: number;
    coalesced_wait_savings: number;
    authority: string;
  };
  source_of_truth: string;
  merge_authority: string;
  release_authority: string;
};

function badgeClass(value: string) {
  if (value === "COMPLETE" || value === "PASS") return "cc-badge good";
  if (value === "STOPPED" || value === "BLOCKED" || value === "FAIL") return "cc-badge warn";
  return "cc-badge neutral";
}

function shortSha(value: string) {
  return value ? value.slice(0, 8) : "—";
}

export default function AgentOperationsPanel({
  snapshot,
}: {
  snapshot?: AgentOperationsSnapshot;
}) {
  if (!snapshot) return null;

  return (
    <div className="studio-shell">
      <div className="studio-head">
        <div>
          <span className="panel-kicker">AGENTIC OPERATIONS · READ ONLY</span>
          <h3>WorkItems · Attempts · Evidence · Draft PRs</h3>
        </div>
        <span className={snapshot.available ? "cc-badge good" : "cc-badge neutral"}>
          {snapshot.available ? "EVIDENCE READY" : "NO AGENT OPERATIONS"}
        </span>
      </div>
      <div className="studio-summary">
        <div><span>WorkItems</span><strong>{snapshot.summary.work_items}</strong></div>
        <div><span>Active</span><strong>{snapshot.summary.active}</strong></div>
        <div><span>Complete</span><strong>{snapshot.summary.complete}</strong></div>
        <div><span>Stopped / blocked</span><strong>{snapshot.summary.stopped_or_blocked}</strong></div>
        <div><span>Draft PRs</span><strong>{snapshot.summary.draft_prs}</strong></div>
        <div><span>Evidence records</span><strong>{snapshot.summary.evidence_records}</strong></div>
      </div>
      {snapshot.production_operations?.available ? (
        <>
          <div className="studio-summary">
            <div><span>Production</span><strong>{snapshot.production_operations.production_status}</strong></div>
            <div><span>Stage</span><strong>{snapshot.production_operations.active_stage}</strong></div>
            <div><span>Operations gate</span><strong>{snapshot.production_operations.operations_gate}</strong></div>
            <div><span>Rollback</span><strong>{snapshot.production_operations.rollback}</strong></div>
            <div><span>SLO alerts</span><strong>{snapshot.production_operations.latency_alert_count}</strong></div>
            <div><span>Coalesced savings</span><strong>{snapshot.production_operations.coalesced_wait_savings}</strong></div>
          </div>
          <p className="cc-note">
            Read-only production evidence · {snapshot.production_operations.operation_count} operations ·
            {snapshot.production_operations.covered_waits} waits / {snapshot.production_operations.external_queries} external queries ·
            {snapshot.production_operations.repeated_signature_stops} repeated-signature stops
          </p>
        </>
      ) : null}
      {snapshot.available ? (
        <div className="studio-projects">
          {snapshot.work_items.slice(0, 6).map((item) => (
            <article className="studio-project-card" key={item.work_item_id}>
              <div className="studio-project-title">
                <strong>{item.repository || item.work_item_id}</strong>
                <span className={badgeClass(item.state)}>{item.state}</span>
              </div>
              <div className="studio-dimensions">
                <div>
                  <span>Identity</span>
                  <strong>{shortSha(item.resolved_sha)}</strong>
                  <small>{item.work_item_id} · risk {item.risk}</small>
                </div>
                <div>
                  <span>Repair budget</span>
                  <strong>{item.budget.repair_attempts?.used ?? 0}/{item.budget.repair_attempts?.max ?? 0}</strong>
                  <small>{item.budget.changed_lines?.used ?? 0}/{item.budget.changed_lines?.max ?? 0} changed lines · max {item.budget.files?.max ?? 0} files</small>
                </div>
                <div>
                  <span>Evidence</span>
                  <strong>{item.evidence_count}</strong>
                  <small>{item.actions} actions · {item.attempts} attempts</small>
                </div>
                <div>
                  <span>Authority</span>
                  <strong>{item.authority_envelope.allowed_capabilities?.length ?? 0} allowed</strong>
                  <small>{item.authority_envelope.denied_capabilities?.length ?? 0} denied · merge {snapshot.merge_authority} · release {snapshot.release_authority}</small>
                </div>
              </div>
              {item.stop_reason || item.next_action ? (
                <p className="cc-note">
                  {item.stop_reason ? `stop: ${item.stop_reason}` : ""}
                  {item.stop_reason && item.next_action ? " · " : ""}
                  {item.next_action ? `next: ${item.next_action}` : ""}
                </p>
              ) : null}
              {item.pr_state ? (
                <p className="cc-note">
                  PR {item.pr_number ? `#${item.pr_number}` : "—"} · {item.pr_state}
                </p>
              ) : null}
            </article>
          ))}
        </div>
      ) : (
        <p className="cc-note">
          No durable WorkItem records have been projected yet. This panel never invents agent activity.
        </p>
      )}
    </div>
  );
}
