#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path
from typing import Any

VERSION = "0.9.0"

def load_plan(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("analysis plan must be an object")
    return payload

def flutter_commands(plan: dict[str, Any], run_tests: bool) -> dict[str, str]:
    lane = str(plan.get("lane", "FULL_RUNTIME"))
    confidence = float(plan.get("confidence", 0))
    scopes = plan.get("static_targets", {}) if isinstance(plan.get("static_targets"), dict) else {}
    analyze_targets = [str(x) for x in scopes.get("flutter_analyze_targets", []) if str(x)]
    test_targets = [str(x) for x in scopes.get("flutter_test_targets", []) if str(x)]

    if lane == "NO_RUNTIME_CHANGE":
        return {"analyze": "", "test": "", "build": ""}
    if confidence >= 0.80 and lane in {"STATIC_ONLY", "FAST_RUNTIME"} and analyze_targets:
        analyze = "dart analyze " + " ".join(shlex.quote(x) for x in analyze_targets)
    else:
        analyze = "flutter analyze"

    test = ""
    if run_tests:
        if confidence >= 0.85 and lane in {"STATIC_ONLY", "FAST_RUNTIME"} and test_targets:
            test = "flutter test " + " ".join(shlex.quote(x) for x in test_targets)
        else:
            test = "flutter test"
    return {"analyze": analyze, "test": test, "build": ""}

def gradle_parts(command: str) -> tuple[str, list[str], list[str]] | None:
    if not command.strip() or any(token in command for token in ("&&", "||", "|", ";", ">", "<")):
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    if not parts:
        return None
    exe = parts[0]
    if not (exe.endswith("gradlew") or exe == "gradle"):
        return None
    tasks: list[str] = []
    options: list[str] = []
    for item in parts[1:]:
        if item.startswith("-"):
            options.append(item)
        else:
            tasks.append(item)
    return exe, tasks, options

def scoped_tasks(tasks: list[str], modules: list[str]) -> list[str]:
    if not modules:
        return tasks
    output: list[str] = []
    for task in tasks:
        if task.startswith(":"):
            output.append(task)
            continue
        for module in modules:
            clean = module.strip("/")
            if clean:
                output.append(f":{clean}:{task}")
    return output or tasks

def native_commands(
    plan: dict[str, Any],
    test_command: str,
    lint_command: str,
    build_command: str,
) -> dict[str, Any]:
    lane = str(plan.get("lane", "FULL_RUNTIME"))
    confidence = float(plan.get("confidence", 0))
    scopes = plan.get("static_targets", {}) if isinstance(plan.get("static_targets"), dict) else {}
    modules = [str(x) for x in scopes.get("android_modules", []) if str(x)]

    if lane == "NO_RUNTIME_CHANGE":
        return {"test": "", "lint": "", "build": "", "batch": "", "batch_safe": False}

    commands = {
        "test": test_command,
        "lint": lint_command,
        "build": "" if lane == "STATIC_ONLY" else build_command,
    }
    if confidence >= 0.82 and lane in {"STATIC_ONLY", "FAST_RUNTIME"} and modules:
        for key in ("test", "lint"):
            parsed = gradle_parts(commands[key])
            if parsed:
                exe, tasks, options = parsed
                commands[key] = shlex.join([exe, *scoped_tasks(tasks, modules), *options])

    parsed = [gradle_parts(commands[k]) for k in ("test", "lint", "build") if commands[k].strip()]
    batch = ""
    batch_safe = False
    if parsed and all(item is not None for item in parsed):
        executables = {item[0] for item in parsed if item}
        if len(executables) == 1:
            exe = next(iter(executables))
            tasks: list[str] = []
            options: list[str] = []
            for item in parsed:
                assert item is not None
                tasks.extend(item[1])
                options.extend(item[2])
            dedup_tasks = list(dict.fromkeys(tasks))
            dedup_options = list(dict.fromkeys(options))
            batch = shlex.join([exe, *dedup_tasks, *dedup_options])
            batch_safe = lane in {"STATIC_ONLY", "FAST_RUNTIME"}

    return {**commands, "batch": batch, "batch_safe": batch_safe}

def self_test() -> None:
    plan = {
        "lane": "FAST_RUNTIME",
        "confidence": 0.92,
        "static_targets": {
            "flutter_analyze_targets": ["lib/features/home"],
            "flutter_test_targets": ["test/features/home/home_test.dart"],
            "android_modules": ["app"],
        },
    }
    flutter = flutter_commands(plan, True)
    assert "lib/features/home" in flutter["analyze"]
    assert "home_test.dart" in flutter["test"]

    native = native_commands(
        plan,
        "./gradlew testDebugUnitTest --stacktrace",
        "./gradlew lintDebug --stacktrace",
        "./gradlew assembleDebug --stacktrace",
    )
    assert ":app:testDebugUnitTest" in native["test"]
    assert native["batch_safe"] and ":app:assembleDebug" in native["batch"]

    full = dict(plan)
    full["lane"] = "FULL_RUNTIME"
    commands = flutter_commands(full, True)
    assert commands["analyze"] == "flutter analyze"
    assert commands["test"] == "flutter test"
    print("AppLab v0.9 Targeted Execution self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan")
    parser.add_argument("--engine", choices=("flutter", "native_android"))
    parser.add_argument("--run-tests", default="true")
    parser.add_argument("--test-command", default="")
    parser.add_argument("--lint-command", default="")
    parser.add_argument("--build-command", default="")
    parser.add_argument("--output")
    parser.add_argument("--github-output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.plan or not args.engine:
        raise SystemExit("--plan and --engine are required")
    plan = load_plan(args.plan)
    if args.engine == "flutter":
        payload = flutter_commands(plan, args.run_tests.lower() in {"1", "true", "yes", "on"})
        payload["build"] = args.build_command
    else:
        payload = native_commands(plan, args.test_command, args.lint_command, args.build_command)
    payload.update({"schema_version": 1, "version": VERSION, "engine": args.engine})
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            for key in ("analyze", "test", "lint", "build", "batch"):
                value = str(payload.get(key, "")).replace("\n", " ")
                handle.write(f"{key}={value}\n")
            handle.write(f"batch_safe={'true' if payload.get('batch_safe') else 'false'}\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
