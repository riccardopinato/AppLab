#!/usr/bin/env python3
from __future__ import annotations

import smart_test_plan

CASES = [
    ("docs", ["README.md"], "NO_RUNTIME_CHANGE", set()),
    ("tests", ["test/features/home/home_test.dart"], "STATIC_ONLY", set()),
    ("ui", ["lib/features/home/home_page.dart"], "FAST_RUNTIME", {"configuration", "performance"}),
    ("network", ["lib/data/api_client.dart"], "FAST_RUNTIME", {"network"}),
    ("worker", ["app/src/main/java/x/SyncWorker.kt"], "FAST_RUNTIME", {"background", "resource_pressure"}),
    ("migration", ["app/src/main/java/x/Migration_4_5.kt"], "FULL_RUNTIME", {"persistence", "storage", "upgrade"}),
    ("manifest", ["app/src/main/AndroidManifest.xml"], "FULL_RUNTIME", {"system", "upgrade"}),
    ("dependency", ["pubspec.yaml"], "FULL_RUNTIME", set()),
]

def main() -> int:
    for name, files, expected_lane, minimum_labs in CASES:
        plan = smart_test_plan.classify(files, "fast", "a" * 40, assume_trusted_baseline=True)
        lane = plan.get("lane")
        if lane != expected_lane:
            raise AssertionError(f"{name}: expected lane {expected_lane}, got {lane}")
        selected = {k for k, v in plan["selected_labs"].items() if v}
        missing = minimum_labs - selected
        if missing:
            raise AssertionError(f"{name}: missing labs {sorted(missing)}")
    print(f"AppLab v0.9 planner regression corpus PASS ({len(CASES)} cases)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
