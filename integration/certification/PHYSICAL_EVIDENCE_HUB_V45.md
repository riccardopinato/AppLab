# AppLab v4.5 — Physical Evidence Hub

AppLab v4.5 adds a separate, trusted physical-device evidence authority for
capabilities that hosted emulator/runtime evidence cannot prove.

The core rule is simple:

> emulator PASS is never physical-device PASS.

Physical evidence is accepted only when AppLab can bind the operator-attested
device session to the exact target repository, immutable source SHA, package,
version/build and APK SHA-256 that the Trusted APK Verifier is evaluating.

## Trust flow

```
real phone session
      ↓
operator records device/scenario/evidence hashes
      ↓
AppLab Physical Evidence Hub workflow on main
      ↓
physical-session.json
      ↓
trusted AppLab workflow run + run-bound artifact
      ↓
Trusted APK Verifier retrieves the AppLab run directly
      ↓
repo / SHA / package / version / exact APK SHA-256 binding
      ↓
physical-evidence.json
      ↓
Certification + Release Reality + Trusted Evidence Manifest
```

A target repository cannot create trusted physical PASS merely by writing a JSON
file. The Trusted APK Verifier accepts physical evidence only by AppLab workflow
run id, verifies that the run:

- belongs to the AppLab repository;
- used `.github/workflows/physical-evidence-hub.yml`;
- came from `workflow_dispatch`;
- completed successfully;
- ran from AppLab `main`;
- has a valid immutable AppLab head SHA.

The verifier then downloads the run-specific artifact itself and validates it
against the current build contract and exact APK bytes.

## Physical session record

A v4.5 record includes:

- repository and immutable target SHA;
- APK SHA-256;
- package id;
- version name and version code;
- device manufacturer/model;
- Android version/build;
- stable scenario id and title;
- tested capabilities;
- preconditions;
- explicit test steps;
- expected and observed result;
- PASS / FAIL / BLOCKED verdict;
- capture time and GitHub operator;
- hashed references to screenshots, logs, video, traces or reports;
- AppLab workflow/run provenance;
- tamper-evident record digest.

Supported capability labels include:

- `gps`
- `background`
- `sensors`
- `camera`
- `scanner`
- `biometrics`
- `keystore`
- `notifications`
- `storage`
- `file_picker`
- `oem_battery`
- `oauth`
- `billing`
- `play_delivery`
- `model_delivery`
- `cross_app`

## Evidence references

v4.5 deliberately distinguishes **record trust** from **external evidence-byte
verification**.

The Hub accepts evidence references with an operator-attested SHA-256. References
may use:

- `https://`
- `artifact://`
- `file-sha256://`

The Hub does not fetch and re-hash arbitrary referenced external files in v4.5.
The record therefore states:

- `operator_attested_hashes=true`
- `reference_bytes_verified_by_hub=false`

The Trusted APK Verifier validates the AppLab record, its provenance and exact
APK binding. It does not falsely claim that a remote screenshot/video byte stream
was independently re-downloaded and verified.

A future capture client/device bridge may strengthen this layer without changing
the v4.5 evidence semantics.

## Capability coverage

Projects can declare required physical capabilities through the v4.3 adapter:

```json
{
  "physical_validation": {
    "required": true,
    "capabilities": ["gps", "background", "notifications"]
  }
}
```

The build contract now preserves those values as
`certification_policy.required_physical_capabilities`.

A physical PASS cannot satisfy certification unless the trusted session covers
all required capabilities. For example, a camera-only PASS cannot satisfy a
project that requires GPS + background.

## Certification semantics

When physical validation is required:

- no trusted record -> **BLOCKED**
- trusted record with incomplete capability coverage -> **BLOCKED**
- trusted record with result BLOCKED -> **BLOCKED**
- trusted record with result FAIL -> **NOT_CERTIFIED**
- trusted record with exact binding, required capability coverage and PASS ->
  physical gate **PASS**

A trusted physical FAIL is evidence about the exact APK and is not hidden merely
because physical validation was optional.

## Release Reality integration

The v4.4 Release Reality ladder now consumes `physical-evidence.json`.

`PHYSICAL_DEVICE_VERIFIED` can become PASS only when the record:

- was revalidated by the Trusted APK Verifier;
- has `exact_artifact_match=true`;
- binds the same repository/source/package/version/APK SHA-256;
- reports PASS;
- covers all required physical capabilities.

If physical evidence is required but unavailable, the stage remains BLOCKED.
If policy does not require physical validation and no physical record is
attached, the stage remains N/A.

## Physical Evidence Hub workflow

Use:

`.github/workflows/physical-evidence-hub.yml`

The workflow is intentionally manual in v4.5 because the first supported model is
a real App Factory operator testing a real device already available to them.

It produces:

- `physical-session.json`
- `physical-session.md`

as:

`applab-physical-evidence-<workflow-run-id>`

The trusted verifier consumes that run id through
`physical_evidence_run_id`.

This first version does not introduce a device farm and does not pretend to
automate hardware behavior that has not actually been executed on a real phone.

## Same-artifact rule

Physical evidence is tied to one APK SHA-256.

If the APK is rebuilt and the bytes change, even from the same source commit and
with the same version label, the previous physical evidence does not validate the
new artifact.

The new APK must receive its own evidence.

## Authority boundaries

v4.5 does not change these rules:

- Web Preview is not physical-device validation.
- emulator evidence is not physical-device evidence.
- simulated-human review is not physical-device evidence.
- target-authored metadata is not trusted physical evidence.
- certification is not distribution/store/production proof.
- BLOCKED and NOT_VERIFIED never become PASS by inference.
