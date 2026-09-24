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
PERMISSION_RE = re.compile(r"^android\.permission\.[A-Z0-9_]+$")


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    evidence: dict[str, Any]


def run(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {
            "schema_version": 1,
            "permissions": {"grant": [], "revoke": []},
            "deep_links": [],
            "biometric": {"enabled": False, "finger_id": 1, "required": False},
            "require_notification": False,
        }

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("system lab config must be an object")
    if int(payload.get("schema_version", 1)) != 1:
        raise ValueError("unsupported system lab config schema")

    allowed = {
        "schema_version",
        "permissions",
        "deep_links",
        "biometric",
        "require_notification",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown system lab keys: {sorted(unknown)}")

    raw_permissions = payload.get("permissions", {})
    if not isinstance(raw_permissions, dict):
        raise ValueError("permissions must be an object")

    grant = raw_permissions.get("grant", [])
    revoke = raw_permissions.get("revoke", [])
    if not isinstance(grant, list) or not isinstance(revoke, list):
        raise ValueError("permissions grant/revoke must be arrays")

    def validated_permissions(values: list[Any]) -> list[str]:
        result: list[str] = []
        for value in values:
            if not isinstance(value, str) or not PERMISSION_RE.fullmatch(value):
                raise ValueError(f"invalid Android permission: {value!r}")
            result.append(value)
        return result

    raw_links = payload.get("deep_links", [])
    if not isinstance(raw_links, list) or len(raw_links) > 12:
        raise ValueError("deep_links must be a bounded array")
    links: list[dict[str, Any]] = []
    for item in raw_links:
        if not isinstance(item, dict):
            raise ValueError("deep link entry must be an object")
        uri = item.get("uri")
        if not isinstance(uri, str) or not uri or len(uri) > 500:
            raise ValueError("deep link uri is invalid")
        links.append(
            {
                "uri": uri,
                "required": bool(item.get("required", True)),
            }
        )

    raw_bio = payload.get("biometric", {})
    if not isinstance(raw_bio, dict):
        raise ValueError("biometric must be an object")
    finger_id = int(raw_bio.get("finger_id", 1))
    if finger_id < 1 or finger_id > 10:
        raise ValueError("biometric finger_id must be 1..10")

    return {
        "schema_version": 1,
        "permissions": {
            "grant": validated_permissions(grant),
            "revoke": validated_permissions(revoke),
        },
        "deep_links": links,
        "biometric": {
            "enabled": bool(raw_bio.get("enabled", False)),
            "finger_id": finger_id,
            "required": bool(raw_bio.get("required", False)),
        },
        "require_notification": bool(payload.get("require_notification", False)),
    }


def pid_of(package_id: str) -> str:
    result = run("adb", "shell", "pidof", package_id)
    return result.stdout.strip().split()[0] if result.stdout.strip() else ""


def wait_for_pid(package_id: str, timeout: float = 15.0) -> str:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        pid = pid_of(package_id)
        if pid:
            return pid
        time.sleep(0.5)
    return ""


def app_crash_state(package_id: str) -> tuple[bool, str]:
    if not pid_of(package_id):
        return True, "application process is not running"
    logcat = run("adb", "logcat", "-b", "all", "-d", "-v", "brief").stdout
    if f"ANR in {package_id}" in logcat:
        return True, "ANR detected"
    fatal = re.search(
        rf"FATAL EXCEPTION:[\s\S]{{0,1800}}Process:\s*{re.escape(package_id)}\b",
        logcat,
    )
    if fatal:
        return True, "fatal exception detected"
    return False, ""


def relaunch(package_id: str) -> str:
    run("adb", "shell", "monkey", "-p", package_id, "-c",
        "android.intent.category.LAUNCHER", "1")
    return wait_for_pid(package_id)


def permission_snapshot(package_id: str) -> dict[str, Any]:
    package_dump = run("adb", "shell", "dumpsys", "package", package_id).stdout
    requested = sorted(set(re.findall(r"android\.permission\.[A-Z0-9_]+", package_dump)))
    appops = run("adb", "shell", "appops", "get", package_id).stdout
    return {
        "requested_permissions": requested,
        "requested_permission_count": len(requested),
        "appops_excerpt": appops[-8000:],
    }


def notification_snapshot(package_id: str) -> dict[str, Any]:
    dump = run("adb", "shell", "dumpsys", "notification", "--noredact").stdout
    matches = [
        line.strip()
        for line in dump.splitlines()
        if package_id in line
    ]
    return {
        "matching_lines": matches[:80],
        "matching_line_count": len(matches),
        "has_notification_evidence": bool(matches),
    }


def service_snapshot(package_id: str) -> dict[str, Any]:
    dump = run("adb", "shell", "dumpsys", "activity", "services", package_id).stdout
    service_records = len(re.findall(r"ServiceRecord\{", dump))
    foreground_markers = len(re.findall(r"(?i)(?:isForeground=true|foregroundId=\d+)", dump))
    return {
        "service_record_count": service_records,
        "foreground_marker_count": foreground_markers,
        "excerpt": dump[-8000:],
    }


def battery_snapshot(package_id: str) -> dict[str, Any]:
    dump = run("adb", "shell", "dumpsys", "deviceidle", "whitelist").stdout
    return {
        "deviceidle_whitelisted": package_id in dump,
    }


def apply_permissions(
    package_id: str,
    config: dict[str, Any],
    findings: list[Finding],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for operation in ("grant", "revoke"):
        for permission in config["permissions"][operation]:
            result = run(
                "adb",
                "shell",
                "pm",
                operation,
                package_id,
                permission,
            )
            success = result.returncode == 0
            actions.append(
                {
                    "operation": operation,
                    "permission": permission,
                    "success": success,
                    "output": result.stdout[-1200:],
                }
            )
            if not success:
                findings.append(
                    Finding(
                        "error",
                        "permission_operation_failed",
                        f"Unable to {operation} configured permission.",
                        {
                            "permission": permission,
                            "output": result.stdout[-1200:],
                        },
                    )
                )
    return actions


def exercise_background_cycle(
    package_id: str,
    findings: list[Finding],
) -> dict[str, Any]:
    before = pid_of(package_id)
    run("adb", "shell", "input", "keyevent", "KEYCODE_HOME")
    time.sleep(1.0)
    background_pid = pid_of(package_id)

    relaunched = relaunch(package_id)
    if not relaunched:
        findings.append(
            Finding(
                "error",
                "resume_failed",
                "Application could not return to foreground after HOME.",
                {},
            )
        )

    return {
        "pid_before": before,
        "pid_background": background_pid,
        "process_survived_background": bool(background_pid),
        "pid_after_resume": relaunched,
    }


def exercise_process_restart(
    package_id: str,
    findings: list[Finding],
) -> dict[str, Any]:
    before = pid_of(package_id)
    run("adb", "shell", "am", "force-stop", package_id)
    time.sleep(0.5)
    after_stop = pid_of(package_id)
    restarted = relaunch(package_id)

    if not restarted:
        findings.append(
            Finding(
                "error",
                "restart_failed",
                "Application failed to relaunch after force-stop.",
                {},
            )
        )

    return {
        "pid_before": before,
        "pid_after_force_stop": after_stop,
        "pid_after_restart": restarted,
        "restart_success": bool(restarted),
    }


def exercise_deep_links(
    package_id: str,
    links: list[dict[str, Any]],
    findings: list[Finding],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in links:
        uri = item["uri"]
        result = run(
            "adb",
            "shell",
            "am",
            "start",
            "-W",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            uri,
            "-p",
            package_id,
        )
        time.sleep(0.8)
        alive = bool(pid_of(package_id))
        command_error = bool(
            re.search(r"(?i)(?:^|\\n)(?:error:|unable to resolve|activity not started)", result.stdout)
        )
        success = result.returncode == 0 and alive and not command_error
        results.append(
            {
                "uri": uri,
                "required": item["required"],
                "success": success,
                "output": result.stdout[-2000:],
            }
        )
        if item["required"] and not success:
            findings.append(
                Finding(
                    "error",
                    "deep_link_failed",
                    "Required deep link did not open successfully.",
                    {"uri": uri, "output": result.stdout[-1200:]},
                )
            )
        elif not success:
            findings.append(
                Finding(
                    "warning",
                    "optional_deep_link_failed",
                    "Optional deep link did not open successfully.",
                    {"uri": uri},
                )
            )
    return results


def exercise_biometric(
    config: dict[str, Any],
    findings: list[Finding],
) -> dict[str, Any]:
    bio = config["biometric"]
    if not bio["enabled"]:
        return {"enabled": False}

    result = run(
        "adb",
        "emu",
        "finger",
        "touch",
        str(bio["finger_id"]),
    )
    success = result.returncode == 0
    if bio["required"] and not success:
        findings.append(
            Finding(
                "error",
                "biometric_injection_failed",
                "Required biometric emulator event failed.",
                {"output": result.stdout[-1200:]},
            )
        )
    elif not success:
        findings.append(
            Finding(
                "warning",
                "biometric_injection_unavailable",
                "Biometric emulator event is unavailable on this AVD.",
                {},
            )
        )
    return {
        "enabled": True,
        "finger_id": bio["finger_id"],
        "required": bio["required"],
        "success": success,
        "output": result.stdout[-1200:],
    }


def evaluate(
    package_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    if not PACKAGE_RE.fullmatch(package_id):
        raise ValueError("invalid package id")

    findings: list[Finding] = []
    initial_pid = pid_of(package_id)
    if not initial_pid:
        restarted = relaunch(package_id)
        if not restarted:
            findings.append(
                Finding(
                    "error",
                    "application_not_running",
                    "Application is not running and could not be relaunched.",
                    {},
                )
            )

    permissions_before = permission_snapshot(package_id)
    permission_actions = apply_permissions(package_id, config, findings)
    permissions_after = permission_snapshot(package_id)

    notifications = notification_snapshot(package_id)
    if config["require_notification"] and not notifications["has_notification_evidence"]:
        findings.append(
            Finding(
                "error",
                "required_notification_missing",
                "No notification evidence was found for the package.",
                {},
            )
        )

    services = service_snapshot(package_id)
    battery = battery_snapshot(package_id)
    background_cycle = exercise_background_cycle(package_id, findings)
    process_restart = exercise_process_restart(package_id, findings)
    deep_links = exercise_deep_links(package_id, config["deep_links"], findings)
    biometric = exercise_biometric(config, findings)

    crashed, crash_reason = app_crash_state(package_id)
    if crashed:
        findings.append(
            Finding(
                "error",
                "runtime_unhealthy",
                "Application runtime is unhealthy after system checks.",
                {"reason": crash_reason},
            )
        )

    errors = [item for item in findings if item.severity == "error"]
    warnings = [item for item in findings if item.severity == "warning"]
    result = "FAIL" if errors else ("WARN" if warnings else "PASS")

    return {
        "schema_version": 1,
        "system_lab_version": "0.6.7",
        "result": result,
        "package_id": package_id,
        "errors": len(errors),
        "warnings": len(warnings),
        "permissions_before": permissions_before,
        "permission_actions": permission_actions,
        "permissions_after": permissions_after,
        "notifications": notifications,
        "services": services,
        "battery": battery,
        "background_cycle": background_cycle,
        "process_restart": process_restart,
        "deep_links": deep_links,
        "biometric": biometric,
        "findings": [asdict(item) for item in findings],
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# AppLab System UI Lab",
        "",
        f"- Result: **{report['result']}**",
        f"- Errors: {report['errors']}",
        f"- Warnings: {report['warnings']}",
        f"- Requested permissions: {report['permissions_after']['requested_permission_count']}",
        f"- Notification evidence: {'yes' if report['notifications']['has_notification_evidence'] else 'no'}",
        f"- Service records: {report['services']['service_record_count']}",
        f"- Foreground service markers: {report['services']['foreground_marker_count']}",
        f"- Background process survived: {'yes' if report['background_cycle']['process_survived_background'] else 'no'}",
        f"- Force-stop restart: {'PASS' if report['process_restart']['restart_success'] else 'FAIL'}",
        "",
        "## Findings",
        "",
    ]
    if report["findings"]:
        for item in report["findings"]:
            lines.append(
                f"- **{item['severity'].upper()} — {item['code']}**: {item['message']}"
            )
    else:
        lines.append("- No system/runtime anomaly detected.")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def self_test() -> None:
    config = load_config(None)
    assert config["permissions"]["grant"] == []
    assert not config["require_notification"]

    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "config.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "permissions": {
                        "grant": ["android.permission.POST_NOTIFICATIONS"],
                        "revoke": [],
                    },
                    "deep_links": [
                        {"uri": "applab://selftest", "required": False}
                    ],
                    "biometric": {
                        "enabled": True,
                        "finger_id": 2,
                        "required": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        parsed = load_config(path)
        assert parsed["permissions"]["grant"] == [
            "android.permission.POST_NOTIFICATIONS"
        ]
        assert parsed["deep_links"][0]["uri"] == "applab://selftest"
        assert parsed["biometric"]["finger_id"] == 2

    try:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "bad.json"
            path.write_text(
                '{"permissions":{"grant":["not.a.permission"]}}',
                encoding="utf-8",
            )
            load_config(path)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid permission must fail")

    print("AppLab System UI Lab self-test PASS")


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
    report = evaluate(args.package_id, config)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "system-lab.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_markdown(report_dir / "system-lab.md", report)
    print(f"AppLab System UI Lab: {report['result']}")
    return 2 if report["result"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
