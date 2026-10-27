#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import PurePosixPath

DOC_SUFFIXES = {".md", ".mdx"}
FULL_DOC_PATHS = {
    "integration/CANONICAL_WORKFLOWS.md",
    "integration/hardening/TECHNICAL_HARDENING_V531.md",
    "integration/hardening/EVIDENCE_SCHEMA_REGISTRY_V534.md",
    "integration/performance/MULTI_PROJECT_DELTA_CALIBRATION_V535.md",
    "integration/review/VIRTUAL_PRODUCT_REVIEW_COUNCIL_V53.md",
}
DOCS_ONLY = "DOCS_ONLY"
FULL = "FULL"


def normalize_path(raw: str) -> str | None:
    value = raw.strip().replace("\\", "/")
    if not value or value.startswith("/"):
        return None
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def classify(paths: list[str], event_name: str) -> str:
    if event_name != "pull_request":
        return FULL

    normalized = [normalize_path(item) for item in paths]
    if not normalized or any(item is None for item in normalized):
        return FULL

    if any(item in FULL_DOC_PATHS for item in normalized if item):
        return FULL

    if all(PurePosixPath(item).suffix.lower() in DOC_SUFFIXES for item in normalized if item):
        return DOCS_ONLY
    return FULL


def self_test() -> None:
    assert classify(["README.md", "integration/roadmap/PLAN.mdx"], "pull_request") == DOCS_ONLY
    assert classify(["ROADMAP.md", "scripts/tool.py"], "pull_request") == FULL
    assert classify(["integration/CANONICAL_WORKFLOWS.md"], "pull_request") == FULL
    assert classify(["integration/hardening/EVIDENCE_SCHEMA_REGISTRY_V534.md"], "pull_request") == FULL
    assert classify([".github/workflows/ci.yml"], "pull_request") == FULL
    assert classify([], "pull_request") == FULL
    assert classify(["../README.md"], "pull_request") == FULL
    assert classify(["README.md"], "push") == FULL


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--paths-file")
    parser.add_argument("--github-output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        print("AppLab v6.0G CI scope self-test PASS")
        return 0

    if not args.paths_file:
        raise SystemExit("--paths-file is required unless --self-test is used")

    with open(args.paths_file, encoding="utf-8") as handle:
        paths = [line.rstrip("\n") for line in handle]

    mode = classify(paths, args.event)
    print(mode)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"mode={mode}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
