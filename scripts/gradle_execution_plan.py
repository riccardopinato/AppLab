#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

META = set("|;&><")

def parse(command: str) -> tuple[str, list[str], list[str]] | None:
    raw = command.strip()
    if not raw or any(ch in raw for ch in META):
        return None
    try:
        parts = shlex.split(raw)
    except ValueError:
        return None
    if not parts:
        return None
    exe = parts[0]
    if not (exe.endswith("gradlew") or exe.endswith("gradle") or exe == "gradle"):
        return None
    tasks: list[str] = []
    options: list[str] = []
    for item in parts[1:]:
        if item.startswith("-"):
            options.append(item)
        else:
            tasks.append(item)
    if not tasks:
        return None
    return exe, tasks, options

def qualify(task: str, modules: list[str]) -> list[str]:
    if ":" in task or not modules:
        return [task]
    values = []
    for module in modules:
        module = module.strip("./").replace("/", ":")
        if module and module not in {"lib", "src"}:
            values.append(f":{module}:{task}")
    return values or [task]

def build(test: str, lint: str, build_cmd: str, plan: dict) -> dict:
    parsed = [parse(x) for x in (test, lint, build_cmd) if x.strip()]
    if not parsed or any(x is None for x in parsed):
        return {"combined": False, "command": "", "reason": "commands are not safely combinable"}
    rows = [x for x in parsed if x is not None]
    executables = {row[0] for row in rows}
    if len(executables) != 1:
        return {"combined": False, "command": "", "reason": "different Gradle executables"}

    low_risk_targeting = (
        str(plan.get("lane")) == "FAST_RUNTIME"
        and str(plan.get("risk", {}).get("level")) == "LOW"
        and float(plan.get("confidence", 0)) >= 0.90
    )
    modules = plan.get("static_plan", {}).get("native_modules", []) if low_risk_targeting else []
    modules = [str(x) for x in modules if str(x) not in {"", "."}]

    tasks: list[str] = []
    options: list[str] = []
    for _, row_tasks, row_options in rows:
        for task in row_tasks:
            for candidate in qualify(task, modules):
                if candidate not in tasks:
                    tasks.append(candidate)
        for option in row_options:
            if option not in options:
                options.append(option)

    command = shlex.join([rows[0][0], *tasks, *options])
    return {
        "combined": True,
        "command": command,
        "targeted_modules": modules,
        "reason": "module-targeted task graph" if modules else "single Gradle task graph",
    }

def self_test() -> None:
    plan = {"lane":"FAST_RUNTIME","risk":{"level":"LOW"},"confidence":0.98,"static_plan":{"native_modules":["app"]}}
    out = build("./gradlew testDebugUnitTest --stacktrace", "./gradlew lintDebug --stacktrace", "./gradlew assembleDebug --stacktrace", plan)
    assert out["combined"]
    assert ":app:testDebugUnitTest" in out["command"]
    assert ":app:assembleDebug" in out["command"]
    full = build("./gradlew testDebugUnitTest", "./gradlew lintDebug", "./gradlew assembleDebug", {"lane":"FULL_RUNTIME","risk":{"level":"HIGH"},"confidence":1,"static_plan":{"native_modules":["app"]}})
    assert " :app:" not in full["command"]
    unsafe = build("./gradlew test | tee x", "", "./gradlew assembleDebug", plan)
    assert not unsafe["combined"]
    print("AppLab Gradle execution planner self-test PASS")

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--test-command",default="")
    parser.add_argument("--lint-command",default="")
    parser.add_argument("--build-command",required=False,default="")
    parser.add_argument("--analysis-plan")
    parser.add_argument("--output")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        self_test(); return 0
    if not args.analysis_plan or not args.output:
        raise SystemExit("--analysis-plan and --output are required")
    plan=json.loads(Path(args.analysis_plan).read_text(encoding="utf-8"))
    payload=build(args.test_command,args.lint_command,args.build_command,plan)
    Path(args.output).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(payload,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
