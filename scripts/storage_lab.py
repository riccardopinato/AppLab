#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")

@dataclass
class Finding:
    severity: str
    code: str
    message: str
    evidence: dict[str, Any]

def run(*args: str, timeout: int = 30, binary: bool = False):
    return subprocess.run(
        list(args),
        text=not binary,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if not binary else subprocess.PIPE,
        timeout=timeout,
        check=False,
    )

def adb(*args: str, timeout: int = 30):
    return run("adb", *args, timeout=timeout)

def load_config(path: Path | None) -> dict[str, Any]:
    defaults = {
        "schema_version": 1,
        "enabled": True,
        "required": False,
        "settle_seconds": 1.5,
        "max_files": 200,
        "max_file_bytes": 10 * 1024 * 1024,
        "minimum_free_mb": 128,
        "stable_path_regex": [],
        "required_path_regex": [],
        "expected_text_regex": [],
        "forbidden_text_regex": [],
    }
    if path is None or not path.is_file():
        return defaults
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("storage integrity config must be an object")
    if int(payload.get("schema_version", 1)) != 1:
        raise ValueError("unsupported storage integrity config schema")
    allowed = set(defaults)
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown storage integrity keys: {sorted(unknown)}")
    settle = float(payload.get("settle_seconds", defaults["settle_seconds"]))
    max_files = int(payload.get("max_files", defaults["max_files"]))
    max_file_bytes = int(payload.get("max_file_bytes", defaults["max_file_bytes"]))
    minimum_free_mb = int(payload.get("minimum_free_mb", defaults["minimum_free_mb"]))
    if not 0.5 <= settle <= 15:
        raise ValueError("settle_seconds must be between 0.5 and 15")
    if not 1 <= max_files <= 1000:
        raise ValueError("max_files must be between 1 and 1000")
    if not 1024 <= max_file_bytes <= 50 * 1024 * 1024:
        raise ValueError("max_file_bytes must be between 1024 and 52428800")
    if not 0 <= minimum_free_mb <= 10240:
        raise ValueError("minimum_free_mb must be between 0 and 10240")
    def regex_list(name: str) -> list[str]:
        raw = payload.get(name, [])
        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            raise ValueError(f"{name} must be a list of strings")
        if len(raw) > 30:
            raise ValueError(f"{name} supports at most 30 expressions")
        for value in raw:
            if len(value) > 300:
                raise ValueError(f"{name} expression is too long")
            re.compile(value)
        return raw
    return {
        "schema_version": 1,
        "enabled": bool(payload.get("enabled", True)),
        "required": bool(payload.get("required", False)),
        "settle_seconds": settle,
        "max_files": max_files,
        "max_file_bytes": max_file_bytes,
        "minimum_free_mb": minimum_free_mb,
        "stable_path_regex": regex_list("stable_path_regex"),
        "required_path_regex": regex_list("required_path_regex"),
        "expected_text_regex": regex_list("expected_text_regex"),
        "forbidden_text_regex": regex_list("forbidden_text_regex"),
    }

def pid_of(package_id: str) -> str:
    r=adb("shell","pidof",package_id,timeout=10)
    return r.stdout.strip().split()[0] if r.stdout.strip() else ""

def wait_for_pid(package_id: str, timeout: float=15.0) -> str:
    start=time.monotonic()
    while time.monotonic()-start < timeout:
        pid=pid_of(package_id)
        if pid: return pid
        time.sleep(0.5)
    return ""

def launch(package_id: str) -> str:
    adb("shell","monkey","-p",package_id,"-c","android.intent.category.LAUNCHER","1",timeout=20)
    return wait_for_pid(package_id)

def runtime_unhealthy(package_id: str) -> str:
    logs=adb("logcat","-b","all","-d","-v","brief",timeout=30).stdout
    if f"ANR in {package_id}" in logs:
        return "ANR detected"
    if re.search(rf"FATAL EXCEPTION:[\s\S]{{0,2200}}Process:\s*{re.escape(package_id)}\b",logs):
        return "fatal exception detected"
    return ""

def disk_free_mb() -> dict[str, Any]:
    r=adb("shell","df","-k","/data",timeout=20)
    lines=[x for x in r.stdout.splitlines() if x.strip()]
    free=None
    if len(lines)>=2:
        parts=lines[-1].split()
        if len(parts)>=4 and parts[3].isdigit():
            free=int(parts[3])//1024
    return {"free_mb":free,"raw":r.stdout[-4000:]}

def run_as_available(package_id: str) -> tuple[bool,str]:
    r=adb("shell","run-as",package_id,"id",timeout=15)
    return r.returncode==0 and "uid=" in r.stdout, r.stdout[-2000:]

