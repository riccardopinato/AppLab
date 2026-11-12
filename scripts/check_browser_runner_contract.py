#!/usr/bin/env python3
"""Fail-closed AppLab runner/Playwright compatibility guard (X10-018).

Policy is intentionally narrow: Playwright 1.55.0 is known compatible
with Ubuntu 24.04 in this repository's exact-head Browser E2E run.
A future browser or OS upgrade requires a reviewed matrix change.
This check never replaces Browser E2E or validates Android device behavior.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

RUNNER = "ubuntu-24.04"
PLAYWRIGHT = "1.55.0"


class RunnerCompatibilityError(ValueError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise RunnerCompatibilityError(code)


def check_contract(workflow: str, package: dict) -> dict[str, str]:
    require(isinstance(workflow, str) and isinstance(package, dict),
            "INVALID_INPUT")
    # Match the exact job, not the scope job running on ubuntu-latest.
    job = re.search(r"(?m)^  live-browser-e2e:\s*\n(?P<job>(?:^    .*(?:\n|$)|^\s*\n)*)", workflow)
    require(job is not None, "BROWSER_JOB_MISSING")
    block = job.group("job")
    require(re.search(r"(?m)^    runs-on: ubuntu-24\.04\s*$", block) is not None,
            "UNSUPPORTED_BROWSER_RUNNER")
    require(re.search(r"(?m)^    needs: scope\s*$", block) is not None
            and re.search(r"(?m)^    if: github\.event_name != 'pull_request' \|\| needs\.scope\.outputs\.run == 'true'\s*$", block) is not None,
            "REQUIRED_SCOPE_GATE_CHANGED")
    require(re.search(r"(?m)^      - name: Browser WebRTC video and input E2E\s*$", block) is not None
            and re.search(r"(?m)^        run: npm test\s*$", block) is not None,
            "BROWSER_E2E_REMOVED")
    version = package.get("devDependencies", {}).get("@playwright/test") if isinstance(package.get("devDependencies"), dict) else None
    require(version == PLAYWRIGHT, "PLAYWRIGHT_VERSION_REQUIRES_REVIEW")
    return {"runner": RUNNER, "playwright": PLAYWRIGHT,
            "evidence_kind": "RUNNER_CONFIGURATION_PREFLIGHT_ONLY"}


def check_host(os_release: str) -> None:
    require(isinstance(os_release, str), "MISSING_HOST_RELEASE")
    found = {}
    for line in os_release.splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        found[key] = value.strip().strip('"').strip("'")
    require(found.get("ID") == "ubuntu" and found.get("VERSION_ID") == "24.04",
            "UNSUPPORTED_HOST_RELEASE")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", type=Path,
                        default=Path(".github/workflows/live-emulator-self-test.yml"))
    parser.add_argument("--package", type=Path,
                        default=Path("frontend/e2e/package.json"))
    parser.add_argument("--os-release", type=Path, default=Path("/etc/os-release"))
    parser.add_argument("--static-only", action="store_true")
    args = parser.parse_args()
    details = check_contract(args.workflow.read_text(encoding="utf-8"),
                             json.loads(args.package.read_text(encoding="utf-8")))
    if not args.static_only:
        check_host(args.os_release.read_text(encoding="utf-8"))
    print(json.dumps({**details,
                      "host_verified": not args.static_only,
                      "browser_e2e_executed": False},
                     sort_keys=True))


if __name__ == "__main__":
    main()
