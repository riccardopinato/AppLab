# AppLab Read-Only Web Preview

AppLab contains privileged local capabilities (Docker socket, KVM, ADB, APK
installation, process control and runtime test execution). Those capabilities
must never be exposed merely to provide a public Web Preview.

## Modes

### Local Live Controller

Used for real verification.

- backend: localhost-only by default in live mode;
- Docker/KVM/ADB available;
- mutable actions enabled;
- WebRTC emulator available.

### Public Read-Only Preview

Used only for UI and information-architecture verification.

Build with:

```bash
cd frontend
VITE_APPLAB_READ_ONLY=true npm run build
```

The resulting build renders:
- Control Center presentation;
- Studio presentation;
- Longitudinal Intelligence presentation;
- Experiment Planner presentation;
- AppLab Analyst presentation.

It contains no privileged backend endpoint.

## Preview evidence

`frontend/public/preview/*.json` are deterministic UI fixtures.

They are marked as preview/non-live data and exist only to exercise rendering.
They are not audit evidence, certification evidence, product telemetry or a live
snapshot of any repository.

## Deployment

`.github/workflows/web-preview.yml` is the canonical public deployment path.

The workflow:
1. builds the frontend with `VITE_APPLAB_READ_ONLY=true`;
2. uses the repository's GitHub Pages base path;
3. uploads only static frontend bytes;
4. deploys through GitHub Pages.

If GitHub Pages has not yet been enabled for the repository, the deployment job
must remain blocked rather than exposing the local controller as a workaround.
