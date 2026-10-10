# AppLab v4.3 — External Project Certification Adapter

AppLab v4.3 adds one canonical project profile between Universal Auto-Discovery
and the existing Flutter/native runners.

The adapter does **not** create a second verifier and does not let a target
repository certify itself. Its job is to normalize project intent and
auto-discovered build metadata before the trusted AppLab pipeline runs.

## Flow

```
target repository/ref
        ↓
Universal Auto-Discovery
        ↓
v4.3 Project Adapter
        ↓
immutable resolved SHA + canonical project profile
        ↓
existing Flutter/native runner
        ↓
build contract
        ↓
Trusted APK Verifier / FAST / FULL / CERTIFICATION
```

The target is checked out once for discovery. The adapter records the exact
40-character HEAD SHA and all downstream verification jobs use that immutable
SHA rather than following a moving branch/tag.

## Zero-config mode

A normal Flutter or native Android project still needs only:

- repository: `owner/name`
- ref: branch, tag or commit

AppLab auto-detects the project engine, working directory, package id, toolchain,
debug/release build commands, APK paths and an AppLab/Maestro smoke flow when
available.

The generated profile additionally records:

- adapter/schema version;
- immutable resolved SHA;
- project type;
- app version/build number when statically available;
- release artifact pattern;
- primary/settings/critical journeys;
- physical-validation requirements;
- deterministic profile fingerprint.

## Optional project contract

A target may add exactly one of:

- `applab.project.json`
- `.applab/project.json`

Example:

```json
{
  "schema_version": 1,
  "project_type": "flutter",
  "working_directory": ".",
  "package_id": "com.example.app",
  "toolchain": {
    "flutter_version": "3.35.0",
    "java_version": "17"
  },
  "release_artifact_pattern": "build/app/outputs/flutter-apk/app-release.apk",
  "journeys": {
    "primary": ".maestro/applab-smoke.yaml",
    "settings": ".maestro/settings.yaml",
    "critical": [
      ".maestro/critical-export.yaml"
    ]
  },
  "physical_validation": {
    "required": true,
    "capabilities": [
      "gps",
      "background"
    ]
  }
}
```

Unknown fields fail closed. Multiple adapter configs, symlinks, unsafe paths,
oversized config and contradictory project types are rejected. Journey/config
paths are checked component-by-component so a symlinked parent directory cannot
escape the target checkout.

Toolchain values are field-validated before they can reach reusable workflow
inputs: SDK levels are numeric and version/channel fields accept only bounded
version-safe syntax. Shell substitutions/metacharacter payloads are rejected.

### Field semantics

- `project_type`: `auto`, `flutter` or `native_android`. An explicit type
  must agree with auto-discovery.
- `working_directory`: v1 treats this as an assertion against auto-discovery,
  not as a shell/build override.
- `package_id`: expected Android identity. The trusted build contract later
  rejects it if the built APK reports a different package id.
- `toolchain`: bounded declarative overrides only. No arbitrary command field
  exists in the adapter contract.
- `release_artifact_pattern`: exact release APK path, or a glob that must match
  the path inferred by auto-discovery.
- `journeys.primary`: becomes the existing Maestro journey used by the
  verification runner.
- `journeys.settings` / `journeys.critical`: retained in the canonical profile
  for later journey/certification orchestration.
- `physical_validation`: may make certification stricter. It cannot downgrade
  a separate `applab-certification.json` policy that already requires a real
  device.

## Trust boundary

The adapter file is target-authored metadata and is therefore **untrusted
intent**, not trusted evidence.

Trusted authority remains outside the target repository:

- repository + immutable resolved SHA;
- actual built APK bytes;
- APK SHA-256;
- APK package/version/signing identity;
- AppLab workflow/run identity;
- Trusted Evidence Manifest;
- Trusted APK Verifier;
- certification gate.

A target cannot declare PASS, CERTIFIED, trusted evidence, artifact SHA or
physical-device verification through `applab.project.json`.

The build contract copies the adapter config into target evidence for
inspectability, but only after proving the evidence path remains inside the
target checkout without symlink traversal. The real APK identity remains
authoritative. If a configured `package_id` exists, APK package detection is
mandatory; missing or mismatched APK identity fails validation.

## Physical validation

The project profile can declare capabilities such as GPS, sensors, background
execution or billing that require real-device verification.

This does not implement the v4.5 Physical Evidence Hub. In v4.3 it only
preserves the requirement and ensures a target cannot accidentally be treated as
fully covered by emulator evidence.

`physical_validation.required=true` or a non-empty capability list escalates
the build certification policy to `requires_real_device=true`.

## Evidence and cache identity

Every profile has a deterministic SHA-256 `profile_fingerprint`.

The Universal Runner forwards that fingerprint into the existing configuration
identity. Changing the adapter profile therefore invalidates incompatible cached
build/verification assumptions instead of silently reusing stale evidence.

`scripts/project_adapter.py` also participates in AppLab's contract/domain
fingerprints.

## Real-project validation

The repository contains `Project Adapter Integration`, which validates the
adapter against immutable revisions of two real App Factory projects:

- CamperBoss @ `6c866bf8884b78703401db8ce08dbcf97d3f893c`
- Battery Guard @ `7d3e0b8257628dea65cedcf174357f9bc06d21bc`

The integration test verifies project type, immutable source identity, package,
version/build discovery, release artifact metadata and deterministic profile
generation without executing untrusted target build commands.

Runtime/build verification remains owned by the existing AppLab runners and
trusted verifier.

## Authority boundaries

v4.3 does not change these semantics:

- FAST is targeted verification, not certification.
- FULL is broad scoped verification, not automatically certification.
- CERTIFICATION remains the only AppLab release-certification authority.
- emulator PASS is not physical-device PASS.
- AppLab runtime PASS is not Play/Internal Testing PASS.
- BLOCKED and NOT VERIFIED are never converted to PASS.