def list_private_files(package_id: str, max_files: int) -> list[str]:
    cmd="cd /data/data/%s && find files shared_prefs databases no_backup -type f 2>/dev/null | head -n %d" % (package_id,max_files)
    r=adb("shell","run-as",package_id,"sh","-c",cmd,timeout=30)
    if r.returncode!=0:
        return []
    return [x.strip() for x in r.stdout.splitlines() if x.strip() and not x.startswith("/")]

def private_file_bytes(package_id: str, relative: str, max_bytes: int) -> bytes | None:
    safe=re.fullmatch(r"[A-Za-z0-9_./@+=,-]+",relative)
    if not safe or ".." in Path(relative).parts:
        return None
    size_cmd=f"cd /data/data/{package_id} && wc -c < {relative}"
    sr=adb("shell","run-as",package_id,"sh","-c",size_cmd,timeout=15)
    try:
        size=int(sr.stdout.strip().splitlines()[-1])
    except Exception:
        return None
    if size<0 or size>max_bytes:
        return None
    r=run("adb","exec-out","run-as",package_id,"cat",f"/data/data/{package_id}/{relative}",timeout=30,binary=True)
    if r.returncode!=0:
        return None
    return bytes(r.stdout)

def private_snapshot(package_id: str, config: dict[str,Any]) -> dict[str,Any]:
    available,detail=run_as_available(package_id)
    if not available:
        return {"available":False,"detail":detail,"files":{}}
    files={}
    for rel in list_private_files(package_id,config["max_files"]):
        data=private_file_bytes(package_id,rel,config["max_file_bytes"])
        if data is None:
            files[rel]={"readable":False}
        else:
            files[rel]={
                "readable":True,
                "size_bytes":len(data),
                "sha256":hashlib.sha256(data).hexdigest(),
            }
    return {"available":True,"detail":detail,"files":files}

def dump_ui(report_dir: Path,name: str) -> str:
    remote=f"/sdcard/applab-{name}.xml"
    out=report_dir/f"{name}.xml"
    adb("shell","rm","-f",remote,timeout=10)
    r=adb("shell","uiautomator","dump","--compressed",remote,timeout=20)
    if r.returncode!=0:
        r=adb("shell","uiautomator","dump",remote,timeout=20)
    if r.returncode==0:
        p=adb("pull",remote,str(out),timeout=20)
        if p.returncode==0 and out.is_file():
            return out.read_text(encoding="utf-8",errors="replace")
    return ""

def capture(report_dir: Path,name: str) -> None:
    r=run("adb","exec-out","screencap","-p",timeout=20,binary=True)
    if r.returncode==0 and r.stdout:
        (report_dir/f"{name}.png").write_bytes(bytes(r.stdout))

