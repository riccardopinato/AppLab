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
ALLOWED_TRIM_LEVELS = {
    "RUNNING_MODERATE",
    "BACKGROUND",
    "RUNNING_LOW",
    "MODERATE",
    "RUNNING_CRITICAL",
    "COMPLETE",
}


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
        "trim_levels": ["RUNNING_LOW", "BACKGROUND"],
        "process_death_cycles": 1,
        "settle_seconds": 1.5,
        "expected_text_regex": [],
        "forbidden_text_regex": [],
    }
    if path is None or not path.is_file():
        return defaults

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("resource pressure config must be an object")
    if int(payload.get("schema_version", 1)) != 1:
        raise ValueError("unsupported resource pressure config schema")

    allowed = {
        "schema_version",
        "enabled",
        "required",
        "trim_levels",
        "process_death_cycles",
        "settle_seconds",
        "expected_text_regex",
        "forbidden_text_regex",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown resource pressure keys: {sorted(unknown)}")

    levels = payload.get("trim_levels", defaults["trim_levels"])
    if not isinstance(levels, list) or not all(isinstance(x, str) for x in levels):
        raise ValueError("trim_levels must be a list of strings")
    if len(levels) > 6:
        raise ValueError("trim_levels supports at most 6 entries")
    normalized_levels = [x.strip().upper() for x in levels]
    unknown_levels = [x for x in normalized_levels if x not in ALLOWED_TRIM_LEVELS]
    if unknown_levels:
        raise ValueError(f"unsupported trim levels: {unknown_levels}")

    death_cycles = int(payload.get("process_death_cycles", 1))
    settle = float(payload.get("settle_seconds", 1.5))
    if not 0 <= death_cycles <= 5:
        raise ValueError("process_death_cycles must be between 0 and 5")
    if not 0.5 <= settle <= 10.0:
        raise ValueError("settle_seconds must be between 0.5 and 10")

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
        "trim_levels": normalized_levels,
        "process_death_cycles": death_cycles,
        "settle_seconds": settle,
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


def wait_for_process_exit(package_id: str, timeout: float = 8.0) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if not pid_of(package_id):
            return True
        time.sleep(0.4)
    return not bool(pid_of(package_id))


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
    if not pid_of(package_id):
        return "application process is not running"
    logs = adb("logcat", "-b", "all", "-d", "-v", "brief", timeout=30).stdout
    if f"ANR in {package_id}" in logs:
        return "ANR detected"
    if re.search(
        rf"FATAL EXCEPTION:[\s\S]{{0,2200}}Process:\s*{re.escape(package_id)}\b",
        logs,
    ):
        return "fatal exception detected"
    return ""


def meminfo(package_id: str) -> dict[str, Any]:
    text = adb("shell", "dumpsys", "meminfo", package_id, timeout=30).stdout
    total_pss = None
    match = re.search(r"TOTAL PSS:\s*([0-9]+)", text)
    if match:
        total_pss = int(match.group(1))
    if total_pss is None:
        match = re.search(r"^\s*TOTAL\s+([0-9]+)", text, flags=re.MULTILINE)
        if match:
            total_pss = int(match.group(1))
    return {
        "total_pss_kb": total_pss,
        "excerpt": text[-8000:],
    }


def dump_ui(report_dir: Path, name: str) -> str:
    remote = f"/sdcard/applab-{name}.xml"
    output = report_dir / f"{name}.xml"
    adb("shell", "rm", "-f", remote, timeout=10)
    result = adb("shell", "uiautomator", "dump", "--compressed", remote, timeout=20)
    if result.returncode != 0:
        result = adb("shell", "uiautomator", "dump", remote, timeout=20)
    if result.returncode == 0:
        pull = adb("pull", remote, str(output), timeout=20)
        if pull.returncode == 0 and output.is_file():
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


def check_text_policy(
    ui_text: str,
    config: dict[str, Any],
    stage: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for pattern in config["expected_text_regex"]:
        if not re.search(pattern, ui_text, flags=re.IGNORECASE):
            findings.append(
                Finding(
                    "error" if config["required"] else "warning",
                    "expected_state_missing",
                    "Expected UI state was not visible after resource/process recovery.",
                    {"stage": stage, "pattern": pattern},
                )
            )
    for pattern in config["forbidden_text_regex"]:
        if re.search(pattern, ui_text, flags=re.IGNORECASE):
            findings.append(
                Finding(
                    "error",
                    "forbidden_state_visible",
                    "Forbidden reset/error state was visible after resource/process recovery.",
                    {"stage": stage, "pattern": pattern},
                )
            )
    return findings


def capture_recovery(
    package_id: str,
    report_dir: Path,
    name: str,
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[Finding]]:
    ui = dump_ui(report_dir, name)
    capture(report_dir, name)
    unhealthy = runtime_unhealthy(package_id)
    findings: list[Finding] = []

    if unhealthy:
        findings.append(
            Finding(
                "error",
                "runtime_unhealthy",
                "Application runtime was unhealthy after resource/process recovery.",
                {"stage": name, "reason": unhealthy},
            )
        )
    if not ui:
        findings.append(
            Finding(
                "error" if config["required"] else "warning",
                "ui_hierarchy_missing",
                "UI hierarchy could not be captured after recovery.",
                {"stage": name},
            )
        )
    else:
        findings.extend(check_text_policy(ui, config, name))

    return {
        "stage": name,
        "pid": pid_of(package_id),
        "ui_hierarchy_captured": bool(ui),
        "memory": meminfo(package_id),
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
    trim_actions: list[dict[str, Any]] = []
    process_death: list[dict[str, Any]] = []
    recoveries: list[dict[str, Any]] = []

    if not config["enabled"]:
        return {
            "schema_version": 1,
            "resource_pressure_lab_version": "0.7.7",
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
                "Application could not be started before resource-pressure testing.",
                {},
            )
        )

    initial_memory = meminfo(package_id) if initial_pid else {}

    for index, level in enumerate(config["trim_levels"], start=1):
        action = adb(
            "shell",
            "am",
            "send-trim-memory",
            package_id,
            level,
            timeout=15,
        )
        time.sleep(config["settle_seconds"])
        current_pid = pid_of(package_id)
        unhealthy = runtime_unhealthy(package_id) if current_pid else "application process is not running"
        trim_actions.append(
            {
                "index": index,
                "level": level,
                "command_success": action.returncode == 0,
                "output": action.stdout[-2000:],
                "pid_after": current_pid,
                "runtime_unhealthy_reason": unhealthy or None,
                "memory_after": meminfo(package_id) if current_pid else {},
            }
        )

        if action.returncode != 0:
            findings.append(
                Finding(
                    "error" if config["required"] else "warning",
                    "trim_memory_unavailable",
                    "Android rejected a trim-memory request.",
                    {"level": level, "output": action.stdout[-2000:]},
                )
            )
        if not current_pid:
            findings.append(
                Finding(
                    "error",
                    "process_died_during_trim",
                    "Application process died during memory-pressure signalling.",
                    {"level": level},
                )
            )
            current_pid = launch(package_id)
        if current_pid and unhealthy:
            findings.append(
                Finding(
                    "error",
                    "runtime_unhealthy_after_trim",
                    "Application became unhealthy after a trim-memory signal.",
                    {"level": level, "reason": unhealthy},
                )
            )

    for cycle in range(1, config["process_death_cycles"] + 1):
        if not pid_of(package_id):
            launch(package_id)
        adb("shell", "input", "keyevent", "KEYCODE_HOME", timeout=10)
        time.sleep(config["settle_seconds"])
        before_pid = pid_of(package_id)
        adb("logcat", "-b", "all", "-c", timeout=20)
        kill = adb("shell", "am", "kill", package_id, timeout=15)
        exited = wait_for_process_exit(package_id)
        after_kill_pid = pid_of(package_id)

        if kill.returncode != 0:
            findings.append(
                Finding(
                    "error" if config["required"] else "warning",
                    "process_kill_unavailable",
                    "Android rejected the background process-death simulation.",
                    {"cycle": cycle, "output": kill.stdout[-2000:]},
                )
            )
        if before_pid and not exited:
            findings.append(
                Finding(
                    "error" if config["required"] else "warning",
                    "process_death_not_observed",
                    "Background process remained alive after the process-death simulation.",
                    {"cycle": cycle, "pid": after_kill_pid},
                )
            )

        recovered_pid = launch(package_id)
        time.sleep(config["settle_seconds"])
        process_death.append(
            {
                "cycle": cycle,
                "pid_before": before_pid,
                "kill_command_success": kill.returncode == 0,
                "process_exit_observed": exited,
                "pid_after_kill": after_kill_pid,
                "pid_after_recovery": recovered_pid,
            }
        )

        if not recovered_pid:
            findings.append(
                Finding(
                    "error",
                    "process_death_recovery_failed",
                    "Application failed to relaunch after simulated background process death.",
                    {"cycle": cycle},
                )
            )
            continue

        stage, stage_findings = capture_recovery(
            package_id,
            report_dir,
            f"resource-recovery-{cycle}",
            config,
        )
        recoveries.append(stage)
        findings.extend(stage_findings)

    errors = sum(1 for item in findings if item.severity == "error")
    warnings = sum(1 for item in findings if item.severity == "warning")
    result = "FAIL" if errors else ("WARN" if warnings else "PASS")

    return {
        "schema_version": 1,
        "resource_pressure_lab_version": "0.7.7",
        "result": result,
        "package_id": package_id,
        "config": config,
        "initial_pid": initial_pid,
        "initial_memory": initial_memory,
        "trim_actions": trim_actions,
        "process_death": process_death,
        "recoveries": recoveries,
        "findings": [asdict(item) for item in findings],
        "errors": errors,
        "warnings": warnings,
    }


def write_report(payload: dict[str, Any], report_dir: Path) -> None:
    (report_dir / "resource-pressure-lab.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Resource Pressure & Process Death Lab",
        "",
        f"- Result: {payload['result']}",
        f"- Package: {payload['package_id']}",
        f"- Trim actions: {len(payload.get('trim_actions', []))}",
        f"- Process-death cycles: {len(payload.get('process_death', []))}",
        f"- Errors: {payload.get('errors', 0)}",
        f"- Warnings: {payload.get('warnings', 0)}",
        "",
    ]
    for item in payload.get("findings", []):
        lines.append(
            f"- {item['severity'].upper()} {item['code']}: {item['message']}"
        )
    (report_dir / "resource-pressure-lab.md").write_text(
        "\n".join(lines).rstrip() + "\n",
        encoding="utf-8",
    )


def self_test() -> None:
    cfg = load_config(None)
    assert cfg["trim_levels"] == ["RUNNING_LOW", "BACKGROUND"]
    assert cfg["process_death_cycles"] == 1

    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "required": True,
                    "trim_levels": ["complete"],
                    "process_death_cycles": 2,
                    "settle_seconds": 1,
                    "expected_text_regex": ["Home"],
                    "forbidden_text_regex": ["Fatal"],
                }
            ),
            encoding="utf-8",
        )
        parsed = load_config(path)
        assert parsed["trim_levels"] == ["COMPLETE"]
        assert parsed["process_death_cycles"] == 2
        assert not check_text_policy('<node text="Home"/>', parsed, "test")
        findings = check_text_policy('<node text="Fatal"/>', parsed, "test")
        assert len(findings) == 2

    print("AppLab Resource Pressure & Process Death Lab self-test PASS")


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
        f"AppLab Resource Pressure & Process Death Lab: {payload['result']} "
        f"(errors={payload['errors']}, warnings={payload['warnings']})"
    )
    return 1 if payload["result"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
