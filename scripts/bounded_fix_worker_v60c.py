#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

import agent_work_graph_v60a as workgraph

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = (
    ROOT
    / "integration"
    / "orchestration"
    / "contracts"
    / "bounded-fix-worker-v1.json"
)

PATH_HEADERS = re.compile(r"^(?:---|\+\+\+)\s+(?:a/|b/)?(.+)$")
BRANCH_SAFE = re.compile(r"[^A-Za-z0-9._/-]+")
PATHLIKE_SUFFIXES = {
    ".dart", ".py", ".kt", ".java", ".kts", ".gradle", ".xml", ".json",
    ".yaml", ".yml", ".sql", ".sh", ".js", ".jsx", ".ts", ".tsx", ".css",
    ".html", ".swift", ".m", ".mm", ".cpp", ".c", ".h", ".hpp", ".toml",
    ".properties", ".md", ".txt",
}


class WorkerError(ValueError):
    pass


def _run(
    cwd: Path,
    *args: str,
    input_text: str | None = None,
    timeout: int = 30,
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
        raise WorkerError(f"command failed to start: {' '.join(args)}") from exc
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-1200:]
        raise WorkerError(f"command failed ({proc.returncode}): {' '.join(args)} :: {detail}")
    return proc


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise WorkerError("unsupported bounded fix worker contract version")
    if payload.get("contract_name") != "APPLAB_BOUNDED_FIX_WORKER":
        raise WorkerError("unexpected bounded fix worker contract")
    if payload.get("authority") != "BRANCH_WORKSPACE_ONLY":
        raise WorkerError("bounded fix worker authority must remain branch-workspace-only")
    return payload


