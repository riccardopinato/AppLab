#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shlex
from typing import Any

SAFE_EXECUTABLES = {"./gradlew", "gradlew", "gradle"}


def gradle_project(module: str) -> str:
    raw = module.strip().strip("/")
    if not raw or raw in {".", "lib", "src"}:
        return ""
    parts = [part for part in raw.split("/") if part and part not in {"android"}]
    if not parts or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts):
        return ""
    return ":" + ":".join(parts)


def task_leaf(task: str) -> str:
    return task.rsplit(":", 1)[-1]


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

    projects = sorted({gradle_project(module) for module in modules} - {""})
    targeted_tasks: list[str] = []
    static_parsed = [parse_gradle_command(test_command), parse_gradle_command(lint_command)]
    for parsed_command in static_parsed:
        if parsed_command is None:
            continue
        for original_task in parsed_command[1]:
            leaf = task_leaf(original_task)
            for project in projects:
                candidate = f"{project}:{leaf}"
                if candidate not in targeted_tasks:
                    targeted_tasks.append(candidate)

    if runtime_required:
        build_parsed = parse_gradle_command(build_command)
        if build_parsed is not None:
            for build_task in build_parsed[1]:
                if build_task not in targeted_tasks:
                    targeted_tasks.append(build_task)

    return {
        "safe": True,
        "combined_command": " ".join([executable, *tasks]),
        "targeted_command": " ".join([executable, *targeted_tasks]) if targeted_tasks else "",
        "tasks": tasks,
        "targeted_tasks": targeted_tasks,
        "modules": modules,
        "gradle_projects": projects,
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
            handle.write(f"targeted_command={payload.get('targeted_command','')}\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
