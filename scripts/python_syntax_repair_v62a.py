#!/usr/bin/env python3
"""Limited generator: actual Python SyntaxError, no arbitrary code synthesis."""
from __future__ import annotations
import difflib
import re
import subprocess
from pathlib import Path

PATTERN = re.compile(r'File "(?:[^"]*/)?(?P<path>scripts/[\w/-]+\.py)", line (?P<line>\d+)')
BLOCK = re.compile(r'^\s*(?:def|async def|class|if|for|while|with)\b')

class NotRepairable(ValueError):
    pass

def generate(root: Path, log: str) -> tuple[dict, dict, str]:
    matches = {(m["path"], int(m["line"])) for m in PATTERN.finditer(log)}
    if "SyntaxError: expected ':'" not in log or len(matches) != 1:
        raise NotRepairable("NO_UNAMBIGUOUS_REAL_SYNTAX_FAILURE")
    path, line = next(iter(matches))
    file = (root / path).resolve()
    if not file.is_relative_to(root.resolve()) or not file.is_file():
        raise NotRepairable("INVALID_PATH")
    tracked = subprocess.check_output(["git", "ls-files", "--", path], cwd=root, text=True)
    if path not in tracked.splitlines():
        raise NotRepairable("NOT_TRACKED")
    old = file.read_text(encoding="utf-8")
    if not old.endswith("\n"):
        raise NotRepairable("UNTERMINATED_SOURCE_UNSUPPORTED")
    try:
        compile(old, path, "exec")
    except SyntaxError as err:
        if err.msg != "expected ':'" or err.lineno != line:
            raise NotRepairable("DIAGNOSTIC_NOT_REPRODUCED") from err
    else:
        raise NotRepairable("NO_FAILURE")
    lines = old.splitlines(keepends=True)
    current = lines[line - 1]
    raw = current.rstrip("\r\n")
    if not BLOCK.match(raw) or raw.rstrip().endswith(":") or "#" in raw:
        raise NotRepairable("AMBIGUOUS_CHANGE")
    lines[line - 1] = raw.rstrip() + ":" + current[len(raw):]
    fixed = "".join(lines)
    compile(fixed, path, "exec")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    triage = {"repository": "riccardopinato/AppLab", "resolved_sha": sha,
              "classification": "BUILD_OR_QUALITY_FAILURE",
              "root_cause_hypotheses": [f"{path}:{line} missing colon"],
              "required_regression_evidence": [path]}
    plan = {"repository": "riccardopinato/AppLab", "head_sha": sha,
            "changed_files": [path], "analysis_truncated": False}
    body = "".join(difflib.unified_diff(
        old.splitlines(keepends=True), fixed.splitlines(keepends=True),
        fromfile="a/" + path, tofile="b/" + path))
    return triage, plan, f"diff --git a/{path} b/{path}\n" + body
