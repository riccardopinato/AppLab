#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
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


class FixWorkerError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise FixWorkerError("unsupported bounded fix worker contract version")
    if payload.get("contract_name") != "APPLAB_BOUNDED_FIX_WORKER":
        raise FixWorkerError("unexpected bounded fix worker contract")
    if payload.get("authority") != "BOUNDED_WORKSPACE_EDIT_ONLY":
        raise FixWorkerError("bounded fix worker authority mismatch")
    return payload


def _run_git(repo_root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FixWorkerError(f"git command failed: {' '.join(args)}") from exc
    return proc.stdout.strip()


def _safe_relative(raw: Any) -> str:
    value = str(raw or "").strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise FixWorkerError(f"unsafe repair path: {raw!r}")
    return path.as_posix()


def _confined_path(repo_root: Path, relative: str, *, allow_missing: bool) -> Path:
    root = repo_root.resolve()
    normalized = _safe_relative(relative)
    candidate = root
    for part in PurePosixPath(normalized).parts:
        candidate = candidate / part
        if candidate.exists() and candidate.is_symlink():
            raise FixWorkerError(f"repair path traverses symlink: {normalized}")
    resolved_parent = candidate.parent.resolve()
    try:
        resolved_parent.relative_to(root)
    except ValueError as exc:
        raise FixWorkerError(f"repair path escapes repository: {normalized}") from exc
    if not allow_missing and not candidate.is_file():
        raise FixWorkerError(f"repair file does not exist: {normalized}")
    return candidate


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FixWorkerError(f"JSON root must be an object: {path}")
    return payload


def _protected(path: str, contract: dict[str, Any]) -> bool:
    if path in set(contract["protected_paths"]):
        return True
    return any(path.startswith(prefix) for prefix in contract["protected_prefixes"])


def _is_test_path(path: str) -> bool:
    lower = path.lower()
    return (
        lower.startswith(("test/", "tests/"))
        or "/src/test/" in f"/{lower}"
        or "/src/androidtest/" in f"/{lower}"
        or lower.endswith(("_test.dart", "_test.py", "_test.kt", "_test.java"))
    )


def _token_count(text: str, tokens: list[str]) -> int:
    lower = text.lower()
    return sum(lower.count(token.lower()) for token in tokens)


def _changed_line_count(before: str, after: str) -> int:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile="before",
        tofile="after",
        lineterm="",
    )
    count = 0
    for line in diff:
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            count += 1
    return count


