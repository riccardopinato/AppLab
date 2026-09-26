#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shlex
from typing import Any

SAFE_EXECUTABLES = {"./gradlew", "gradlew", "gradle"}


def parse_gradle_command(raw: str) -> tuple[str, list[str]] | None:
    if not raw.strip() or any(token in raw for token in ("&&", "||", ";", "|", ">", "<", "\n", "\r")):
        return None
    try:
        parts = shlex.split(raw)
    except ValueError:
        return None
    if not parts or parts[0] not in SAFE_EXECUTABLES:
        return None
    executable = parts[0]
    tasks: list[str] = []
    for item in parts[1:]:
        if item.startswith("-"):
            continue
        if not re.fullmatch(r"[:A-Za-z0-9_.-]+", item):
            return None
        tasks.append(item)
    return (executable, tasks) if tasks else None


def plan(test_command: str, lint_command: str, build_command: str, modules: list[str], runtime_required: bool) -> dict[str, Any]:
    parsed = [
        parse_gradle_command(test_command),
        parse_gradle_command(lint_command),
        parse_gradle_command(build_command) if runtime_required else None,
    ]
    required = [item for item in parsed if item is not None]
    if not required:
        return {
            "safe": False,
            "combined_command": "",
            "tasks": [],
            "modules": modules,
            "reason": "no safely parseable Gradle commands",
        }
    executables = {item[0] for item in required}
    if len(executables) != 1:
        return {
            "safe": False,
            "combined_command": "",
            "tasks": [],
            "modules": modules,
            "reason": "Gradle commands use different executables",
        }

    tasks: list[str] = []
    for _, current in required:
        for task in current:
            if task not in tasks:
                tasks.append(task)
    executable = next(iter(executables))
    return {
        "safe": True,
        "combined_command": " ".join([executable, *tasks]),
        "tasks": tasks,
        "modules": modules,
        "reason": "single Gradle task graph reuses configuration and build outputs",
    }


def self_test() -> None:
    payload = plan(
        "./gradlew testDebugUnitTest --stacktrace",
        "./gradlew lintDebug --stacktrace",
        "./gradlew assembleDebug --stacktrace",
        ["app"],
        True,
    )
    assert payload["safe"]
    assert payload["tasks"] == ["testDebugUnitTest", "lintDebug", "assembleDebug"]
    assert parse_gradle_command("bash custom.sh") is None
    assert parse_gradle_command("./gradlew test && rm -rf x") is None
    print("AppLab Gradle execution planner self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-command", default="")
    parser.add_argument("--lint-command", default="")
    parser.add_argument("--build-command", default="")
    parser.add_argument("--modules-json", default="[]")
    parser.add_argument("--runtime-required", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    modules = json.loads(args.modules_json)
    if not isinstance(modules, list):
        raise SystemExit("--modules-json must be an array")
    payload = plan(
        args.test_command,
        args.lint_command,
        args.build_command,
        [str(item) for item in modules],
        args.runtime_required,
    )
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"safe={str(bool(payload['safe'])).lower()}\n")
            handle.write(f"combined_command={payload['combined_command']}\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
