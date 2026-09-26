#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, shlex, subprocess, time
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

def gradle_parts(command: str) -> tuple[str,list[str],list[str]]|None:
    try: parts=shlex.split(command)
    except ValueError: return None
    if not parts or Path(parts[0]).name not in {"gradlew","gradle"}: return None
    exe=parts[0]; tasks=[]; flags=[]
    for token in parts[1:]:
        (flags if token.startswith("-") else tasks).append(token)
    return exe,tasks,flags

def module_tasks(project: Path, commands: list[str], modules: list[str], safe: bool) -> list[str]|None:
    parsed=[gradle_parts(c) for c in commands if c.strip()]
    if not parsed or any(x is None for x in parsed): return None
    executables={x[0] for x in parsed if x}
    if len(executables)!=1: return None
    tasks=[]; flags=[]
    for item in parsed:
        assert item
        tasks.extend(item[1]); flags.extend(item[2])
    tasks=list(dict.fromkeys(tasks)); flags=list(dict.fromkeys(flags))
    if safe and len(modules)==1:
        module=modules[0]
        if (project/module/"build.gradle").is_file() or (project/module/"build.gradle.kts").is_file():
            tasks=[t if ":" in t else f":{module}:{t}" for t in tasks]
    return [next(iter(executables)),*tasks,*flags]

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--plan",required=True); ap.add_argument("--engine",required=True)
    ap.add_argument("--project-dir",required=True); ap.add_argument("--report-dir",required=True)
    ap.add_argument("--test-command",default=""); ap.add_argument("--lint-command",default="")
    ap.add_argument("--build-command",default=""); ap.add_argument("--github-output",default="")
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:
        assert gradle_parts("./gradlew testDebugUnitTest --stacktrace")
        print("AppLab adaptive checks self-test PASS"); return 0
    plan=json.loads(Path(args.plan).read_text(encoding="utf-8"))
    project=Path(args.project_dir).resolve(); report=Path(args.report_dir).resolve(); report.mkdir(parents=True,exist_ok=True)
    lane=plan["lane"]; risk=int(plan.get("risk_score",100)); confidence=float(plan.get("confidence",0))
    out: dict[str,Any]={"schema_version":1,"lane":lane,"engine":args.engine,
        "analyze":"NOT_RUN","lint":"NOT_RUN","unit_tests":"NOT_RUN","build":"NOT_RUN","timings":{}}
    if lane=="NO_RUNTIME_CHANGE":
        pass
    elif args.engine=="flutter":
        full=lane in {"FULL_RUNTIME","CERTIFICATION"} or risk>=55 or confidence<0.8
        analyze_targets=[p for p in plan.get("targets",{}).get("dart_analyze",[]) if (project/p).is_file()]
        test_targets=[p for p in plan.get("targets",{}).get("dart_tests",[]) if (project/p).is_file()]
        changed_tests=[p for p in plan.get("changed_files",[]) if p.endswith("_test.dart") and (project/p).is_file()]
        analyze_cmd=["flutter","analyze"] if full or not analyze_targets else ["dart","analyze",*analyze_targets]
        out["analyze"],out["timings"]["analyze_seconds"]=run(analyze_cmd,project,report/"adaptive-analyze.txt")
        if out["analyze"]=="FAIL": raise SystemExit(1)
        tests=list(dict.fromkeys(changed_tests+test_targets))
        if full:
            test_cmd=["flutter","test"]
        elif tests:
            test_cmd=["flutter","test",*tests]
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
        combined=module_tasks(project,commands,plan.get("targets",{}).get("gradle_modules",[]),safe_target)
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
