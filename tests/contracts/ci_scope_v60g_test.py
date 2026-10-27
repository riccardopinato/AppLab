#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci_scope_v60g.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

spec = importlib.util.spec_from_file_location("ci_scope_v60g", SCRIPT)
assert spec and spec.loader
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


def main() -> int:
    assert scope.classify(["ROADMAP.md"], "pull_request") == scope.DOCS_ONLY
    assert scope.classify(
        ["integration/roadmap/APPLAB_V6_CLOSED_LOOP_AGENTIC_ENGINEERING.md"],
        "pull_request",
    ) == scope.DOCS_ONLY
    assert scope.classify(["README.md", "docs/guide.mdx"], "pull_request") == scope.DOCS_ONLY
    assert scope.classify(["README.md", "scripts/ci_scope_v60g.py"], "pull_request") == scope.FULL
    for protected_doc in scope.FULL_DOC_PATHS:
        assert scope.classify([protected_doc], "pull_request") == scope.FULL
    assert scope.classify([".github/workflows/ci.yml"], "pull_request") == scope.FULL
    assert scope.classify([], "pull_request") == scope.FULL
    assert scope.classify(["README.md"], "push") == scope.FULL

    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Resolve v6.0G CI scope" in text
    assert "scripts/ci_scope_v60g.py" in text
    assert "needs.scope.outputs.mode != 'DOCS_ONLY'" in text
    assert "Docs-only CI fast path" in text
    assert "Docs-only dependency-audit fast path" in text
    assert "fetch-depth: 0" in text
    assert "git diff --no-renames --name-only" in text
    assert "core.whitespace=-blank-at-eol diff --check" in text
    assert "PostgreSQL v5.4B + v5.4E + v5.4F durable schema smoke" in text
    assert "Build backend container" in text
    assert "Build frontend container" in text

    print("AppLab v6.0G CI scope contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
