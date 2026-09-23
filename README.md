# AppLab

AppLab is a reusable Android APK verification lab.

## v0.3 — Live Android Emulator

AppLab can now own the Android runtime instead of requiring an emulator to be
started manually.

The v0.3 Live stack:

```
Browser / AppLab UI
        |
        | HTTP + WebSocket
        v
AppLab Controller + WebRTC Gateway
        |
        | gRPC :8554
        v
Google Android Emulator container
        |
        +--> ADB :5555
        +--> /dev/kvm
```

From the dashboard you can:

- start the managed Android emulator;
- wait for Android boot automatically;
- start the Google WebRTC signaling gateway;
- view and control Android in the browser;
- restart or stop the complete live runtime;
- upload/install APKs;
- launch/restart/stop/clear/uninstall apps;
- run Maestro flows;
- inspect screenshots, filtered Logcat and PASS/FAIL diagnostics;
- keep controller history across restarts.

## Requirements for Live mode

Live Emulator requires a **Linux host with KVM**. Docker Desktop on Windows and
macOS does not provide the KVM setup required by Google's Android Emulator
containers.

Check the host first:

```bash
chmod +x scripts/check_live_host.sh
./scripts/check_live_host.sh
```

Bare-metal Linux is preferred. Cloud VMs can work when nested virtualization is
enabled.

## Start AppLab v0.3 Live

```bash
cp .env.example .env
docker compose -f docker-compose.live.yml up --build
```

Then open:

```
http://localhost:5173
```

The browser frontend talks to:

- AppLab backend: `http://localhost:8000`
- WebRTC gateway: `localhost:8080`
- Android ADB: `127.0.0.1:5555`
- Android Emulator gRPC/WebRTC: `127.0.0.1:8554`

Press **Start emulator** in the Live Runtime panel. AppLab will pull/start the
configured Android Emulator image, connect ADB, wait for
`sys.boot_completed=1`, then launch the WebRTC gateway.

The default image is Google's published API 30 Google APIs x86_64 container:

```
us-docker.pkg.dev/android-emulator-268719/images/30-google-x64:30.1.2
```

Override `APPLAB_EMULATOR_IMAGE` in `.env` to use a compatible image you
have built or published for newer Android API levels.

## Standard Control Center

The non-KVM control plane remains available:

```bash
docker compose up --build
```

This mode controls an existing ADB target and does not manage the emulator
lifecycle itself.

## Quality Gate

```
code -> analyze -> tests -> APK -> emulator -> install -> launch
     -> Maestro -> screenshot -> Logcat -> crash scan -> report
```

## Main API

```
GET  /api/runtime
POST /api/runtime/start
POST /api/runtime/restart
POST /api/runtime/stop

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

For Flutter repositories, use
`.github/workflows/verify-flutter.yml` as the reusable AppLab runtime gate.

## Upstream foundations

- Google Android Emulator / android-emulator-container-scripts
- Google android-emulator-webrtc
- ReactiveCircus android-emulator-runner
- Maestro

See `NOTICE.md`.
