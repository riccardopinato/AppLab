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
    all_entries = {
        str(item.get("repository", "")).strip(): item
        for item in watchlist.get("repositories", [])
        if isinstance(item, dict)
    }
    entries = {
        repository: item
        for repository, item in all_entries.items()
        if item.get("enabled", True)
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
        "riccardopinato/Agenda-per-Anna",
        "riccardopinato/App-corpo-umano",
        "riccardopinato/TasteAI",
        "riccardopinato/Notification-Control",
        "riccardopinato/Wonderlog",
        "riccardopinato/World-Days",
    }
    require(
        expected_targets <= set(entries),
        f"watchlist missing current operational targets: {sorted(expected_targets - set(entries))}",
    )
    inventory_only = {
        "riccardopinato/FrameLab-Google-AI-Studio":
            "PRIVATE_INTENTIONALLY_OUT_OF_SCOPE",
        "riccardopinato/Cozy-game-nome-da-scegliere-":
            "NO_EXECUTABLE_ANDROID_OR_FLUTTER_PROJECT",
        "riccardopinato/Neon-arcade-runner":
            "UNSUPPORTED_CAPACITOR_VITE_RUNTIME",
    }
    for repository, reason in inventory_only.items():
        require(repository in all_entries, f"watchlist inventory missing {repository}")
        require(
            all_entries[repository].get("enabled") is False
            and all_entries[repository].get("exclusion_reason") == reason,
            f"{repository}: inventory-only exclusion contract drifted",
        )

    public_targets = {
        "riccardopinato/app-fotografia",
        "riccardopinato/PDF-Unifier",
        "riccardopinato/App-corpo-umano",
    }
    for repository in public_targets:
        require(
            "requires_target_token" not in entries[repository],
            f"{repository}: public watcher target must not require APPLAB_TARGET_TOKEN",
        )
    require(
        not any(item.get("requires_target_token") is True for item in entries.values()),
        "current enabled watcher inventory must not require private target credentials",
    )
    require(
        entries["riccardopinato/CamperBoss"].get("ref") == "main",
        "CamperBoss watcher must track production main rather than a stale release branch",
    )

    target_token = "secrets.APPLAB_TARGET_TOKEN || github.token"
    watcher = (WORKFLOWS / "repo-watcher.yml").read_text(encoding="utf-8")
    require(
        "GITHUB_TOKEN: ${{ github.token }}" in watcher
        and "APPLAB_TARGET_TOKEN: ${{ secrets.APPLAB_TARGET_TOKEN }}" in watcher,
        "Repo Watcher must expose whether private target auth is actually configured",
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
        if runner_name == "external-native-android-runner.yml":
            require(
                'PREVIEW_PLATFORM="platforms;android-${{ inputs.compile_sdk }}.0"' in runner_text
                and '"$SDKMANAGER" --channel=3' in runner_text
                and '"$PREVIEW_PLATFORM"' in runner_text,
                "native runner must retry the versioned preview SDK package for preview compileSdk",
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