def _candidate_map(investigation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    rows = investigation.get("ranked_candidate_files")
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            path = _safe_relative(row.get("path"))
        except FixWorkerError:
            continue
        result[path] = row
    return result


def _required_regression_paths(investigation: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    rows = investigation.get("required_regression_targets")
    if not isinstance(rows, list):
        return result
    for value in rows:
        text = str(value or "").strip()
        if "/" not in text:
            continue
        try:
            path = _safe_relative(text)
        except FixWorkerError:
            continue
        if _is_test_path(path):
            result.add(path)
    return result


def _assert_clean_repair_branch(
    repo_root: Path,
    source_sha: str,
    contract: dict[str, Any],
) -> str:
    head = _run_git(repo_root, "rev-parse", "HEAD").lower()
    if head != source_sha.lower():
        raise FixWorkerError("workspace HEAD does not match exact WorkItem source SHA")
    branch = _run_git(repo_root, "branch", "--show-current")
    if not branch.startswith(str(contract["required_branch_prefix"])):
        raise FixWorkerError("workspace must use an isolated applab-repair/* branch")
    status = _run_git(repo_root, "status", "--porcelain")
    if status:
        raise FixWorkerError("repair workspace must be clean before bounded edit")
    return branch


def _validate_work_item(work_item: dict[str, Any]) -> None:
    workgraph.validate_work_item(work_item, workgraph.load_contract())
    if work_item.get("risk") == "SECURITY":
        raise FixWorkerError("security-risk WorkItem cannot enter autonomous fix worker")
    allowed = set(
        (work_item.get("authority_envelope") or {}).get("allowed_capabilities") or []
    )
    if "ALLOW_CODE_EDIT" not in allowed:
        raise FixWorkerError("WorkItem does not grant ALLOW_CODE_EDIT")


def _validate_identity(
    work_item: dict[str, Any],
    investigation: dict[str, Any],
    patch: dict[str, Any],
) -> None:
    expected = {
        "repository": str(work_item.get("repository") or ""),
        "resolved_sha": str(work_item.get("resolved_sha") or "").lower(),
    }
    for name, payload in (("investigation", investigation), ("patch_plan", patch)):
        if str(payload.get("repository") or "") != expected["repository"]:
            raise FixWorkerError(f"{name} repository identity mismatch")
        if str(payload.get("resolved_sha") or "").lower() != expected["resolved_sha"]:
            raise FixWorkerError(f"{name} source SHA identity mismatch")
    if str(patch.get("work_item_id") or "") != str(work_item.get("work_item_id") or ""):
        raise FixWorkerError("patch_plan WorkItem identity mismatch")


def _apply_replacements(text: str, replacements: list[Any], path: str) -> str:
    result = text
    if not replacements:
        raise FixWorkerError(f"existing file repair requires replacements: {path}")
    for index, raw in enumerate(replacements):
        if not isinstance(raw, dict):
            raise FixWorkerError(f"replacement {index} must be an object: {path}")
        old = raw.get("old")
        new = raw.get("new")
        expected = raw.get("expected_occurrences", 1)
        if not isinstance(old, str) or not old:
            raise FixWorkerError(f"replacement {index} old text must be non-empty: {path}")
        if not isinstance(new, str) or old == new:
            raise FixWorkerError(f"replacement {index} must materially change text: {path}")
        if not isinstance(expected, int) or expected < 1:
            raise FixWorkerError(f"replacement {index} expected_occurrences invalid: {path}")
        actual = result.count(old)
        if actual != expected:
            raise FixWorkerError(
                f"replacement occurrence mismatch for {path}: expected {expected}, got {actual}"
            )
        result = result.replace(old, new)
    return result


def _test_strength_guard(
    path: str,
    before: str,
    after: str,
    contract: dict[str, Any],
    *,
    created: bool,
) -> None:
    if not _is_test_path(path):
        return
    assertions_before = _token_count(before, contract["test_assertion_tokens"])
    assertions_after = _token_count(after, contract["test_assertion_tokens"])
    skips_before = _token_count(before, contract["test_skip_tokens"])
    skips_after = _token_count(after, contract["test_skip_tokens"])
    if created and assertions_after < 1:
        raise FixWorkerError("new regression test must contain an assertion signal")
    if assertions_after < assertions_before:
        raise FixWorkerError("repair would weaken existing test assertion signals")
    if skips_after > skips_before:
        raise FixWorkerError("repair would introduce additional test skip/disable signals")


def prepare_repair(
    work_item: dict[str, Any],
    investigation: dict[str, Any],
    patch: dict[str, Any],
    repo_root: Path,
    contract: dict[str, Any],
) -> dict[str, Any]:
    _validate_work_item(work_item)
    _validate_identity(work_item, investigation, patch)
    if investigation.get("state") != "LOCALIZED":
        raise FixWorkerError("investigation is not LOCALIZED")
    if investigation.get("edit_recommendation") != "ELIGIBLE_FOR_BOUNDED_REPAIR":
        raise FixWorkerError("investigation does not authorize bounded repair")

    source_sha = str(work_item["resolved_sha"]).lower()
    branch = _assert_clean_repair_branch(repo_root, source_sha, contract)
    candidates = _candidate_map(investigation)
    regression_paths = _required_regression_paths(investigation)
    min_confidence = float(contract["candidate_min_confidence"])

    if patch.get("schema_version") != 1:
        raise FixWorkerError("patch_plan schema_version must be 1")
    if patch.get("record_type") != "BOUNDED_REPAIR_PATCH_V60C":
        raise FixWorkerError("patch_plan record_type mismatch")
    attempt = patch.get("attempt_number")
    max_attempts = min(
        int(contract["max_repair_attempts"]),
        int((work_item.get("budgets") or {}).get("max_repair_attempts", 0)),
    )
    if not isinstance(attempt, int) or attempt < 1 or attempt > max_attempts:
        raise FixWorkerError("repair attempt exceeds WorkItem repair budget")
    edits = patch.get("edits")
    if not isinstance(edits, list) or not edits:
        raise FixWorkerError("patch_plan edits must be a non-empty list")

    max_files = min(
        int(contract["max_files"]),
        int((work_item.get("budgets") or {}).get("max_files", 0)),
    )
    if len(edits) > max_files:
        raise FixWorkerError("repair exceeds file budget")

    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_changed_lines = 0

    for raw in edits:
        if not isinstance(raw, dict):
            raise FixWorkerError("patch edit must be an object")
        path = _safe_relative(raw.get("path"))
        if path in seen:
            raise FixWorkerError(f"duplicate patch path: {path}")
        seen.add(path)
        if _protected(path, contract):
            raise FixWorkerError(f"protected path cannot be edited: {path}")

        target = _confined_path(repo_root, path, allow_missing=True)
        exists = target.is_file()
        is_regression = path in regression_paths and _is_test_path(path)
        candidate = candidates.get(path)

        if exists:
            if candidate is None and not is_regression:
                raise FixWorkerError(f"edit path lacks investigator candidate proof: {path}")
            if candidate is not None:
                if str(candidate.get("kind") or "") == "PROTECTED":
                    raise FixWorkerError(f"investigator marked path protected: {path}")
                if float(candidate.get("confidence", 0.0) or 0.0) < min_confidence and not is_regression:
                    raise FixWorkerError(f"candidate confidence below repair threshold: {path}")
            before = target.read_text(encoding="utf-8")
            expected_hash = str(raw.get("before_sha256") or "")
            if expected_hash != _sha256_text(before):
                raise FixWorkerError(f"before_sha256 mismatch: {path}")
            after = _apply_replacements(before, raw.get("replacements") or [], path)
            created = False
        else:
            if not is_regression:
                raise FixWorkerError(
                    f"new file is allowed only for required regression target: {path}"
                )
            if raw.get("before_sha256") not in {None, ""}:
                raise FixWorkerError(f"new file must not declare before_sha256: {path}")
            content = raw.get("create_content")
            if not isinstance(content, str) or not content:
                raise FixWorkerError(f"new regression file requires create_content: {path}")
            before = ""
            after = content
            created = True

        _test_strength_guard(path, before, after, contract, created=created)
        changed_lines = _changed_line_count(before, after)
        if changed_lines < 1:
            raise FixWorkerError(f"repair edit has no material line change: {path}")
        total_changed_lines += changed_lines
        prepared.append(
            {
                "path": path,
                "target": target,
                "before": before,
                "after": after,
                "created": created,
                "changed_lines": changed_lines,
                "before_sha256": _sha256_text(before) if not created else None,
                "after_sha256": _sha256_text(after),
            }
        )

    max_lines = min(
        int(contract["max_changed_lines"]),
        int((work_item.get("budgets") or {}).get("max_changed_lines", 0)),
    )
    if total_changed_lines > max_lines:
        raise FixWorkerError("repair exceeds changed-line budget")

    return {
        "schema_version": 1,
        "record_type": "BOUNDED_REPAIR_PREPARED_V60C",
        "authority": "BOUNDED_WORKSPACE_EDIT_ONLY",
        "repository": work_item["repository"],
        "resolved_sha": source_sha,
        "work_item_id": work_item["work_item_id"],
        "attempt_number": attempt,
        "branch": branch,
        "total_changed_lines": total_changed_lines,
        "files": prepared,
    }


def _status_paths(repo_root: Path) -> set[str]:
    output = _run_git(repo_root, "status", "--porcelain")
    paths: set[str] = set()
    for line in output.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        try:
            paths.add(_safe_relative(path))
        except FixWorkerError:
            continue
    return paths


def apply_prepared(
    prepared: dict[str, Any],
    repo_root: Path,
    *,
    apply: bool,
) -> dict[str, Any]:
    files = prepared["files"]
    public_files = [
        {
            key: value
            for key, value in item.items()
            if key not in {"target", "before", "after"}
        }
        for item in files
    ]
    if not apply:
        return {
            **{key: value for key, value in prepared.items() if key != "files"},
            "state": "VALIDATED_DRY_RUN",
            "files": public_files,
            "commit_performed": False,
            "push_performed": False,
            "merge_performed": False,
            "release_performed": False,
        }

    written: list[dict[str, Any]] = []
    try:
        for item in files:
            target: Path = item["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".applab-repair.tmp")
            temp.write_text(item["after"], encoding="utf-8")
            os.replace(temp, target)
            written.append(item)

        actual = _status_paths(repo_root)
        expected = {item["path"] for item in files}
        if actual != expected:
            raise FixWorkerError(
                f"workspace diff escaped bounded repair set: expected={sorted(expected)} actual={sorted(actual)}"
            )
    except Exception:
        for item in reversed(written):
            target: Path = item["target"]
            if item["created"]:
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
            else:
                target.write_text(item["before"], encoding="utf-8")
        raise

    return {
        **{key: value for key, value in prepared.items() if key != "files"},
        "state": "APPLIED_IN_ISOLATED_WORKSPACE",
        "files": public_files,
        "commit_performed": False,
        "push_performed": False,
        "merge_performed": False,
        "release_performed": False,
        "code_hygiene_required": True,
        "focused_verification_required": True,
    }


def run_worker(
    work_item: dict[str, Any],
    investigation: dict[str, Any],
    patch: dict[str, Any],
    repo_root: Path,
    *,
    apply: bool,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    prepared = prepare_repair(
        work_item, investigation, patch, repo_root.resolve(), contract
    )
    return apply_prepared(prepared, repo_root.resolve(), apply=apply)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        _git(root, "init", "-b", "main")
        _git(root, "config", "user.email", "applab@example.invalid")
        _git(root, "config", "user.name", "AppLab Self Test")
        (root / "lib").mkdir()
        (root / "test").mkdir()
        source = root / "lib/fix.dart"
        test = root / "test/fix_test.dart"
        source.write_text("bool fixed() => false;\n", encoding="utf-8")
        test.write_text("void main() { assert(fixed() == false); }\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-m", "fixture")
        source_sha = _run_git(root, "rev-parse", "HEAD")

        work_item = {
            "schema_version": 1,
            "record_type": "APPLAB_WORK_ITEM",
            "work_item_id": "wrk_fix",
            "operation_id": "op_fix",
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
                "max_files": 5,
                "max_changed_lines": 250,
                "max_repair_attempts": 2,
                "max_agent_actions": 24,
            },
            "acceptance_criteria": ["regression test"],
            "required_evidence": ["exact source identity"],
            "rollback": {"strategy": "restore exact pre-edit bytes"},
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
                    "path": "lib/fix.dart",
                    "kind": "SOURCE",
                    "score": 150,
                    "confidence": 0.95,
                    "signals": [{"kind": "EXACT_DIAGNOSTIC_PATH"}],
                    "paired_tests": ["test/fix_test.dart"],
                }
            ],
            "required_regression_targets": ["test/fix_test.dart"],
        }

        _git(root, "checkout", "-b", "applab-repair/self-test")
        patch = {
            "schema_version": 1,
            "record_type": "BOUNDED_REPAIR_PATCH_V60C",
            "repository": "owner/app",
            "resolved_sha": source_sha,
            "work_item_id": "wrk_fix",
            "attempt_number": 1,
            "edits": [
                {
                    "path": "lib/fix.dart",
                    "before_sha256": _sha256_text(source.read_text(encoding="utf-8")),
                    "replacements": [
                        {
                            "old": "bool fixed() => false;",
                            "new": "bool fixed() => true;",
                            "expected_occurrences": 1,
                        }
                    ],
                },
                {
                    "path": "test/new_regression_test.dart",
                    "before_sha256": "",
                    "create_content": "void main() { assert(true); }\n",
                },
            ],
        }
        investigation["required_regression_targets"].append(
            "test/new_regression_test.dart"
        )

        dry = run_worker(work_item, investigation, patch, root, apply=False)
        assert dry["state"] == "VALIDATED_DRY_RUN"
        assert source.read_text(encoding="utf-8") == "bool fixed() => false;\n"

        weakening = {
            **patch,
            "edits": [
                {
                    "path": "test/fix_test.dart",
                    "before_sha256": _sha256_text(test.read_text(encoding="utf-8")),
                    "replacements": [
                        {
                            "old": "assert(fixed() == false);",
                            "new": "print(fixed());",
                            "expected_occurrences": 1,
                        }
                    ],
                }
            ],
        }
        try:
            run_worker(work_item, investigation, weakening, root, apply=False)
        except FixWorkerError as exc:
            assert "weaken existing test assertion" in str(exc)
        else:
            raise AssertionError("test weakening unexpectedly passed")

        applied = run_worker(work_item, investigation, patch, root, apply=True)
        assert applied["state"] == "APPLIED_IN_ISOLATED_WORKSPACE"
        assert applied["commit_performed"] is False
        assert source.read_text(encoding="utf-8") == "bool fixed() => true;\n"
        assert (root / "test/new_regression_test.dart").is_file()
        assert _status_paths(root) == {
            "lib/fix.dart",
            "test/new_regression_test.dart",
        }

    print("AppLab v6.0C bounded autonomous fix worker self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-item", default="")
    parser.add_argument("--investigation", default="")
    parser.add_argument("--patch-plan", default="")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.work_item or not args.investigation or not args.patch_plan:
        raise SystemExit("--work-item, --investigation and --patch-plan are required")
    report = run_worker(
        _read_json(args.work_item),
        _read_json(args.investigation),
        _read_json(args.patch_plan),
        Path(args.repo_root),
        apply=args.apply,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