def _safe_rel(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    text = re.sub(r"/+", "/", text).strip("/")
    if not text or text == "/dev/null":
        return ""
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        return ""
    return path.as_posix()


def _looks_like_path(value: str) -> bool:
    path = _safe_rel(value)
    if not path:
        return False
    return "/" in path or Path(path).suffix.lower() in PATHLIKE_SUFFIXES


def _patch_paths(patch_text: str) -> set[str]:
    paths: set[str] = set()
    for line in patch_text.splitlines():
        match = PATH_HEADERS.match(line)
        if not match:
            continue
        raw = match.group(1).split("\t", 1)[0].strip()
        if raw == "/dev/null":
            continue
        path = _safe_rel(raw)
        if path:
            paths.add(path)
    return paths


def _is_test_path(path: str) -> bool:
    lower = f"/{path.lower()}"
    return (
        path.lower().startswith(("test/", "tests/"))
        or "/src/test/" in lower
        or "/src/androidtest/" in lower
        or Path(path).name.lower().startswith("test_")
        or Path(path).stem.lower().endswith("_test")
    )


def _is_protected(path: str, contract: dict[str, Any]) -> bool:
    lower = path.lower()
    if path in set(contract["protected_exact_paths"]):
        return True
    if any(lower.startswith(str(prefix).lower()) for prefix in contract["protected_prefixes"]):
        return True
    name = Path(path).name.lower()
    for pattern in contract["protected_name_patterns"]:
        token = str(pattern).lower()
        if token == ".env" and name.startswith(".env"):
            return True
        if token.startswith(".") and name.endswith(token):
            return True
        if name == token:
            return True
    return False


def _allowed_paths(investigation: dict[str, Any]) -> set[str]:
    allowed: set[str] = set()
    rows = investigation.get("ranked_candidate_files")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            path = _safe_rel(row.get("path"))
            if path and str(row.get("kind", "")).upper() != "PROTECTED":
                allowed.add(path)
            tests = row.get("paired_tests")
            if isinstance(tests, list):
                for raw in tests:
                    test_path = _safe_rel(raw)
                    if test_path:
                        allowed.add(test_path)
    regressions = investigation.get("required_regression_targets")
    if isinstance(regressions, list):
        for raw in regressions:
            text = str(raw or "")
            if _looks_like_path(text):
                path = _safe_rel(text)
                if path:
                    allowed.add(path)
    return allowed


def _validate_inputs(
    work_item: dict[str, Any],
    investigation: dict[str, Any],
    exact_source_sha: str,
    attempt_number: int,
    contract: dict[str, Any],
) -> set[str]:
    workgraph.validate_work_item(work_item, workgraph.load_contract())
    if "ALLOW_CODE_EDIT" not in work_item["authority_envelope"]["allowed_capabilities"]:
        raise WorkerError("WorkItem does not grant ALLOW_CODE_EDIT")
    if work_item["resolved_sha"] != exact_source_sha:
        raise WorkerError("WorkItem resolved_sha does not match exact source SHA")
    if investigation.get("resolved_sha") != exact_source_sha:
        raise WorkerError("investigation resolved_sha does not match exact source SHA")
    if investigation.get("state") != contract["required_investigation_state"]:
        raise WorkerError("investigation is not in LOCALIZED state")
    if investigation.get("edit_recommendation") != contract["required_edit_recommendation"]:
        raise WorkerError("investigation is not eligible for bounded repair")
    if investigation.get("classification") not in contract["supported_failure_classes"]:
        raise WorkerError("failure class is not eligible for bounded repair")
    if attempt_number < 1:
        raise WorkerError("attempt_number must be >= 1")
    work_budget = int(work_item["budgets"]["max_repair_attempts"])
    ceiling = int(contract["budgets"]["max_repair_attempts"])
    if attempt_number > min(work_budget, ceiling):
        raise WorkerError("repair attempt exceeds WorkItem/contract budget")
    allowed = _allowed_paths(investigation)
    if not allowed:
        raise WorkerError("investigation exposes no bounded candidate/regression paths")
    return allowed


def _preflight_patch(
    repo_root: Path,
    patch_file: Path,
    patch_text: str,
    allowed_paths: set[str],
    work_item: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    if not patch_text.strip():
        raise WorkerError("patch is empty")
    lowered = patch_text.lower()
    if "git binary patch" in lowered or "binary files " in lowered:
        raise WorkerError("binary patches are not allowed")
    if "rename from " in lowered or "rename to " in lowered:
        raise WorkerError("rename patches are not allowed in v6.0C")
    if "deleted file mode " in lowered:
        raise WorkerError("file deletion patches are not allowed in v6.0C")
    paths = _patch_paths(patch_text)
    if not paths:
        raise WorkerError("patch contains no repository paths")
    protected = sorted(path for path in paths if _is_protected(path, contract))
    if protected:
        raise WorkerError("patch touches protected path(s): " + ", ".join(protected))
    outside = sorted(paths - allowed_paths)
    if outside:
        raise WorkerError("patch escapes causal repair scope: " + ", ".join(outside))

    max_files = min(
        int(work_item["budgets"]["max_files"]),
        int(contract["budgets"]["max_files"]),
    )
    if len(paths) > max_files:
        raise WorkerError(f"patch changes {len(paths)} files; budget is {max_files}")

    stats_proc = _run(repo_root, "git", "apply", "--numstat", str(patch_file))
    additions = 0
    deletions = 0
    stats: list[dict[str, Any]] = []
    for line in stats_proc.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        if parts[0] == "-" or parts[1] == "-":
            raise WorkerError("binary/unknown patch statistics are not allowed")
        path = _safe_rel(parts[2])
        add = int(parts[0])
        delete = int(parts[1])
        additions += add
        deletions += delete
        stats.append({"path": path, "additions": add, "deletions": delete})
    changed_lines = additions + deletions
    max_lines = min(
        int(work_item["budgets"]["max_changed_lines"]),
        int(contract["budgets"]["max_changed_lines"]),
    )
    if changed_lines > max_lines:
        raise WorkerError(f"patch changes {changed_lines} lines; budget is {max_lines}")
    _run(repo_root, "git", "apply", "--check", str(patch_file))
    return {
        "paths": sorted(paths),
        "stats": stats,
        "additions": additions,
        "deletions": deletions,
        "changed_lines": changed_lines,
    }


def _status_paths(workspace: Path) -> dict[str, str]:
    proc = _run(workspace, "git", "status", "--porcelain=v1", "-z")
    result: dict[str, str] = {}
    for raw in proc.stdout.split("\0"):
        if not raw:
            continue
        if len(raw) < 4:
            continue
        status = raw[:2]
        path = _safe_rel(raw[3:])
        if not path:
            continue
        result[path] = status
    return result


def _test_weakening_findings(diff_text: str, contract: dict[str, Any]) -> list[str]:
    assertions = tuple(str(x).lower() for x in contract["assertion_tokens"])
    skips = tuple(str(x).lower() for x in contract["test_weakening_tokens"])
    findings: list[str] = []
    current_path = ""
    deleted_assertions = 0
    added_assertions = 0

    def flush_hunk() -> None:
        nonlocal deleted_assertions, added_assertions
        if current_path and _is_test_path(current_path):
            if deleted_assertions > added_assertions:
                findings.append(f"assertion/test coverage deletion in {current_path}")
        deleted_assertions = 0
        added_assertions = 0

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            flush_hunk()
            parts = line.split()
            current_path = _safe_rel(
                parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else ""
            )
            continue
        if line.startswith("@@"):
            flush_hunk()
            continue
        if not current_path or not _is_test_path(current_path):
            continue
        lower = line.lower()
        if line.startswith("-") and not line.startswith("---"):
            if any(token in lower for token in assertions):
                deleted_assertions += 1
        if line.startswith("+") and not line.startswith("+++"):
            if any(token in lower for token in skips):
                findings.append(f"skip/disable insertion in {current_path}")
            if any(token in lower for token in assertions):
                added_assertions += 1
    flush_hunk()
    return sorted(set(findings))


def _branch_name(exact_source_sha: str, attempt_number: int) -> str:
    raw = f"applab/repair/{exact_source_sha[:10]}-a{attempt_number}"
    return BRANCH_SAFE.sub("-", raw).strip("-/")


def apply_bounded_patch(
    repo_root: Path,
    patch_path: Path,
    work_item: dict[str, Any],
    investigation: dict[str, Any],
    *,
    attempt_number: int,
    result_patch_path: Path | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    repo_root = repo_root.resolve()
    if not (repo_root / ".git").exists():
        probe = _run(repo_root, "git", "rev-parse", "--git-dir", check=False)
        if probe.returncode != 0:
            raise WorkerError("repo_root is not a Git repository")

    head = _run(repo_root, "git", "rev-parse", "HEAD").stdout.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise WorkerError("workspace HEAD is not an exact lowercase SHA")
    exact_source_sha = head
    allowed = _validate_inputs(
        work_item,
        investigation,
        exact_source_sha,
        attempt_number,
        contract,
    )
    patch_path = patch_path.resolve()
    patch_text = patch_path.read_text(encoding="utf-8", errors="strict")
    preflight = _preflight_patch(
        repo_root,
        patch_path,
        patch_text,
        allowed,
        work_item,
        contract,
    )
    patch_sha = hashlib.sha256(patch_text.encode("utf-8")).hexdigest()

    temp_root = Path(tempfile.mkdtemp(prefix="applab-repair-"))
    workspace = temp_root / "worktree"
    branch = _branch_name(exact_source_sha, attempt_number)
    try:
        _run(repo_root, "git", "worktree", "add", "--detach", str(workspace), exact_source_sha, timeout=60)
        _run(workspace, "git", "checkout", "-b", branch)
        _run(workspace, "git", "apply", str(patch_path))

        status = _status_paths(workspace)
        untracked = sorted(path for path, code in status.items() if code == "??")
        if untracked:
            _run(workspace, "git", "add", "-N", "--", *untracked)
            status = _status_paths(workspace)
        if not status:
            return {
                "schema_version": 1,
                "record_type": "BOUNDED_FIX_RESULT_V60C",
                "authority": "BRANCH_WORKSPACE_ONLY",
                "state": "NO_CHANGE",
                "repository": investigation.get("repository", ""),
                "resolved_sha": exact_source_sha,
                "work_item_id": str(work_item.get("work_item_id") or ""),
                "attempt_number": attempt_number,
                "branch": branch,
                "patch_sha256": patch_sha,
                "repository_mutation_performed": False,
                "remote_write_performed": False,
                "verification_authority": "UNCHANGED",
            }

        changed_paths = sorted(status)
        if set(changed_paths) != set(preflight["paths"]):
            raise WorkerError("applied workspace paths differ from preflight patch paths")
        unsupported_status = [
            f"{path}:{code}"
            for path, code in status.items()
            if "D" in code or "R" in code
        ]
        if unsupported_status:
            raise WorkerError("delete/rename result is not allowed: " + ", ".join(unsupported_status))
        protected = sorted(path for path in changed_paths if _is_protected(path, contract))
        if protected:
            raise WorkerError("applied workspace touches protected path(s): " + ", ".join(protected))

        applied_diff = _run(workspace, "git", "diff", "--no-ext-diff", "--binary").stdout
        weakening = _test_weakening_findings(applied_diff, contract)
        if weakening:
            raise WorkerError("test weakening detected: " + "; ".join(weakening))

        # Ensure no path appeared outside the deterministic causal scope after apply.
        outside = sorted(set(changed_paths) - allowed)
        if outside:
            raise WorkerError("applied workspace escaped causal scope: " + ", ".join(outside))

        result_patch_sha = hashlib.sha256(applied_diff.encode("utf-8")).hexdigest()
        if result_patch_path is not None:
            result_patch_path.parent.mkdir(parents=True, exist_ok=True)
            result_patch_path.write_text(applied_diff, encoding="utf-8")

        return {
            "schema_version": 1,
            "record_type": "BOUNDED_FIX_RESULT_V60C",
            "authority": "BRANCH_WORKSPACE_ONLY",
            "state": "READY_FOR_VERIFICATION",
            "repository": investigation.get("repository", ""),
            "resolved_sha": exact_source_sha,
            "work_item_id": str(work_item.get("work_item_id") or ""),
            "attempt_number": attempt_number,
            "branch": branch,
            "patch_sha256": patch_sha,
            "result_patch_sha256": result_patch_sha,
            "changed_files": changed_paths,
            "additions": preflight["additions"],
            "deletions": preflight["deletions"],
            "changed_lines": preflight["changed_lines"],
            "required_regression_targets": investigation.get("required_regression_targets", []),
            "repository_mutation_performed": True,
            "mutation_scope": "EPHEMERAL_LOCAL_WORKTREE_ONLY",
            "remote_write_performed": False,
            "merge_performed": False,
            "release_performed": False,
            "verification_authority": "UNCHANGED",
            "certification_authority": "UNCHANGED",
            "next_action": "RUN_FOCUSED_AND_APPLAB_VERIFICATION",
        }
    finally:
        if workspace.exists():
            _run(repo_root, "git", "worktree", "remove", "--force", str(workspace), check=False)
        shutil.rmtree(temp_root, ignore_errors=True)


def _read_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise WorkerError(f"JSON root must be an object: {path}")
    return payload


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "repo"
        root.mkdir()
        _run(root, "git", "init")
        _run(root, "git", "config", "user.email", "applab@example.invalid")
        _run(root, "git", "config", "user.name", "AppLab")
        (root / "lib").mkdir()
        (root / "tests").mkdir()
        (root / "lib/client.py").write_text("def value():\n    return 1\n", encoding="utf-8")
        (root / "tests/test_client.py").write_text(
            "from lib.client import value\n\ndef test_value():\n    assert value() == 1\n",
            encoding="utf-8",
        )
        _run(root, "git", "add", ".")
        _run(root, "git", "commit", "-m", "fixture")
        sha = _run(root, "git", "rev-parse", "HEAD").stdout.strip()

        operation = {
            "schema_version": 1,
            "record_type": "APPLAB_OPERATION",
            "operation_id": "op_v60c",
            "correlation_id": "cor_v60c",
            "operation_class": "VERIFICATION",
            "analysis_mode": "fast",
            "repository": "owner/app",
            "source_ref": "main",
            "resolved_sha": sha,
            "applab_sha": "c" * 40,
            "contract_fingerprint": "",
            "plan_digest_sha256": "",
            "force_generation": 0,
            "idempotency_key": "",
            "queue_key": "owner/app|main|VERIFICATION",
            "priority": 200,
            "state": "QUEUED",
            "authority": "ORCHESTRATION_ONLY",
        }
        import durable_brain_v54a as brain
        operation["idempotency_key"] = brain.operation_idempotency_key(operation)
        work_item = workgraph.adapt_operation_to_work_item(
            operation,
            work_item_id="wrk_v60c",
            allow_code_edit=True,
        )
        investigation = {
            "repository": "owner/app",
            "resolved_sha": sha,
            "classification": "APP_RUNTIME_FAILURE",
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

        patch = Path(raw) / "repair.patch"
        patch.write_text(
            """diff --git a/lib/client.py b/lib/client.py
--- a/lib/client.py
+++ b/lib/client.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 2
diff --git a/tests/test_client.py b/tests/test_client.py
--- a/tests/test_client.py
+++ b/tests/test_client.py
@@ -2,4 +2,4 @@
 
 def test_value():
-    assert value() == 1
+    assert value() == 2
""",
            encoding="utf-8",
        )
        # Replacing an assertion with another assertion is allowed; the heuristic
        # rejects assertion deletion only when it is not replaced on the same diff.
        # For the self-test use source-only patch to avoid ambiguous weakening.
        patch.write_text(
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
        report = apply_bounded_patch(
            root,
            patch,
            work_item,
            investigation,
            attempt_number=1,
            result_patch_path=result_patch,
        )
        assert report["state"] == "READY_FOR_VERIFICATION", report
        assert report["changed_files"] == ["lib/client.py"]
        assert report["remote_write_performed"] is False
        assert result_patch.is_file()

        protected = Path(raw) / "protected.patch"
        protected.write_text(
            """diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1 +1 @@
-old
+new
""",
            encoding="utf-8",
        )
        try:
            apply_bounded_patch(root, protected, work_item, investigation, attempt_number=1)
        except WorkerError as exc:
            assert "protected" in str(exc) or "causal repair scope" in str(exc)
        else:
            raise AssertionError("protected workflow patch unexpectedly accepted")

        weakening = Path(raw) / "weakening.patch"
        weakening.write_text(
            """diff --git a/tests/test_client.py b/tests/test_client.py
--- a/tests/test_client.py
+++ b/tests/test_client.py
@@ -2,3 +2,3 @@
 
 def test_value():
-    assert value() == 1
+    return
""",
            encoding="utf-8",
        )
        try:
            apply_bounded_patch(root, weakening, work_item, investigation, attempt_number=1)
        except WorkerError as exc:
            assert "test weakening" in str(exc)
        else:
            raise AssertionError("test assertion deletion unexpectedly accepted")

        denied = dict(investigation, edit_recommendation="HUMAN_OR_DEEPER_INVESTIGATION_REQUIRED")
        try:
            apply_bounded_patch(root, patch, work_item, denied, attempt_number=1)
        except WorkerError as exc:
            assert "not eligible" in str(exc)
        else:
            raise AssertionError("non-eligible investigation unexpectedly edited code")

    print("AppLab v6.0C bounded fix worker self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=False, default=".")
    parser.add_argument("--patch", default="")
    parser.add_argument("--work-item", default="")
    parser.add_argument("--investigation", default="")
    parser.add_argument("--attempt-number", type=int, default=1)
    parser.add_argument("--result-patch", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.patch or not args.work_item or not args.investigation:
        raise SystemExit("--patch, --work-item and --investigation are required")
    report = apply_bounded_patch(
        Path(args.repo_root),
        Path(args.patch),
        _read_json(args.work_item),
        _read_json(args.investigation),
        attempt_number=args.attempt_number,
        result_patch_path=Path(args.result_patch) if args.result_patch else None,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
