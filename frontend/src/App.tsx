import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Emulator } from "android-emulator-webrtc/dist/index.js";
import type { EmulatorRef } from "android-emulator-webrtc/dist/components/emulator/emulator";

const BACKEND = import.meta.env.VITE_BACKEND_URL || "http://localhost:8000";
const DEFAULT_GATEWAY = import.meta.env.VITE_GATEWAY_URI || "localhost:8080";

type DeviceInfo = {
  serial: string;
  model: string;
  manufacturer: string;
  android: string;
  sdk: string;
  boot_completed: string;
};

type RuntimeStatus = {
  docker_available: boolean;
  docker_error: string;
  kvm_available: boolean;
  image: string;
  container_name: string;
  container_id: string;
  container_state: string;
  adb_serial: string;
  adb_ready: boolean;
  boot_completed: boolean;
  gateway_ready: boolean;
  gateway_uri: string;
  gateway_log: string;
  live_ready: boolean;
};

type AppStatus = {
  package_id: string;
  installed: boolean;
  running: boolean;
  foreground: boolean;
  pid: string;
};

type Issue = {
  code: string;
  severity: string;
  message: string;
};

type Report = {
  result: "PASS" | "FAIL";
  package_id: string;
  running: boolean;
  issue_count: number;
  issues: Issue[];
  status: AppStatus;
  device: DeviceInfo;
};

type TestCatalog = {
  available: boolean;
  flows: string[];
};

