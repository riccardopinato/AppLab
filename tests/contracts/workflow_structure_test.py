#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SHA_ACTION = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def walk_uses(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "uses" and isinstance(child, str):
                found.append(child.strip())
            found.extend(walk_uses(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(walk_uses(child))
    return found


def main() -> int:
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    require(files, "workflow directory must contain workflows")

    for path in files:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        require(isinstance(payload, dict), f"{path.name}: YAML root must be an object")
        require("name" in payload, f"{path.name}: workflow name missing")
        require("on" in payload, f"{path.name}: trigger block missing")
        jobs = payload.get("jobs")
        require(isinstance(jobs, dict) and jobs, f"{path.name}: jobs must be a non-empty object")
        for job_name, job in jobs.items():
            require(isinstance(job, dict), f"{path.name}:{job_name}: job must be an object")
            require(
                "runs-on" in job or "uses" in job,
                f"{path.name}:{job_name}: job must declare runs-on or reusable uses",
            )

        for uses in walk_uses(payload):
            if uses.startswith("./") or uses.startswith("docker://"):
                continue
            require(
                SHA_ACTION.fullmatch(uses) is not None,
                f"{path.name}: external action/workflow must be pinned to a 40-char SHA: {uses}",
            )

    registry = (ROOT / "integration" / "CANONICAL_WORKFLOWS.md").read_text(encoding="utf-8")
    require("verify-flutter.yml" in registry, "public Flutter compatibility wrapper must be classified")
    require("apk-emulator-smoke.yml" in registry, "manual APK diagnostic workflow must be classified")
    require(
        not (WORKFLOWS / "camperboss-16c-build-once.yml").exists(),
        "project-specific one-off workflow must not remain in AppLab core",
    )
    watchlist = json.loads((ROOT / "watchlist.json").read_text(encoding="utf-8"))
    entries = {
        str(item.get("repository", "")).strip(): item
        for item in watchlist.get("repositories", [])
        if isinstance(item, dict) and item.get("enabled", True)
    }
    expected_targets = {
        "riccardopinato/TrailPath",
        "riccardopinato/Battery_Guard",
        "riccardopinato/Notes-Ecosistema",
        "riccardopinato/Send-to-pc",
        "riccardopinato/CamperBoss",
        "riccardopinato/app-fotografia",
        "riccardopinato/Android-Omni-Cleaner",
        "riccardopinato/PDF-Unifier",
        "riccardopinato/FrameLab-Google-AI-Studio",
        "riccardopinato/Agenda-per-Anna",
        "riccardopinato/App-corpo-umano",
        "riccardopinato/TasteAI",
        "riccardopinato/Notification-Control",
        "riccardopinato/Wonderlog",
        "riccardopinato/World-Days",
    }
    require(
        expected_targets <= set(entries),
        f"watchlist missing operational v5.3.5 targets: {sorted(expected_targets - set(entries))}",
    )
    require(
        entries["riccardopinato/CamperBoss"].get("ref") == "main",
        "CamperBoss watcher must track production main rather than a stale release branch",
    )

    target_token = "secrets.APPLAB_TARGET_TOKEN || github.token"
    watcher = (WORKFLOWS / "repo-watcher.yml").read_text(encoding="utf-8")
    require(
        "GITHUB_TOKEN: ${{ github.token }}" in watcher
        and f"APPLAB_TARGET_TOKEN: ${{{{ {target_token} }}}}" in watcher,
        "Repo Watcher must separate AppLab cache auth from private target auth",
    )
    require(
        watcher.count("secrets: inherit") >= 3,
        "Repo Watcher must forward target authentication to all reusable verification runners",
    )
    for runner_name in (
        "universal-project-runner.yml",
        "external-project-runner.yml",
        "external-native-android-runner.yml",
    ):
        runner_text = (WORKFLOWS / runner_name).read_text(encoding="utf-8")
        require(
            "APPLAB_TARGET_TOKEN:" in runner_text and target_token in runner_text,
            f"{runner_name}: private target token contract missing",
        )
        if runner_name != "universal-project-runner.yml":
            require(
                "authenticated_fetch()" in runner_text
                and "credential.helper=!f()" in runner_text,
                f"{runner_name}: private baseline fetch must use ephemeral target credentials",
            )
    universal = (WORKFLOWS / "universal-project-runner.yml").read_text(encoding="utf-8")
    require(
        universal.count("secrets: inherit") >= 2,
        "Universal runner must forward target authentication to Flutter/native child runners",
    )

    wrapper = (WORKFLOWS / "verify-flutter.yml").read_text(encoding="utf-8")
    require("v0.6.3 Unified Flutter Gate" not in wrapper, "public wrapper must not expose stale v0.6.3 naming")

    print(f"AppLab workflow structure contract PASS ({len(files)} workflows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
