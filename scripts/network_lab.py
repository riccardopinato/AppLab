#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def run(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def adb(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return run("adb", *args, timeout=timeout)


def load_config(path: Path | None) -> dict[str, Any]:
    defaults = {
        "schema_version": 1,
        "enabled": True,
        "required": False,
        "offline_seconds": 2.0,
        "recovery_timeout_seconds": 15.0,
        "relaunch_while_offline": True,
    }
    if path is None or not path.is_file():
        return defaults

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("network lab config must be an object")
    if int(payload.get("schema_version", 1)) != 1:
        raise ValueError("unsupported network lab config schema")

    allowed = {
        "schema_version",
        "enabled",
        "required",
        "offline_seconds",
        "recovery_timeout_seconds",
        "relaunch_while_offline",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown network lab keys: {sorted(unknown)}")

    offline_seconds = float(payload.get("offline_seconds", 2.0))
    recovery_timeout = float(payload.get("recovery_timeout_seconds", 15.0))
    if not 0.5 <= offline_seconds <= 20.0:
        raise ValueError("offline_seconds must be between 0.5 and 20")
    if not 3.0 <= recovery_timeout <= 60.0:
        raise ValueError("recovery_timeout_seconds must be between 3 and 60")

    return {
        "schema_version": 1,
        "enabled": bool(payload.get("enabled", True)),
        "required": bool(payload.get("required", False)),
        "offline_seconds": offline_seconds,
        "recovery_timeout_seconds": recovery_timeout,
        "relaunch_while_offline": bool(
            payload.get("relaunch_while_offline", True)
        ),
    }


def pid_of(package_id: str) -> str:
    result = adb("shell", "pidof", package_id, timeout=10)
    return result.stdout.strip().split()[0] if result.stdout.strip() else ""


def wait_for_pid(package_id: str, timeout: float = 15.0) -> str:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        pid = pid_of(package_id)
        if pid:
            return pid
        time.sleep(0.5)
    return ""


def relaunch(package_id: str) -> str:
    adb(
        "shell",
        "monkey",
        "-p",
        package_id,
        "-c",
        "android.intent.category.LAUNCHER",
        "1",
        timeout=20,
    )
    return wait_for_pid(package_id)


def network_snapshot() -> dict[str, Any]:
    connectivity = adb("shell", "dumpsys", "connectivity", timeout=30).stdout
    airplane = adb(
        "shell", "settings", "get", "global", "airplane_mode_on", timeout=10
    ).stdout.strip()
    validated_lines = [
        line.strip()
        for line in connectivity.splitlines()
        if "VALIDATED" in line and "INTERNET" in line
    ]
    return {
        "airplane_mode": airplane == "1",
        "validated_internet": bool(validated_lines),
        "validated_lines": validated_lines[:20],
        "connectivity_excerpt": connectivity[-10000:],
    }


def set_airplane_mode(enabled: bool) -> dict[str, Any]:
    state = "enable" if enabled else "disable"
    primary = adb(
        "shell", "cmd", "connectivity", "airplane-mode", state, timeout=15
    )
    if primary.returncode == 0:
        return {
            "success": True,
            "method": "cmd connectivity airplane-mode",
            "output": primary.stdout[-2000:],
        }

    value = "1" if enabled else "0"
    setting = adb(
        "shell",
        "settings",
        "put",
        "global",
        "airplane_mode_on",
        value,
        timeout=10,
    )
    broadcast = adb(
        "shell",
        "am",
        "broadcast",
        "-a",
        "android.intent.action.AIRPLANE_MODE",
        "--ez",
        "state",
        "true" if enabled else "false",
        timeout=15,
    )
    success = setting.returncode == 0 and broadcast.returncode == 0
    return {
        "success": success,
        "method": "settings+broadcast",
        "output": (setting.stdout + "\n" + broadcast.stdout)[-3000:],
    }


def wait_for_connectivity(
    expected_online: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    start = time.monotonic()
    last = network_snapshot()
    while time.monotonic() - start < timeout_seconds:
        if bool(last["validated_internet"]) == expected_online:
            return {
                "matched": True,
                "elapsed_seconds": round(time.monotonic() - start, 3),
                "snapshot": last,
            }
        time.sleep(0.75)
        last = network_snapshot()
    return {
        "matched": False,
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "snapshot": last,
    }


def app_crash_state(package_id: str) -> tuple[bool, str]:
    if not pid_of(package_id):
        return True, "application process is not running"
    logcat = adb("logcat", "-b", "all", "-d", "-v", "brief", timeout=30).stdout
    if f"ANR in {package_id}" in logcat:
        return True, "ANR detected"
    fatal = re.search(
        rf"FATAL EXCEPTION:[\s\S]{{0,2200}}Process:\s*{re.escape(package_id)}\b",
        logcat,
    )
    if fatal:
        return True, "fatal exception detected"
    return False, ""


def capture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = subprocess.run(
        ["adb", "exec-out", "screencap", "-p"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=20,
        check=False,
    )
    if raw.returncode == 0 and raw.stdout:
        path.write_bytes(raw.stdout)


def evaluate(
    package_id: str,
    config: dict[str, Any],
    report_dir: Path,
) -> dict[str, Any]:
    if not PACKAGE_RE.fullmatch(package_id):
        raise ValueError("invalid package id")

    findings: list[Finding] = []
    report_dir.mkdir(parents=True, exist_ok=True)
    initial = network_snapshot()

    if not config["enabled"]:
        return {
            "schema_version": 1,
            "network_lab_version": "0.7.3",
            "result": "SKIPPED",
            "package_id": package_id,
            "config": config,
            "initial": initial,
            "findings": [],
            "errors": 0,
            "warnings": 0,
        }

    initial_pid = pid_of(package_id) or relaunch(package_id)
    if not initial_pid:
        findings.append(
            Finding(
                "error",
                "application_not_running",
                "Application could not be started before network testing.",
                {},
            )
        )

    offline_action: dict[str, Any] = {}
    offline_wait: dict[str, Any] = {}
    offline_pid = ""
    offline_relaunch_pid = ""
    recovery_action: dict[str, Any] = {}
    recovery_wait: dict[str, Any] = {}
    recovered_pid = ""

    try:
        offline_action = set_airplane_mode(True)
        if not offline_action["success"]:
            severity = "error" if config["required"] else "warning"
            findings.append(
                Finding(
                    severity,
                    "offline_toggle_unavailable",
                    "The emulator could not enter airplane/offline mode.",
                    {"action": offline_action},
                )
            )
        else:
            offline_wait = wait_for_connectivity(False, 12.0)
            if not offline_wait["matched"]:
                severity = "error" if config["required"] else "warning"
                findings.append(
                    Finding(
                        severity,
                        "offline_state_not_confirmed",
                        "Validated Internet connectivity remained available after the offline toggle.",
                        {"state": offline_wait},
                    )
                )

        time.sleep(config["offline_seconds"])
        offline_pid = pid_of(package_id)
        if not offline_pid:
            findings.append(
                Finding(
                    "error",
                    "process_died_offline",
                    "Application process died after connectivity was removed.",
                    {},
                )
            )

        if offline_pid and config["relaunch_while_offline"]:
            adb("shell", "am", "force-stop", package_id, timeout=10)
            offline_relaunch_pid = relaunch(package_id)
            if not offline_relaunch_pid:
                findings.append(
                    Finding(
                        "error",
                        "offline_relaunch_failed",
                        "Application failed to relaunch while offline.",
                        {},
                    )
                )

        crashed, reason = app_crash_state(package_id)
        if crashed:
            findings.append(
                Finding(
                    "error",
                    "offline_runtime_unhealthy",
                    "Application runtime became unhealthy while offline.",
                    {"reason": reason},
                )
            )
        capture(report_dir / "network-offline.png")
    finally:
        recovery_action = set_airplane_mode(initial["airplane_mode"])

    expected_online = bool(initial["validated_internet"]) and not initial["airplane_mode"]
    if expected_online:
        recovery_wait = wait_for_connectivity(
            True, config["recovery_timeout_seconds"]
        )
        if not recovery_wait["matched"]:
            severity = "error" if config["required"] else "warning"
            findings.append(
                Finding(
                    severity,
                    "network_recovery_not_confirmed",
                    "Validated Internet connectivity did not recover within the configured timeout.",
                    {"state": recovery_wait},
                )
            )
    else:
        recovery_wait = {
            "matched": True,
            "elapsed_seconds": 0.0,
            "snapshot": network_snapshot(),
            "note": "initial state was already offline or unvalidated",
        }

    recovered_pid = pid_of(package_id) or relaunch(package_id)
    if not recovered_pid:
        findings.append(
            Finding(
                "error",
                "recovery_relaunch_failed",
                "Application failed to run after connectivity restoration.",
                {},
            )
        )

    crashed, reason = app_crash_state(package_id)
    if crashed:
        findings.append(
            Finding(
                "error",
                "recovery_runtime_unhealthy",
                "Application runtime is unhealthy after connectivity restoration.",
                {"reason": reason},
            )
        )
    capture(report_dir / "network-recovered.png")

    errors = [item for item in findings if item.severity == "error"]
    warnings = [item for item in findings if item.severity == "warning"]
    result = "FAIL" if errors else ("WARN" if warnings else "PASS")

    return {
        "schema_version": 1,
        "network_lab_version": "0.7.3",
        "result": result,
        "package_id": package_id,
        "config": config,
        "errors": len(errors),
        "warnings": len(warnings),
        "initial": initial,
        "offline": {
            "action": offline_action,
            "wait": offline_wait,
            "pid": offline_pid,
            "relaunch_pid": offline_relaunch_pid,
        },
        "recovery": {
            "action": recovery_action,
            "wait": recovery_wait,
            "pid": recovered_pid,
        },
        "findings": [asdict(item) for item in findings],
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# AppLab Network & Offline Lab",
        "",
        f"- Result: **{report['result']}**",
        f"- Errors: {report.get('errors', 0)}",
        f"- Warnings: {report.get('warnings', 0)}",
        f"- Initial validated Internet: {'yes' if report.get('initial', {}).get('validated_internet') else 'no'}",
        f"- Initial airplane mode: {'on' if report.get('initial', {}).get('airplane_mode') else 'off'}",
        "",
        "## Findings",
        "",
    ]
    findings = report.get("findings", [])
    if findings:
        for item in findings:
            lines.append(
                f"- **{item['severity'].upper()} — {item['code']}**: {item['message']}"
            )
    else:
        lines.append("- No network/offline runtime anomaly detected.")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def self_test() -> None:
    defaults = load_config(None)
    assert defaults["enabled"] is True
    assert defaults["required"] is False
    assert defaults["relaunch_while_offline"] is True

    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "network.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "required": True,
                    "offline_seconds": 1.5,
                    "recovery_timeout_seconds": 20,
                    "relaunch_while_offline": False,
                }
            ),
            encoding="utf-8",
        )
        parsed = load_config(path)
        assert parsed["required"] is True
        assert parsed["offline_seconds"] == 1.5
        assert parsed["recovery_timeout_seconds"] == 20
        assert parsed["relaunch_while_offline"] is False

    try:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "bad.json"
            path.write_text('{"offline_seconds":100}', encoding="utf-8")
            load_config(path)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid network timing must fail")

    print("AppLab Network & Offline Lab self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id")
    parser.add_argument("--report-dir")
    parser.add_argument("--config")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.package_id or not args.report_dir:
        raise SystemExit("--package-id and --report-dir are required")

    config = load_config(Path(args.config) if args.config else None)
    report_dir = Path(args.report_dir)
    report = evaluate(args.package_id, config, report_dir)
    (report_dir / "network-lab.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_markdown(report_dir / "network-lab.md", report)
    print(f"AppLab Network & Offline Lab: {report['result']}")
    return 2 if report["result"] == "FAIL" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"AppLab Network & Offline Lab warning: {exc}")
        raise SystemExit(0)
