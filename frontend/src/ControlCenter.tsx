import { useCallback, useEffect, useMemo, useState } from "react";

type ReleaseMeta = {
  artifact_url?: string;
  artifact_name?: string;
  changelog_summary?: string;
  apk?: {
    filename?: string;
    version_name?: string;
    version_code?: string;
    size_human?: string;
    sha256?: string;
  };
};

type PerformanceMetrics = {
  startup?: {
    cold?: { total_time_ms?: number | null };
    warm?: { total_time_ms?: number | null };
  };
  memory?: { pss_kb?: number | null };
  gfx?: { janky_percent?: number | null };
  apk?: { host_apk_bytes?: number | null };
};

type ProjectRow = {
  repository: string;
  key: string;
  engine: string;
  ref: string;
  enabled: boolean;
  resolved_sha: string;
  result: string;
  maestro: string;
  visual_qa: string;
  visual_regression: string;
  visual_journey: string;
  interaction_crawl: string;
  system_lab: string;
  network_lab: string;
  persistence_lab: string;
  configuration_lab: string;
  resource_pressure_lab: string;
  background_lab: string;
  storage_lab: string;
  upgrade_lab: string;
  performance_lab: string;
  performance?: PerformanceMetrics;
  applab_version: string;
  analysis_mode?: string;
  analysis_lane?: string;
  risk_score?: number | null;
  confidence?: number | null;
  shadow_full?: boolean;
  failure_intelligence?: { kind?: string; retryable?: boolean; reason?: string };
  flaky_detection?: { suspected?: boolean; labs?: string[] };
  release_readiness?: { status?: string; missing_gates?: string[] };
  playbook?: { category?: string; recommended_playbook?: string; required_labs?: string[] };
  learning_applied_labs?: string[];
  verification_budget_seconds?: number | null;
  budget_pressure?: boolean;
  certification_status: string;
  certification_display_status?: string;
  certified_sha?: string;
  certification?: {
    status?: string;
    matrix?: Array<{
      api_level?: string;
      emulator_profile?: string;
      target?: string;
      arch?: string;
    }>;
  };
  recorded_at: string;
  watcher_run_id: string;
  watcher_run_url: string;
  release?: ReleaseMeta;
};

type RecentRow = {
  recorded_at?: string;
  repository?: string;
  resolved_sha?: string;
  result?: string;
  engine?: string;
  maestro?: string;
  visual_qa?: string;
  visual_regression?: string;
  visual_journey?: string;
  interaction_crawl?: string;
  system_lab?: string;
  network_lab?: string;
  persistence_lab?: string;
  configuration_lab?: string;
  resource_pressure_lab?: string;
  background_lab?: string;
  storage_lab?: string;
  upgrade_lab?: string;
  performance_lab?: string;
  performance?: PerformanceMetrics;
  watcher_run_id?: string;
  watcher_run_url?: string;
  applab_version?: string;
  analysis_mode?: string;
  analysis_lane?: string;
  risk_score?: number | null;
  confidence?: number | null;
  shadow_full?: boolean;
  failure_intelligence?: { kind?: string; retryable?: boolean };
  flaky_detection?: { suspected?: boolean; labs?: string[] };
  release_readiness?: { status?: string };
  playbook?: { category?: string; recommended_playbook?: string };
  learning_applied_labs?: string[];
  verification_budget_seconds?: number | null;
  budget_pressure?: boolean;
  certification_status?: string;
  certification?: {
    status?: string;
    matrix?: Array<{
      api_level?: string;
      emulator_profile?: string;
      target?: string;
      arch?: string;
    }>;
  };
  release?: ReleaseMeta;
};

