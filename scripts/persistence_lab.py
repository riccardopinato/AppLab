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
        "restart_cycles": 2,
        "settle_seconds": 1.5,
        "expected_text_regex": [],
        "forbidden_text_regex": [],
    }
    if path is None or not path.is_file():
        return defaults

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("persistence lab config must be an object")
    if int(payload.get("schema_version", 1)) != 1:
        raise ValueError("unsupported persistence lab config schema")

    allowed = {
        "schema_version",
        "enabled",
        "required",
        "restart_cycles",
        "settle_seconds",
        "expected_text_regex",
        "forbidden_text_regex",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown persistence lab keys: {sorted(unknown)}")

    restart_cycles = int(payload.get("restart_cycles", 2))
    settle_seconds = float(payload.get("settle_seconds", 1.5))
    if not 1 <= restart_cycles <= 5:
        raise ValueError("restart_cycles must be between 1 and 5")
    if not 0.5 <= settle_seconds <= 10.0:
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
        "restart_cycles": restart_cycles,
        "settle_seconds": settle_seconds,
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


def package_runtime_unhealthy(package_id: str) -> str:
    pid = pid_of(package_id)
    if not pid:
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


def check_text_policy(
    ui_text: str,
    config: dict[str, Any],
    cycle: int,
) -> list[Finding]:
    findings: list[Finding] = []
    for pattern in config["expected_text_regex"]:
        if not re.search(pattern, ui_text, flags=re.IGNORECASE):
            findings.append(
                Finding(
                    "error" if config["required"] else "warning",
                    "expected_state_missing",
                    "Expected persisted UI state was not visible after restart.",
                    {"cycle": cycle, "pattern": pattern},
                )
            )
    for pattern in config["forbidden_text_regex"]:
        if re.search(pattern, ui_text, flags=re.IGNORECASE):
            findings.append(
                Finding(
                    "error",
                    "forbidden_state_visible",
                    "Forbidden reset/error UI state was visible after restart.",
                    {"cycle": cycle, "pattern": pattern},
                )
            )
    return findings


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

    if not config["enabled"]:
        return {
            "schema_version": 1,
            "persistence_lab_version": "0.7.4",
            "result": "SKIPPED",
            "package_id": package_id,
            "config": config,
            "cycles": [],
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
                "Application could not be started before persistence testing.",
                {},
            )
        )

    for cycle in range(1, config["restart_cycles"] + 1):
        before_pid = pid_of(package_id)
        adb("shell", "am", "force-stop", package_id, timeout=10)
        stopped_pid = pid_of(package_id)
        relaunched_pid = relaunch(package_id)
        time.sleep(config["settle_seconds"])

        ui = dump_ui(report_dir, f"persistence-cycle-{cycle}")
        capture(report_dir, f"persistence-cycle-{cycle}")
        unhealthy = package_runtime_unhealthy(package_id)

        cycle_result = {
            "cycle": cycle,
            "pid_before": before_pid,
            "pid_after_force_stop": stopped_pid,
            "pid_after_relaunch": relaunched_pid,
            "ui_hierarchy_captured": bool(ui),
            "runtime_unhealthy_reason": unhealthy or None,
        }
        cycles.append(cycle_result)

        if stopped_pid:
            findings.append(
                Finding(
                    "warning",
                    "force_stop_not_observed",
                    "Process was still visible immediately after force-stop.",
                    {"cycle": cycle, "pid": stopped_pid},
                )
            )
        if not relaunched_pid:
            findings.append(
                Finding(
                    "error",
                    "relaunch_failed",
                    "Application failed to relaunch after force-stop.",
                    {"cycle": cycle},
                )
            )
        if unhealthy:
            findings.append(
                Finding(
                    "error",
                    "runtime_unhealthy_after_restart",
                    "Application runtime was unhealthy after restart.",
                    {"cycle": cycle, "reason": unhealthy},
                )
            )
        if not ui:
            findings.append(
                Finding(
                    "error" if config["required"] else "warning",
                    "ui_hierarchy_missing",
                    "UI hierarchy could not be captured after restart.",
                    {"cycle": cycle},
                )
            )
        else:
            findings.extend(check_text_policy(ui, config, cycle))

    errors = sum(1 for item in findings if item.severity == "error")
    warnings = sum(1 for item in findings if item.severity == "warning")
    result = "FAIL" if errors else ("WARN" if warnings else "PASS")

    return {
        "schema_version": 1,
        "persistence_lab_version": "0.7.4",
        "result": result,
        "package_id": package_id,
        "config": config,
        "cycles": cycles,
        "findings": [asdict(item) for item in findings],
        "errors": errors,
        "warnings": warnings,
    }


def write_report(payload: dict[str, Any], report_dir: Path) -> None:
    (report_dir / "persistence-lab.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Persistence & Restart Lab",
        "",
        f"- Result: {payload['result']}",
        f"- Package: {payload['package_id']}",
        f"- Restart cycles: {len(payload.get('cycles', []))}",
        f"- Errors: {payload.get('errors', 0)}",
        f"- Warnings: {payload.get('warnings', 0)}",
        "",
    ]
    for item in payload.get("findings", []):
        lines.append(
            f"- {item['severity'].upper()} {item['code']}: {item['message']}"
        )
    (report_dir / "persistence-lab.md").write_text(
        "\n".join(lines).rstrip() + "\n",
        encoding="utf-8",
    )


def self_test() -> None:
    cfg = load_config(None)
    assert cfg["enabled"] is True
    assert cfg["restart_cycles"] == 2
    assert cfg["expected_text_regex"] == []

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "required": True,
                    "restart_cycles": 3,
                    "settle_seconds": 2,
                    "expected_text_regex": ["Home", "Saved"],
                    "forbidden_text_regex": ["Fatal error"],
                }
            ),
            encoding="utf-8",
        )
        parsed = load_config(path)
        assert parsed["required"] is True
        assert parsed["restart_cycles"] == 3
        assert len(parsed["expected_text_regex"]) == 2

        findings = check_text_policy(
            '<node text="Home Saved"/>',
            parsed,
            1,
        )
        assert not findings, findings

        findings = check_text_policy(
            '<node text="Fatal error"/>',
            parsed,
            1,
        )
        assert any(x.code == "expected_state_missing" for x in findings)
        assert any(x.code == "forbidden_state_visible" for x in findings)

    print("AppLab Persistence & Restart Lab self-test PASS")


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
        f"AppLab Persistence & Restart Lab: {payload['result']} "
        f"(errors={payload['errors']}, warnings={payload['warnings']})"
    )
    return 1 if payload["result"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
