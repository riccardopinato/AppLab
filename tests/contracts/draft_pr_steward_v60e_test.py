#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_work_graph_v60a as workgraph  # noqa: E402
import bounded_fix_worker_v60c as fix_worker  # noqa: E402
import draft_pr_steward_v60e as steward  # noqa: E402
import durable_brain_v54a as brain  # noqa: E402


def expect_error(callback, contains: str) -> None:
    try:
        callback()
    except steward.StewardError as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected StewardError containing {contains!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "repo"
        root.mkdir()
        steward._run(root, "git", "init")
        steward._run(root, "git", "config", "user.email", "fixture@example.invalid")
        steward._run(root, "git", "config", "user.name", "Fixture")
        (root / "lib").mkdir()
        (root / "tests").mkdir()
        (root / "lib/client.py").write_text(
            "def value():\n    return 1\n",
            encoding="utf-8",
        )
        (root / "tests/test_client.py").write_text(
            "from lib.client import value\n\ndef test_value():\n    assert value() == 1\n",
            encoding="utf-8",
        )
        steward._run(root, "git", "add", ".")
        steward._run(root, "git", "commit", "-m", "fixture")
        source_sha = steward._run(root, "git", "rev-parse", "HEAD").stdout.strip()

        operation = brain._operation_fixture(
            "op_steward",
            "owner/app",
            "main",
            source_sha,
            "c" * 40,
        )
        work_item = workgraph.adapt_operation_to_work_item(
            operation,
            work_item_id="wrk_steward",
            allow_code_edit=True,
        )
        assert "CREATE_DRAFT_PR" in work_item["authority_envelope"]["allowed_capabilities"]
        assert "UPDATE_DRAFT_PR" in work_item["authority_envelope"]["allowed_capabilities"]

        investigation = {
            "repository": "owner/app",
            "resolved_sha": source_sha,
            "classification": "BUILD_OR_QUALITY_FAILURE",
            "state": "LOCALIZED",
            "edit_recommendation": "ELIGIBLE_FOR_BOUNDED_REPAIR",
            "ranked_candidate_files": [
                {
                    "path": "lib/client.py",
                    "kind": "SOURCE",
                    "paired_tests": ["tests/test_client.py"],
                }
            ],
            "required_regression_targets": ["tests/test_client.py"],
        }
        candidate = Path(raw) / "candidate.patch"
        candidate.write_text(
            """diff --git a/lib/client.py b/lib/client.py
--- a/lib/client.py
+++ b/lib/client.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 2
""",
            encoding="utf-8",
        )
        result_patch = Path(raw) / "result.patch"
        repair = fix_worker.apply_bounded_patch(
            root,
            candidate,
            work_item,
            investigation,
            attempt_number=1,
            result_patch_path=result_patch,
        )
        assert repair["state"] == "READY_FOR_VERIFICATION"

        materialized = steward.materialize_local(
            root,
            work_item,
            repair,
            result_patch,
            chain_attempt_number=1,
            root_work_item_id=work_item["work_item_id"],
            root_resolved_sha=source_sha,
            target_base_branch="main",
        )
        assert materialized["state"] == "MATERIALIZED_LOCAL"
        assert materialized["parent_sha"] == source_sha
        assert materialized["repaired_source_sha"] != source_sha
        assert materialized["repair_identity_sha256"].startswith("sha256:")
        assert materialized["remote_write_performed"] is False
        assert (
            steward._run(
                root,
                "git",
                "show-ref",
                "--verify",
                f"refs/heads/{materialized['repair_branch']}",
                check=False,
            ).returncode
            != 0
        )
        assert (
            steward._run(root, "git", "rev-parse", "HEAD").stdout.strip()
            == source_sha
        )

        branch = materialized["repair_branch"]
        create = steward.decide_remote_action(
            chain_attempt_number=1,
            source_sha=source_sha,
            repaired_sha=materialized["repaired_source_sha"],
            remote_branch_sha="",
            existing_prs=[],
            target_base_branch="main",
            repair_branch=branch,
        )
        assert create == {
            "push_required": True,
            "pr_action": "CREATE_DRAFT_PR",
        }

        existing = [
            {
                "number": 42,
                "isDraft": True,
                "baseRefName": "main",
                "headRefName": branch,
                "url": "https://github.com/owner/app/pull/42",
            }
        ]
        idempotent = steward.decide_remote_action(
            chain_attempt_number=1,
            source_sha=source_sha,
            repaired_sha=materialized["repaired_source_sha"],
            remote_branch_sha=materialized["repaired_source_sha"],
            existing_prs=existing,
            target_base_branch="main",
            repair_branch=branch,
        )
        assert idempotent == {
            "push_required": False,
            "pr_action": "REUSE_DRAFT_PR",
        }

        not_draft = [dict(existing[0], isDraft=False)]
        expect_error(
            lambda: steward.decide_remote_action(
                chain_attempt_number=2,
                source_sha=materialized["repaired_source_sha"],
                repaired_sha="d" * 40,
                remote_branch_sha=materialized["repaired_source_sha"],
                existing_prs=not_draft,
                target_base_branch="main",
                repair_branch=branch,
            ),
            "no longer draft",
        )

        wrong_base = [dict(existing[0], baseRefName="release")]
        expect_error(
            lambda: steward.decide_remote_action(
                chain_attempt_number=2,
                source_sha=materialized["repaired_source_sha"],
                repaired_sha="d" * 40,
                remote_branch_sha=materialized["repaired_source_sha"],
                existing_prs=wrong_base,
                target_base_branch="main",
                repair_branch=branch,
            ),
            "base mismatch",
        )

        # The steward may target main with a PR, but the repair branch itself can
        # never be used as the base or be written as main.
        expect_error(
            lambda: steward._validate_target_base(branch, branch, steward.load_contract()),
            "repair",
        )

    steward.self_test()
    print("AppLab v6.0E draft PR steward contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