type Snapshot = {
  available: boolean;
  generated_at: string;
  summary: {
    projects: number;
    pass: number;
    fail: number;
    not_run: number;
    certified: number;
    certified_current?: number;
    certified_stale?: number;
    certification_blocked: number;
    not_certified: number;
    lanes?: Record<string, number>;
    shadow_runs?: number;
    shadow_false_negatives?: number;
    retryable_failures?: number;
    flaky_suspects?: number;
    release_ready?: number;
    adaptive_metrics?: {
      sample_count?: number;
      planner_ms?: { p50?: number | null; p95?: number | null };
      total_seconds?: { p50?: number | null; p95?: number | null };
      wall_clock_seconds?: { p50?: number | null; p95?: number | null };
      runtime_seconds?: { p50?: number | null; p95?: number | null };
      quality_seconds?: { p50?: number | null; p95?: number | null };
      lane_metrics?: Record<
        string,
        {
          sample_count?: number;
          wall_clock_seconds?: { p50?: number | null; p95?: number | null };
        }
      >;
      avd_cache_hit_ratio?: number | null;
      maestro_cache_hit_ratio?: number | null;
      shadow_runs?: number;
      shadow_false_negatives?: number;
      shadow_missed_warnings?: number;
      shadow_over_selections?: number;
      budget_exceeded_runs?: number;
      learning_applied_runs?: number;
    };
  };
  projects: ProjectRow[];
  recent: RecentRow[];
};

type StudioProject = {
  project_id: string;
  product?: {
    engine?: string;
    confidence?: string;
    capabilities?: string[];
    screen_like_files?: number;
    entity_count?: number;
    surface_count?: number;
    lifecycle_review_signals?: number;
    documentation_drift_signals?: number;
    code_confirmed_capabilities?: number;
    doc_only_capabilities?: number;
    flow_nodes?: number;
    flow_edges?: number;
    orphan_surface_candidates?: number;
  } | null;
  ux?: { review_signals?: number } | null;
  architecture?: {
    review_signals?: number;
    local_first?: string;
  } | null;
  consistency?: {
    total?: number;
    high_review?: number;
    review?: number;
    info?: number;
    by_domain?: Record<string, number>;
    top_findings?: Array<{
      domain?: string;
      kind?: string;
      severity?: string;
      subject?: string;
    }>;
  } | null;
  market?: {
    competitors?: number;
    common_gap_reviews?: number;
    differentiator_signals?: number;
    recurring_pain_signals?: number;
  } | null;
  audit?: {
    selected_lab_count?: number;
    manual_review_required?: boolean;
    top_labs?: Array<{ lab?: string; priority?: string }>;
  } | null;
};

type StudioSnapshot = {
  available: boolean;
  generated_at: string;
  summary: {
    projects: number;
    with_market: number;
    manual_review: number;
    recurrent_patterns: number;
  };
  projects: StudioProject[];
  portfolio?: {
    project_count?: number;
    reusable_pattern_candidates?: Array<{
      key?: string;
      project_count?: number;
      projects?: string[];
    }>;
    recurrent_review_signals?: Array<{
      domain?: string;
      key?: string;
      project_count?: number;
      projects?: string[];
    }>;
  };
};

function badgeClass(value: string) {
  if (value === "PASS" || value === "CERTIFIED" || value === "CERTIFIED_CURRENT") return "cc-badge good";
  if (value === "CERTIFIED_STALE") return "cc-badge warn";
  if (value === "FAIL" || value === "ERROR" || value === "NOT_CERTIFIED")
    return "cc-badge bad";
  if (value === "WARN" || value === "BLOCKED") return "cc-badge warn";
  return "cc-badge neutral";
}

function shortSha(value: string) {
  return value ? value.slice(0, 8) : "—";
}

function gate(value: string) {
  return value && value !== "—" ? value : "—";
}

