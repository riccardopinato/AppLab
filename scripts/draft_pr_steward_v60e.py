#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import agent_work_graph_v60a as workgraph
import verify_repair_loop_v60d as repair_loop

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = (
    ROOT
    / "integration"
    / "orchestration"
    / "contracts"
    / "draft-pr-steward-v1.json"
)
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,180}$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class StewardError(ValueError):
    pass


def _run(
    cwd: Path,
    *args: str,
    input_text: str | None = None,
    timeout: int = 60,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            list(args),
            cwd=str(cwd),
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StewardError(f"command failed to start: {' '.join(args)}") from exc
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-1600:]
        raise StewardError(
            f"command failed ({proc.returncode}): {' '.join(args)} :: {detail}"
        )
    return proc


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise StewardError("unsupported draft PR steward contract version")
    if payload.get("contract_name") != "APPLAB_DRAFT_PR_STEWARD":
        raise StewardError("unexpected draft PR steward contract")
    if payload.get("authority") != "DRAFT_BRANCH_AND_PR_ONLY":
        raise StewardError("draft PR steward authority mismatch")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_branch_component(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return value[:80] or "work"


def repair_branch_name(
    root_work_item_id: str,
    root_resolved_sha: str,
    contract: dict[str, Any] | None = None,
) -> str:
    contract = contract or load_contract()
    sha = str(root_resolved_sha or "").lower()
    if not SHA40_RE.fullmatch(sha):
        raise StewardError("root_resolved_sha must be an exact SHA")
    prefix = str(contract["branch_prefix"])
    branch = f"{prefix}{_safe_branch_component(root_work_item_id)}-{sha[:10]}"
    if not BRANCH_RE.fullmatch(branch):
        raise StewardError("generated repair branch is invalid")
    return branch


def _capabilities(work_item: dict[str, Any]) -> set[str]:
    workgraph.validate_work_item(work_item, workgraph.load_contract())
    envelope = work_item.get("authority_envelope")
    if not isinstance(envelope, dict):
        raise StewardError("WorkItem authority envelope is missing")
    return {
        str(value)
        for value in envelope.get("allowed_capabilities", [])
        if str(value)
    }


def _validate_target_base(base_branch: str, repair_branch: str, contract: dict[str, Any]) -> str:
    value = str(base_branch or "").strip()
    if value.startswith("refs/heads/"):
        value = value.removeprefix("refs/heads/")
    if not BRANCH_RE.fullmatch(value) or value.startswith("/") or ".." in value.split("/"):
        raise StewardError("target base branch is invalid")
    if value.startswith(str(contract["branch_prefix"])):
        raise StewardError("repair PR base cannot be another repair branch")
    if value == repair_branch:
        raise StewardError("repair branch cannot target itself")
    return value


def _validate_repair(
    work_item: dict[str, Any],
    repair_result: dict[str, Any],
    *,
    chain_attempt_number: int,
    patch_path: Path,
) -> str:
    if repair_result.get("record_type") != "BOUNDED_FIX_RESULT_V60C":
        raise StewardError("unexpected v6.0C repair result")
    if repair_result.get("state") != "READY_FOR_VERIFICATION":
        raise StewardError("repair result is not ready for materialization")
    repository = str(work_item.get("repository") or "")
    source_sha = str(work_item.get("resolved_sha") or "").lower()
    if str(repair_result.get("repository") or "") != repository:
        raise StewardError("repair result repository mismatch")
    if str(repair_result.get("resolved_sha") or "").lower() != source_sha:
        raise StewardError("repair result source SHA mismatch")
    if str(repair_result.get("work_item_id") or "") != str(
        work_item.get("work_item_id") or ""
    ):
        raise StewardError("repair result WorkItem mismatch")
    if int(repair_result.get("attempt_number", 0) or 0) != chain_attempt_number:
        raise StewardError("repair result attempt number mismatch")
    expected_patch = str(repair_result.get("result_patch_sha256") or "").lower()
    if not SHA256_RE.fullmatch(expected_patch):
        raise StewardError("repair result patch hash is invalid")
    if sha256_file(patch_path) != expected_patch:
        raise StewardError("materialization patch bytes do not match repair result")
    return repair_loop.repair_identity(repair_result)


def _origin_repository(remote_url: str) -> str:
    value = str(remote_url or "").strip()
    patterns = (
        r"^https://github\.com/([^/]+/[^/]+?)(?:\.git)?$",
        r"^git@github\.com:([^/]+/[^/]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/([^/]+/[^/]+?)(?:\.git)?$",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, value)
        if match:
            return match.group(1)
    return ""


def materialize_local(
    repo_root: Path,
    work_item: dict[str, Any],
    repair_result: dict[str, Any],
    patch_path: Path,
    *,
    chain_attempt_number: int,
    root_work_item_id: str,
    root_resolved_sha: str,
    target_base_branch: str,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    capabilities = _capabilities(work_item)
    required = (
        contract["required_capabilities"]["create"]
        if chain_attempt_number == 1
        else contract["required_capabilities"]["update"]
    )
    if required not in capabilities:
        raise StewardError(f"WorkItem does not grant {required}")
    if chain_attempt_number < 1 or chain_attempt_number > int(contract["max_repair_attempts"]):
        raise StewardError("chain attempt number exceeds steward budget")

    repo_root = repo_root.resolve()
    source_sha = _run(repo_root, "git", "rev-parse", "HEAD").stdout.strip().lower()
    if source_sha != str(work_item.get("resolved_sha") or "").lower():
        raise StewardError("repository HEAD does not match WorkItem exact source SHA")

    patch_path = patch_path.resolve()
    repair_identity = _validate_repair(
        work_item,
        repair_result,
        chain_attempt_number=chain_attempt_number,
        patch_path=patch_path,
    )
    branch = repair_branch_name(root_work_item_id, root_resolved_sha, contract)
    base = _validate_target_base(target_base_branch, branch, contract)

    temp_root = Path(tempfile.mkdtemp(prefix="applab-pr-steward-"))
    workspace = temp_root / "worktree"
    branch_created = False
    try:
        _run(repo_root, "git", "worktree", "add", "--detach", str(workspace), source_sha)
        _run(workspace, "git", "checkout", "-b", branch)
        branch_created = True
        _run(workspace, "git", "apply", "--check", str(patch_path))
        _run(workspace, "git", "apply", str(patch_path))
        _run(workspace, "git", "add", "-A")

        staged = _run(
            workspace,
            "git",
            "diff",
            "--cached",
            "--no-ext-diff",
            "--binary",
        ).stdout
        staged_hash = hashlib.sha256(staged.encode("utf-8")).hexdigest()
        expected_hash = str(repair_result["result_patch_sha256"]).lower()
        if staged_hash != expected_hash:
            raise StewardError(
                "staged materialization diff does not match v6.0C result patch identity"
            )

        _run(workspace, "git", "config", "user.name", "AppLab Repair Steward")
        _run(
            workspace,
            "git",
            "config",
            "user.email",
            "applab-repair@users.noreply.github.com",
        )
        message = (
            f"fix(applab): bounded repair attempt {chain_attempt_number} "
            f"for {root_work_item_id}"
        )
        _run(workspace, "git", "commit", "--no-gpg-sign", "-m", message)
        repaired_sha = _run(workspace, "git", "rev-parse", "HEAD").stdout.strip().lower()
        parent_sha = _run(workspace, "git", "rev-parse", "HEAD^").stdout.strip().lower()
        if parent_sha != source_sha:
            raise StewardError("materialized repair commit parent mismatch")

        return {
            "schema_version": 1,
            "record_type": "DRAFT_PR_MATERIALIZATION_V60E",
            "authority": "DRAFT_BRANCH_AND_PR_ONLY",
            "state": "MATERIALIZED_LOCAL",
            "repository": str(work_item["repository"]),
            "root_work_item_id": root_work_item_id,
            "work_item_id": str(work_item["work_item_id"]),
            "chain_attempt_number": chain_attempt_number,
            "parent_sha": parent_sha,
            "repaired_source_sha": repaired_sha,
            "repair_identity_sha256": repair_identity,
            "result_patch_sha256": expected_hash,
            "repair_branch": branch,
            "target_base_branch": base,
            "commit_message": message,
            "remote_write_performed": False,
            "pr_created_or_updated": False,
            "merge_authority": "DENIED",
            "release_authority": "DENIED",
        }
    finally:
        if workspace.exists():
            _run(repo_root, "git", "worktree", "remove", "--force", str(workspace), check=False)
        if branch_created:
            _run(repo_root, "git", "branch", "-D", branch, check=False)
        shutil.rmtree(temp_root, ignore_errors=True)


def decide_remote_action(
    *,
    chain_attempt_number: int,
    source_sha: str,
    repaired_sha: str,
    remote_branch_sha: str,
    existing_prs: list[dict[str, Any]],
    target_base_branch: str,
    repair_branch: str,
) -> dict[str, Any]:
    source_sha = source_sha.lower()
    repaired_sha = repaired_sha.lower()
    remote = str(remote_branch_sha or "").lower()
    if remote and not SHA40_RE.fullmatch(remote):
        raise StewardError("remote repair branch SHA is invalid")
    if len(existing_prs) > 1:
        raise StewardError("multiple open PRs exist for the repair branch")

    if not remote:
        if chain_attempt_number != 1:
            raise StewardError("update attempt requires existing repair branch")
        push = True
    elif remote == repaired_sha:
        push = False
    elif remote == source_sha:
        if chain_attempt_number == 1:
            raise StewardError("first attempt repair branch unexpectedly exists at source SHA")
        push = True
    else:
        raise StewardError("remote repair branch does not match source or repaired SHA")

    if existing_prs:
        pr = existing_prs[0]
        if pr.get("isDraft") is not True:
            raise StewardError("existing repair PR is no longer draft")
        if str(pr.get("baseRefName") or "") != target_base_branch:
            raise StewardError("existing repair PR base mismatch")
        if str(pr.get("headRefName") or "") != repair_branch:
            raise StewardError("existing repair PR head mismatch")
        if not remote:
            raise StewardError("existing repair PR has no remote repair branch")
        pr_action = "REUSE_DRAFT_PR" if remote == repaired_sha else "UPDATE_DRAFT_PR"
    else:
        pr_action = "CREATE_DRAFT_PR"

    return {
        "push_required": push,
        "pr_action": pr_action,
    }


def _remote_branch_sha(repo_root: Path, branch: str) -> str:
    proc = _run(
        repo_root,
        "git",
        "ls-remote",
        "--heads",
        "origin",
        f"refs/heads/{branch}",
    )
    line = proc.stdout.strip()
    if not line:
        return ""
    return line.split()[0].lower()


def _open_prs(repo_root: Path, repository: str, branch: str) -> list[dict[str, Any]]:
    proc = _run(
        repo_root,
        "gh",
        "pr",
        "list",
        "--repo",
        repository,
        "--head",
        branch,
        "--state",
        "open",
        "--limit",
        "10",
        "--json",
        "number,isDraft,baseRefName,headRefName,url",
    )
    payload = json.loads(proc.stdout or "[]")
    if not isinstance(payload, list):
        raise StewardError("gh pr list returned invalid payload")
    return [row for row in payload if isinstance(row, dict)]


def execute_remote(
    repo_root: Path,
    work_item: dict[str, Any],
    repair_result: dict[str, Any],
    patch_path: Path,
    *,
    chain_attempt_number: int,
    root_work_item_id: str,
    root_resolved_sha: str,
    target_base_branch: str,
    title: str,
    body: str,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    capabilities = _capabilities(work_item)
    create_cap = str(contract["required_capabilities"]["create"])
    update_cap = str(contract["required_capabilities"]["update"])

    repo_root = repo_root.resolve()
    source_sha = _run(repo_root, "git", "rev-parse", "HEAD").stdout.strip().lower()
    if source_sha != str(work_item["resolved_sha"]).lower():
        raise StewardError("repository HEAD does not match WorkItem exact source SHA")

    remote_url = _run(repo_root, "git", "remote", "get-url", "origin").stdout.strip()
    remote_repo = _origin_repository(remote_url)
    if remote_repo != str(work_item["repository"]):
        raise StewardError("origin repository does not match WorkItem repository")

    # Materialize again in a trusted ephemeral worktree so the exact commit that
    # is pushed is produced from the same validated patch bytes.
    patch_path = patch_path.resolve()
    repair_identity = _validate_repair(
        work_item,
        repair_result,
        chain_attempt_number=chain_attempt_number,
        patch_path=patch_path,
    )
    branch = repair_branch_name(root_work_item_id, root_resolved_sha, contract)
    base = _validate_target_base(target_base_branch, branch, contract)

    temp_root = Path(tempfile.mkdtemp(prefix="applab-pr-steward-remote-"))
    workspace = temp_root / "worktree"
    branch_created = False
    try:
        _run(repo_root, "git", "worktree", "add", "--detach", str(workspace), source_sha)
        _run(workspace, "git", "checkout", "-b", branch)
        branch_created = True
        _run(workspace, "git", "apply", "--check", str(patch_path))
        _run(workspace, "git", "apply", str(patch_path))
        _run(workspace, "git", "add", "-A")
        staged = _run(
            workspace, "git", "diff", "--cached", "--no-ext-diff", "--binary"
        ).stdout
        staged_hash = hashlib.sha256(staged.encode("utf-8")).hexdigest()
        expected_hash = str(repair_result["result_patch_sha256"]).lower()
        if staged_hash != expected_hash:
            raise StewardError("remote materialization diff identity mismatch")

        _run(workspace, "git", "config", "user.name", "AppLab Repair Steward")
        _run(
            workspace,
            "git",
            "config",
            "user.email",
            "applab-repair@users.noreply.github.com",
        )
        message = (
            f"fix(applab): bounded repair attempt {chain_attempt_number} "
            f"for {root_work_item_id}"
        )
        _run(workspace, "git", "commit", "--no-gpg-sign", "-m", message)
        repaired_sha = _run(workspace, "git", "rev-parse", "HEAD").stdout.strip().lower()
        parent_sha = _run(workspace, "git", "rev-parse", "HEAD^").stdout.strip().lower()
        if parent_sha != source_sha:
            raise StewardError("remote materialization parent mismatch")

        remote_sha = _remote_branch_sha(repo_root, branch)
        prs = _open_prs(repo_root, str(work_item["repository"]), branch)
        decision = decide_remote_action(
            chain_attempt_number=chain_attempt_number,
            source_sha=source_sha,
            repaired_sha=repaired_sha,
            remote_branch_sha=remote_sha,
            existing_prs=prs,
            target_base_branch=base,
            repair_branch=branch,
        )

        if decision["push_required"]:
            capability = create_cap if chain_attempt_number == 1 else update_cap
            if capability not in capabilities:
                raise StewardError(f"WorkItem does not grant {capability}")
            _run(
                workspace,
                "git",
                "push",
                "origin",
                f"HEAD:refs/heads/{branch}",
                timeout=120,
            )
            remote_sha = repaired_sha

        pr_url = ""
        pr_number: int | None = None
        action = str(decision["pr_action"])
        if action == "CREATE_DRAFT_PR":
            if create_cap not in capabilities:
                raise StewardError(f"WorkItem does not grant {create_cap}")
            body_file = temp_root / "pr-body.md"
            body_file.write_text(body, encoding="utf-8")
            proc = _run(
                repo_root,
                "gh",
                "pr",
                "create",
                "--repo",
                str(work_item["repository"]),
                "--draft",
                "--base",
                base,
                "--head",
                branch,
                "--title",
                title,
                "--body-file",
                str(body_file),
                timeout=120,
            )
            pr_url = proc.stdout.strip().splitlines()[-1]
            state = "DRAFT_PR_CREATED"
        else:
            if not prs:
                raise StewardError("draft PR disappeared during stewardship")
            pr = prs[0]
            pr_number = int(pr["number"])
            pr_url = str(pr.get("url") or "")
            if action == "UPDATE_DRAFT_PR" and update_cap not in capabilities:
                raise StewardError(f"WorkItem does not grant {update_cap}")
            # A fast-forward branch update updates the draft PR automatically.
            # No ready/approve/merge mutation is performed.
            state = "DRAFT_PR_UPDATED" if action == "UPDATE_DRAFT_PR" else "DRAFT_PR_CREATED"

        return {
            "schema_version": 1,
            "record_type": "DRAFT_PR_MATERIALIZATION_V60E",
            "authority": "DRAFT_BRANCH_AND_PR_ONLY",
            "state": state,
            "repository": str(work_item["repository"]),
            "root_work_item_id": root_work_item_id,
            "work_item_id": str(work_item["work_item_id"]),
            "chain_attempt_number": chain_attempt_number,
            "parent_sha": parent_sha,
            "repaired_source_sha": repaired_sha,
            "repair_identity_sha256": repair_identity,
            "result_patch_sha256": expected_hash,
            "repair_branch": branch,
            "target_base_branch": base,
            "remote_branch_sha": remote_sha,
            "pr_number": pr_number,
            "pr_url": pr_url,
            "remote_write_performed": bool(decision["push_required"] or action == "CREATE_DRAFT_PR"),
            "merge_performed": False,
            "release_performed": False,
            "self_approval_performed": False,
        }
    finally:
        if workspace.exists():
            _run(repo_root, "git", "worktree", "remove", "--force", str(workspace), check=False)
        if branch_created:
            _run(repo_root, "git", "branch", "-D", branch, check=False)
        shutil.rmtree(temp_root, ignore_errors=True)


def _read_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise StewardError(f"JSON root must be an object: {path}")
    return payload


def self_test() -> None:
    contract = load_contract()
    branch = repair_branch_name("wrk_demo", "a" * 40, contract)
    assert branch.startswith("applab/repair/")
    assert decide_remote_action(
        chain_attempt_number=1,
        source_sha="a" * 40,
        repaired_sha="b" * 40,
        remote_branch_sha="",
        existing_prs=[],
        target_base_branch="main",
        repair_branch=branch,
    ) == {"push_required": True, "pr_action": "CREATE_DRAFT_PR"}

    idempotent = decide_remote_action(
        chain_attempt_number=1,
        source_sha="a" * 40,
        repaired_sha="b" * 40,
        remote_branch_sha="b" * 40,
        existing_prs=[
            {
                "number": 12,
                "isDraft": True,
                "baseRefName": "main",
                "headRefName": branch,
                "url": "https://github.com/owner/app/pull/12",
            }
        ],
        target_base_branch="main",
        repair_branch=branch,
    )
    assert idempotent == {"push_required": False, "pr_action": "REUSE_DRAFT_PR"}

    update = decide_remote_action(
        chain_attempt_number=2,
        source_sha="b" * 40,
        repaired_sha="c" * 40,
        remote_branch_sha="b" * 40,
        existing_prs=[
            {
                "number": 12,
                "isDraft": True,
                "baseRefName": "main",
                "headRefName": branch,
                "url": "https://github.com/owner/app/pull/12",
            }
        ],
        target_base_branch="main",
        repair_branch=branch,
    )
    assert update == {"push_required": True, "pr_action": "UPDATE_DRAFT_PR"}

    try:
        decide_remote_action(
            chain_attempt_number=2,
            source_sha="b" * 40,
            repaired_sha="c" * 40,
            remote_branch_sha="d" * 40,
            existing_prs=[],
            target_base_branch="main",
            repair_branch=branch,
        )
    except StewardError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("diverged remote branch unexpectedly accepted")

    print("AppLab v6.0E draft PR steward self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--work-item", default="")
    parser.add_argument("--repair-result", default="")
    parser.add_argument("--patch", default="")
    parser.add_argument("--attempt-number", type=int, default=1)
    parser.add_argument("--root-work-item-id", default="")
    parser.add_argument("--root-resolved-sha", default="")
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--title", default="AppLab bounded repair")
    parser.add_argument("--body", default="Automated bounded repair generated by AppLab.")
    parser.add_argument("--execute-remote", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    required = (
        args.work_item,
        args.repair_result,
        args.patch,
        args.root_work_item_id,
        args.root_resolved_sha,
    )
    if not all(required):
        raise SystemExit(
            "--work-item, --repair-result, --patch, --root-work-item-id and "
            "--root-resolved-sha are required"
        )
    work_item = _read_json(args.work_item)
    repair_result = _read_json(args.repair_result)
    if args.execute_remote:
        report = execute_remote(
            Path(args.repo_root),
            work_item,
            repair_result,
            Path(args.patch),
            chain_attempt_number=args.attempt_number,
            root_work_item_id=args.root_work_item_id,
            root_resolved_sha=args.root_resolved_sha,
            target_base_branch=args.base_branch,
            title=args.title,
            body=args.body,
        )
    else:
        report = materialize_local(
            Path(args.repo_root),
            work_item,
            repair_result,
            Path(args.patch),
            chain_attempt_number=args.attempt_number,
            root_work_item_id=args.root_work_item_id,
            root_resolved_sha=args.root_resolved_sha,
            target_base_branch=args.base_branch,
        )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
