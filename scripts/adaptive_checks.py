#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, shlex, subprocess, tempfile, time
from pathlib import Path
from typing import Any

def run(cmd: list[str], cwd: Path, log: Path) -> tuple[str,float]:
    start=time.perf_counter()
    with log.open("w",encoding="utf-8") as out:
        p=subprocess.run(cmd,cwd=cwd,stdout=out,stderr=subprocess.STDOUT,check=False)
    return ("PASS" if p.returncode==0 else "FAIL", round(time.perf_counter()-start,3))

def shell(command: str, cwd: Path, log: Path) -> tuple[str,float]:
    start=time.perf_counter()
    with log.open("w",encoding="utf-8") as out:
        p=subprocess.run(["bash","-Eeuo","pipefail","-c",command],cwd=cwd,stdout=out,stderr=subprocess.STDOUT,check=False)
    return ("PASS" if p.returncode==0 else "FAIL", round(time.perf_counter()-start,3))

SAFE_GRADLE_FLAGS = {
    "--stacktrace", "--full-stacktrace", "--info", "--debug", "--quiet",
    "--warn", "--no-daemon", "--offline", "--refresh-dependencies",
    "--scan", "--no-scan", "--continue", "--rerun-tasks", "--parallel",
    "--no-parallel", "--configure-on-demand", "--no-configure-on-demand",
}

def gradle_parts(command: str) -> tuple[str,list[str],list[str]]|None:
    try:
        parts=shlex.split(command)
    except ValueError:
        return None
    if not parts or Path(parts[0]).name not in {"gradlew","gradle"}:
        return None
    exe=parts[0]
    tasks:list[str]=[]
    flags:list[str]=[]
    for token in parts[1:]:
        if token.startswith("-"):
            # Only reorder flags that are known to be standalone. Options such
            # as "-p android" or "--project-dir android" carry a positional
            # argument, so combining/reordering them is unsafe.
            if token not in SAFE_GRADLE_FLAGS:
                return None
            flags.append(token)
        else:
            tasks.append(token)
    return exe,tasks,flags

