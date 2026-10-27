#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_work_graph_v60a as workgraph  # noqa: E402
import bounded_fix_worker_v60c as mod  # noqa: E402


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def expect_error(fn, contains: str) -> None:
    try:
        fn()
    except mod.FixWorkerError as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected FixWorkerError containing {contains!r}")


def sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        git(root, "init", "-b", "main")
        git(root, "config", "user.email", "applab@example.invalid")
        git(root, "config", "user.name", "AppLab Contract Test")
        source = root / "lib/service.dart"
        workflow = root / ".github/workflows/ci.yml"
        source.parent.mkdir(parents=True)
        workflow.parent.mkdir(parents=True)
        source.write_text("int value() => 1;\n", encoding="utf-8")
        workflow.write_text("name: CI\n", encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-m", "fixture")
        source_sha = git(root, "rev-parse", "HEAD")

        work_item = {
            "schema_version": 1,
            "record_type": "APPLAB_WORK_ITEM",
            "work_item_id": "wrk_contract",
            "operation_id": "op_contract",
            "repository": "owner/app",
            "source_ref": "main",
            "resolved_sha": source_sha,
            "baseline_sha": "",
            "applab_sha": "c" * 40,
            "risk": "NORMAL",
            "state": "PLANNED",
            "authority": "ORCHESTRATION_ONLY",
            "authority_envelope": {
                "allowed_capabilities": [
                    "READ_REPOSITORY",
                    "READ_EVIDENCE",
                    "RUN_FOCUSED_TESTS",
                    "RUN_APPLAB_FAST",
                    "ALLOW_CODE_EDIT",
                ],
                "denied_capabilities": list(
                    workgraph.load_contract()["authority_envelope"]["mandatory_denials"]
                ),
            },
            "budgets": {
                "max_files": 1,
                "max_changed_lines": 10,
                "max_repair_attempts": 1,
                "max_agent_actions": 10,
            },
            "acceptance_criteria": ["focused regression"],
            "required_evidence": ["exact source identity"],
            "rollback": {"strategy": "restore bytes"},
            "terminal_conditions": list(workgraph.load_contract()["terminal_conditions"]),
        }
        investigation = {
            "schema_version": 1,
            "record_type": "CAUSAL_REPO_INVESTIGATION_V60B",
            "authority": "PROPOSAL_ONLY",
            "repository": "owner/app",
            "resolved_sha": source_sha,
            "classification": "BUILD_OR_QUALITY_FAILURE",
            "state": "LOCALIZED",
            "edit_recommendation": "ELIGIBLE_FOR_BOUNDED_REPAIR",
            "ranked_candidate_files": [
                {
                    "path": "lib/service.dart",
                    "kind": "SOURCE",
                    "confidence": 0.9,
                    "score": 120,
                    "signals": [],
                    "paired_tests": [],
                },
                {
                    "path": ".github/workflows/ci.yml",
                    "kind": "PROTECTED",
                    "confidence": 0.99,
                    "score": 200,
                    "signals": [],
                    "paired_tests": [],
                },
            ],
            "required_regression_targets": [],
        }
        valid_patch = {
            "schema_version": 1,
            "record_type": "BOUNDED_REPAIR_PATCH_V60C",
            "repository": "owner/app",
            "resolved_sha": source_sha,
            "work_item_id": "wrk_contract",
            "attempt_number": 1,
            "edits": [
                {
                    "path": "lib/service.dart",
                    "before_sha256": sha("int value() => 1;\n"),
                    "replacements": [
                        {
                            "old": "int value() => 1;",
                            "new": "int value() => 2;",
                            "expected_occurrences": 1,
                        }
                    ],
                }
            ],
        }

        # main is never a valid repair workspace.
        expect_error(
            lambda: mod.run_worker(
                work_item, investigation, valid_patch, root, apply=False
            ),
            "isolated applab-repair",
        )
        git(root, "checkout", "-b", "applab-repair/contract")

        bad_hash = copy.deepcopy(valid_patch)
        bad_hash["edits"][0]["before_sha256"] = "sha256:" + "0" * 64
        expect_error(
            lambda: mod.run_worker(
                work_item, investigation, bad_hash, root, apply=False
            ),
            "before_sha256 mismatch",
        )

        escape = copy.deepcopy(valid_patch)
        escape["edits"][0]["path"] = "../service.dart"
        expect_error(
            lambda: mod.run_worker(
                work_item, investigation, escape, root, apply=False
            ),
            "unsafe repair path",
        )

        protected = copy.deepcopy(valid_patch)
        protected["edits"][0] = {
            "path": ".github/workflows/ci.yml",
            "before_sha256": sha("name: CI\n"),
            "replacements": [
                {
                    "old": "name: CI",
                    "new": "name: Broken",
                    "expected_occurrences": 1,
                }
            ],
        }
        expect_error(
            lambda: mod.run_worker(
                work_item, investigation, protected, root, apply=False
            ),
            "protected path",
        )

        second_attempt = copy.deepcopy(valid_patch)
        second_attempt["attempt_number"] = 2
        expect_error(
            lambda: mod.run_worker(
                work_item, investigation, second_attempt, root, apply=False
            ),
            "repair attempt exceeds",
        )

        denied = copy.deepcopy(work_item)
        denied["authority_envelope"]["allowed_capabilities"].remove("ALLOW_CODE_EDIT")
        expect_error(
            lambda: mod.run_worker(
                denied, investigation, valid_patch, root, apply=False
            ),
            "does not grant ALLOW_CODE_EDIT",
        )

        dry = mod.run_worker(
            work_item, investigation, valid_patch, root, apply=False
        )
        assert dry["state"] == "VALIDATED_DRY_RUN"
        assert source.read_text(encoding="utf-8") == "int value() => 1;\n"

    mod.self_test()
    print("AppLab v6.0C bounded fix worker contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
