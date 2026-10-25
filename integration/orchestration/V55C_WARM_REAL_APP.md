# AppLab v5.5C — Warm Worker Real-App Pilot

Status: **IMPLEMENTED AS BOUNDED REAL-APP EQUIVALENCE GATE / AUTHORITY UNCHANGED**

The v5.5C pilot extends the v5.4F warm trusted-runtime equivalence contract to the two real applications in the v5.5 pilot set: CamperBoss and TrailPath. Both remain routed through the Universal Project Runner. Target build scripts execute only in the existing untrusted GitHub Actions build boundary; a warm worker may receive only the isolated APK/runtime contract.

Equivalence is exact-artifact-bound and compares repository, source SHA, AppLab SHA, APK SHA-256, package identity, analysis mode, specialist-lab results and verdict. Isolation cleanup remains mandatory. Any mismatch is non-promotable and GitHub Actions remains the fallback executor.

Smart Test Plan, Trusted Verifier, Release Assurance and Production Certification authority are unchanged. This pilot cannot mint PASS/CERTIFIED and cannot reduce coverage.