def evaluate(package_id: str,config: dict[str,Any],report_dir: Path) -> dict[str,Any]:
    if not PACKAGE_RE.fullmatch(package_id):
        raise ValueError("invalid package id")
    report_dir.mkdir(parents=True,exist_ok=True)
    findings:list[Finding]=[]
    if not config["enabled"]:
        return {"schema_version":1,"storage_lab_version":"0.7.9","result":"SKIPPED","package_id":package_id,"config":config,"findings":[],"errors":0,"warnings":0}

    initial_pid=pid_of(package_id) or launch(package_id)
    if not initial_pid:
        findings.append(Finding("error","application_not_running","Application could not be started before storage integrity testing.",{}))

    disk_before=disk_free_mb()
    if disk_before["free_mb"] is not None and disk_before["free_mb"] < config["minimum_free_mb"]:
        findings.append(Finding("error" if config["required"] else "warning","low_free_space","Device free space is below the configured threshold.",{"free_mb":disk_before["free_mb"],"minimum_free_mb":config["minimum_free_mb"]}))

    before=private_snapshot(package_id,config)
    if not before["available"]:
        findings.append(Finding("error" if config["required"] else "warning","private_storage_unavailable","run-as cannot inspect the app private storage on this APK.",{"detail":before["detail"]}))
    else:
        paths=list(before["files"])
        for pattern in config["required_path_regex"]:
            if not any(re.search(pattern,p,re.IGNORECASE) for p in paths):
                findings.append(Finding("error" if config["required"] else "warning","required_storage_path_missing","Configured private-storage path pattern was not found.",{"pattern":pattern}))

    adb("logcat","-b","all","-c",timeout=20)
    adb("shell","am","force-stop",package_id,timeout=15)
    time.sleep(config["settle_seconds"])
    recovered_pid=launch(package_id)
    time.sleep(config["settle_seconds"])
    if not recovered_pid:
        findings.append(Finding("error","storage_restart_failed","Application failed to relaunch during storage integrity verification.",{}))

    unhealthy=runtime_unhealthy(package_id)
    if unhealthy:
        findings.append(Finding("error","runtime_unhealthy_after_storage_restart","Application runtime was unhealthy after storage restart.",{"reason":unhealthy}))

    after=private_snapshot(package_id,config)
    comparisons=[]
    if before["available"] and after["available"]:
        for path,b in before["files"].items():
            a=after["files"].get(path)
            changed=bool(b.get("sha256") and a and a.get("sha256") and b["sha256"]!=a["sha256"])
            comparisons.append({"path":path,"before":b,"after":a,"changed":changed})
            if a is None:
                for pattern in config["stable_path_regex"]:
                    if re.search(pattern,path,re.IGNORECASE):
                        findings.append(Finding("error","stable_storage_path_missing","A configured stable storage file disappeared after restart.",{"path":path,"pattern":pattern}))
            elif changed:
                for pattern in config["stable_path_regex"]:
                    if re.search(pattern,path,re.IGNORECASE):
                        findings.append(Finding("error","stable_storage_hash_changed","A configured stable storage file changed across restart.",{"path":path,"pattern":pattern}))

    ui=dump_ui(report_dir,"storage-recovery")
    capture(report_dir,"storage-recovery")
    if not ui:
        findings.append(Finding("error" if config["required"] else "warning","ui_hierarchy_missing","UI hierarchy could not be captured after storage recovery.",{}))
    else:
        for pattern in config["expected_text_regex"]:
            if not re.search(pattern,ui,re.IGNORECASE):
                findings.append(Finding("error" if config["required"] else "warning","expected_state_missing","Expected UI state was not visible after storage recovery.",{"pattern":pattern}))
        for pattern in config["forbidden_text_regex"]:
            if re.search(pattern,ui,re.IGNORECASE):
                findings.append(Finding("error","forbidden_state_visible","Forbidden reset/error state was visible after storage recovery.",{"pattern":pattern}))

    disk_after=disk_free_mb()
    errors=sum(1 for x in findings if x.severity=="error")
    warnings=sum(1 for x in findings if x.severity=="warning")
    result="FAIL" if errors else ("WARN" if warnings else "PASS")
    return {
        "schema_version":1,
        "storage_lab_version":"0.7.9",
        "result":result,
        "package_id":package_id,
        "config":config,
        "initial_pid":initial_pid,
        "recovered_pid":recovered_pid,
        "disk_before":disk_before,
        "disk_after":disk_after,
        "private_storage_before":before,
        "private_storage_after":after,
        "comparisons":comparisons,
        "ui_hierarchy_captured":bool(ui),
        "findings":[asdict(x) for x in findings],
        "errors":errors,
        "warnings":warnings,
    }

def write_report(payload: dict[str,Any],report_dir: Path) -> None:
    (report_dir/"storage-lab.json").write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    lines=[
        "# Storage & Data Integrity Lab","",
        f"- Result: {payload['result']}",
        f"- Package: {payload['package_id']}",
        f"- Private storage inspectable: {payload.get('private_storage_before',{}).get('available',False)}",
        f"- Files compared: {len(payload.get('comparisons',[]))}",
        f"- Errors: {payload.get('errors',0)}",
        f"- Warnings: {payload.get('warnings',0)}","",
    ]
    for item in payload.get("findings",[]):
        lines.append(f"- {item['severity'].upper()} {item['code']}: {item['message']}")
    (report_dir/"storage-lab.md").write_text("\n".join(lines).rstrip()+"\n",encoding="utf-8")

def self_test() -> None:
    cfg=load_config(None)
    assert cfg["max_files"]==200
    assert cfg["minimum_free_mb"]==128
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        p=Path(raw)/"policy.json"
        p.write_text(json.dumps({
            "schema_version":1,"required":True,"settle_seconds":1,
            "max_files":50,"max_file_bytes":1048576,"minimum_free_mb":64,
            "stable_path_regex":["shared_prefs/.*"],
            "required_path_regex":["databases/.*"],
            "expected_text_regex":["Home"],"forbidden_text_regex":["Reset"]
        }),encoding="utf-8")
        parsed=load_config(p)
        assert parsed["required"] is True
        assert parsed["max_files"]==50
        assert parsed["stable_path_regex"]==["shared_prefs/.*"]
    print("AppLab Storage & Data Integrity Lab self-test PASS")

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--package-id")
    parser.add_argument("--report-dir",default="applab-report")
    parser.add_argument("--config")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        self_test(); return 0
    if not args.package_id:
        parser.error("--package-id is required")
    config=load_config(Path(args.config) if args.config else None)
    report_dir=Path(args.report_dir)
    payload=evaluate(args.package_id,config,report_dir)
    write_report(payload,report_dir)
    print(f"AppLab Storage & Data Integrity Lab: {payload['result']} (errors={payload['errors']}, warnings={payload['warnings']})")
    return 1 if payload["result"]=="FAIL" else 0

if __name__=="__main__":
    raise SystemExit(main())
