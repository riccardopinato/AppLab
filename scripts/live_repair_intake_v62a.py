#!/usr/bin/env python3
"""AppLab v6.2A: connect actual durable canary admission to causal investigation."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import agent_work_graph_v60a as graphmod
import causal_repo_investigator_v60b as investigator
import durable_store_v54b as storemod
import self_canary_witness_v62a as witness

SELF = "riccardopinato/AppLab"


class RepairAdmissionError(ValueError):
    pass


def inspect_repair(root: Path, db: Path, admission: dict, closed: dict,
                   triage: dict, plan: dict, diagnostics: str) -> dict:
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if not (
        admission.get("admitted") is True and admission.get("live") is True
        and admission.get("dispatch") is True
        and closed.get("live_requested") is True
        and closed.get("dispatch") is False
        and closed.get("stage") == "SELF_CANARY"
        and admission.get("repository") == closed.get("repository") == SELF
        and admission.get("source_ref") == closed.get("source_ref") == "refs/heads/main"
        and admission.get("resolved_sha") == closed.get("resolved_sha") == sha
        and admission.get("applab_sha") == closed.get("applab_sha") == sha
        and admission.get("operation_id") == closed.get("operation_id")
        and closed.get("effective_draft_pr_authorized") is True
        and closed.get("effective_mutation_authorized") is True
        and closed.get("work_item_state") == "INVESTIGATING"
    ):
        raise RepairAdmissionError("EXACT_LIVE_ADMISSION_REQUIRED")
    delivery = str(admission.get("source_delivery_id") or "")
    parts = delivery.split(":")
    if len(parts) != 2 or not all(part.isdigit() and int(part) > 0 for part in parts):
        raise RepairAdmissionError("GITHUB_DELIVERY_IDENTITY_MISSING")
    run_id, run_attempt = map(int, parts)
    witness.admission_witness(admission, closed, run_id=run_id,
                              run_attempt=run_attempt)
    if os.environ.get("GITHUB_ACTIONS") == "true" and (
        os.environ.get("GITHUB_RUN_ID") != str(run_id)
        or os.environ.get("GITHUB_RUN_ATTEMPT") != str(run_attempt)
        or os.environ.get("GITHUB_EVENT_NAME") != "push"
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or os.environ.get("GITHUB_SHA") != sha
    ):
        raise RepairAdmissionError("GITHUB_RUNTIME_EVENT_MISMATCH")

    with storemod.SQLiteShadowStore(db) as store:
        graph = graphmod.AgentWorkGraphStore(store, graphmod.load_contract())
        work = graph.get_work_item(closed["work_item_id"])
        if not (
            graph.integrity_report()["ok"]
            and work["operation_id"] == admission["operation_id"]
            and work["resolved_sha"] == sha
            and work["repository"] == SELF
            and work["applab_sha"] == sha
            and work["source_ref"] == "refs/heads/main"
            and work["current_state"] == "INVESTIGATING"
            and work["risk"] in ("LOW", "NORMAL")
        ):
            raise RepairAdmissionError("WORK_ITEM_NOT_ELIGIBLE")
    if triage.get("repository") != SELF or triage.get("resolved_sha") != sha:
        raise RepairAdmissionError("TRIAGE_IDENTITY_MISMATCH")
    if plan.get("repository") != SELF or plan.get("head_sha") != sha:
        raise RepairAdmissionError("PLAN_IDENTITY_MISMATCH")
    analysis = investigator.build_investigation(triage, plan, root, diagnostics=diagnostics)
    return {
        "schema_version": 1,
        "record_type": "APPLAB_V62A_CAUSAL_REPAIR_INTAKE",
        "source_sha": sha,
        "operation_id": work["operation_id"],
        "work_item_id": work["work_item_id"],
        "investigation": analysis,
        "next": ("BOUNDED_WORKER_ELIGIBLE" if analysis["state"] == "LOCALIZED"
                 and analysis["edit_recommendation"] == "ELIGIBLE_FOR_BOUNDED_REPAIR"
                 else "STOP_INSUFFICIENT_CAUSAL_EVIDENCE"),
        "patch_applied": False,
        "draft_pr_verified": False,
        "promotion_counted": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("db", "admission", "closed-loop", "triage", "plan", "diagnostics", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    read = lambda key: json.loads(Path(getattr(args, key)).read_text(encoding="utf-8"))
    result = inspect_repair(Path(args.repo_root), Path(args.db), read("admission"),
                            read("closed_loop"), read("triage"), read("plan"),
                            Path(args.diagnostics).read_text(encoding="utf-8"))
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
