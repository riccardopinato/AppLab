#!/usr/bin/env python3
"""v6.2A: real diagnostic -> deterministic proposal -> bounded repair attempt."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import live_repair_attempt_v62a as execution
import python_syntax_repair_v62a as proposal


def process(root: Path, db: Path, admission: dict, closed: dict,
            diagnostics: str, publish: bool = False) -> dict:
    triage, plan, diff = proposal.generate(root, diagnostics)
    with tempfile.TemporaryDirectory(prefix="applab-v62a-proposal-") as raw:
        patch = Path(raw) / "candidate.patch"
        patch.write_text(diff, encoding="utf-8")
        return execution.run(root, db, admission, closed, triage, plan,
                             diagnostics, patch, publish=publish)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--closed-loop", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    root = a.repo_root.resolve()
    result = process(root, a.db,
                     json.loads(a.admission.read_text(encoding="utf-8")),
                     json.loads(a.closed_loop.read_text(encoding="utf-8")),
                     a.diagnostics.read_text(encoding="utf-8"), a.publish)
    a.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": result["next"], "promotion_counted": False}))


if __name__ == "__main__":
    main()