def module_tasks(
    project: Path,
    commands: list[str],
    modules: list[str],
    safe: bool,
    build_command: str = "",
) -> list[str]|None:
    raw_commands=[command for command in commands if command.strip()]
    parsed=[gradle_parts(command) for command in raw_commands]
    if not parsed or any(item is None for item in parsed):
        return None
    executables={item[0] for item in parsed if item}
    if len(executables)!=1:
        return None

    scoped_module = ""
    if safe and len(modules)==1:
        candidate=modules[0]
        if (project/candidate/"build.gradle").is_file() or (project/candidate/"build.gradle.kts").is_file():
            scoped_module=candidate

    tasks:list[str]=[]
    flags:list[str]=[]
    normalized_build=build_command.strip()
    for command,item in zip(raw_commands,parsed):
        assert item
        is_application_build=bool(normalized_build) and command.strip()==normalized_build
        for task in item[1]:
            if scoped_module and not is_application_build and ":" not in task:
                tasks.append(f":{scoped_module}:{task}")
            else:
                # The configured APK-producing task stays at its original scope.
                # Prefixing it with a changed library module could skip :app.
                tasks.append(task)
        flags.extend(item[2])
    return [next(iter(executables)),*dict.fromkeys(tasks),*dict.fromkeys(flags)]

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--plan"); ap.add_argument("--engine")
    ap.add_argument("--project-dir"); ap.add_argument("--repo-root",default=""); ap.add_argument("--report-dir")
    ap.add_argument("--test-command",default=""); ap.add_argument("--lint-command",default="")
    ap.add_argument("--build-command",default=""); ap.add_argument("--github-output",default=""); ap.add_argument("--skip-quality",action="store_true")
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:
        assert gradle_parts("./gradlew testDebugUnitTest --stacktrace")
        assert gradle_parts("./gradlew -p android test") is None
        assert gradle_parts("./gradlew --project-dir android test") is None
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw)
            (root/"feature").mkdir()
            (root/"feature"/"build.gradle.kts").write_text("plugins {}\n", encoding="utf-8")
            combined=module_tasks(
                root,
                ["./gradlew testDebugUnitTest", "./gradlew lintDebug", "./gradlew assembleDebug"],
                ["feature"],
                True,
                "./gradlew assembleDebug",
            )
            assert combined is not None
            assert ":feature:testDebugUnitTest" in combined
            assert ":feature:lintDebug" in combined
            assert "assembleDebug" in combined
            assert ":feature:assembleDebug" not in combined
        print("AppLab adaptive checks self-test PASS"); return 0
    if not all((args.plan,args.engine,args.project_dir,args.report_dir)):
        raise SystemExit("--plan, --engine, --project-dir and --report-dir are required")
    plan=json.loads(Path(args.plan).read_text(encoding="utf-8"))
    project=Path(args.project_dir).resolve(); report=Path(args.report_dir).resolve(); report.mkdir(parents=True,exist_ok=True)
    repo_root=Path(args.repo_root).resolve() if args.repo_root else project
    try:
        prefix=project.relative_to(repo_root).as_posix()
    except ValueError:
        prefix="."
    def local_path(value:str)->str:
        value=value.replace("\\","/")
        return value[len(prefix)+1:] if prefix not in {"",".","./"} and value.startswith(prefix+"/") else value
    lane=plan["lane"]; risk=int(plan.get("risk_score",100)); confidence=float(plan.get("confidence",0))
    out: dict[str,Any]={"schema_version":1,"lane":lane,"engine":args.engine,
        "analyze":"NOT_RUN","lint":"NOT_RUN","unit_tests":"NOT_RUN","build":"NOT_RUN","timings":{}}
    if lane=="NO_RUNTIME_CHANGE":
        pass
    elif args.engine=="flutter":
        full=lane in {"FULL_RUNTIME","CERTIFICATION"} or risk>=55 or confidence<0.8
        analyze_targets=[local_path(p) for p in plan.get("targets",{}).get("dart_analyze",[])]
        analyze_targets=[p for p in analyze_targets if (project/p).is_file()]
        test_targets=[local_path(p) for p in plan.get("targets",{}).get("dart_tests",[])]
        test_targets=[p for p in test_targets if (project/p).is_file()]
        changed_tests=[local_path(p) for p in plan.get("changed_files",[]) if p.endswith("_test.dart")]
        changed_tests=[p for p in changed_tests if (project/p).is_file()]
        if not args.skip_quality:
            analyze_cmd=["flutter","analyze"] if full or not analyze_targets else ["dart","analyze",*analyze_targets]
            out["analyze"],out["timings"]["analyze_seconds"]=run(analyze_cmd,project,report/"adaptive-analyze.txt")
            if out["analyze"]=="FAIL": raise SystemExit(1)
            tests=list(dict.fromkeys(changed_tests+test_targets))
            if full:
                test_cmd=["flutter","test"]
            elif tests:
                test_cmd=["flutter","test",*tests]
            elif lane == "FAST_RUNTIME":
                # A runtime change without a provably safe mirrored test target
                # must retain the previous full-suite safety net.
                test_cmd=["flutter","test"]
            else:
                test_cmd=[]
            if test_cmd:
                out["unit_tests"],out["timings"]["test_seconds"]=run(test_cmd,project,report/"adaptive-test.txt")
                if out["unit_tests"]=="FAIL": raise SystemExit(1)
        if plan.get("run_build") and args.build_command:
            out["build"],out["timings"]["build_seconds"]=shell(args.build_command,project,report/"adaptive-build.txt")
            if out["build"]=="FAIL": raise SystemExit(1)
    else:
        commands=[]
        if args.test_command: commands.append(args.test_command)
        if args.lint_command: commands.append(args.lint_command)
        if plan.get("run_build") and args.build_command: commands.append(args.build_command)
        safe_target=lane=="FAST_RUNTIME" and risk<45 and confidence>=0.85
        local_changed=[local_path(p) for p in plan.get("changed_files",[])]
        modules=sorted({p.split("/",1)[0] for p in local_changed if "/" in p and (project/p.split("/",1)[0]).is_dir()})
        combined=module_tasks(
            project,
            commands,
            modules,
            safe_target,
            args.build_command if plan.get("run_build") else "",
        )
        start=time.perf_counter()
        if combined:
            status,_=run(combined,project,report/"adaptive-gradle.txt")
        else:
            status="PASS"
            for idx,cmd in enumerate(commands):
                status,_=shell(cmd,project,report/f"adaptive-gradle-{idx}.txt")
                if status=="FAIL": break
        out["timings"]["gradle_seconds"]=round(time.perf_counter()-start,3)
        if status=="FAIL": raise SystemExit(1)
        out["unit_tests"]="PASS" if args.test_command else "NOT_RUN"
        out["lint"]="PASS" if args.lint_command else "NOT_RUN"
        out["build"]="PASS" if plan.get("run_build") and args.build_command else "NOT_RUN"
    path=report/"adaptive-quality.json"; path.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    if args.github_output:
        with Path(args.github_output).open("a",encoding="utf-8") as h:
            for k in ("analyze","lint","unit_tests","build"): h.write(f"{k}={out[k]}\n")
    print(json.dumps(out,indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
