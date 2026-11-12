# X10-029 — Visual baseline/replay adoption for consumer apps

**Factory baseline:** App-Factory-Core@c5adc147046beb7024629466d10eeb799c3c2619 · Master v27 · Golden Index v29.

The adapter does not reimplement image comparison. It delegates to AppLab's existing scripts/visual_regression.py after validating an **approved reference baseline** pin, exact source repository and SHA, package/screen and display profile (locale, theme, text scale, phone/tablet), screenshot and UI hierarchy hashes, and source/run-bound UI interaction receipts.

An approved baseline is supplied by a trusted external lookup, never silently generated from a failing or unknown screenshot. Missing baseline emits NO_BASELINE and cannot be recorded as PASS. A comparator WARN, excessive dynamic masking, display-size mismatch, or possible false positive emits REQUIRES_HUMAN_VISUAL_REVIEW, with no automatic approval. A comparator FAIL remains REGRESSION_REPORTED.

This is deliberately a REPORT_ONLY contract: tests use local synthetic screenshots and a fixture baseline lookup, not production Android screenshot capture or independently verified user interactions. No claim that the reference review URL is independently authenticated, no visual/device certification, no automatic baseline acceptance, and no consumer code modifications. A future real runner must bind capture bytes, action traces, baseline reviewer and exact GitHub evidence before certifying any production UI.
