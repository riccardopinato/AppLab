#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

TRANSIENT_RE = re.compile(
    r"Broken pipe|Failure calling service package|device offline|device not found|"
    r"connection reset|closed.*transport|transport.*error|no devices/emulators found",
    re.IGNORECASE,
)
SYSTEM_TRANSIENT_RE = re.compile(
    r"DeadSystemException|registerUiTestAutomationService.*null object reference|"
    r"UiAutomationConnection.*NullPointerException|system_server.*(died|crash|restarting)|"
    r"ServiceManager.*(dead|Bad file descriptor)",
    re.IGNORECASE,
)
FLUTTER_FAILURE_RE = re.compile(
    r"Unhandled Exception:|EXCEPTION CAUGHT BY (WIDGETS|RENDERING|SCHEDULER) LIBRARY|"
    r"Failed assertion:|Another exception was thrown",
    re.IGNORECASE,
)


class TransientInfrastructure(RuntimeError):
    pass


def adb(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["adb", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TransientInfrastructure(
            "adb timeout: " + " ".join(args)
        ) from exc


def checked_adb(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    completed = adb(*args, timeout=timeout)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise TransientInfrastructure(
            f"adb failed ({completed.returncode}): {' '.join(args)}"
            + (f": {detail[:240]}" if detail else "")
        )
    return completed


def relaunch(package_id: str) -> None:
    checked_adb("wait-for-device", timeout=60)
    checked_adb("shell", "am", "force-stop", package_id, timeout=20)
    checked_adb(
        "shell", "monkey", "-p", package_id,
        "-c", "android.intent.category.LAUNCHER", "1",
        timeout=30,
    )
    time.sleep(2)


def recover(package_id: str) -> None:
    checked_adb("wait-for-device", timeout=60)
    ready = False
    for _ in range(30):
        try:
            boot = adb("shell", "getprop", "sys.boot_completed", timeout=10)
            packages = adb(
                "shell", "cmd", "package", "list", "packages", "android", timeout=10
            )
            accessibility = adb(
                "shell", "service", "check", "accessibility", timeout=10
            )
        except TransientInfrastructure:
            time.sleep(2)
            continue
        if (
            boot.stdout.strip() == "1"
            and packages.returncode == 0
            and accessibility.returncode == 0
        ):
            ready = True
            break
        time.sleep(2)
    if not ready:
        raise TransientInfrastructure("emulator services did not recover inside bounded retry")
    relaunch(package_id)
    try:
        adb("logcat", "-b", "all", "-c", timeout=10)
    except TransientInfrastructure:
        pass


def wrapper_text(package_id: str, flow: Path) -> str:
    flow_value = json.dumps(str(flow))
    return (
        f"appId: {package_id}\n---\n"
        "- runFlow:\n"
        '    when:\n      visible: "Pixel Launcher isn\'t responding"\n'
        "    commands:\n"
        '      - tapOn:\n          text: "Close app"\n          optional: true\n'
        "- runFlow:\n"
        f"    file: {flow_value}\n"
    )


def system_transient(root: Path, attempt: int) -> bool:
    path = root / f"attempt-{attempt}-system-logcat.txt"
    try:
        log = adb("logcat", "-b", "all", "-d", "-v", "threadtime", timeout=30)
        text = (log.stdout or "") + (log.stderr or "")
    except TransientInfrastructure as exc:
        text = f"TRANSIENT_ADB_ERROR: {exc}\n"
        path.write_text(text, encoding="utf-8")
        return True
    path.write_text(text, encoding="utf-8")
    return bool(SYSTEM_TRANSIENT_RE.search(text))


def runtime_health(
    *,
    package_id: str,
    root: Path,
    attempt: int,
) -> dict[str, Any]:
    pid_result = adb("shell", "pidof", package_id, timeout=15)
    pid_text = (pid_result.stdout or "") + (pid_result.stderr or "")
    pid = pid_result.stdout.strip().split()
    if pid_result.returncode != 0:
        if TRANSIENT_RE.search(pid_text):
            raise TransientInfrastructure(
                "adb pid query transport failure: " + pid_text.strip()[:240]
            )
        if not pid:
            return {
                "result": "FAIL",
                "reason": "application process died during journey",
                "pid": "",
            }
    if not pid:
        return {
            "result": "FAIL",
            "reason": "application process died during journey",
            "pid": "",
        }
    pid_value = pid[0]
    global_log = checked_adb("logcat", "-b", "all", "-d", "-v", "threadtime", timeout=30)
    app_log = checked_adb("logcat", f"--pid={pid_value}", "-d", "-v", "threadtime", timeout=30)
    global_text = (global_log.stdout or "") + (global_log.stderr or "")
    app_text = (app_log.stdout or "") + (app_log.stderr or "")
    global_path = root / f"attempt-{attempt}-runtime-logcat.txt"
    app_path = root / f"attempt-{attempt}-app-logcat.txt"
    global_path.write_text(global_text, encoding="utf-8")
    app_path.write_text(app_text, encoding="utf-8")

    reason = ""
    if f"ANR in {package_id}" in global_text:
        reason = "ANR detected during journey"
    elif "FATAL EXCEPTION" in global_text and f"Process: {package_id}" in global_text:
        reason = "fatal exception detected during journey"
    elif FLUTTER_FAILURE_RE.search(app_text):
        reason = "unhandled Flutter/framework exception detected during journey"

    return {
        "result": "FAIL" if reason else "PASS",
        "reason": reason,
        "pid": pid_value,
        "global_log": str(global_path),
        "app_log": str(app_path),
    }


def _infra_attempt(
    *,
    attempt: int,
    started: float,
    root: Path,
    reason: str,
) -> dict[str, Any]:
    path = root / f"attempt-{attempt}-infrastructure.txt"
    path.write_text(reason + "\n", encoding="utf-8")
    return {
        "attempt": attempt,
        "result": "FAIL",
        "transient": True,
        "phase": "infrastructure",
        "reason": reason,
        "seconds": round(time.monotonic() - started, 3),
        "log": str(path),
    }


def run_attempt(
    *,
    attempt: int,
    wrapper: Path,
    package_id: str,
    root: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        checked_adb("logcat", "-b", "all", "-c", timeout=10)
        relaunch(package_id)
    except TransientInfrastructure as exc:
        return _infra_attempt(
            attempt=attempt, started=started, root=root, reason=str(exc)
        )

    output_dir = root / f"attempt-{attempt}"
    output_dir.mkdir(parents=True, exist_ok=True)
    console = root / f"attempt-{attempt}.log"
    completed = subprocess.run(
        ["maestro", "test", str(wrapper), "--test-output-dir", str(output_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    text = (completed.stdout or "") + (completed.stderr or "")
    console.write_text(text, encoding="utf-8")

    if completed.returncode != 0:
        transient = bool(TRANSIENT_RE.search(text))
        if not transient:
            transient = system_transient(root, attempt)
        return {
            "attempt": attempt,
            "result": "FAIL",
            "transient": transient,
            "phase": "maestro",
            "reason": (
                "transient Maestro/infrastructure failure"
                if transient
                else "functional Maestro failure; not retried"
            ),
            "seconds": round(time.monotonic() - started, 3),
            "log": str(console),
        }

    try:
        health = runtime_health(
            package_id=package_id,
            root=root,
            attempt=attempt,
        )
    except TransientInfrastructure as exc:
        return _infra_attempt(
            attempt=attempt, started=started, root=root, reason=str(exc)
        )

    return {
        "attempt": attempt,
        "result": health["result"],
        "transient": False,
        "phase": "runtime_health",
        "reason": health.get("reason", ""),
        "pid": health.get("pid", ""),
        "health": health,
        "seconds": round(time.monotonic() - started, 3),
        "log": str(console),
    }
