#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_VERSION = "4.0.2"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_version_alignment() -> None:
    backend = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    require(
        f'APP_VERSION = "{EXPECTED_VERSION}"' in backend,
        "backend APP_VERSION is not aligned with AppLab release",
    )
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    require(package.get("version") == EXPECTED_VERSION, "frontend package version drift")
    require(lock.get("version") == EXPECTED_VERSION, "frontend lock version drift")
    require(
        (lock.get("packages") or {}).get("", {}).get("version") == EXPECTED_VERSION,
        "frontend root lock package version drift",
    )
    studio = (ROOT / "scripts/studio_snapshot.py").read_text(encoding="utf-8")
    require(
        f'STUDIO_VERSION = "{EXPECTED_VERSION}"' in studio,
        "Studio snapshot version drift",
    )
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    require(
        f'"version":"{EXPECTED_VERSION}"' in ci,
        "CI backend health assertion version drift",
    )


def check_local_controller_boundary() -> None:
    live = (ROOT / "docker-compose.live.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    require(
        "APPLAB_BIND_HOST: ${APPLAB_BIND_HOST:-127.0.0.1}" in live,
        "Live controller must bind to loopback by default",
    )
    require("APPLAB_BIND_HOST" in dockerfile, "backend bind host must be configurable")
    require(
        "get.maestro.mobile.dev" not in dockerfile,
        "remote curl|bash style Maestro installer is forbidden",
    )
    require("MAESTRO_SHA256" in dockerfile, "Maestro release bytes must be hash-pinned")


def check_actions_pinned() -> None:
    problems: list[str] = []
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.search(r"\buses:\s*([^\s#]+)", line)
            if not match:
                continue
            target = match.group(1)
            if target.startswith("./") or target.startswith("docker://"):
                continue
            if "@" not in target:
                problems.append(f"{path.relative_to(ROOT)}:{number}: missing ref: {target}")
                continue
            ref = target.rsplit("@", 1)[1]
            if not SHA40.fullmatch(ref):
                problems.append(
                    f"{path.relative_to(ROOT)}:{number}: external action is not SHA-pinned: {target}"
                )
    require(not problems, "\n".join(problems))


def check_trusted_review_contract() -> None:
    workflow = (ROOT / ".github/workflows/autonomous-app-review-v31.yml").read_text(
        encoding="utf-8"
    )
    for needle in (
        "lineage_ref:",
        "base_sha:",
        "--lineage-ref",
        "--base-sha",
        "Build Studio snapshot",
        "scripts/studio_snapshot.py",
        "studio.json",
    ):
        require(needle in workflow, f"trusted review missing audit-hardening contract: {needle}")


def check_schema_forwarding() -> None:
    control = (ROOT / "backend/app/control_center.py").read_text(encoding="utf-8")
    studio = (ROOT / "backend/app/studio.py").read_text(encoding="utf-8")
    require(
        "normalized_summary = dict(summary)" in control,
        "Control Center backend must preserve forward-compatible summary fields",
    )
    require(
        "normalized_summary = dict(summary)" in studio,
        "Studio backend must preserve forward-compatible summary fields",
    )


def check_no_floating_self_reference() -> None:
    wrapper = (ROOT / ".github/workflows/verify-flutter.yml").read_text(encoding="utf-8")
    require("@main" not in wrapper, "reusable AppLab wrapper must not float on @main")
    require(
        "uses: ./.github/workflows/external-project-runner.yml" in wrapper,
        "Flutter wrapper must bind to the same AppLab revision",
    )


def main() -> int:
    check_version_alignment()
    check_local_controller_boundary()
    check_actions_pinned()
    check_trusted_review_contract()
    check_schema_forwarding()
    check_no_floating_self_reference()
    print("AppLab audit hardening contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
