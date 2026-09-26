#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import smart_test_plan


PATH_CASES = [
    ("docs", ["README.md"], "NO_RUNTIME_CHANGE", set()),
    ("tests", ["test/features/home/home_test.dart"], "STATIC_ONLY", set()),
    ("ui", ["lib/features/home/home_page.dart"], "FAST_RUNTIME", {"configuration", "performance"}),
    ("network", ["lib/data/api_client.dart"], "FAST_RUNTIME", {"network"}),
    ("worker", ["app/src/main/java/x/SyncWorker.kt"], "FAST_RUNTIME", {"background", "resource_pressure"}),
    ("migration", ["app/src/main/java/x/Migration_4_5.kt"], "FULL_RUNTIME", {"persistence", "storage", "upgrade"}),
    ("manifest", ["app/src/main/AndroidManifest.xml"], "FULL_RUNTIME", {"system", "upgrade"}),
    ("dependency", ["pubspec.yaml"], "FULL_RUNTIME", set()),
]


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args],
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def run(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def init_repo(root: Path) -> str:
    run(root, "init", "-q")
    run(root, "config", "user.email", "applab@example.test")
    run(root, "config", "user.name", "AppLab Regression")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    run(root, "add", ".")
    run(root, "commit", "-qm", "base")
    return git(root, "rev-parse", "HEAD")


def commit_all(root: Path, message: str) -> str:
    run(root, "add", "-A")
    run(root, "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD")


def path_level_cases() -> int:
    for name, files, expected_lane, minimum_labs in PATH_CASES:
        plan = smart_test_plan.classify(
            files, "fast", "a" * 40, assume_trusted_baseline=True
        )
        lane = plan.get("lane")
        if lane != expected_lane:
            raise AssertionError(f"{name}: expected lane {expected_lane}, got {lane}")
        selected = {k for k, v in plan["selected_labs"].items() if v}
        missing = minimum_labs - selected
        if missing:
            raise AssertionError(f"{name}: missing labs {sorted(missing)}")
    return len(PATH_CASES)


def non_ancestor_case() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        base = init_repo(root)

        run(root, "checkout", "-qb", "side")
        (root / "side.txt").write_text("side\n", encoding="utf-8")
        side = commit_all(root, "side")

        run(root, "checkout", "-q", "-b", "head", base)
        (root / "README.md").write_text("head\n", encoding="utf-8")
        commit_all(root, "head")

        plan = smart_test_plan.plan_repository(root, "fast", side)
        assert plan["lane"] == "FULL_RUNTIME"
        assert plan["fallback_full"] is True
        assert plan["baseline_state"] == "non_ancestor"


def large_diff_case() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        base = init_repo(root)
        generated = root / "lib" / "generated"
        generated.mkdir(parents=True)
        for index in range(501):
            (generated / f"item_{index:03d}.dart").write_text(
                f"const item{index} = {index};\n", encoding="utf-8"
            )
        commit_all(root, "large refactor")

        plan = smart_test_plan.plan_repository(root, "fast", base)
        assert plan["lane"] == "FULL_RUNTIME"
        assert plan["fallback_full"] is True
        assert plan["changed_file_count"] == 501


def dependency_impact_case() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        init_repo(root)
        api = root / "lib" / "data" / "api_client.dart"
        home = root / "lib" / "features" / "home" / "home_page.dart"
        api.parent.mkdir(parents=True)
        home.parent.mkdir(parents=True)
        api.write_text("class ApiClient { Future<void> load() async {} }\n", encoding="utf-8")
        home.write_text(
            "import '../../data/api_client.dart';\n"
            "void render(ApiClient client) {}\n",
            encoding="utf-8",
        )
        base = commit_all(root, "network foundation")

        api.write_text(
            "class ApiClient { Future<void> load() async { /* http */ } }\n",
            encoding="utf-8",
        )
        commit_all(root, "change api client")

        plan = smart_test_plan.plan_repository(root, "fast", base)
        assert "lib/features/home/home_page.dart" in plan["dependency_impacted_files"]
        assert plan["selected_labs"]["network"] is True
        assert plan["selected_labs"]["configuration"] is True


def historical_risk_case() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        init_repo(root)
        api = root / "lib" / "data" / "api_client.dart"
        api.parent.mkdir(parents=True)
        api.write_text("class ApiClient {}\n", encoding="utf-8")
        base = commit_all(root, "api base")
        api.write_text("class ApiClient { /* http retry */ }\n", encoding="utf-8")
        commit_all(root, "api change")

        normal = smart_test_plan.plan_repository(root, "fast", base)
        assert normal["lane"] == "FAST_RUNTIME"

        risky = smart_test_plan.plan_repository(
            root,
            "fast",
            base,
            historical_risk={"network": 8, "generic_failure": 8},
        )
        assert risky["lane"] == "FULL_RUNTIME"
        assert risky["risk_score"] >= 70


def changed_test_target_case() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        init_repo(root)
        test_file = root / "test" / "features" / "home" / "home_test.dart"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("void main() {}\n", encoding="utf-8")
        base = commit_all(root, "test base")
        test_file.write_text("void main() { /* assertion */ }\n", encoding="utf-8")
        commit_all(root, "test change")

        plan = smart_test_plan.plan_repository(root, "fast", base)
        assert plan["lane"] == "STATIC_ONLY"
        assert "test/features/home/home_test.dart" in plan["static_targets"]["flutter_test_targets"]


def rename_and_delete_cases() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        init_repo(root)
        cache = root / "lib" / "cache.dart"
        cache.parent.mkdir(parents=True)
        cache.write_text("class Cache {}\n", encoding="utf-8")
        base = commit_all(root, "cache base")
        run(root, "mv", "lib/cache.dart", "lib/cache_store.dart")
        commit_all(root, "rename cache")
        rename_plan = smart_test_plan.plan_repository(root, "fast", base)
        assert any(item.get("status") == "R" for item in rename_plan["changed_file_details"])
        assert rename_plan["risk_score"] >= 30

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        init_repo(root)
        database = root / "app" / "src" / "main" / "java" / "x" / "AppDatabase.kt"
        database.parent.mkdir(parents=True)
        database.write_text("class AppDatabase\n", encoding="utf-8")
        base = commit_all(root, "database base")
        database.unlink()
        commit_all(root, "delete database")
        delete_plan = smart_test_plan.plan_repository(root, "fast", base)
        assert any(item.get("status") == "D" for item in delete_plan["changed_file_details"])
        assert delete_plan["lane"] == "FULL_RUNTIME"


def main() -> int:
    count = path_level_cases()
    non_ancestor_case()
    large_diff_case()
    dependency_impact_case()
    historical_risk_case()
    changed_test_target_case()
    rename_and_delete_cases()
    count += 7
    print(f"AppLab v0.9 planner regression corpus PASS ({count} scenarios)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
