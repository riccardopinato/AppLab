# v6.3D — Three-way parallel FULL shadow pilot

**Factory baseline:** `174a05e165076c9e4b2d61a20acd85ca6b215f12` (Master v27).
**AppLab parent:** `46816a1786820eb7c0edab7500ca950b10c7718c`.
**Stage:** advisory pilot; NOT authoritative. No production time saving is claimed.

## What runs concurrently
Only for explicitly opted-in trusted repositories with `mode: shadow` and
`full_shadow: true`, `FULL_RUNTIME` plans with the **entire catalog** selected
can run three independent emulator jobs against the **same immutable APK build
contract**: (1) UI/navigation/onboarding, (2) diary/memories, and
(3) deep/security/Vault. Every journey is assigned to exactly one shadow group;
a missing group, incomplete/duplicated catalog or CERTIFICATION fails closed to
the current full non-sharded verifier. Unmatched paths may exist in FULL shadow
because the canonical FULL verifier still tests the entire application; they
must never become selective PASS authority.

The existing primary FULL verifier remains **the sole authoritative gate**,
running unchanged in parallel with the advisory shards. Each shadow shard uses
its own Android emulator. The existing baseline admission remains mandatory;
missing visual or upgrade baselines disable the pilot rather than promote it.
The extra shadow-report job audits matching repository/source SHA/APK SHA-256,
duplicate/missing journeys, and per-shard PASS from uploaded evidence. FAIL in
advisory reports **cannot** become workflow PASS or certification; reports are
diagnostic only. No target-side declarations can enable authoritative FULL.

## Why not authoritative
Current v5.9C authoritative sharding is FAST-only, selectively partitions deep
journeys, and has no validated equivalence proof for the complete FULL suite.
The legacy primary covers more than catalog journeys: visual checkpoints,
multi-screen crawler, security/Vault lifecycle, storage, restart/recovery, labs,
upgrade/migration and artifact/certification boundaries. A three-shard journey
union alone does not prove equivalence with those probes or their required
shared state. Unproven parallelism must not replace a trusted PASS.

## Evidence required before any promotion
1. Independent shadow run on an exact downstream HEAD with all three shard
   artifacts and the canonical FULL result; record the same APK hash.
2. Measure per-shard versus canonical duration, cold/warm AVD setup, number of
   retries, missing/wrong/duplicated journey IDs and GitHub runner-minutes.
3. Demonstrate coverage equivalence with explicit critical scenarios including
   600k PBKDF2, wrong and correct Vault unlock, restart/persistence, backup,
   migrations, screenshots, interaction/visual and crawler behavior.
4. Introduce separate fail-closed FULL aggregation design and tests before any
   proposed `authoritative` option; CERTIFICATION remains unchanged.

This is an instrumentation/validation phase, likely to increase total CI
runner-minutes before a later safe promotion. The consumer Anna workflow must
be pinned to a *reviewed merged* AppLab SHA in a separate gated PR.