type HistoryEntry = {
  timestamp: string;
  action: string;
  status: string;
  package_id: string;
  details: Record<string, unknown>;
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${BACKEND}${path}`, {
    ...init,
    headers,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return body as T;
}

function verdictClass(value?: string) {
  if (value === "PASS") return "good";
  if (value === "FAIL") return "bad";
  return "neutral";
}

export default function App() {
  const emulatorRef = useRef<EmulatorRef | null>(null);
  const [gateway, setGateway] = useState(DEFAULT_GATEWAY);
  const [packageId, setPackageId] = useState(() => localStorage.getItem("applab.package") || "");
  const [apk, setApk] = useState<File | null>(null);
  const [device, setDevice] = useState<DeviceInfo | null>(null);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [appStatus, setAppStatus] = useState<AppStatus | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [tests, setTests] = useState<TestCatalog>({ available: false, flows: ["generic-smoke"] });
  const [selectedFlow, setSelectedFlow] = useState("generic-smoke");
  const [testOutput, setTestOutput] = useState("");
  const [logcat, setLogcat] = useState("");
  const [status, setStatus] = useState("Ready");
  const [webrtcState, setWebrtcState] = useState("idle");
  const [busy, setBusy] = useState(false);
  const [viewMode, setViewMode] = useState<"live" | "screenshot">("live");
  const [screenshotNonce, setScreenshotNonce] = useState(0);
  const [screenshotVisible, setScreenshotVisible] = useState(false);

  const cleanPackage = packageId.trim();
  const screenshotUrl = useMemo(
    () => `${BACKEND}/api/screenshot?t=${screenshotNonce}`,
    [screenshotNonce],
  );

  useEffect(() => {
    localStorage.setItem("applab.package", packageId);
  }, [packageId]);

  useEffect(() => {
    if (!runtime?.live_ready) {
      setWebrtcState("idle");
    }
  }, [runtime?.live_ready]);

  const refreshRuntime = useCallback(async () => {
    try {
      const next = await api<RuntimeStatus>("/api/runtime");
      setRuntime(next);
      if (next.gateway_uri) setGateway(next.gateway_uri);
    } catch {
      setRuntime(null);
    }
  }, []);

  const refreshDevice = useCallback(async () => {
    try {
      const next = await api<DeviceInfo>("/api/device");
      setDevice(next);
    } catch {
      setDevice(null);
    }
  }, []);

  const refreshHistory = useCallback(async () => {
    try {
      const body = await api<{ entries: HistoryEntry[] }>("/api/history?limit=24");
      setHistory(body.entries);
    } catch {
      setHistory([]);
    }
  }, []);

  const refreshTests = useCallback(async () => {
    try {
      const body = await api<TestCatalog>("/api/tests");
      setTests(body);
      if (!body.flows.includes(selectedFlow)) {
        setSelectedFlow(body.flows[0] || "generic-smoke");
      }
    } catch {
      setTests({ available: false, flows: ["generic-smoke"] });
    }
  }, [selectedFlow]);

  const refreshPackage = useCallback(async () => {
    if (!cleanPackage) {
      setAppStatus(null);
      setReport(null);
      return;
    }

    try {
      const next = await api<AppStatus>(
        `/api/app/status?package_id=${encodeURIComponent(cleanPackage)}`,
      );
      setAppStatus(next);
    } catch {
      setAppStatus(null);
    }
  }, [cleanPackage]);

  const refreshReport = useCallback(async () => {
    if (!cleanPackage) {
      setReport(null);
      return;
    }

    try {
      const next = await api<Report>(
        `/api/report?package_id=${encodeURIComponent(cleanPackage)}`,
      );
      setReport(next);
    } catch {
      setReport(null);
    }
  }, [cleanPackage]);

  const refreshLogcat = useCallback(async () => {
    const suffix = cleanPackage
      ? `&package_id=${encodeURIComponent(cleanPackage)}`
      : "";
    const body = await api<{ logcat: string }>(`/api/logcat?lines=900${suffix}`);
    setLogcat(body.logcat || "");
  }, [cleanPackage]);

  const refreshAll = useCallback(async () => {
    await Promise.allSettled([
      refreshRuntime(),
      refreshDevice(),
      refreshPackage(),
      refreshReport(),
      refreshHistory(),
      refreshTests(),
    ]);
  }, [refreshDevice, refreshHistory, refreshPackage, refreshReport, refreshRuntime, refreshTests]);

  useEffect(() => {
    void refreshAll();
    const timer = window.setInterval(() => {
      void refreshRuntime();
      void refreshDevice();
      void refreshPackage();
    }, 8000);
    return () => window.clearInterval(timer);
  }, [refreshAll, refreshDevice, refreshPackage, refreshRuntime]);

  const runAction = async <T,>(label: string, work: () => Promise<T>) => {
    setBusy(true);
    setStatus(`${label}…`);
    try {
      const result = await work();
      setStatus(`${label}: OK`);
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus(`${label}: ${message}`);
      throw error;
    } finally {
      setBusy(false);
    }
  };

  const runtimeAction = async (path: string, label: string) => {
    try {
      const next = await runAction(label, () =>
        api<RuntimeStatus>(path, { method: "POST" }),
      );
      setRuntime(next);
      if (next.gateway_uri) setGateway(next.gateway_uri);
      if (next.live_ready) setViewMode("live");
      await Promise.allSettled([refreshDevice(), refreshHistory()]);
    } catch {
      await refreshRuntime();
    }
  };

  const install = async () => {
    try {
      await runAction("Install APK", async () => {
        if (!apk) throw new Error("Choose an APK first");
        const form = new FormData();
        form.append("file", apk);

        const response = await fetch(`${BACKEND}/api/apk/install`, {
          method: "POST",
          body: form,
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || "Install failed");

        if (body.package_id) {
          setPackageId(body.package_id);
        }
        return body;
      });
      await refreshAll();
    } catch {
      // Status already contains the actionable error.
    }
  };

  const packageAction = async (path: string, label: string) => {
    try {
      await runAction(label, async () => {
        if (!cleanPackage) throw new Error("Package id required");
        return api(path, {
          method: "POST",
          body: JSON.stringify({ package_id: cleanPackage }),
        });
      });
      await Promise.allSettled([refreshPackage(), refreshReport(), refreshHistory()]);
    } catch {
      // Status already contains the actionable error.
    }
  };

  const uninstall = async () => {
    if (!cleanPackage) {
      setStatus("Uninstall: package id required");
      return;
    }
    if (!window.confirm(`Uninstall ${cleanPackage} from the emulator?`)) return;
    await packageAction("/api/app/uninstall", "Uninstall");
  };

  const captureScreenshot = async () => {
    setScreenshotVisible(true);
    setScreenshotNonce(Date.now());
    setViewMode("screenshot");
    setStatus("Screenshot refreshed");
  };

  const runTest = async () => {
    try {
      const result = await runAction("AppLab Test", async () => {
        if (!cleanPackage) throw new Error("Package id required");
        return api<{ ok: boolean; flow: string; output: string }>("/api/tests/run", {
          method: "POST",
          body: JSON.stringify({
            package_id: cleanPackage,
            flow: selectedFlow,
          }),
        });
      });

      setTestOutput(result.output || (result.ok ? "PASS" : "FAIL"));
      await Promise.allSettled([
        refreshPackage(),
        refreshReport(),
        refreshHistory(),
        refreshLogcat(),
      ]);
      setScreenshotVisible(true);
      setScreenshotNonce(Date.now());
      setViewMode("screenshot");
    } catch {
      await Promise.allSettled([refreshReport(), refreshHistory()]);
    }
  };

  const hardwareKey = async (key: string, rtcKey: string) => {
    try {
      if (viewMode === "live" && emulatorRef.current?.sendKey) {
        emulatorRef.current.sendKey(rtcKey);
        setStatus(`${key}: sent over WebRTC`);
        return;
      }
      await runAction(key, () =>
        api("/api/device/key", {
          method: "POST",
          body: JSON.stringify({ key }),
        }),
      );
    } catch {
      // Status already contains the actionable error.
    }
  };

  const clearLogcat = async () => {
    try {
      await runAction("Clear Logcat", () =>
        api("/api/logcat/clear", { method: "POST" }),
      );
      setLogcat("");
      await refreshHistory();
    } catch {
      // Status already contains the actionable error.
    }
  };

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">ANDROID VERIFICATION LAB</p>
          <div className="title-row">
            <h1>AppLab</h1>
            <span className="version">v0.6.3</span>
          </div>
          <p className="subtitle">Live Android Emulator · WebRTC · ADB · Maestro · Diagnostics</p>
        </div>
        <div className={`status-pill ${status.includes("OK") || status === "Ready" ? "good" : "neutral"}`}>
          <span className="status-dot" />
          {status}
        </div>
      </header>

      <section className="metrics">
        <article className={`metric-card ${runtime?.live_ready ? "good" : "neutral"}`}>
          <span>Live Runtime</span>
          <strong>{runtime?.live_ready ? "READY" : runtime?.container_state === "running" ? "BOOTING" : "STOPPED"}</strong>
          <small>{runtime?.live_ready ? "Android + WebRTC online" : runtime?.kvm_available ? "KVM available" : "Linux/KVM required"}</small>
        </article>
        <article className="metric-card">
          <span>Emulator</span>
          <strong>{device?.boot_completed === "1" ? "ONLINE" : "OFFLINE"}</strong>
          <small>{device ? `${device.model} · Android ${device.android}` : "ADB not connected"}</small>
        </article>
        <article className="metric-card">
          <span>Application</span>
          <strong>{appStatus?.running ? "RUNNING" : appStatus?.installed ? "STOPPED" : "NO APP"}</strong>
          <small>{appStatus?.pid ? `PID ${appStatus.pid}` : cleanPackage || "Select a package"}</small>
        </article>
        <article className={`metric-card ${verdictClass(report?.result)}`}>
          <span>Runtime QA</span>
          <strong>{report?.result || "NOT RUN"}</strong>
          <small>{report ? `${report.issue_count} issue(s)` : "Run diagnostics or Maestro"}</small>
        </article>
      </section>

      <section className="workspace">
        <div className="phone-card">
          <div className="phone-toolbar">
            <div>
              <span className="panel-kicker">DEVICE VIEW</span>
              <strong>{device?.model || "Android Emulator"}</strong>
            </div>
            <div className="segmented">
              <button
                className={viewMode === "live" ? "active" : ""}
                onClick={() => setViewMode("live")}
              >
                Live
              </button>
              <button
                className={viewMode === "screenshot" ? "active" : ""}
                onClick={() => setViewMode("screenshot")}
              >
                Screenshot
              </button>
            </div>
          </div>

          <div
            className="phone-frame"
            data-testid="device-live-view"
            data-webrtc-state={webrtcState}
          >
            {viewMode === "live" ? (
              runtime?.live_ready ? (
                <Emulator
                  key={`${gateway}-${runtime.container_id}`}
                  ref={emulatorRef}
                  uri={gateway}
                  muted
                  onStateChange={(state: string) => {
                    setWebrtcState(state);
                    setStatus(`WebRTC: ${state}`);
                  }}
                  onError={(error: unknown) => {
                    setWebrtcState("error");
                    setStatus(`WebRTC: ${String(error)}`);
                  }}
                />
              ) : (
                <div className="empty-phone">
                  <strong>Live runtime offline</strong>
                  <span>Start the managed emulator to connect WebRTC.</span>
                </div>
              )
            ) : screenshotVisible ? (
              <img
                className="phone-screenshot"
                src={screenshotUrl}
                alt="Latest Android emulator screenshot"
              />
            ) : (
              <div className="empty-phone">
                <strong>No screenshot yet</strong>
                <span>Use Capture in Diagnostics.</span>
              </div>
            )}
          </div>

          <div className="hardware">
            <button disabled={busy} onClick={() => hardwareKey("back", "GoBack")}>Back</button>
            <button data-testid="hardware-home" disabled={busy} onClick={() => hardwareKey("home", "GoHome")}>Home</button>
            <button disabled={busy} onClick={() => hardwareKey("recent", "AppSwitch")}>Recent</button>
            <button disabled={busy} onClick={() => hardwareKey("power", "Power")}>Power</button>
          </div>

          <label className="compact-field">
            WebRTC Gateway
            <input value={gateway} onChange={(event) => setGateway(event.target.value)} />
          </label>
        </div>

        <div className="controls">
          <section className="panel runtime-panel">
            <div className="panel-heading">
              <div>
                <span className="panel-kicker">00 · LIVE RUNTIME</span>
                <h2>Managed Android Emulator</h2>
              </div>
              <div className={`mini-badge ${runtime?.live_ready ? "good" : runtime?.docker_available && runtime?.kvm_available ? "neutral" : "bad"}`}>
                {runtime?.live_ready ? "LIVE" : runtime?.container_state === "running" ? "BOOTING" : "OFFLINE"}
              </div>
            </div>

            <div className="runtime-grid">
              <div><span>Docker</span><strong>{runtime?.docker_available ? "READY" : "OFFLINE"}</strong></div>
              <div><span>KVM</span><strong>{runtime?.kvm_available ? "READY" : "MISSING"}</strong></div>
              <div><span>ADB</span><strong>{runtime?.adb_ready ? "READY" : "OFFLINE"}</strong></div>
              <div><span>WebRTC</span><strong>{runtime?.gateway_ready ? "READY" : "OFFLINE"}</strong></div>
            </div>

            <p className="runtime-image">{runtime?.image || "Live runtime not available in this deployment."}</p>
            {runtime?.docker_error ? <p className="runtime-error">{runtime.docker_error}</p> : null}

            <div className="button-grid">
              <button
                className="primary"
                disabled={busy || runtime?.live_ready}
                onClick={() => void runtimeAction("/api/runtime/start", "Start emulator")}
              >
                Start emulator
              </button>
              <button
                disabled={busy || runtime?.container_state !== "running"}
                onClick={() => void runtimeAction("/api/runtime/restart", "Restart emulator")}
              >
                Restart
              </button>
              <button
                className="danger"
                disabled={busy || runtime?.container_state === "missing"}
                onClick={() => void runtimeAction("/api/runtime/stop", "Stop emulator")}
              >
                Stop
              </button>
            </div>
          </section>

          <section className="panel">
            <div className="panel-heading">
              <div>
                <span className="panel-kicker">01 · DEVICE</span>
                <h2>Android runtime</h2>
              </div>
              <button className="ghost" onClick={() => void refreshAll()}>Refresh</button>
            </div>
            <div className="device-grid">
              <div><span>Model</span><strong>{device?.model || "—"}</strong></div>
              <div><span>Android</span><strong>{device?.android || "—"}</strong></div>
              <div><span>SDK</span><strong>{device?.sdk || "—"}</strong></div>
              <div><span>Serial</span><strong>{device?.serial || "—"}</strong></div>
            </div>
          </section>

          <section className="panel">
            <div className="panel-heading">
              <div>
                <span className="panel-kicker">02 · APPLICATION</span>
                <h2>APK & process control</h2>
              </div>
              <div className={`mini-badge ${appStatus?.running ? "good" : "neutral"}`}>
                {appStatus?.foreground ? "FOREGROUND" : appStatus?.running ? "BACKGROUND" : "IDLE"}
              </div>
            </div>

            <div className="apk-row">
              <label className="file-picker">
                <input
                  type="file"
                  accept=".apk,application/vnd.android.package-archive"
                  onChange={(event) => setApk(event.target.files?.[0] || null)}
                />
                <span>{apk?.name || "Choose APK"}</span>
              </label>
              <button className="primary" disabled={busy || !apk} onClick={() => void install()}>
                Install APK
              </button>
            </div>

            <label>
              Package id
              <input
                placeholder="com.example.app"
                value={packageId}
                onChange={(event) => setPackageId(event.target.value)}
              />
            </label>

            <div className="button-grid">
              <button disabled={busy || !cleanPackage} onClick={() => void packageAction("/api/app/launch", "Launch")}>Launch</button>
              <button disabled={busy || !cleanPackage} onClick={() => void packageAction("/api/app/restart", "Restart")}>Restart</button>
              <button disabled={busy || !cleanPackage} onClick={() => void packageAction("/api/app/stop", "Stop")}>Stop</button>
              <button disabled={busy || !cleanPackage} onClick={() => void packageAction("/api/app/clear", "Clear data")}>Clear data</button>
              <button className="danger" disabled={busy || !cleanPackage} onClick={() => void uninstall()}>Uninstall</button>
            </div>
          </section>

          <section className="panel qa-panel">
            <div className="panel-heading">
              <div>
                <span className="panel-kicker">03 · AUTOMATED QA</span>
                <h2>Run AppLab Test</h2>
              </div>
              <div className={`mini-badge ${tests.available ? "good" : "bad"}`}>
                Maestro {tests.available ? "READY" : "OFFLINE"}
              </div>
            </div>

            <div className="test-row">
              <label>
                Test flow
                <select
                  value={selectedFlow}
                  onChange={(event) => setSelectedFlow(event.target.value)}
                >
                  {tests.flows.map((flow) => (
                    <option key={flow} value={flow}>{flow}</option>
                  ))}
                </select>
              </label>
              <button
                className="primary run-test"
                disabled={busy || !cleanPackage || !tests.available}
                onClick={() => void runTest()}
              >
                Run AppLab Test
              </button>
            </div>

            <div className={`verdict ${verdictClass(report?.result)}`}>
              <div>
                <span>VERDICT</span>
                <strong>{report?.result || "NOT RUN"}</strong>
              </div>
              <div>
                <span>PROCESS</span>
                <strong>{report?.status.running ? "ALIVE" : "STOPPED"}</strong>
              </div>
              <div>
                <span>ISSUES</span>
                <strong>{report?.issue_count ?? "—"}</strong>
              </div>
            </div>

            {report?.issues.length ? (
              <div className="issues">
                {report.issues.map((issue) => (
                  <div key={issue.code}>
                    <strong>{issue.code}</strong>
                    <span>{issue.message}</span>
                  </div>
                ))}
              </div>
            ) : null}

            {testOutput ? <pre className="test-output">{testOutput}</pre> : null}
          </section>

          <section className="panel">
            <div className="panel-heading">
              <div>
                <span className="panel-kicker">04 · DIAGNOSTICS</span>
                <h2>Screenshot & Logcat</h2>
              </div>
            </div>
            <div className="button-grid">
              <button onClick={() => void captureScreenshot()}>Capture screenshot</button>
              <button
                onClick={() =>
                  void runAction("Logcat", refreshLogcat).catch(() => undefined)
                }
              >
                Refresh Logcat
              </button>
              <button onClick={() => void clearLogcat()}>Clear Logcat</button>
              <button
                onClick={() =>
                  void runAction("Runtime report", refreshReport).catch(() => undefined)
                }
              >
                Re-run diagnostics
              </button>
            </div>
            <pre className="logcat">{logcat || "Package-filtered Logcat will appear here."}</pre>
          </section>

          <section className="panel">
            <div className="panel-heading">
              <div>
                <span className="panel-kicker">05 · HISTORY</span>
                <h2>Recent sessions</h2>
              </div>
              <button className="ghost" onClick={() => void refreshHistory()}>Refresh</button>
            </div>
            <div className="history">
              {history.length ? history.map((entry, index) => (
                <div className="history-row" key={`${entry.timestamp}-${index}`}>
                  <span className={`history-status ${entry.status === "PASS" ? "good" : "bad"}`} />
                  <div>
                    <strong>{entry.action}</strong>
                    <small>{entry.package_id || "AppLab"}</small>
                  </div>
                  <time>{new Date(entry.timestamp).toLocaleTimeString()}</time>
                </div>
              )) : (
                <p className="empty-copy">No controller actions recorded yet.</p>
              )}
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}
