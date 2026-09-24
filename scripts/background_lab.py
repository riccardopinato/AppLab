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
        "background_cycles": 1,
        "settle_seconds": 1.5,
        "force_doze": True,
        "app_standby": True,
        "require_notification": False,
        "expected_service_regex": [],
        "expected_job_regex": [],
        "expected_text_regex": [],
        "forbidden_text_regex": [],
    }
    if path is None or not path.is_file():
        return defaults

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("background lab config must be an object")
    if int(payload.get("schema_version", 1)) != 1:
        raise ValueError("unsupported background lab config schema")

    allowed = {
        "schema_version",
        "enabled",
        "required",
        "background_cycles",
        "settle_seconds",
        "force_doze",
        "app_standby",
        "require_notification",
        "expected_service_regex",
        "expected_job_regex",
        "expected_text_regex",
        "forbidden_text_regex",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown background lab keys: {sorted(unknown)}")

    cycles = int(payload.get("background_cycles", 1))
    settle = float(payload.get("settle_seconds", 1.5))
    if not 1 <= cycles <= 5:
        raise ValueError("background_cycles must be between 1 and 5")
    if not 0.5 <= settle <= 15.0:
        raise ValueError("settle_seconds must be between 0.5 and 15")

    def regex_list(name: str) -> list[str]:
        raw = payload.get(name, [])
        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            raise ValueError(f"{name} must be a list of strings")
        if len(raw) > 20:
            raise ValueError(f"{name} supports at most 20 expressions")
        for value in raw:
            if len(value) > 300:
                raise ValueError(f"{name} expression is too long")
            re.compile(value)
        return raw

    return {
        "schema_version": 1,
        "enabled": bool(payload.get("enabled", True)),
        "required": bool(payload.get("required", False)),
        "background_cycles": cycles,
        "settle_seconds": settle,
        "force_doze": bool(payload.get("force_doze", True)),
        "app_standby": bool(payload.get("app_standby", True)),
        "require_notification": bool(payload.get("require_notification", False)),
        "expected_service_regex": regex_list("expected_service_regex"),
        "expected_job_regex": regex_list("expected_job_regex"),
        "expected_text_regex": regex_list("expected_text_regex"),
        "forbidden_text_regex": regex_list("forbidden_text_regex"),
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


def launch(package_id: str) -> str:
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


def runtime_unhealthy(package_id: str) -> str:
    logs = adb("logcat", "-b", "all", "-d", "-v", "brief", timeout=30).stdout
    if f"ANR in {package_id}" in logs:
        return "ANR detected"
    if re.search(
        rf"FATAL EXCEPTION:[\s\S]{{0,2200}}Process:\s*{re.escape(package_id)}\b",
        logs,
    ):
        return "fatal exception detected"
    return ""


def dump_ui(report_dir: Path, name: str) -> str:
    remote = f"/sdcard/applab-{name}.xml"
    output = report_dir / f"{name}.xml"
    adb("shell", "rm", "-f", remote, timeout=10)
    dumped = adb("shell", "uiautomator", "dump", "--compressed", remote, timeout=20)
    if dumped.returncode != 0:
        dumped = adb("shell", "uiautomator", "dump", remote, timeout=20)
    if dumped.returncode == 0:
        pulled = adb("pull", remote, str(output), timeout=20)
        if pulled.returncode == 0 and output.is_file():
            return output.read_text(encoding="utf-8", errors="replace")
    return ""


def capture(report_dir: Path, name: str) -> None:
    raw = subprocess.run(
        ["adb", "exec-out", "screencap", "-p"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=20,
        check=False,
    )
    if raw.returncode == 0 and raw.stdout:
        (report_dir / f"{name}.png").write_bytes(raw.stdout)


def snapshot_background_state(package_id: str) -> dict[str, Any]:
    services = adb(
        "shell", "dumpsys", "activity", "services", package_id, timeout=30
    ).stdout
    jobs = adb(
        "shell", "dumpsys", "jobscheduler", package_id, timeout=30
    ).stdout
    notifications = adb(
        "shell", "dumpsys", "notification", "--noredact", timeout=30
    ).stdout
    notification_lines = [
        line.strip()
        for line in notifications.splitlines()
        if package_id in line
    ][:80]
    deviceidle = adb("shell", "dumpsys", "deviceidle", timeout=30).stdout
    inactive = adb(
        "shell", "am", "get-inactive", package_id, timeout=15
    ).stdout.strip()
    return {
        "pid": pid_of(package_id),
        "services_excerpt": services[-10000:],
        "jobs_excerpt": jobs[-12000:],
        "notification_lines": notification_lines,
        "deviceidle_excerpt": deviceidle[-12000:],
        "inactive_output": inactive,
    }


def check_regexes(
    text: str,
    patterns: list[str],
    *,
    code: str,
    message: str,
    stage: str,
    required: bool,
) -> list[Finding]:
    findings: list[Finding] = []
    for pattern in patterns:
        if not re.search(pattern, text, flags=re.IGNORECASE):
            findings.append(
                Finding(
                    "error" if required else "warning",
                    code,
                    message,
                    {"stage": stage, "pattern": pattern},
                )
            )
    return findings


def check_ui_policy(
    ui_text: str,
    config: dict[str, Any],
    stage: str,
) -> list[Finding]:
    findings = check_regexes(
        ui_text,
        config["expected_text_regex"],
        code="expected_state_missing",
        message="Expected UI state was not visible after background/Doze recovery.",
        stage=stage,
        required=config["required"],
    )
    for pattern in config["forbidden_text_regex"]:
        if re.search(pattern, ui_text, flags=re.IGNORECASE):
            findings.append(
                Finding(
                    "error",
                    "forbidden_state_visible",
                    "Forbidden reset/error UI state was visible after background/Doze recovery.",
                    {"stage": stage, "pattern": pattern},
                )
            )
    return findings


def set_app_inactive(package_id: str, inactive: bool) -> dict[str, Any]:
    result = adb(
        "shell",
        "am",
        "set-inactive",
        package_id,
        "true" if inactive else "false",
        timeout=15,
    )
    observed = adb(
        "shell", "am", "get-inactive", package_id, timeout=15
    )
    return {
        "success": result.returncode == 0,
        "requested": inactive,
        "output": result.stdout[-2000:],
        "observed": observed.stdout.strip(),
    }


def force_doze(enabled: bool) -> dict[str, Any]:
    if enabled:
        result = adb("shell", "dumpsys", "deviceidle", "force-idle", timeout=20)
    else:
        result = adb("shell", "dumpsys", "deviceidle", "unforce", timeout=20)
    return {
        "success": result.returncode == 0,
        "enabled": enabled,
        "output": result.stdout[-3000:],
    }


def recover_foreground(
    package_id: str,
    report_dir: Path,
    stage: str,
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[Finding]]:
    findings: list[Finding] = []
    recovered_pid = launch(package_id)
    time.sleep(config["settle_seconds"])
    if not recovered_pid:
        findings.append(
            Finding(
                "error",
                "foreground_recovery_failed",
                "Application failed to return to the foreground after background/Doze testing.",
                {"stage": stage},
            )
        )
        return {
            "stage": stage,
            "pid": "",
            "ui_hierarchy_captured": False,
        }, findings

    unhealthy = runtime_unhealthy(package_id)
    if unhealthy:
        findings.append(
            Finding(
                "error",
                "runtime_unhealthy_after_recovery",
                "Application runtime was unhealthy after background/Doze recovery.",
                {"stage": stage, "reason": unhealthy},
            )
        )

    ui = dump_ui(report_dir, stage)
    capture(report_dir, stage)
    if not ui:
        findings.append(
            Finding(
                "error" if config["required"] else "warning",
                "ui_hierarchy_missing",
                "UI hierarchy could not be captured after background/Doze recovery.",
                {"stage": stage},
            )
        )
    else:
        findings.extend(check_ui_policy(ui, config, stage))

    return {
        "stage": stage,
        "pid": pid_of(package_id),
        "ui_hierarchy_captured": bool(ui),
        "runtime_unhealthy_reason": unhealthy or None,
    }, findings


def evaluate(
    package_id: str,
    config: dict[str, Any],
    report_dir: Path,
) -> dict[str, Any]:
    if not PACKAGE_RE.fullmatch(package_id):
        raise ValueError("invalid package id")

    report_dir.mkdir(parents=True, exist_ok=True)
    findings: list[Finding] = []
    cycles: list[dict[str, Any]] = []
    recoveries: list[dict[str, Any]] = []
    standby_actions: list[dict[str, Any]] = []
    doze_actions: list[dict[str, Any]] = []

    if not config["enabled"]:
        return {
            "schema_version": 1,
            "background_lab_version": "0.7.8",
            "result": "SKIPPED",
            "package_id": package_id,
            "config": config,
            "findings": [],
            "errors": 0,
            "warnings": 0,
        }

    initial_pid = pid_of(package_id) or launch(package_id)
    if not initial_pid:
        findings.append(
            Finding(
                "error",
                "application_not_running",
                "Application could not be started before background/Doze testing.",
                {},
            )
        )

    initial = snapshot_background_state(package_id)

    try:
        for cycle in range(1, config["background_cycles"] + 1):
            adb("logcat", "-b", "all", "-c", timeout=20)
            adb("shell", "input", "keyevent", "KEYCODE_HOME", timeout=10)
            time.sleep(config["settle_seconds"])

            background_pid = pid_of(package_id)
            background_unhealthy = runtime_unhealthy(package_id)
            cycle_payload: dict[str, Any] = {
                "cycle": cycle,
                "pid_background": background_pid,
                "runtime_unhealthy_reason": background_unhealthy or None,
            }

            if background_unhealthy:
                findings.append(
                    Finding(
                        "error",
                        "runtime_unhealthy_in_background",
                        "Application produced an ANR or fatal exception while backgrounded.",
                        {"cycle": cycle, "reason": background_unhealthy},
                    )
                )

            if config["app_standby"]:
                standby = set_app_inactive(package_id, True)
                standby["cycle"] = cycle
                standby_actions.append(standby)
                cycle_payload["standby"] = standby
                if not standby["success"]:
                    findings.append(
                        Finding(
                            "error" if config["required"] else "warning",
                            "app_standby_unavailable",
                            "Android could not apply the App Standby simulation.",
                            {"cycle": cycle, "output": standby["output"]},
                        )
                    )
                time.sleep(config["settle_seconds"])

            if config["force_doze"]:
                doze = force_doze(True)
                doze["cycle"] = cycle
                doze_actions.append(doze)
                cycle_payload["doze"] = doze
                if not doze["success"]:
                    findings.append(
                        Finding(
                            "error" if config["required"] else "warning",
                            "doze_unavailable",
                            "Android could not enter forced Doze mode.",
                            {"cycle": cycle, "output": doze["output"]},
                        )
                    )
                time.sleep(config["settle_seconds"])

            state = snapshot_background_state(package_id)
            cycle_payload["background_state"] = state

            findings.extend(
                check_regexes(
                    state["services_excerpt"],
                    config["expected_service_regex"],
                    code="expected_service_missing",
                    message="Expected foreground/background service was not visible.",
                    stage=f"background-{cycle}",
                    required=config["required"],
                )
            )
            findings.extend(
                check_regexes(
                    state["jobs_excerpt"],
                    config["expected_job_regex"],
                    code="expected_job_missing",
                    message="Expected JobScheduler/WorkManager evidence was not visible.",
                    stage=f"background-{cycle}",
                    required=config["required"],
                )
            )
            if config["require_notification"] and not state["notification_lines"]:
                findings.append(
                    Finding(
                        "error" if config["required"] else "warning",
                        "notification_missing",
                        "No package notification was visible while background execution was tested.",
                        {"cycle": cycle},
                    )
                )

            if config["force_doze"]:
                restore_doze = force_doze(False)
                cycle_payload["doze_restore"] = restore_doze
                if not restore_doze["success"]:
                    findings.append(
                        Finding(
                            "error" if config["required"] else "warning",
                            "doze_restore_failed",
                            "Android could not explicitly leave forced Doze mode.",
                            {"cycle": cycle, "output": restore_doze["output"]},
                        )
                    )

            if config["app_standby"]:
                restore_standby = set_app_inactive(package_id, False)
                cycle_payload["standby_restore"] = restore_standby
                if not restore_standby["success"]:
                    findings.append(
                        Finding(
                            "error" if config["required"] else "warning",
                            "standby_restore_failed",
                            "Android could not explicitly leave App Standby simulation.",
                            {"cycle": cycle, "output": restore_standby["output"]},
                        )
                    )

            recovery, recovery_findings = recover_foreground(
                package_id,
                report_dir,
                f"background-recovery-{cycle}",
                config,
            )
            recoveries.append(recovery)
            findings.extend(recovery_findings)
            cycle_payload["recovery"] = recovery
            cycles.append(cycle_payload)
    finally:
        if config["force_doze"]:
            force_doze(False)
        if config["app_standby"]:
            set_app_inactive(package_id, False)

    final = snapshot_background_state(package_id)
    errors = sum(1 for item in findings if item.severity == "error")
    warnings = sum(1 for item in findings if item.severity == "warning")
    result = "FAIL" if errors else ("WARN" if warnings else "PASS")

    return {
        "schema_version": 1,
        "background_lab_version": "0.7.8",
        "result": result,
        "package_id": package_id,
        "config": config,
        "initial_pid": initial_pid,
        "initial": initial,
        "cycles": cycles,
        "standby_actions": standby_actions,
        "doze_actions": doze_actions,
        "recoveries": recoveries,
        "final": final,
        "findings": [asdict(item) for item in findings],
        "errors": errors,
        "warnings": warnings,
    }


def write_report(payload: dict[str, Any], report_dir: Path) -> None:
    (report_dir / "background-lab.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Background Execution, Doze & Recovery Lab",
        "",
        f"- Result: {payload['result']}",
        f"- Package: {payload['package_id']}",
        f"- Background cycles: {len(payload.get('cycles', []))}",
        f"- Errors: {payload.get('errors', 0)}",
        f"- Warnings: {payload.get('warnings', 0)}",
        "",
    ]
    for item in payload.get("findings", []):
        lines.append(
            f"- {item['severity'].upper()} {item['code']}: {item['message']}"
        )
    (report_dir / "background-lab.md").write_text(
        "\n".join(lines).rstrip() + "\n",
        encoding="utf-8",
    )


def self_test() -> None:
    cfg = load_config(None)
    assert cfg["background_cycles"] == 1
    assert cfg["force_doze"] is True
    assert cfg["app_standby"] is True

    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "required": True,
                    "background_cycles": 2,
                    "settle_seconds": 1,
                    "force_doze": False,
                    "app_standby": True,
                    "require_notification": True,
                    "expected_service_regex": ["ForegroundService"],
                    "expected_job_regex": ["WorkManager"],
                    "expected_text_regex": ["Home"],
                    "forbidden_text_regex": ["Fatal"],
                }
            ),
            encoding="utf-8",
        )
        parsed = load_config(path)
        assert parsed["background_cycles"] == 2
        assert parsed["force_doze"] is False
        assert parsed["require_notification"] is True
        assert not check_ui_policy('<node text="Home"/>', parsed, "test")
        findings = check_ui_policy('<node text="Fatal"/>', parsed, "test")
        assert len(findings) == 2
        service_findings = check_regexes(
            "ForegroundService running",
            parsed["expected_service_regex"],
            code="missing",
            message="missing",
            stage="test",
            required=True,
        )
        assert not service_findings

    print("AppLab Background Execution, Doze & Recovery Lab self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id")
    parser.add_argument("--report-dir", default="applab-report")
    parser.add_argument("--config")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if not args.package_id:
        parser.error("--package-id is required")

    config = load_config(Path(args.config) if args.config else None)
    report_dir = Path(args.report_dir)
    payload = evaluate(args.package_id, config, report_dir)
    write_report(payload, report_dir)
    print(
        f"AppLab Background Execution, Doze & Recovery Lab: {payload['result']} "
        f"(errors={payload['errors']}, warnings={payload['warnings']})"
    )
    return 1 if payload["result"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