export default function ControlCenter({ backend }: { backend: string }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [studio, setStudio] = useState<StudioSnapshot | null>(null);
  const [error, setError] = useState("");
  const [studioError, setStudioError] = useState("");
  const [expanded, setExpanded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(`${backend}/api/control-center`, {
        cache: "no-store",
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(body.detail || `HTTP ${response.status}`);
      }
      setSnapshot(body as Snapshot);
      setError("");
    } catch (err) {
      setSnapshot(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [backend]);

  const refreshStudio = useCallback(async () => {
    try {
      const response = await fetch(`${backend}/api/studio`, {
        cache: "no-store",
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(body.detail || `HTTP ${response.status}`);
      }
      setStudio(body as StudioSnapshot);
      setStudioError("");
    } catch (err) {
      setStudio(null);
      setStudioError(err instanceof Error ? err.message : String(err));
    }
  }, [backend]);

  useEffect(() => {
    void refresh();
    void refreshStudio();
    const timer = window.setInterval(() => {
      void refresh();
      void refreshStudio();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [refresh, refreshStudio]);

  const recent = useMemo(
    () => snapshot?.recent.slice(0, expanded ? 20 : 6) || [],
    [expanded, snapshot?.recent],
  );

  return (
    <section className="control-center panel">
      <div className="panel-heading">
        <div>
          <span className="panel-kicker">00 · PROJECT CONTROL CENTER</span>
          <h2>Repository Quality Gate</h2>
        </div>
        <div className="cc-heading-actions">
          {snapshot?.generated_at ? (
            <small>
              updated {new Date(snapshot.generated_at).toLocaleString()}
            </small>
          ) : null}
          <button className="ghost" onClick={() => void refresh()}>
            Refresh
          </button>
        </div>
      </div>

      {error ? (
        <p className="runtime-error">Control Center unavailable: {error}</p>
      ) : null}

      {studioError ? (
        <p className="runtime-error">Studio unavailable: {studioError}</p>
      ) : null}

      <div className="studio-shell">
        <div className="studio-head">
          <div>
            <span className="panel-kicker">APP LAB STUDIO · PRODUCT INTELLIGENCE</span>
            <h3>Product · UX · Architecture · Market · Portfolio</h3>
          </div>
          <span className={studio?.available ? "cc-badge good" : "cc-badge neutral"}>
            {studio?.available ? "EVIDENCE READY" : "NO STUDIO SNAPSHOT"}
          </span>
        </div>

        {studio?.available ? (
          <>
            <div className="studio-summary">
              <div><span>Analyzed projects</span><strong>{studio.summary.projects}</strong></div>
              <div><span>Market evidence</span><strong>{studio.summary.with_market}</strong></div>
              <div><span>Manual review</span><strong>{studio.summary.manual_review}</strong></div>
              <div><span>Reusable patterns</span><strong>{studio.summary.recurrent_patterns}</strong></div>
            </div>

            <div className="studio-projects">
              {studio.projects.map((project) => (
                <article className="studio-project-card" key={project.project_id}>
                  <div className="studio-project-title">
                    <strong>{project.project_id}</strong>
                    <span className="cc-badge neutral">{project.product?.engine ?? "unknown"}</span>
                  </div>
                  <div className="studio-dimensions">
                    <div>
                      <span>Product</span>
                      <strong>{project.product?.capabilities?.length ?? 0}</strong>
                      <small>{project.product?.confidence ?? "UNKNOWN"} confidence · {project.product?.code_confirmed_capabilities ?? 0} code-confirmed · {project.product?.doc_only_capabilities ?? 0} doc-only · {project.product?.entity_count ?? 0} entities · {project.product?.flow_nodes ?? 0}/{project.product?.flow_edges ?? 0} flow · {project.product?.orphan_surface_candidates ?? 0} orphan review · {project.product?.lifecycle_review_signals ?? 0} lifecycle review · {project.product?.documentation_drift_signals ?? 0} doc drift</small>
                    </div>
                    <div>
                      <span>UX</span>
                      <strong>{project.ux?.review_signals ?? 0}</strong>
                      <small>review signals</small>
                    </div>
                    <div>
                      <span>Architecture</span>
                      <strong>{project.architecture?.review_signals ?? 0}</strong>
                      <small>{project.architecture?.local_first ?? "UNKNOWN"}</small>
                    </div>
                    <div>
                      <span>Consistency</span>
                      <strong>{project.consistency?.total ?? 0}</strong>
                      <small>{project.consistency?.high_review ?? 0} high · {project.consistency?.review ?? 0} review</small>
                    </div>
                    <div>
                      <span>Market</span>
                      <strong>{project.market?.competitors ?? 0}</strong>
                      <small>
                        {project.market
                          ? `${project.market.common_gap_reviews ?? 0} gap review · ${project.market.differentiator_signals ?? 0} differentiators`
                          : "no external evidence"}
                      </small>
                    </div>
                    <div>
                      <span>Audit plan</span>
                      <strong>{project.audit?.selected_lab_count ?? 0}</strong>
                      <small>{project.audit?.manual_review_required ? "manual review required" : "automated evidence only"}</small>
                    </div>
                  </div>
                  {project.consistency?.top_findings?.length ? (
                    <div className="studio-labs">
                      {project.consistency.top_findings.slice(0, 5).map((finding, index) => (
                        <span key={`${finding.domain}-${finding.kind}-${finding.subject}-${index}`}>
                          {finding.severity} · {finding.domain} · {finding.kind}{finding.subject ? ` · ${finding.subject}` : ""}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {project.audit?.top_labs?.length ? (
                    <div className="studio-labs">
                      {project.audit.top_labs.slice(0, 5).map((lab) => (
                        <span key={lab.lab}>{lab.priority} · {lab.lab}</span>
                      ))}
                    </div>
                  ) : null}
                </article>
              ))}
            </div>

            {(studio.portfolio?.reusable_pattern_candidates?.length ?? 0) > 0 ? (
              <div className="studio-portfolio">
                <strong>Cross-App reusable pattern candidates</strong>
                <div className="studio-labs">
                  {studio.portfolio?.reusable_pattern_candidates?.slice(0, 8).map((item) => (
                    <span key={item.key}>{item.key} · {item.project_count ?? 0} projects</span>
                  ))}
                </div>
              </div>
            ) : null}
          </>
        ) : (
          <div className="cc-empty studio-empty">
            <strong>Studio evidence is optional and separate from runtime certification.</strong>
            <span>Mount a generated <code>studio.json</code> to expose Product, UX, Architecture, Market and Cross-App evidence here.</span>
          </div>
        )}
      </div>

      {!snapshot?.available ? (
        <div className="cc-empty">
          <strong>No watcher snapshot mounted yet.</strong>
          <span>
            The Repo Watcher now publishes <code>control-center.json</code> with
            the central history artifact.
          </span>
        </div>
      ) : (
        <>
          <div className="cc-summary">
            <div>
              <span>Projects</span>
              <strong>{snapshot.summary.projects}</strong>
            </div>
            <div className="good">
              <span>PASS</span>
              <strong>{snapshot.summary.pass}</strong>
            </div>
            <div className="good">
              <span>Certified current</span>
              <strong>{snapshot.summary.certified_current ?? snapshot.summary.certified}</strong>
            </div>
            <div className="bad">
              <span>FAIL</span>
              <strong>{snapshot.summary.fail}</strong>
            </div>
            <div>
              <span>Not run</span>
              <strong>{snapshot.summary.not_run}</strong>
            </div>
          </div>

          {snapshot.summary.adaptive_metrics ? (
            <div className="cc-summary">
              <div>
                <span>Adaptive samples</span>
                <strong>{snapshot.summary.adaptive_metrics.sample_count ?? 0}</strong>
              </div>
              <div>
                <span>Wall clock p50 / p95</span>
                <strong>
                  {snapshot.summary.adaptive_metrics.wall_clock_seconds?.p50 ?? "—"}s /{" "}
                  {snapshot.summary.adaptive_metrics.wall_clock_seconds?.p95 ?? "—"}s
                </strong>
              </div>
              <div>
                <span>Runtime p50 / p95</span>
                <strong>
                  {snapshot.summary.adaptive_metrics.runtime_seconds?.p50 ?? "—"}s /{" "}
                  {snapshot.summary.adaptive_metrics.runtime_seconds?.p95 ?? "—"}s
                </strong>
              </div>
              <div>
                <span>AVD cache</span>
                <strong>
                  {snapshot.summary.adaptive_metrics.avd_cache_hit_ratio != null
                    ? `${Math.round(snapshot.summary.adaptive_metrics.avd_cache_hit_ratio * 100)}%`
                    : "—"}
                </strong>
              </div>
              <div>
                <span>Shadow false negatives</span>
                <strong>{snapshot.summary.adaptive_metrics.shadow_false_negatives ?? 0}</strong>
              </div>
              <div>
                <span>Shadow missed WARN</span>
                <strong>{snapshot.summary.adaptive_metrics.shadow_missed_warnings ?? 0}</strong>
              </div>
              <div>
                <span>Shadow over-selection</span>
                <strong>{snapshot.summary.adaptive_metrics.shadow_over_selections ?? 0}</strong>
              </div>
              <div>
                <span>Budget exceeded</span>
                <strong>{snapshot.summary.adaptive_metrics.budget_exceeded_runs ?? 0}</strong>
              </div>
              <div>
                <span>Learning applied</span>
                <strong>{snapshot.summary.adaptive_metrics.learning_applied_runs ?? 0}</strong>
              </div>
              <div>
                <span>Retryable failures</span>
                <strong>{snapshot.summary.retryable_failures ?? 0}</strong>
              </div>
              <div>
                <span>Flaky suspects</span>
                <strong>{snapshot.summary.flaky_suspects ?? 0}</strong>
              </div>
              <div className="good">
                <span>Release ready</span>
                <strong>{snapshot.summary.release_ready ?? 0}</strong>
              </div>
            </div>
          ) : null}

          {snapshot.summary.adaptive_metrics?.lane_metrics ? (
            <div className="cc-summary">
              {Object.entries(snapshot.summary.adaptive_metrics.lane_metrics).map(
                ([lane, metrics]) => (
                  <div key={lane}>
                    <span>{lane}</span>
                    <strong>
                      {metrics.wall_clock_seconds?.p50 ?? "—"}s /{" "}
                      {metrics.wall_clock_seconds?.p95 ?? "—"}s
                    </strong>
                    <small>{metrics.sample_count ?? 0} samples</small>
                  </div>
                ),
              )}
            </div>
          ) : null}

          <div className="cc-table-wrap">
            <table className="cc-table">
              <thead>
                <tr>
                  <th>Project</th>
                  <th>SHA</th>
                  <th>Engine</th>
                  <th>Mode</th>
                  <th>Lane</th>
                  <th>Risk</th>
                  <th>Confidence</th>
                  <th>Playbook</th>
                  <th>Failure</th>
                  <th>Readiness</th>
                  <th>Certification</th>
                  <th>Verdict</th>
                  <th>Maestro</th>
                  <th>Visual</th>
                  <th>Journey</th>
                  <th>Crawler</th>
                  <th>System</th>
                  <th>Network</th>
                  <th>Persistence</th>
                  <th>Configuration</th>
                  <th>Resources</th>
                  <th>Background</th>
                  <th>Storage</th>
                  <th>Upgrade</th>
                  <th>Performance</th>
                  <th>Release APK</th>
                </tr>
              </thead>
              <tbody>
                {snapshot.projects.map((project) => (
                  <tr key={project.repository}>
                    <td>
                      <div className="cc-project">
                        <strong>{project.repository}</strong>
                        <small>{project.applab_version || "AppLab"}</small>
                      </div>
                    </td>
                    <td>
                      <code>{shortSha(project.resolved_sha)}</code>
                    </td>
                    <td>{project.engine}</td>
                    <td>{project.analysis_mode ?? "full"}</td>
                    <td>{project.analysis_lane ?? "FULL_RUNTIME"}{project.shadow_full ? " · shadow" : ""}</td>
                    <td>{project.risk_score ?? "—"}</td>
                    <td>{project.confidence != null ? `${Math.round(project.confidence * 100)}%` : "—"}</td>
                    <td>
                      <div className="cc-project">
                        <span>{project.playbook?.category ?? "—"}</span>
                        <small>{project.learning_applied_labs?.length ? `learned +${project.learning_applied_labs.length}` : "baseline policy"}</small>
                      </div>
                    </td>
                    <td>
                      <div className="cc-project">
                        <span className={badgeClass(project.failure_intelligence?.kind === "NONE" ? "PASS" : project.failure_intelligence?.retryable ? "WARN" : project.failure_intelligence?.kind ? "FAIL" : "—")}>
                          {project.failure_intelligence?.kind ?? "—"}
                        </span>
                        <small>{project.failure_intelligence?.retryable ? "retryable" : project.flaky_detection?.suspected ? "flaky suspect" : "—"}</small>
                      </div>
                    </td>
                    <td>
                      <div className="cc-project">
                        <span className={badgeClass(project.release_readiness?.status === "RELEASE_READY" ? "PASS" : project.release_readiness?.status === "BLOCKED" ? "FAIL" : "WARN")}>
                          {project.release_readiness?.status ?? "—"}
                        </span>
                        <small>{project.verification_budget_seconds ? `${project.verification_budget_seconds}s budget${project.budget_pressure ? " · pressure" : ""}` : "no budget data"}</small>
                      </div>
                    </td>
                    <td>
                      <div className="cc-project">
                        <span className={badgeClass(project.certification_display_status ?? project.certification_status)}>
                          {gate(project.certification_display_status ?? project.certification_status)}
                        </span>
                        <small>
                          {project.certified_sha
                            ? `${shortSha(project.certified_sha)} · API ${project.certification?.matrix?.[0]?.api_level ?? "?"}${project.certification_display_status === "CERTIFIED_STALE" ? " · newer SHA not certified" : ""}`
                            : "no production certification"}
                        </small>
                      </div>
                    </td>
                    <td>
                      <span className={badgeClass(project.result)}>
                        {project.result}
                      </span>
                    </td>
                    <td>{gate(project.maestro)}</td>
                    <td>{gate(project.visual_regression || project.visual_qa)}</td>
                    <td>{gate(project.visual_journey)}</td>
                    <td>{gate(project.interaction_crawl)}</td>
                    <td>{gate(project.system_lab)}</td>
                    <td>{gate(project.network_lab)}</td>
                    <td>{gate(project.persistence_lab)}</td>
                    <td>{gate(project.configuration_lab)}</td>
                    <td>{gate(project.resource_pressure_lab)}</td>
                    <td>{gate(project.background_lab)}</td>
                    <td>{gate(project.storage_lab)}</td>
                    <td>{gate(project.upgrade_lab)}</td>
                    <td>
                      <div className="cc-project">
                        <span className={badgeClass(project.performance_lab)}>
                          {gate(project.performance_lab)}
                        </span>
                        <small>
                          {project.performance?.startup?.cold?.total_time_ms != null
                            ? `${project.performance.startup.cold.total_time_ms} ms cold`
                            : "no baseline"}
                        </small>
                      </div>
                    </td>
                    <td>
                      {project.release?.artifact_url ? (
                        <a
                          className="cc-release-link"
                          href={project.release.artifact_url}
                          target="_blank"
                          rel="noreferrer"
                          title={project.release.changelog_summary || "Verified installable APK"}
                        >
                          {project.release.apk?.version_name
                            ? `v${project.release.apk.version_name}`
                            : "Download"}
                          {project.release.apk?.size_human
                            ? ` · ${project.release.apk.size_human}`
                            : ""}
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="cc-history-head">
            <strong>Recent watcher results</strong>
            {snapshot.recent.length > 6 ? (
              <button className="ghost" onClick={() => setExpanded((value) => !value)}>
                {expanded ? "Show less" : "Show more"}
              </button>
            ) : null}
          </div>

          <div className="cc-history">
            {recent.map((item, index) => (
              <div
                className="cc-history-row"
                key={`${item.recorded_at || ""}-${item.repository || ""}-${index}`}
              >
                <span className={badgeClass(item.result || "NOT_RUN")}>
                  {item.result || "NOT_RUN"}
                </span>
                <div>
                  <strong>{item.repository || "unknown"}</strong>
                  <small>
                    {shortSha(item.resolved_sha || "")}
                    {item.engine ? ` · ${item.engine}` : ""}
                    {item.analysis_lane ? ` · ${item.analysis_lane}` : ""}
                    {item.risk_score != null ? ` · risk ${item.risk_score}` : ""}
                    {item.failure_intelligence?.kind ? ` · ${item.failure_intelligence.kind}` : ""}
                    {item.release_readiness?.status ? ` · ${item.release_readiness.status}` : ""}
                    {item.certification_status &&
                    item.certification_status !== "NOT_REQUESTED"
                      ? ` · ${item.certification_status}`
                      : ""}
                  </small>
                </div>
                <time>
                  {item.recorded_at
                    ? new Date(item.recorded_at).toLocaleString()
                    : "—"}
                </time>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
