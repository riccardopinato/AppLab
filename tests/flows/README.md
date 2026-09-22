# Maestro flows

Project-specific flows belong here or in the application repository.

Run a flow through the generic verifier:

```bash
MAESTRO_FLOW=tests/flows/my-flow.yaml ./scripts/verify_apk.sh app.apk com.example.app
```

Generate a minimal launch/home/relaunch flow:

```bash
./scripts/create_maestro_smoke.sh com.example.app
```
