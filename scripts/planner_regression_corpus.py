#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import smart_test_plan

CASES = [
    {"name":"docs-only","files":["README.md"],"lane":"NO_RUNTIME_CHANGE","labs":[]},
    {"name":"nested-docs","files":["product/docs/architecture.md"],"lane":"NO_RUNTIME_CHANGE","labs":[]},
    {"name":"tests-only","files":["test/home_test.dart"],"lane":"STATIC_ONLY","labs":[]},
    {"name":"flutter-ui","files":["lib/features/home/home_page.dart"],"lane":"FAST_RUNTIME","labs":["configuration","performance"]},
    {"name":"network-client","files":["lib/data/api_client.dart"],"lane":"FAST_RUNTIME","labs":["network","performance"]},
    {"name":"background-worker","files":["app/src/main/java/x/SyncWorker.kt"],"lane":"FAST_RUNTIME","labs":["background","resource_pressure","performance"]},
    {"name":"manifest","files":["app/src/main/AndroidManifest.xml"],"lane":"FAST_RUNTIME","labs":["system","upgrade"]},
    {"name":"database","files":["app/src/main/java/x/AppDatabase.kt"],"lane":"FAST_RUNTIME","labs":["persistence","storage","upgrade"]},
    {"name":"migration","files":["app/src/main/java/x/Migration_4_5.kt"],"lane":"FAST_RUNTIME","labs":["persistence","storage","upgrade"]},
    {"name":"storage","files":["lib/storage/file_cache.dart"],"lane":"FAST_RUNTIME","labs":["storage","persistence","performance"]},
    {"name":"camera","files":["lib/camera/camera_page.dart"],"lane":"FAST_RUNTIME","labs":["system","resource_pressure","configuration","performance"]},
    {"name":"notification","files":["app/src/main/java/x/NotificationService.kt"],"lane":"FAST_RUNTIME","labs":["system","background","resource_pressure","performance"]},
    {"name":"gradle","files":["app/build.gradle.kts"],"lane":"FAST_RUNTIME","labs":["performance","upgrade"]},
    {"name":"pubspec","files":["pubspec.yaml"],"lane":"FAST_RUNTIME","labs":["performance","upgrade"]},
    {"name":"image-asset","files":["assets/images/hero.webp"],"lane":"FAST_RUNTIME","labs":["performance","resource_pressure"]},
    {"name":"github-only","files":[".github/workflows/ci.yml"],"lane":"STATIC_ONLY","labs":[]},
]

def main() -> int:
    failures: list[str] = []
    for case in CASES:
        plan = smart_test_plan.classify(case["files"], "fast", "a" * 40)
        if plan["lane"] != case["lane"]:
            failures.append(f"{case['name']}: lane {plan['lane']} != {case['lane']}")
        for lab in case["labs"]:
            if not plan["selected_labs"].get(lab):
                failures.append(f"{case['name']}: expected lab {lab}")
    if failures:
        raise SystemExit("\n".join(failures))

    # Repository-aware escalation cases: these prove the risk engine, ancestry
    # checks and large-diff fail-safe rather than only path rules.
    with tempfile.TemporaryDirectory() as raw:
        root=Path(raw)
        subprocess.run(["git","init","-q",str(root)],check=True)
        subprocess.run(["git","-C",str(root),"config","user.email","applab@example.test"],check=True)
        subprocess.run(["git","-C",str(root),"config","user.name","AppLab Corpus"],check=True)
        (root/"README.md").write_text("base\n",encoding="utf-8")
        subprocess.run(["git","-C",str(root),"add","."],check=True)
        subprocess.run(["git","-C",str(root),"commit","-qm","base"],check=True)
        baseline=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
        db=root/"app/src/main/java/x/AppDatabase.kt"
        db.parent.mkdir(parents=True)
        db.write_text("import androidx.room.Database\nclass AppDatabase\n",encoding="utf-8")
        subprocess.run(["git","-C",str(root),"add","."],check=True)
        subprocess.run(["git","-C",str(root),"commit","-qm","schema"],check=True)
        plan=smart_test_plan.build_plan(root,"fast",baseline,"native_android")
        if plan["lane"]!="FULL_RUNTIME" or not plan["fallback_full"]:
            failures.append("repository-aware schema change must escalate to FULL_RUNTIME")
        if plan["risk"]["level"] not in {"HIGH","CRITICAL"}:
            failures.append("schema change must be HIGH/CRITICAL risk")

    if failures:
        raise SystemExit("\n".join(failures))
    print(f"AppLab planner regression corpus PASS ({len(CASES)+1} scenarios)")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
