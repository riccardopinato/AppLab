#!/usr/bin/env python3
"""v6.2A actual repair runner. Never promotes success from local checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
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
        *, publish: bool = False) -> dict:
    observed = intake.inspect_repair(root, db, admission, closed,
                                      triage, plan, diagnostics)
    if observed["next"] != "BOUNDED_WORKER_ELIGIBLE":
        raise AttemptBlocked("CAUSAL_INVESTIGATION_NOT_ELIGIBLE")
    with storemod.SQLiteShadowStore(db) as store:
        graph = graphmod.AgentWorkGraphStore(store, graphmod.load_contract())
        work = graph.get_work_item(observed["work_item_id"])
        if not graph.integrity_report()["ok"]:
            raise AttemptBlocked("DURABLE_GRAPH_INTEGRITY")
    with tempfile.TemporaryDirectory(prefix="applab-v62a-attempt-") as raw:
        result_patch = Path(raw) / "validated.patch"
        repair = worker.apply_bounded_patch(
            root, patch, work, observed["investigation"],
            attempt_number=1, result_patch_path=result_patch)
        if repair.get("state") != "READY_FOR_VERIFICATION":
            raise AttemptBlocked("BOUNDED_PATCH_NOT_READY")
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
        return {
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
