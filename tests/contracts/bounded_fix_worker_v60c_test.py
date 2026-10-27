#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import bounded_fix_worker_v60c as worker  # noqa: E402
import durable_brain_v54a as brain  # noqa: E402
import agent_work_graph_v60a as workgraph  # noqa: E402


def expect_error(callback, contains: str) -> None:
    try:
        callback()
    except worker.WorkerError as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected WorkerError containing {contains!r}")


def write_patch(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "repo"
        root.mkdir()
        worker._run(root, "git", "init")
        worker._run(root, "git", "config", "user.email", "applab@example.invalid")
        worker._run(root, "git", "config", "user.name", "AppLab")
        (root / "lib").mkdir()
        (root / "tests").mkdir()
        (root / ".github/workflows").mkdir(parents=True)
        (root / "lib/client.py").write_text(
            "def value():\n    return 1\n",
            encoding="utf-8",
        )
        (root / "lib/other.py").write_text(
            "def other():\n    return 0\n",
            encoding="utf-8",
        )
        (root / "tests/test_client.py").write_text(
            "from lib.client import value\n\ndef test_value():\n    assert value() == 1\n",
            encoding="utf-8",
        )
        (root / ".github/workflows/ci.yml").write_text("name: CI\n", encoding="utf-8")
        worker._run(root, "git", "add", ".")
        worker._run(root, "git", "commit", "-m", "fixture")
        sha = worker._run(root, "git", "rev-parse", "HEAD").stdout.strip()

        operation = brain._operation_fixture(
            "op_worker_contract",
            "owner/app",
            "main",
            sha,
            "c" * 40,
        )
        work_item = workgraph.adapt_operation_to_work_item(
            operation,
            work_item_id="wrk_worker_contract",
            allow_code_edit=True,
        )
        investigation = {
            "schema_version": 1,
            "record_type": "CAUSAL_REPO_INVESTIGATION_V60B",
            "authority": "PROPOSAL_ONLY",
            "repository": "owner/app",
            "resolved_sha": sha,
            "classification": "APP_RUNTIME_FAILURE",
            "state": "LOCALIZED",
            "edit_recommendation": "ELIGIBLE_FOR_BOUNDED_REPAIR",
            "ranked_candidate_files": [
                {
                    "path": "lib/client.py",
                    "kind": "SOURCE",
                    "paired_tests": ["tests/test_client.py", "tests/test_regression.py"],
                }
            ],
            "required_regression_targets": [
                "tests/test_client.py",
                "tests/test_regression.py",
            ],
        }

        source_patch = write_patch(
            Path(raw) / "source.patch",
            """diff --git a/lib/client.py b/lib/client.py
--- a/lib/client.py
+++ b/lib/client.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 2
""",
        )
        result_patch = Path(raw) / "result.patch"
        report = worker.apply_bounded_patch(
            root,
            source_patch,
            work_item,
            investigation,
            attempt_number=1,
            result_patch_path=result_patch,
        )
        assert report["state"] == "READY_FOR_VERIFICATION"
        assert report["changed_files"] == ["lib/client.py"]
        assert report["remote_write_performed"] is False
        assert report["merge_performed"] is False
        assert report["release_performed"] is False
        assert result_patch.is_file()
        # The worker edited only its ephemeral worktree.
        assert (root / "lib/client.py").read_text(encoding="utf-8") == "def value():\n    return 1\n"

        # A new regression test is allowed when the investigator explicitly
        # exposed that path. Intent-to-add must preserve it in the result diff.
        new_test_patch = write_patch(
            Path(raw) / "new-test.patch",
            """diff --git a/tests/test_regression.py b/tests/test_regression.py
new file mode 100644
--- /dev/null
+++ b/tests/test_regression.py
@@ -0,0 +1,5 @@
+from lib.client import value
+
+def test_regression():
+    assert value() == 1
+
""",
        )
        new_test_result = Path(raw) / "new-test-result.patch"
        new_test = worker.apply_bounded_patch(
            root,
            new_test_patch,
            work_item,
            investigation,
            attempt_number=1,
            result_patch_path=new_test_result,
        )
        assert new_test["state"] == "READY_FOR_VERIFICATION"
        assert new_test["changed_files"] == ["tests/test_regression.py"]
        assert "test_regression" in new_test_result.read_text(encoding="utf-8")

        # Replacing an assertion with another assertion is not weakening.
        assertion_patch = write_patch(
            Path(raw) / "assertion.patch",
            """diff --git a/tests/test_client.py b/tests/test_client.py
--- a/tests/test_client.py
+++ b/tests/test_client.py
@@ -2,4 +2,4 @@
 
 def test_value():
-    assert value() == 1
+    assert value() == 2
""",
        )
        assertion = worker.apply_bounded_patch(
            root,
            assertion_patch,
            work_item,
            investigation,
            attempt_number=1,
        )
        assert assertion["state"] == "READY_FOR_VERIFICATION"

        weakening_patch = write_patch(
            Path(raw) / "weakening.patch",
            """diff --git a/tests/test_client.py b/tests/test_client.py
--- a/tests/test_client.py
+++ b/tests/test_client.py
@@ -2,4 +2,4 @@
 
 def test_value():
-    assert value() == 1
+    return
""",
        )
        expect_error(
            lambda: worker.apply_bounded_patch(
                root, weakening_patch, work_item, investigation, attempt_number=1
            ),
            "test weakening",
        )

        skip_patch = write_patch(
            Path(raw) / "skip.patch",
            """diff --git a/tests/test_client.py b/tests/test_client.py
--- a/tests/test_client.py
+++ b/tests/test_client.py
@@ -1,4 +1,5 @@
+import pytest
 from lib.client import value
 
+@pytest.mark.skip
 def test_value():
     assert value() == 1
""",
        )
        expect_error(
            lambda: worker.apply_bounded_patch(
                root, skip_patch, work_item, investigation, attempt_number=1
            ),
            "test weakening",
        )

        out_of_scope = write_patch(
            Path(raw) / "outside.patch",
            """diff --git a/lib/other.py b/lib/other.py
--- a/lib/other.py
+++ b/lib/other.py
@@ -1,2 +1,2 @@
 def other():
-    return 0
+    return 1
""",
        )
        expect_error(
            lambda: worker.apply_bounded_patch(
                root, out_of_scope, work_item, investigation, attempt_number=1
            ),
            "escapes causal repair scope",
        )

        protected = write_patch(
            Path(raw) / "protected.patch",
            """diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1 +1 @@
-name: CI
+name: Broken
""",
        )
        protected_investigation = copy.deepcopy(investigation)
        protected_investigation["ranked_candidate_files"].append(
            {"path": ".github/workflows/ci.yml", "kind": "SOURCE", "paired_tests": []}
        )
        expect_error(
            lambda: worker.apply_bounded_patch(
                root, protected, work_item, protected_investigation, attempt_number=1
            ),
            "protected",
        )

        wrong_identity = copy.deepcopy(work_item)
        wrong_identity["resolved_sha"] = "d" * 40
        expect_error(
            lambda: worker.apply_bounded_patch(
                root, source_patch, wrong_identity, investigation, attempt_number=1
            ),
            "resolved_sha",
        )

        denied = copy.deepcopy(investigation)
        denied["edit_recommendation"] = "HUMAN_OR_DEEPER_INVESTIGATION_REQUIRED"
        expect_error(
            lambda: worker.apply_bounded_patch(
                root, source_patch, work_item, denied, attempt_number=1
            ),
            "not eligible",
        )

        expect_error(
            lambda: worker.apply_bounded_patch(
                root, source_patch, work_item, investigation, attempt_number=3
            ),
            "attempt exceeds",
        )

    worker.self_test()
    print("AppLab v6.0C bounded fix worker contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
