import { useMemo, useRef, useState } from "react";
import { Emulator } from "android-emulator-webrtc/dist/index.js";
import type { EmulatorRef } from "android-emulator-webrtc/dist/components/emulator/emulator";

const BACKEND = import.meta.env.VITE_BACKEND_URL || "http://localhost:8000";
const DEFAULT_GATEWAY = import.meta.env.VITE_GATEWAY_URI || "localhost:8080";

async function jsonRequest(path: string, init?: RequestInit) {
  const response = await fetch(`${BACKEND}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return body;
}

export default function App() {
  const emulatorRef = useRef<EmulatorRef | null>(null);
  const [gateway, setGateway] = useState(DEFAULT_GATEWAY);
  const [packageId, setPackageId] = useState("");
  const [apk, setApk] = useState<File | null>(null);
  const [status, setStatus] = useState("Idle");
  const [logcat, setLogcat] = useState("");
  const [screenshotNonce, setScreenshotNonce] = useState(0);
  const screenshotUrl = useMemo(
    () => `${BACKEND}/api/screenshot?t=${screenshotNonce}`,
    [screenshotNonce],
  );

  const action = async (name: string, fn: () => Promise<unknown>) => {
    setStatus(`${name}…`);
    try {
      await fn();
      setStatus(`${name}: OK`);
    } catch (error) {
      setStatus(`${name}: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const packageAction = (path: string, label: string) =>
    action(label, async () => {
      if (!packageId.trim()) throw new Error("Package id required");
      await jsonRequest(path, {
        method: "POST",
        body: JSON.stringify({ package_id: packageId.trim() }),
      });
    });

  const install = () =>
    action("Install APK", async () => {
      if (!apk) throw new Error("Choose an APK first");
      const form = new FormData();
      form.append("file", apk);
      const response = await fetch(`${BACKEND}/api/apk/install`, {
        method: "POST",
        body: form,
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "Install failed");
    });

  const hardwareKey = async (key: string, rtcKey: string) => {
    if (emulatorRef.current?.sendKey) {
      emulatorRef.current.sendKey(rtcKey);
      return;
    }
    await jsonRequest("/api/device/key", {
      method: "POST",
      body: JSON.stringify({ key }),
    });
  };

  return (
    <main className="app-shell">
      <header>
        <div>
          <p className="eyebrow">ANDROID VERIFICATION LAB</p>
          <h1>AppLab</h1>
        </div>
        <div className="status">{status}</div>
      </header>

      <section className="grid">
        <div className="phone-card">
          <div className="phone-frame">
            <Emulator
              ref={emulatorRef}
              uri={gateway}
              muted
              onStateChange={(state: string) => setStatus(`WebRTC: ${state}`)}
              onError={(error: unknown) => setStatus(`WebRTC: ${String(error)}`)}
            />
          </div>
          <div className="hardware">
            <button onClick={() => hardwareKey("back", "GoBack")}>Back</button>
            <button onClick={() => hardwareKey("home", "GoHome")}>Home</button>
            <button onClick={() => hardwareKey("recent", "AppSwitch")}>Recent</button>
            <button onClick={() => hardwareKey("power", "Power")}>Power</button>
          </div>
        </div>

        <div className="controls">
          <div className="panel">
            <h2>Connection</h2>
            <label>
              Emulator Gateway
              <input value={gateway} onChange={(e) => setGateway(e.target.value)} />
            </label>
            <p className="hint">WebRTC is optional. ADB controls work without video.</p>
          </div>

          <div className="panel">
            <h2>APK</h2>
            <label className="file">
              <input
                type="file"
                accept=".apk,application/vnd.android.package-archive"
                onChange={(e) => setApk(e.target.files?.[0] || null)}
              />
              {apk?.name || "Choose APK"}
            </label>
            <button className="primary" onClick={install}>Install APK</button>
          </div>

          <div className="panel">
            <h2>Application</h2>
            <label>
              Package id
              <input
                placeholder="com.example.app"
                value={packageId}
                onChange={(e) => setPackageId(e.target.value)}
              />
            </label>
            <div className="button-grid">
              <button onClick={() => packageAction("/api/app/launch", "Launch")}>Launch</button>
              <button onClick={() => packageAction("/api/app/stop", "Stop")}>Stop</button>
              <button onClick={() => packageAction("/api/app/clear", "Clear data")}>Clear data</button>
            </div>
          </div>

          <div className="panel">
            <h2>Diagnostics</h2>
            <div className="button-grid">
              <button onClick={() => setScreenshotNonce(Date.now())}>Screenshot</button>
              <button
                onClick={() =>
                  action("Logcat", async () => {
                    const body = await jsonRequest("/api/logcat?lines=700");
                    setLogcat(body.logcat || "");
                  })
                }
              >
                Refresh Logcat
              </button>
              <button
                onClick={() =>
                  action("Clear Logcat", () =>
                    jsonRequest("/api/logcat/clear", { method: "POST" }),
                  )
                }
              >
                Clear Logcat
              </button>
            </div>
            <img className="screenshot" src={screenshotUrl} alt="Latest emulator screenshot" />
            <pre>{logcat || "Logcat output will appear here."}</pre>
          </div>
        </div>
      </section>
    </main>
  );
}
