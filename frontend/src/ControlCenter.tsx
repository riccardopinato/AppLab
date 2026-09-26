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
  verification_lane?: string;
  risk?: { label?: string; score?: number };
  confidence?: number | null;
  shadow_full?: boolean;
  verification_fingerprint?: string;
  cache_domains?: string[];
  telemetry?: { planner_duration_ms?: number };
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
  verification_lane?: string;
  risk?: { label?: string; score?: number };
  confidence?: number | null;
  shadow_full?: boolean;
  verification_fingerprint?: string;
  cache_domains?: string[];
  telemetry?: { planner_duration_ms?: number };
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
    fast_runtime?: number;
    full_runtime?: number;
    no_runtime?: number;
    shadow_runs?: number;
    shadow_false_negatives?: number;
  };
  projects: ProjectRow[];
  recent: RecentRow[];
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
  const [error, setError] = useState("");
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

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(timer);
  }, [refresh]);

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
                    <td>
                      <div className="cc-project">
                        <strong>{project.verification_lane || "—"}</strong>
                        <small>{project.shadow_full ? "shadow FULL" : project.verification_fingerprint || "—"}</small>
                      </div>
                    </td>
                    <td>
                      <div className="cc-project">
                        <span className={badgeClass(project.risk?.label === "CRITICAL" ? "FAIL" : project.risk?.label === "HIGH" ? "WARN" : "PASS")}>
                          {project.risk?.label || "—"}
                        </span>
                        <small>
                          {project.confidence != null
                            ? `${Math.round(project.confidence * 100)}% confidence`
                            : "—"}
                        </small>
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
                    {item.verification_lane ? ` · ${item.verification_lane}` : ""}
                    {item.risk?.label ? ` · ${item.risk.label}` : ""}
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
