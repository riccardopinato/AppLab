# AppLab

AppLab is a reusable Android APK verification lab.

## Layers

1. **Quality Gate** — boot Android in CI, install an APK, launch it, capture screenshot/UI hierarchy/Logcat, verify the process survives, detect crashes/ANRs and optionally run Maestro.
2. **Live Controller** — browser UI for ADB control and optional Google Emulator WebRTC streaming.

The development gate is:

```
code -> analyze -> tests -> APK -> emulator -> install -> launch
     -> smoke -> screenshot -> Logcat -> crash scan -> report
```

## Quick local verification

```bash
chmod +x scripts/*.sh
./scripts/verify_apk.sh path/to/app.apk
```

The package id is auto-detected with `apkanalyzer`, `aapt2` or `aapt`; it can also be passed explicitly:

```bash
./scripts/verify_apk.sh path/to/app.apk com.example.app
```

Artifacts are written to `applab-report/`: screenshot, UI hierarchy, Logcat, device data and a Markdown summary.

## GitHub Actions

Run **APK Emulator Smoke** manually with a direct APK URL, or copy `integration/flutter/applab.yml.example` to an app repository as `.github/workflows/applab.yml`.

That template builds the Flutter APK and checks out this repository only for the reusable verification scripts.

## Live controller

```bash
docker compose up --build
```

Frontend: http://localhost:5173  
Backend: http://localhost:8000

Set `ADB_SERIAL` in `.env` when needed.

The frontend uses Google's `android-emulator-webrtc` package when a compatible Emulator Gateway is available. WebRTC is deliberately separate from the Quality Gate so streaming cannot create false functional failures.

## Upstream foundations

- Google Android Emulator / android-emulator-container-scripts
- Google android-emulator-webrtc
- ReactiveCircus android-emulator-runner
- Maestro

See `NOTICE.md`.
