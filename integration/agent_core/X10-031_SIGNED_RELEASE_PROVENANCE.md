# X10-031 — Signed APK/AAB provenance gate

Factory: App-Factory-Core@c5adc147046beb7024629466d10eeb799c3c2619 · Master v27 · Golden Index v29.

## Scope of this source PR

No new build tool, signer, certificate/keystore authority, artifact uploader or Store release. The narrowly scoped adapter in scripts/x10_signed_release_provenance.py consumes existing **AppLab package_build_contract** and its real APK identity/signature inspectors. For AAB, a separate *trusted* jarsigner/bundletool inspector must be provided by the runner; absence of that inspector blocks verification. This code does not itself implement the AAB platform inspector.

The adapter checks immutable source SHA + AppLab SHA, package/version, artifact bytes and SHA-256, nonempty release signer certificate fingerprint, APK signed-release contract, APK versus AAB/ABI scope, workflow run/artifact URL format, and source-bound manifest identity. APK ABI scope is checked directly against the archive's lib/<abi>/*.so directory entries (no untrusted ZIP extraction). Bundles additionally require AAB SHA-256/size/package/version/signer in the trusted source-bound build contract; a valid JAR signature alone never proves the source revision. The build consumer repository is distinct from the workflow repository: run artifacts may belong to the consumer repository or the canonical riccardopinato/AppLab controller; any other run repository fails closed. The URL is still NOT independently confirmed to exist. Its only success-shaped result is **PENDING_INDEPENDENT_REMOTE_AND_DEVICE_EVIDENCE**: merely matching an artifact URL pattern does not prove an uploaded artifact exists, and unit-test fake inspectors do not validate real signing.

Existing authorities remain:
- package_build_contract.py: real trusted APK inspection, signing and packaged build evidence.
- release_reality.py: canonical release-stage truth and same-byte identity.
- release_artifact.py: downstream certification-gated publishing and artifact binding.
- GitHub Actions and independent review: exact source/CI; separate upload URL, physical device, store and production evidence.
- No production signing key is generated, read or transmitted in this PR.

## Acceptance gates

Negative fixture cases cover tampered bytes, build-source drift, absent signer, debug variant, stale artifact URL, mismatched version, unsafe path/symlink, missing AAB inspector, missing or tampered source-bound AAB digest, failed AAB signature, mismatched APK native ABI and duplicate ABI scope.

**Source+CI only**, pending exact-head AppLab required workflow gates, independent review and merge. No newly signed APK/AAB is built here, and no real app consumer, device or Store is certified. A real per-consumer attestation requires a credentialed trusted runner, actual signed bytes, platform inspectors, GitHub artifact reconciliation and provenance evidence, then separate Release Reality/physical/store gates.
