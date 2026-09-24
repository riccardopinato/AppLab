#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def should_promote(payload: dict) -> tuple[bool, str]:
    result = str(payload.get("result", "UNKNOWN"))
    if result != "PASS":
        return False, f"performance result is {result}"
    return True, "performance gate passed without advisory regressions"


def prepare(
    report_dir: Path,
    baseline_dir: Path,
    repository: str,
    resolved_sha: str,
    run_id: str,
    version: str,
) -> tuple[bool, str]:
    source = report_dir / "performance-lab.json"
    if not source.is_file():
        return False, "performance-lab.json is missing"

    payload = json.loads(source.read_text(encoding="utf-8"))
    promote, reason = should_promote(payload)
    if not promote:
        return False, reason

    if baseline_dir.exists():
        shutil.rmtree(baseline_dir)
    baseline_dir.mkdir(parents=True)

    shutil.copy2(source, baseline_dir / "performance-lab.json")
    metadata = {
        "schema_version": 1,
        "applab_version": version,
        "repository": repository,
        "resolved_sha": resolved_sha,
        "workflow_run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "promotion_policy": "pass-only",
    }
    (baseline_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return True, reason


def self_test() -> None:
    assert should_promote({"result": "PASS"})[0]
    assert not should_promote({"result": "WARN"})[0]
    assert not should_promote({"result": "FAIL"})[0]
    print("AppLab performance baseline self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir")
    parser.add_argument("--baseline-dir")
    parser.add_argument("--repository", default="")
    parser.add_argument("--resolved-sha", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--version", default="0.7.2")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.report_dir or not args.baseline_dir:
        raise SystemExit("--report-dir and --baseline-dir are required")

    promote, reason = prepare(
        Path(args.report_dir),
        Path(args.baseline_dir),
        args.repository,
        args.resolved_sha,
        args.run_id,
        args.version,
    )
    print(
        f"AppLab performance baseline: "
        f"{'PROMOTE' if promote else 'SKIP'} — {reason}"
    )
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"promote={'true' if promote else 'false'}\n")
            handle.write(f"reason={reason}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
