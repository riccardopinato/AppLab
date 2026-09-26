#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path
from typing import Any

SAFE_TASK = re.compile(r"^:?[A-Za-z0-9_.:-]+$")

def parse_gradle(command: str) -> tuple[str, list[str], list[str]] | None:
    if not command.strip():
        return None
    if any(token in command for token in ("&&", "||", ";", "|", ">", "<", "\n", "\r")):
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    if not parts:
        return None
    launcher = parts[0]
    if launcher not in {"./gradlew", "gradlew", "gradle"}:
        return None
    tasks: list[str] = []
    opts: list[str] = []
    for part in parts[1:]:
        if part.startswith("-"):
            opts.append(part)
        elif SAFE_TASK.fullmatch(part):
            tasks.append(part)
        else:
            return None
    return launcher, tasks, opts

def module_notation(module: str) -> str:
    module = module.strip().strip("/")
    if not module or module == ".":
        return ""
    return ":" + ":".join(p for p in module.split("/") if p)

def valid_module(repo_root: Path, module: str) -> bool:
    if not module or module == ".":
        return False
    root = repo_root / module
    return (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file()

def qualify_task(task: str, module: str) -> str:
    if not module or task.startswith(":"):
        return task
    prefix = module_notation(module)
    return f"{prefix}:{task}" if prefix else task

def build_plan(
    repo_root: Path,
    impact: dict[str, Any],
    test_command: str,
    lint_command: str,
    build_command: str,
) -> dict[str, Any]:
    lane = str(impact.get("lane", "FULL_RUNTIME"))
    run_tests = bool(impact.get("run_tests", True))
    run_static = bool(impact.get("run_static_analysis", True))
    run_build = bool(impact.get("run_build", True))
    modules = [str(x) for x in impact.get("impacted_modules", [])]
    target_module = ""
    if (
        str(impact.get("effective_mode")) == "fast"
        and float(impact.get("confidence", 0)) >= 0.85
        and len(modules) == 1
        and valid_module(repo_root, modules[0])
    ):
        target_module = modules[0]

    commands = {
        "test": test_command if run_tests else "",
        "lint": lint_command if run_static else "",
        "build": build_command if run_build else "",
    }
    parsed = {name: parse_gradle(cmd) if cmd else None for name, cmd in commands.items()}
    active = [(name, value) for name, value in parsed.items() if commands[name]]
    can_combine = bool(active) and all(value is not None for _, value in active)
    launchers = {value[0] for _, value in active if value is not None}
    can_combine = can_combine and len(launchers) == 1

    if not can_combine:
        return {
            "schema_version": 1,
            "lane": lane,
            "combined": False,
            "target_module": target_module,
            "test_command": commands["test"],
            "lint_command": commands["lint"],
            "build_command": commands["build"],
            "combined_command": "",
            "reason": "custom_or_incompatible_commands",
        }

    launcher = next(iter(launchers))
    tasks: list[str] = []
    opts: list[str] = []
    for name in ("test", "lint", "build"):
        value = parsed[name]
        if value is None:
            continue
        _, task_list, option_list = value
        for task in task_list:
            candidate = qualify_task(task, target_module) if name in {"test", "lint"} else task
            if candidate not in tasks:
                tasks.append(candidate)
        for opt in option_list:
            if opt not in opts:
                opts.append(opt)

    combined = " ".join(shlex.quote(x) for x in [launcher, *tasks, *opts])
    return {
        "schema_version": 1,
        "lane": lane,
        "combined": True,
        "target_module": target_module,
        "test_command": "",
        "lint_command": "",
        "build_command": "",
        "combined_command": combined,
        "reason": "single_gradle_task_graph",
    }

def emit(path: Path, plan: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key in ("combined", "target_module", "test_command", "lint_command", "build_command", "combined_command"):
            value = plan.get(key, "")
            if isinstance(value, bool):
                value = str(value).lower()
            handle.write(f"{key}={value}\n")

def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        app = root / "app"
        app.mkdir()
        (app / "build.gradle.kts").write_text("plugins {}\n", encoding="utf-8")
        impact = {
            "lane": "FAST_RUNTIME", "effective_mode": "fast", "confidence": 0.95,
            "impacted_modules": ["app"], "run_tests": True, "run_static_analysis": True, "run_build": True,
        }
        plan = build_plan(root, impact, "./gradlew testDebugUnitTest", "./gradlew lintDebug", "./gradlew assembleDebug")
        assert plan["combined"]
        assert ":app:testDebugUnitTest" in plan["combined_command"]
        assert ":app:lintDebug" in plan["combined_command"]
        assert "assembleDebug" in plan["combined_command"]

        fallback = build_plan(root, impact, "bash test.sh", "./gradlew lintDebug", "./gradlew assembleDebug")
        assert not fallback["combined"]
    print("AppLab native task graph self-test PASS")

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root")
    p.add_argument("--impact-plan")
    p.add_argument("--test-command", default="")
    p.add_argument("--lint-command", default="")
    p.add_argument("--build-command", default="")
    p.add_argument("--output")
    p.add_argument("--github-output")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.repo_root or not args.impact_plan or not args.output:
        raise SystemExit("--repo-root, --impact-plan and --output are required")
    impact = json.loads(Path(args.impact_plan).read_text(encoding="utf-8"))
    plan = build_plan(
        Path(args.repo_root).resolve(), impact,
        args.test_command, args.lint_command, args.build_command,
    )
    Path(args.output).write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.github_output:
        emit(Path(args.github_output), plan)
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
