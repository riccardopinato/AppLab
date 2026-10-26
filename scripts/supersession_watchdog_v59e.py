#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.error
from pathlib import Path

import supersession_support_v59e as support
import watchdog_github_v59e as github

ENGINE_VERSION = support.ENGINE_VERSION
load_config = support.load_config
group_key = support.group_key
plan_candidates = support.plan_candidates
fetch_workflow_runs = support.fetch_workflow_runs
descendant_status = support.descendant_status
evaluate_candidate = support.evaluate_candidate
disabled_payload = support.disabled_payload


def self_test() -> None:
    support.self_test()
    print("AppLab v5.9E supersession watchdog self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
    )
    parser.add_argument(
        "--config",
        default="config/supersession-watchdog.json",
    )
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.repository or "/" not in args.repository:
        raise SystemExit("--repository owner/name is required")

    config = load_config(Path(args.config))
    if not config["enabled"] or config["global_kill_switch"]:
        payload = disabled_payload(
            args.repository,
            dry_run=args.dry_run,
        )
    else:
        runs = fetch_workflow_runs(args.repository, args.token)
        candidates = plan_candidates(
            runs,
            workflow_names=set(config["workflow_names"]),
            allowed_events=set(
                config.get("allowed_events", ["push", "pull_request"])
            ),
        )
        rows: list[dict] = []
        cancellations = 0
        max_cancel = int(config["max_cancellations_per_run"])

        for old, new in candidates:
            if cancellations >= max_cancel:
                break
            try:
                proven, status = descendant_status(
                    args.repository,
                    str(old["head_sha"]),
                    str(new["head_sha"]),
                    args.token,
                )
                decision = evaluate_candidate(
                    old=old,
                    new=new,
                    ancestry_proven=proven,
                    ancestry_status=status,
                )
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                ValueError,
            ) as exc:
                decision = evaluate_candidate(
                    old=old,
                    new=new,
                    ancestry_proven=False,
                    ancestry_status="LOOKUP_ERROR",
                )
                decision["reason"] = "ANCESTRY_LOOKUP_ERROR"
                decision["error"] = str(exc)

            if decision["decision"] == "CANCEL":
                if args.dry_run:
                    decision["dispatch"] = "DRY_RUN"
                else:
                    github.api(
                        (
                            "https://api.github.com/repos/"
                            f"{args.repository}/actions/runs/{old['id']}/cancel"
                        ),
                        args.token,
                        method="POST",
                        user_agent="AppLab-Supersession-Watchdog/5.9E",
                    )
                    decision["dispatch"] = "CANCEL_REQUESTED"
                cancellations += 1
            else:
                decision["dispatch"] = "NONE"
            rows.append(decision)

        payload = {
            "schema_version": 1,
            "engine_version": ENGINE_VERSION,
            "record_type": "SUPERSESSION_WATCHDOG_V59E",
            "authority": "ORCHESTRATION_ONLY",
            "status": "PASS",
            "repository": args.repository,
            "dry_run": bool(args.dry_run),
            "cancellation_count": cancellations,
            "ancestry_required": True,
            "cross_repository_cancellation": False,
            "protected_stages_unchanged": True,
            "github_actions_fallback": True,
            "rows": rows,
        }

    if args.output:
        Path(args.output).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
