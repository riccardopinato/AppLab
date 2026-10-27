#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import autonomous_pr_steward_v60e as mod  # noqa: E402
import verify_repair_loop_v60d as loopmod  # noqa: E402


def expect_error(fn, contains: str) -> None:
    try:
        fn()
    except mod.StewardError as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected StewardError containing {contains!r}")


def main() -> int:
    item = loopmod._fixture_work_item()
    item["authority_envelope"]["allowed_capabilities"].extend(
        ["CREATE_DRAFT_PR", "UPDATE_DRAFT_PR"]
    )
    fix = loopmod._fix(1)
    with tempfile.TemporaryDirectory() as raw:
        patch = Path(raw) / "result.patch"
        patch.write_text(
            "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-a\n+b\n",
            encoding="utf-8",
        )
        fix["result_patch_sha256"] = hashlib.sha256(patch.read_bytes()).hexdigest()
        fix["branch"] = "applab/repair/bbbbbbbbbb-a1"
        loop = {
            "schema_version": 1,
            "record_type": "VERIFY_REPAIR_LOOP_DECISION_V60D",
            "authority": "ORCHESTRATION_ONLY",
            "repository": "owner/app",
            "resolved_sha": "b" * 40,
            "work_item_id": item["work_item_id"],
            "state": "COMPLETE",
            "next_action": "OPEN_DRAFT_PR",
            "reason_code": "VERIFIED_PASS",
            "fix_result_identity_sha256": loopmod.fix_result_identity(fix),
            "merge_authority": "DENIED",
            "release_authority": "DENIED",
        }
        plan = mod.build_plan(item, fix, loop, patch, "owner/app", "main")
        assert plan["pr_must_remain_draft"] is True
        assert plan["merge_performed"] is False
        assert plan["release_performed"] is False

        no_cap = copy.deepcopy(item)
        no_cap["authority_envelope"]["allowed_capabilities"].remove("CREATE_DRAFT_PR")
        expect_error(
            lambda: mod.build_plan(no_cap, fix, loop, patch, "owner/app", "main"),
            "must grant CREATE_DRAFT_PR",
        )

        wrong_patch = Path(raw) / "wrong.patch"
        wrong_patch.write_text("different\n", encoding="utf-8")
        expect_error(
            lambda: mod.build_plan(item, fix, loop, wrong_patch, "owner/app", "main"),
            "result patch SHA-256 mismatch",
        )

        non_draft_branch = copy.deepcopy(fix)
        non_draft_branch["branch"] = "main"
        non_draft_branch["result_patch_sha256"] = hashlib.sha256(patch.read_bytes()).hexdigest()
        wrong_loop = dict(loop, fix_result_identity_sha256=loopmod.fix_result_identity(non_draft_branch))
        expect_error(
            lambda: mod.build_plan(item, non_draft_branch, wrong_loop, patch, "owner/app", "main"),
            "branch",
        )

        bad_authority = dict(loop, merge_authority="ALLOWED")
        expect_error(
            lambda: mod.build_plan(item, fix, bad_authority, patch, "owner/app", "main"),
            "authority boundary",
        )

    review = mod.reconcile_observation(
        ci_state="PASS", unresolved_review_findings=2, superseded=False
    )
    assert review["next_action"] == "RUN_CAUSAL_INVESTIGATOR"
    assert review["resolve_external_findings"] is False
    superseded = mod.reconcile_observation(
        ci_state="PASS", unresolved_review_findings=0, superseded=True
    )
    assert superseded["close_pr"] is False

    mod.self_test()
    print("AppLab v6.0E autonomous PR steward contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
