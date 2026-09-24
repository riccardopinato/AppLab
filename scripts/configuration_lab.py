#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import struct
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
        "rotation_cycles": 2,
        "background_cycles": 2,
        "settle_seconds": 1.0,
        "expected_text_regex": [],
        "forbidden_text_regex": [],
    }
    if path is None or not path.is_file():
        return defaults
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("configuration lab config must be an object")
    if int(payload.get("schema_version", 1)) != 1:
        raise ValueError("unsupported configuration lab schema")
    allowed = {
        "schema_version",
        "enabled",
        "required",
        "rotation_cycles",
        "background_cycles",
        "settle_seconds",
        "expected_text_regex",
        "forbidden_text_regex",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown configuration lab keys: {sorted(unknown)}")

    rotation_cycles = int(payload.get("rotation_cycles", 2))
    background_cycles = int(payload.get("background_cycles", 2))
    settle = float(payload.get("settle_seconds", 1.0))
    if not 0 <= rotation_cycles <= 5:
        raise ValueError("rotation_cycles must be between 0 and 5")
    if not 0 <= background_cycles <= 10:
        raise ValueError("background_cycles must be between 0 and 10")
    if not 0.25 <= settle <= 10.0:
        raise ValueError("settle_seconds must be between 0.25 and 10")

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
        "rotation_cycles": rotation_cycles,
        "background_cycles": background_cycles,
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


def capture_png(report_dir: Path, name: str) -> tuple[int, int]:
    raw = subprocess.run(
        ["adb", "exec-out", "screencap", "-p"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=20,
        check=False,
    )
    path = report_dir / f"{name}.png"
    if raw.returncode != 0 or len(raw.stdout) < 24:
        return 0, 0
    path.write_bytes(raw.stdout)
    if raw.stdout[:8] != b"\x89PNG\r\n\x1a\n":
        return 0, 0
    return struct.unpack(">II", raw.stdout[16:24])


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


def text_findings(ui: str, config: dict[str, Any], stage: str) -> list[Finding]:
    findings: list[Finding] = []
    for pattern in config["expected_text_regex"]:
        if not re.search(pattern, ui, flags=re.IGNORECASE):
            findings.append(
                Finding(
                    "error" if config["required"] else "warning",
                    "expected_state_missing",
                    "Expected UI state was not visible after lifecycle/configuration change.",
                    {"stage": stage, "pattern": pattern},
                )
            )
    for pattern in config["forbidden_text_regex"]:
        if re.search(pattern, ui, flags=re.IGNORECASE):
            findings.append(
                Finding(
                    "error",
                    "forbidden_state_visible",
                    "Forbidden reset/error state was visible after lifecycle/configuration change.",
                    {"stage": stage, "pattern": pattern},
                )
            )
    return findings


def snapshot_stage(
    package_id: str,
    report_dir: Path,
    name: str,
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[Finding]]:
    ui = dump_ui(report_dir, name)
    size = capture_png(report_dir, name)
    unhealthy = runtime_unhealthy(package_id)
    findings: list[Finding] = []
    if unhealthy:
        findings.append(
            Finding(
                "error",
                "runtime_unhealthy",
                "Application became unhealthy during configuration/lifecycle stress.",
                {"stage": name, "reason": unhealthy},
            )
        )
    if not ui:
        findings.append(
            Finding(
                "error" if config["required"] else "warning",
                "ui_hierarchy_missing",
                "UI hierarchy could not be captured.",
                {"stage": name},
            )
        )
    else:
        findings.extend(text_findings(ui, config, name))
    return {
        "stage": name,
        "pid": pid_of(package_id),
        "screenshot_width": size[0],
        "screenshot_height": size[1],
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
    stages: list[dict[str, Any]] = []

    if not config["enabled"]:
        return {
            "schema_version": 1,
            "configuration_lab_version": "0.7.6",
            "result": "SKIPPED",
            "package_id": package_id,
            "config": config,
            "stages": [],
            "findings": [],
            "errors": 0,
            "warnings": 0,
        }

    initial_pid = pid_of(package_id) or launch(package_id)
    if not initial_pid:
        findings.append(
            Finding("error", "application_not_running", "Application could not be started.", {})
        )

    auto_rotation = adb("shell", "settings", "get", "system", "accelerometer_rotation", timeout=10).stdout.strip()
    user_rotation = adb("shell", "settings", "get", "system", "user_rotation", timeout=10).stdout.strip()

    try:
        adb("shell", "settings", "put", "system", "accelerometer_rotation", "0", timeout=10)
        for cycle in range(1, config["rotation_cycles"] + 1):
            adb("shell", "settings", "put", "system", "user_rotation", "1", timeout=10)
            time.sleep(config["settle_seconds"])
            stage, extra = snapshot_stage(
                package_id, report_dir, f"config-landscape-{cycle}", config
            )
            stages.append(stage)
            findings.extend(extra)

            adb("shell", "settings", "put", "system", "user_rotation", "0", timeout=10)
            time.sleep(config["settle_seconds"])
            stage, extra = snapshot_stage(
                package_id, report_dir, f"config-portrait-{cycle}", config
            )
            stages.append(stage)
            findings.extend(extra)

        for cycle in range(1, config["background_cycles"] + 1):
            adb("shell", "input", "keyevent", "KEYCODE_HOME", timeout=10)
            time.sleep(config["settle_seconds"])
            background_pid = pid_of(package_id)
            foreground_pid = launch(package_id)
            time.sleep(config["settle_seconds"])
            stage, extra = snapshot_stage(
                package_id, report_dir, f"config-foreground-{cycle}", config
            )
            stage["background_pid"] = background_pid
            stage["foreground_pid"] = foreground_pid
            stages.append(stage)
            findings.extend(extra)
            if not foreground_pid:
                findings.append(
                    Finding(
                        "error",
                        "foreground_return_failed",
                        "Application failed to return to foreground.",
                        {"cycle": cycle},
                    )
                )
    finally:
        if user_rotation in {"0", "1", "2", "3"}:
            adb("shell", "settings", "put", "system", "user_rotation", user_rotation, timeout=10)
        if auto_rotation in {"0", "1"}:
            adb("shell", "settings", "put", "system", "accelerometer_rotation", auto_rotation, timeout=10)

    rotation_samples = [
        x for x in stages if x["stage"].startswith("config-landscape-")
    ]
    if config["rotation_cycles"] and rotation_samples:
        observed = any(
            int(x["screenshot_width"]) > int(x["screenshot_height"])
            for x in rotation_samples
            if x["screenshot_width"] and x["screenshot_height"]
        )
        if not observed:
            findings.append(
                Finding(
                    "error" if config["required"] else "warning",
                    "landscape_not_observed",
                    "Landscape display geometry was not observed during rotation stress.",
                    {},
                )
            )

    errors = sum(1 for x in findings if x.severity == "error")
    warnings = sum(1 for x in findings if x.severity == "warning")
    result = "FAIL" if errors else ("WARN" if warnings else "PASS")
    return {
        "schema_version": 1,
        "configuration_lab_version": "0.7.6",
        "result": result,
        "package_id": package_id,
        "config": config,
        "initial_pid": initial_pid,
        "stages": stages,
        "findings": [asdict(x) for x in findings],
        "errors": errors,
        "warnings": warnings,
    }


def write_report(payload: dict[str, Any], report_dir: Path) -> None:
    (report_dir / "configuration-lab.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Configuration & Lifecycle Stress Lab",
        "",
        f"- Result: {payload['result']}",
        f"- Package: {payload['package_id']}",
        f"- Stages: {len(payload.get('stages', []))}",
        f"- Errors: {payload.get('errors', 0)}",
        f"- Warnings: {payload.get('warnings', 0)}",
        "",
    ]
    for item in payload.get("findings", []):
        lines.append(f"- {item['severity'].upper()} {item['code']}: {item['message']}")
    (report_dir / "configuration-lab.md").write_text(
        "\n".join(lines).rstrip() + "\n",
        encoding="utf-8",
    )


def self_test() -> None:
    cfg = load_config(None)
    assert cfg["rotation_cycles"] == 2
    assert cfg["background_cycles"] == 2
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "required": True,
                    "rotation_cycles": 1,
                    "background_cycles": 3,
                    "expected_text_regex": ["Home"],
                }
            ),
            encoding="utf-8",
        )
        parsed = load_config(path)
        assert parsed["required"] is True
        assert parsed["background_cycles"] == 3
        assert not text_findings('<node text="Home"/>', parsed, "test")
    print("AppLab Configuration & Lifecycle Stress Lab self-test PASS")


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
        f"AppLab Configuration & Lifecycle Stress Lab: {payload['result']} "
        f"(errors={payload['errors']}, warnings={payload['warnings']})"
    )
    return 1 if payload["result"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
