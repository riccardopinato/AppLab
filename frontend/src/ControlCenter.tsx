import { useCallback, useEffect, useMemo, useState } from "react";

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
  applab_version: string;
  recorded_at: string;
  watcher_run_id: string;
  watcher_run_url: string;
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
  watcher_run_id?: string;
  watcher_run_url?: string;
  applab_version?: string;
};

type Snapshot = {
  available: boolean;
  generated_at: string;
  summary: {
    projects: number;
    pass: number;
    fail: number;
    not_run: number;
  };
  projects: ProjectRow[];
  recent: RecentRow[];
};

function badgeClass(value: string) {
  if (value === "PASS") return "cc-badge good";
  if (value === "FAIL" || value === "ERROR") return "cc-badge bad";
  if (value === "WARN") return "cc-badge warn";
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
                  <th>Verdict</th>
                  <th>Maestro</th>
                  <th>Visual</th>
                  <th>Journey</th>
                  <th>Crawler</th>
                  <th>System</th>
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
