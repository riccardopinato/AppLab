#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import agent_work_graph_v60a as workgraph
import verify_repair_loop_v60d as repairloop

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = ROOT / "integration" / "orchestration" / "contracts" / "autonomous-pr-steward-v1.json"
REPO_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class StewardError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise StewardError("unsupported PR steward contract version")
    if payload.get("contract_name") != "APPLAB_AUTONOMOUS_PR_STEWARD":
        raise StewardError("unexpected PR steward contract")
    if payload.get("authority") != "DRAFT_PR_STEWARDSHIP_ONLY":
        raise StewardError("PR steward authority must remain draft-only")
    return payload


def _run(cwd: Path, *args: str, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        list(args), cwd=str(cwd), capture_output=True, text=True, check=False, timeout=timeout
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-1500:]
        raise StewardError(
            "command failed (%s): %s :: %s"
            % (proc.returncode, " ".join(args), detail)
        )
    return proc


def _read_json(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise StewardError("JSON root must be object: " + path)
    return value


def _patch_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate(
    work_item: dict[str, Any],
    fix_result: dict[str, Any],
    loop: dict[str, Any],
    patch_path: Path,
    repository: str,
    base_branch: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    workgraph.validate_work_item(work_item, workgraph.load_contract())
    if not REPO_RE.fullmatch(repository):
        raise StewardError("repository must be owner/name")
    source_sha = str(work_item.get("resolved_sha") or "").lower()
    if not SHA_RE.fullmatch(source_sha):
        raise StewardError("WorkItem resolved_sha must be exact 40-hex")
    if repository != str(work_item.get("repository") or ""):
        raise StewardError("repository does not match WorkItem")
    allowed = set((work_item.get("authority_envelope") or {}).get("allowed_capabilities") or [])
    if "CREATE_DRAFT_PR" not in allowed or "UPDATE_DRAFT_PR" not in allowed:
        raise StewardError("WorkItem must grant CREATE_DRAFT_PR and UPDATE_DRAFT_PR")

    if fix_result.get("record_type") != contract["required_fix_record_type"]:
        raise StewardError("fix_result is not canonical BOUNDED_FIX_RESULT_V60C")
    if fix_result.get("state") != "READY_FOR_VERIFICATION":
        raise StewardError("fix_result is not READY_FOR_VERIFICATION")
    expected = {
        "repository": repository,
        "resolved_sha": source_sha,
        "work_item_id": str(work_item.get("work_item_id") or ""),
    }
    for field, value in expected.items():
        actual = str(fix_result.get(field) or "")
        if field == "resolved_sha":
            actual = actual.lower()
        if actual != value:
            raise StewardError("fix_result %s identity mismatch" % field)
    if fix_result.get("remote_write_performed") is not False:
        raise StewardError("steward expects an unpushed v6.0C result")

    if loop.get("record_type") != "VERIFY_REPAIR_LOOP_DECISION_V60D":
        raise StewardError("loop decision is not v6.0D")
    if loop.get("state") != contract["required_loop_state"]:
        raise StewardError("loop is not COMPLETE")
    if loop.get("reason_code") != contract["required_loop_reason"]:
        raise StewardError("loop is not VERIFIED_PASS")
    if loop.get("next_action") != contract["required_loop_next_action"]:
        raise StewardError("loop does not authorize OPEN_DRAFT_PR")
    if loop.get("merge_authority") != "DENIED" or loop.get("release_authority") != "DENIED":
        raise StewardError("loop authority boundary is incompatible")
    fix_identity = repairloop.fix_result_identity(fix_result)
    if str(loop.get("fix_result_identity_sha256") or "") != fix_identity:
        raise StewardError("loop/fix-result identity mismatch")

    patch_path = patch_path.resolve()
    if not patch_path.is_file():
        raise StewardError("result patch is missing")
    patch_sha = _patch_sha256(patch_path)
    if patch_sha != str(fix_result.get("result_patch_sha256") or "").lower():
        raise StewardError("result patch SHA-256 mismatch")

    branch = str(fix_result.get("branch") or "")
    if not branch.startswith(str(contract["branch_prefix"])):
        raise StewardError("repair branch is outside steward branch prefix")
    if branch in {"main", "master", base_branch}:
        raise StewardError("steward cannot write default/base branch")

    return {
        "repository": repository,
        "source_sha": source_sha,
        "work_item_id": expected["work_item_id"],
        "base_branch": base_branch,
        "branch": branch,
        "fix_identity": fix_identity,
        "patch_sha256": patch_sha,
        "attempt_number": int(fix_result.get("attempt_number", 0) or 0),
    }


def build_plan(
    work_item: dict[str, Any],
    fix_result: dict[str, Any],
    loop: dict[str, Any],
    patch_path: Path,
    repository: str,
    base_branch: str,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    identity = _validate(
        work_item, fix_result, loop, patch_path, repository, base_branch, contract
    )
    return {
        "schema_version": 1,
        "record_type": "AUTONOMOUS_PR_STEWARD_PLAN_V60E",
        "authority": "DRAFT_PR_STEWARDSHIP_ONLY",
        "state": "PLAN_ONLY",
        **identity,
        "operations": [
            "CREATE_LOCAL_BRANCH_FROM_EXACT_SHA",
            "APPLY_VERIFIED_RESULT_PATCH",
            "COMMIT_BOUNDED_REPAIR",
            "PUSH_REPAIR_BRANCH",
            "CREATE_OR_UPDATE_DRAFT_PR",
        ],
        "forbidden_actions": list(contract["forbidden_actions"]),
        "pr_must_remain_draft": True,
        "merge_performed": False,
        "release_performed": False,
    }


def _existing_pr(cwd: Path, repository: str, branch: str) -> dict[str, Any] | None:
    proc = _run(
        cwd,
        "gh", "pr", "list",
        "--repo", repository,
        "--head", branch,
        "--state", "open",
        "--json", "number,isDraft,state,headRefName,baseRefName,url",
        "--limit", "10",
    )
    rows = json.loads(proc.stdout or "[]")
    if not rows:
        return None
    if len(rows) > 1:
        raise StewardError("multiple open PRs exist for repair branch")
    return rows[0]


def _body(plan_payload: dict[str, Any], evidence_summary: str) -> str:
    lines = [
        "## AppLab bounded repair",
        "",
        "- WorkItem: %s" % plan_payload["work_item_id"],
        "- Source SHA: %s" % plan_payload["source_sha"],
        "- Fix identity: %s" % plan_payload["fix_identity"],
        "- Attempt: %s" % plan_payload["attempt_number"],
        "- v6.0D result: COMPLETE / VERIFIED_PASS",
        "- Authority: draft PR stewardship only",
        "",
        "### Evidence",
        evidence_summary.strip() or "Exact fix-result identity verified.",
        "",
        "This PR remains draft. AppLab cannot self-approve, merge or release it.",
        "",
    ]
    return "\n".join(lines)


def execute(
    repo_root: Path,
    plan_payload: dict[str, Any],
    patch_path: Path,
    *,
    title: str,
    evidence_summary: str,
) -> dict[str, Any]:
    if plan_payload.get("state") != "PLAN_ONLY":
        raise StewardError("execute requires a validated PLAN_ONLY payload")
    if not os.environ.get("GH_TOKEN") and not os.environ.get("GITHUB_TOKEN"):
        raise StewardError("GH_TOKEN/GITHUB_TOKEN is required for remote draft stewardship")
    repo_root = repo_root.resolve()
    head = _run(repo_root, "git", "rev-parse", "HEAD").stdout.strip().lower()
    if head != plan_payload["source_sha"]:
        raise StewardError("local checkout is not exact source SHA")
    if _run(repo_root, "git", "status", "--porcelain").stdout.strip():
        raise StewardError("steward checkout must be clean")

    branch = plan_payload["branch"]
    _run(repo_root, "git", "checkout", "-B", branch, plan_payload["source_sha"])
    _run(repo_root, "git", "apply", "--check", str(patch_path.resolve()))
    _run(repo_root, "git", "apply", str(patch_path.resolve()))
    _run(repo_root, "git", "add", "-A")
    staged = _run(repo_root, "git", "diff", "--cached", "--name-only").stdout.strip()
    if not staged:
        raise StewardError("verified repair patch produced no staged change")
    _run(
        repo_root, "git", "commit",
        "-m", "fix(applab): bounded repair %s attempt %s"
        % (plan_payload["work_item_id"], plan_payload["attempt_number"]),
    )
    repair_commit = _run(repo_root, "git", "rev-parse", "HEAD").stdout.strip().lower()
    _run(
        repo_root, "git", "push", "--force-with-lease",
        "origin", "HEAD:refs/heads/" + branch,
        timeout=120,
    )

    existing = _existing_pr(repo_root, plan_payload["repository"], branch)
    body = _body(plan_payload, evidence_summary)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
        tmp.write(body)
        body_path = tmp.name
    try:
        if existing is None:
            proc = _run(
                repo_root,
                "gh", "pr", "create",
                "--repo", plan_payload["repository"],
                "--base", plan_payload["base_branch"],
                "--head", branch,
                "--draft",
                "--title", title,
                "--body-file", body_path,
            )
            url = proc.stdout.strip()
            state = "DRAFT_PR_CREATED"
        else:
            if existing.get("isDraft") is not True:
                raise StewardError("existing repair PR is not draft; steward refuses update")
            _run(
                repo_root,
                "gh", "pr", "edit", str(existing["number"]),
                "--repo", plan_payload["repository"],
                "--title", title,
                "--body-file", body_path,
            )
            url = str(existing.get("url") or "")
            state = "DRAFT_PR_UPDATED"
    finally:
        Path(body_path).unlink(missing_ok=True)

    pr = _existing_pr(repo_root, plan_payload["repository"], branch)
    if not pr or pr.get("isDraft") is not True:
        raise StewardError("stewarded PR is not draft")
    return {
        **plan_payload,
        "state": state,
        "repair_commit_sha": repair_commit,
        "pull_request_number": int(pr["number"]),
        "pull_request_url": url or str(pr.get("url") or ""),
        "pull_request_draft": True,
        "merge_performed": False,
        "release_performed": False,
        "next_action": "WAIT_CI_OR_REVIEW",
    }


def reconcile_observation(
    *,
    ci_state: str,
    unresolved_review_findings: int,
    superseded: bool,
) -> dict[str, Any]:
    if superseded:
        return {
            "state": "BLOCKED",
            "next_action": "REQUIRE_ANCESTRY_EQUIVALENCE_REVIEW",
            "close_pr": False,
        }
    if unresolved_review_findings > 0 or ci_state.upper() in {"FAIL", "FAILED", "ERROR"}:
        return {
            "state": "INVESTIGATE_REVIEW",
            "next_action": "RUN_CAUSAL_INVESTIGATOR",
            "resolve_external_findings": False,
        }
    if ci_state.upper() in {"PENDING", "QUEUED", "IN_PROGRESS", "WAITING"}:
        return {"state": "WAITING_CI", "next_action": "WAIT"}
    if ci_state.upper() in {"PASS", "SUCCESS", "SUCCEEDED"}:
        return {
            "state": "WAITING_CI",
            "next_action": "HUMAN_OR_INDEPENDENT_APPROVAL",
            "mark_ready": False,
            "merge": False,
        }
    return {"state": "BLOCKED", "next_action": "HUMAN_DECISION_REQUIRED"}


def self_test() -> None:
    item = repairloop._fixture_work_item()
    item["authority_envelope"]["allowed_capabilities"].extend(
        ["CREATE_DRAFT_PR", "UPDATE_DRAFT_PR"]
    )
    fix = repairloop._fix(1)
    with tempfile.TemporaryDirectory() as raw:
        patch = Path(raw) / "result.patch"
        patch.write_text(
            "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-a\n+b\n",
            encoding="utf-8",
        )
        fix["result_patch_sha256"] = _patch_sha256(patch)
        fix["branch"] = "applab/repair/bbbbbbbbbb-a1"
        identity = repairloop.fix_result_identity(fix)
        loop = {
            "schema_version": 1,
            "record_type": "VERIFY_REPAIR_LOOP_DECISION_V60D",
            "authority": "ORCHESTRATION_ONLY",
            "repository": "owner/app",
            "resolved_sha": "b" * 40,
            "work_item_id": "wrk_loop",
            "state": "COMPLETE",
            "next_action": "OPEN_DRAFT_PR",
            "reason_code": "VERIFIED_PASS",
            "fix_result_identity_sha256": identity,
            "merge_authority": "DENIED",
            "release_authority": "DENIED",
        }
        payload = build_plan(item, fix, loop, patch, "owner/app", "main")
        assert payload["state"] == "PLAN_ONLY"
        assert payload["pr_must_remain_draft"] is True
        assert "MERGE" in payload["forbidden_actions"]

        bad = dict(loop, next_action="MERGE")
        try:
            build_plan(item, fix, bad, patch, "owner/app", "main")
        except StewardError as exc:
            assert "OPEN_DRAFT_PR" in str(exc)
        else:
            raise AssertionError("merge-like loop action unexpectedly accepted")

    failed = reconcile_observation(
        ci_state="FAIL", unresolved_review_findings=0, superseded=False
    )
    assert failed["next_action"] == "RUN_CAUSAL_INVESTIGATOR"
    green = reconcile_observation(
        ci_state="PASS", unresolved_review_findings=0, superseded=False
    )
    assert green["merge"] is False and green["mark_ready"] is False
    print("AppLab v6.0E autonomous PR steward self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--work-item", default="")
    parser.add_argument("--fix-result", default="")
    parser.add_argument("--loop-decision", default="")
    parser.add_argument("--result-patch", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--title", default="AppLab bounded repair")
    parser.add_argument("--evidence-summary", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    required = (
        args.work_item,
        args.fix_result,
        args.loop_decision,
        args.result_patch,
        args.repository,
    )
    if not all(required):
        raise SystemExit(
            "--work-item, --fix-result, --loop-decision, --result-patch and --repository are required"
        )
    payload = build_plan(
        _read_json(args.work_item),
        _read_json(args.fix_result),
        _read_json(args.loop_decision),
        Path(args.result_patch),
        args.repository,
        args.base_branch,
    )
    if args.execute:
        payload = execute(
            Path(args.repo_root),
            payload,
            Path(args.result_patch),
            title=args.title,
            evidence_summary=args.evidence_summary,
        )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
