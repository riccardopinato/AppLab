#!/usr/bin/env python3
"""Read-only background collection for v6.2. Never mints repair proof."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PILOT = "Controlled Event-Driven Pilot"
PREFIX = "applab-v62a-local-repair-"
REPO = "riccardopinato/AppLab"


class ProofObserverError(ValueError):
    pass


def summarize(runs_payload: dict[str, Any], artifacts_payload: dict[str, Any],
              *, active_stage: str = "SELF_CANARY") -> dict[str, Any]:
    runs = runs_payload.get("workflow_runs")
    artifacts = artifacts_payload.get("artifacts")
    if not isinstance(runs, list) or not isinstance(artifacts, list):
        raise ProofObserverError("GitHub runs and artifact payloads are required")
    if active_stage not in ("SELF_CANARY", "PILOT_3", "PILOT_5"):
        raise ProofObserverError("unknown rollout stage")

    observed: dict[int, dict[str, Any]] = {}
    for raw in runs:
        if not isinstance(raw, dict):
            raise ProofObserverError("malformed run")
        if raw.get("name") != PILOT or raw.get("event") != "push":
            continue
        if raw.get("head_branch") != "main":
            continue
        run_id = raw.get("id")
        sha = raw.get("head_sha")
        if not isinstance(run_id, int) or run_id < 1:
            raise ProofObserverError("invalid GitHub run ID")
        if not isinstance(sha, str) or len(sha) != 40:
            raise ProofObserverError("invalid source SHA")
        status = str(raw.get("status") or "")
        conclusion = raw.get("conclusion")
        if status not in ("queued", "in_progress", "completed", "waiting", "pending"):
            raise ProofObserverError("unsupported status")
        if status == "completed" and conclusion not in (
            "success", "failure", "cancelled", "timed_out", "skipped", "action_required", "neutral", "stale"
        ):
            raise ProofObserverError("unknown terminal conclusion")
        observed[run_id] = {
            "run_id": run_id,
            "sha": sha,
            "status": status,
            "conclusion": conclusion,
            "url": f"https://github.com/{REPO}/actions/runs/{run_id}",
            "candidate_artifact_seen": False,
        }

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ProofObserverError("malformed artifact metadata")
        name = str(artifact.get("name") or "")
        if not name.startswith(PREFIX):
            continue
        suffix = name[len(PREFIX):]
        if not suffix.isdecimal():
            continue
        run_id = int(suffix)
        lineage = artifact.get("workflow_run")
        if not isinstance(lineage, dict) or lineage.get("id") != run_id:
            continue
        if run_id in observed and artifact.get("expired") is False:
            # Name alone does NOT prove a patch or even successful intake.
            observed[run_id]["candidate_artifact_seen"] = True

    items = sorted(observed.values(), key=lambda item: item["run_id"], reverse=True)
    terminal = [item for item in items if item["status"] == "completed"]
    result = {
        "schema_version": 1,
        "record_type": "APPLAB_V62_BACKGROUND_PROOF_OBSERVATION",
        "authority": "READ_ONLY_NON_AUTHORITATIVE",
        "factory_implementation": "V62_FEATURE_DELIVERY",
        "active_stage": active_stage,
        "source_repository": REPO,
        "sample_truncated": len(runs) >= 100 or len(artifacts) >= 100,
        "observed_self_canary_runs": len(items),
        "verify_only_or_other_success_runs": sum(x["conclusion"] == "success" for x in terminal),
        "failed_or_cancelled_runs": sum(x["conclusion"] in ("failure", "cancelled", "timed_out") for x in terminal),
        "active_runs": len(items) - len(terminal),
        "repair_artifact_metadata_observed": sum(x["candidate_artifact_seen"] for x in items),
        "complete_causal_repairs_certified_here": 0,
        "real_repair_target": 3,
        "real_repair_gate": "BACKGROUND_PROOF_PENDING",
        "requires_external_exact_head_pr_review_merge_receipts": True,
        "promotion_authorized": False,
        "policy_changed": False,
        "results": items[:20],
    }
    return result


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "## AppLab v6.2 — background operational proof watch",
        "",
        f"- Rollout: \`{report['active_stage']}\` (unchanged)",
        f"- Observed live main canary runs (bounded sample): {report['observed_self_canary_runs']}",
        f"- Successful runner outcomes (not repairs): {report['verify_only_or_other_success_runs']}",
        f"- Failed/cancelled canaries: {report['failed_or_cancelled_runs']}",
        f"- Repair artifact metadata observed (not validated repairs): {report['repair_artifact_metadata_observed']}",
        "- Certified complete causal repair receipts **in this collector**: 0/3",
        "- 3 independent operation proofs remain an asynchronous promotion gate.",
        "- No automatic code, policy, release, branch, or stage change.",
        "",
    ]
    if report["sample_truncated"]:
        lines.append("- Sample limited to latest GitHub API page; not lifetime totals.")
    lines.extend(["", "| Run | SHA | Status | Repair artifact metadata |", "|---|---|---|---|"])
    for item in report["results"][:10]:
        status = item["conclusion"] if item["status"] == "completed" else item["status"]
        lines.append(f"| [#{item['run_id']}]({item['url']}) | \`{item['sha'][:8]}\` | {status} | {str(item['candidate_artifact_seen']).lower()} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    report = summarize(json.loads(args.runs.read_text(encoding="utf-8")),
                       json.loads(args.artifacts.read_text(encoding="utf-8")),
                       active_stage=str(policy["active_stage"]))
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    args.output_md.write_text(markdown(report), encoding="utf-8")


if __name__ == "__main__":
    main()
