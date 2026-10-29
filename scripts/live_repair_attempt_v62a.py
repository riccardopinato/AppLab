#!/usr/bin/env python3
"""v6.2A actual repair runner. Never promotes success from local checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import agent_work_graph_v60a as graphmod
import bounded_fix_worker_v60c as worker
import draft_pr_steward_v60e as steward
import durable_store_v54b as storemod
import live_repair_intake_v62a as intake


class AttemptBlocked(ValueError):
    pass


def run(root: Path, db: Path, admission: dict, closed: dict, triage: dict,
        plan: dict, diagnostics: str, patch: Path,
        *, publish: bool = False, evidence_patch_path: Path | None = None,
        expected_patch_sha256: str | None = None) -> dict:
    if publish and (not isinstance(expected_patch_sha256, str)
                    or len(expected_patch_sha256) != 64
                    or any(char not in "0123456789abcdef" for char in expected_patch_sha256)):
        raise AttemptBlocked("PUBLISHED_DRAFT_REQUIRES_APPROVED_PATCH_HASH")
    observed = intake.inspect_repair(root, db, admission, closed,
                                      triage, plan, diagnostics)
    if observed["next"] != "BOUNDED_WORKER_ELIGIBLE":
        raise AttemptBlocked("CAUSAL_INVESTIGATION_NOT_ELIGIBLE")
    with storemod.SQLiteShadowStore(db) as store:
        graph = graphmod.AgentWorkGraphStore(store, graphmod.load_contract())
        work = graph.get_work_item(observed["work_item_id"])
        if not graph.integrity_report()["ok"]:
            raise AttemptBlocked("DURABLE_GRAPH_INTEGRITY")
        # Immutable Work Graph action records the attempted code edit.
        occurred = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        suffix = hashlib.sha256(work["work_item_id"].encode()).hexdigest()[:24]
        decision_id, action_id = "dec_" + suffix, "act_" + suffix
        graph.put_decision({
            "schema_version": 1, "record_type": "APPLAB_WORK_DECISION",
            "decision_id": decision_id, "work_item_id": work["work_item_id"],
            "kind": "APPLY_PATCH", "reason_code": "V62A_BOUNDED_REPAIR",
            "evidence_ref_ids": [], "created_at": occurred,
        })
        graph.put_action({
            "schema_version": 1, "record_type": "APPLAB_WORK_ACTION",
            "action_id": action_id, "work_item_id": work["work_item_id"],
            "decision_id": decision_id, "capability": "ALLOW_CODE_EDIT",
            "state": "RUNNING", "created_at": occurred,
        })
        # A durable state transition is the exclusive repair lease. Replays
        # cannot pass the intake INVESTIGATING-state check a second time.
        occurred = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for old, new in (("INVESTIGATING", "PLANNED"), ("PLANNED", "EXECUTING")):
            transition_id = "trn_" + hashlib.sha256(
                (work["work_item_id"] + ":V62A:" + new).encode()
            ).hexdigest()[:24]
            graph.transition(
                transition_id=transition_id, work_item_id=work["work_item_id"],
                from_state=old, to_state=new, reason_code="V62A_BOUND_REPAIR_LEASE",
                created_at=occurred)

    with tempfile.TemporaryDirectory(prefix="applab-v62a-attempt-") as raw:
        result_patch = Path(raw) / "validated.patch"
        repair = worker.apply_bounded_patch(
            root, patch, work, observed["investigation"],
            attempt_number=1, result_patch_path=result_patch)
        if repair.get("state") != "READY_FOR_VERIFICATION":
            raise AttemptBlocked("BOUNDED_PATCH_NOT_READY")
        if publish and repair["result_patch_sha256"] != expected_patch_sha256:
            raise AttemptBlocked("READ_ONLY_CANDIDATE_PATCH_IDENTITY_MISMATCH")

        # Focused executable validation uses only an ephemeral detached worktree.
        working = Path(raw) / "focused"
        subprocess.run(["git", "worktree", "add", "--detach",
                        str(working), observed["source_sha"]],
                       cwd=root, check=True, stdout=subprocess.DEVNULL)
        try:
            subprocess.run(["git", "apply", "--check", str(result_patch)],
                           cwd=working, check=True)
            subprocess.run(["git", "apply", str(result_patch)],
                           cwd=working, check=True)
            subprocess.run(["python", "-m", "compileall", "-q", "scripts"],
                           cwd=working, check=True, timeout=90)
            tests = repair.get("required_regression_targets", [])
            if not tests:
                raise AttemptBlocked("NO_FOCUSED_TEST_EVIDENCE")
            for test in tests:
                if not isinstance(test, str) or ".." in Path(test).parts:
                    raise AttemptBlocked("UNSAFE_FOCUSED_TEST")
                if test.startswith("tests/") and test.endswith("_test.py"):
                    subprocess.run(["python", test], cwd=working, check=True, timeout=90)
                elif test.startswith("scripts/") and test.endswith(".py"):
                    subprocess.run(["python", "-m", "py_compile", test],
                                   cwd=working, check=True, timeout=90)
                else:
                    raise AttemptBlocked("UNSUPPORTED_FOCUSED_TEST")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(working)],
                           cwd=root, check=True, stdout=subprocess.DEVNULL)
        args = {
            "chain_attempt_number": 1,
            "root_work_item_id": work["work_item_id"],
            "root_resolved_sha": work["resolved_sha"],
            "target_base_branch": "main",
        }
        if publish:
            materialized = steward.execute_remote(
                root, work, repair, result_patch,
                title="fix(applab): bounded self-canary repair",
                body=("Bounded causal repair attempt for WorkItem "
                      + work["work_item_id"] + "; source SHA "
                      + work["resolved_sha"]
                      + ". Pending independent review and trusted checks. "
                        "Not a certified repair."), **args)
        else:
            materialized = steward.materialize_local(
                root, work, repair, result_patch, **args)
        if evidence_patch_path is not None:
            evidence_patch_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_patch_path.write_bytes(result_patch.read_bytes())
        return {
            "candidate_patch_artifact": str(evidence_patch_path.name) if evidence_patch_path else None,
            "candidate_commit_persisted": False,
            "schema_version": 1,
            "record_type": "APPLAB_V62A_BOUNDED_REPAIR_EXECUTION",
            "repository": "riccardopinato/AppLab",
            "source_sha": observed["source_sha"],
            "operation_id": work["operation_id"],
            "work_item_id": work["work_item_id"],
            "patch_sha256": repair["result_patch_sha256"],
            "repair_identity_sha256": materialized["repair_identity_sha256"],
            "diagnostics_sha256": hashlib.sha256(diagnostics.encode()).hexdigest(),
            "changed_files": repair["changed_files"],
            "focused_compileall": "PASS",
            "materialization_state": materialized["state"],
            "candidate_sha": materialized["repaired_source_sha"],
            "draft_pr_url": materialized.get("pr_url", ""),
            "trusted_runtime_verified": False,
            "independent_review_verified": False,
            "post_gate_merge_verified": False,
            "promotion_counted": False,
            "next": "WAIT_EXACT_HEAD_EXTERNAL_VERIFICATION",
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("db", "admission", "closed-loop", "triage", "plan",
                 "diagnostics", "patch", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    def read(key: str) -> dict:
        return json.loads(Path(getattr(args, key)).read_text(encoding="utf-8"))
    result = run(Path(args.repo_root).resolve(), Path(args.db),
                 read("admission"), read("closed_loop"), read("triage"),
                 read("plan"), Path(args.diagnostics).read_text(encoding="utf-8"),
                 Path(args.patch), publish=args.publish)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"state": result["next"], "promotion_counted": False}))


if __name__ == "__main__":
    main()
