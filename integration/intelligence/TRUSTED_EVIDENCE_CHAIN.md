# AppLab v3.0.1 — Trusted Evidence Chain

v3.0.1 closes the trust gap between AppLab runtime verification and product review.

## Binding

The Trusted APK Verifier now emits `trusted-evidence-manifest.json` only after a
successful trusted runtime verification.

The manifest binds the evidence pack to:

- target repository
- immutable resolved Git SHA
- Android package id
- GitHub workflow run id
- analysis mode
- verification contract fingerprint
- configuration fingerprint
- trusted AppLab workflow SHA

Every evidence file in the report directory is covered by SHA-256 and byte size.

## Validation

Consumers recompute every hash and verify the binding against the expected
repository/SHA/run. Extra unlisted files, missing files, tampered files, unsafe
paths or binding mismatches reject the evidence pack.

The manifest is created inside the Trusted Verifier after `result.json` is
finalized and before the artifact is uploaded. Target source code does not author
the manifest.

## Legacy v3 workflow

`autonomous-app-review-v3.yml` no longer accepts target-authored runtime evidence.
The old `runtime_evidence_path` input is retained only for compatibility and is
explicitly rejected when non-empty.

Static-only v3 review remains available and correctly returns
`EVIDENCE_INCOMPLETE`.

## Trust boundary

This is integrity/provenance binding, not a public-key signature. Trust derives
from the isolated Trusted Verifier job plus immutable GitHub Actions artifact
provenance and deterministic hashes.

CERTIFICATION remains independent and authoritative for production release.
