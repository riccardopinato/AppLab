# AppLab Doctor

AppLab Doctor is the v4.1 local/runner preflight utility.

It answers a simple question before expensive work starts:

> Is this environment capable of running the requested AppLab profile?

## Profiles

### core

Requires:

- Git;
- Python.

### android

Additionally requires:

- Java;
- ADB.

Android SDK, Gradle, Docker and GitHub CLI are reported as optional context.

### flutter

Additionally requires:

- Flutter;
- Dart.

### full

Requires the core Android/runtime toolchain plus Docker and GitHub CLI. The Docker client must also be able to reach a responsive daemon via the active Docker context/`DOCKER_HOST`; a stopped or inaccessible daemon blocks `READY`. On Linux, `/dev/kvm` is required for the full local-emulator profile.

## Usage

```bash
python scripts/applab_doctor.py --profile full
```

Machine-readable evidence:

```bash
python scripts/applab_doctor.py \
  --profile flutter \
  --output doctor.json \
  --markdown doctor.md
```

Exit status is non-zero when a required dependency is missing. Use
`--advisory` only when collecting diagnostics without blocking.

Doctor never installs packages, changes permissions, starts Docker, modifies ADB
state or edits project configuration.
