# AppLab

AppLab is a reusable Android APK verification lab.

## v0.2 — Live Control Center

The browser dashboard is now an operational Android QA console rather than a
static controller. It provides:

- emulator/device health and Android/SDK information;
- APK upload and install;
- package auto-detection when available;
- launch, restart, stop, clear-data and uninstall controls;
- WebRTC device view when an Emulator Gateway is connected;
- screenshot fallback when streaming is unavailable;
- package-filtered Logcat;
- runtime PASS/FAIL diagnostics for process death, ANR, Android fatal
  exceptions and unhandled Flutter/framework exceptions;
- Maestro flow discovery and one-click execution;
- persistent controller history in Docker;
- reusable CI quality gates for Flutter application repositories.

## Quality Gate

```
code -> analyze -> tests -> APK -> emulator -> install -> launch
     -> Maestro -> screenshot -> Logcat -> crash scan -> report
```

## Live Control Center

```bash
cp .env.example .env
docker compose up --build
```

Frontend: http://localhost:5173  
Backend API: http://localhost:8000

Set `ADB_SERIAL` when the controller must target a remote ADB endpoint.
`VITE_GATEWAY_URI` points the browser at a compatible Android Emulator
WebRTC gateway. Streaming is optional: all ADB controls and diagnostics work
without it.

The backend image includes ADB, Java and Maestro. Controller actions are
stored in the `applab-data` Docker volume.

## Main API

```
GET  /api/device
GET  /api/apps
GET  /api/app/status?package_id=...
POST /api/apk/install
POST /api/app/launch
POST /api/app/restart
POST /api/app/stop
POST /api/app/clear
POST /api/app/uninstall
GET  /api/screenshot
GET  /api/logcat?package_id=...
GET  /api/report?package_id=...
GET  /api/tests
POST /api/tests/run
GET  /api/history
```

## CI verification

```bash
chmod +x scripts/*.sh
./scripts/verify_apk.sh path/to/app.apk com.example.app
```

Artifacts are written to `applab-report/`: screenshots, UI hierarchy,
package-filtered/full Logcat and Markdown summary.

For Flutter repositories, use
`.github/workflows/verify-flutter.yml` as the reusable AppLab runtime gate.

## Upstream foundations

- Google Android Emulator / android-emulator-container-scripts
- Google android-emulator-webrtc
- ReactiveCircus android-emulator-runner
- Maestro

See `NOTICE.md`.
