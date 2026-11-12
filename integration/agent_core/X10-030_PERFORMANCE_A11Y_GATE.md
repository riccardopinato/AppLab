# X10-030 — Benchmark comparabili e accessibilità Android

Factory baseline: App-Factory-Core@c5adc147046beb7024629466d10eeb799c3c2619 (Master v27 / Golden Index v29).

The new source adapter reuses AppLab Performance Lab regression_findings. It accepts at least three provenance-matched cold-start/PSS/jank samples of the same source SHA, APK digest, workflow run, package and device profile. Median comparison reuses the existing AppLab regression thresholds. It does not introduce a new benchmark runner, baseline producer, or independent certification authority.

Android UI hierarchy SHA-256 is checked against its bytes, reported device screen size and density. Enabled controls are analyzed in dp; touch targets under 48dp, missing labels and off-screen bounds require human accessibility review. Baseline selection is supplied by a trusted external reviewer and must match the same device profile. Missing baseline, WARN or regression cannot be turned into a PASS.

All returns are REPORT_ONLY and explicitly mark consumer, physical device and trusted runtime unverified. Synthetic fixture tests are not real device data; low_end_profile_candidate based on reported RAM is not device attestation. Real low-end device performance, TalkBack usability, physical testing and product release remain separate human/release gates. X10-033 may consume the report but must not infer certified status from source/CI.

Review hardening: approved baselines must contain comparable cold start, PSS and jank measurements before invoking the existing regression comparator; an empty baseline cannot become a match. Enabled long-clickable custom views are included in the 48dp/label checks.
