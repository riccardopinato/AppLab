#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
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


def run(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
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
        "settle_seconds": 2.0,
        "expected_text_regex": [],
        "forbidden_text_regex": [],
    }
    if path is None or not path.is_file():
        return defaults
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("upgrade lab config must be an object")
    if int(payload.get("schema_version", 1)) != 1:
        raise ValueError("unsupported upgrade lab config schema")
    allowed = {
        "schema_version",
        "enabled",
        "required",
        "settle_seconds",
        "expected_text_regex",
        "forbidden_text_regex",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown upgrade lab keys: {sorted(unknown)}")
    settle = float(payload.get("settle_seconds", 2.0))
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
        "settle_seconds": settle,
        "expected_text_regex": regex_list("expected_text_regex"),
        "forbidden_text_regex": regex_list("forbidden_text_regex"),
    }


def find_tool(name: str) -> str:
    direct = shutil.which(name)
    if direct:
        return direct
    sdk = os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT")
    if sdk:
        candidates = sorted((Path(sdk) / "build-tools").glob(f"*/{name}"), reverse=True)
        if candidates:
            return str(candidates[0])
    return ""


def apk_identity(apk: Path) -> dict[str, str]:
    out = {"package_id": "", "version_name": "", "version_code": ""}
    aapt = find_tool("aapt")
    if aapt:
        result = run(aapt, "dump", "badging", str(apk))
        line = next((x for x in result.stdout.splitlines() if x.startswith("package:")), "")
        for key, pattern in {
            "package_id": r"name='([^']*)'",
            "version_name": r"versionName='([^']*)'",
            "version_code": r"versionCode='([^']*)'",
        }.items():
            match = re.search(pattern, line)
            if match:
                out[key] = match.group(1).strip()
    if not out["package_id"]:
        apkanalyzer = find_tool("apkanalyzer")
        if apkanalyzer:
            for key, parts in {
                "package_id": ("manifest", "application-id"),
                "version_name": ("manifest", "version-name"),
                "version_code": ("manifest", "version-code"),
            }.items():
                result = run(apkanalyzer, *parts, str(apk))
                if result.returncode == 0:
                    out[key] = result.stdout.strip()
    return out


def generate_keystore(path: Path) -> None:
    keytool = shutil.which("keytool")
    if not keytool:
        raise RuntimeError("keytool is unavailable")
    result = run(
        keytool,
        "-genkeypair",
        "-noprompt",
        "-keystore",
        str(path),
        "-storepass",
        "android",
        "-keypass",
        "android",
        "-alias",
        "applab",
        "-keyalg",
        "RSA",
        "-keysize",
        "2048",
        "-validity",
        "3650",
        "-dname",
        "CN=AppLab Upgrade Test,O=AppLab,C=US",
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"keytool failed: {result.stdout[-2000:]}")


def sign_apk(source: Path, output: Path, keystore: Path) -> None:
    apksigner = find_tool("apksigner")
    if not apksigner:
        raise RuntimeError("apksigner is unavailable")
    result = run(
        apksigner,
        "sign",
        "--ks",
        str(keystore),
        "--ks-key-alias",
        "applab",
        "--ks-pass",
        "pass:android",
        "--key-pass",
        "pass:android",
        "--out",
        str(output),
        str(source),
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"apksigner failed: {result.stdout[-3000:]}")
    verify = run(apksigner, "verify", str(output), timeout=60)
    if verify.returncode != 0:
        raise RuntimeError(f"signed APK verification failed: {verify.stdout[-2000:]}")


def pid_of(package_id: str) -> str:
    result = adb("shell", "pidof", package_id, timeout=10)
    return result.stdout.strip().split()[0] if result.stdout.strip() else ""


def wait_for_pid(package_id: str, timeout: float = 20.0) -> str:
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


def check_text_policy(ui: str, config: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for pattern in config["expected_text_regex"]:
        if not re.search(pattern, ui, flags=re.IGNORECASE):
            findings.append(
                Finding(
                    "error" if config["required"] else "warning",
                    "expected_state_missing_after_upgrade",
                    "Expected UI state was not visible after upgrade.",
                    {"pattern": pattern},
                )
            )
    for pattern in config["forbidden_text_regex"]:
        if re.search(pattern, ui, flags=re.IGNORECASE):
            findings.append(
                Finding(
                    "error",
                    "forbidden_state_visible_after_upgrade",
                    "Forbidden reset/error UI state was visible after upgrade.",
                    {"pattern": pattern},
                )
            )
    return findings


def evaluate(
    package_id: str,
    baseline_apk: Path | None,
    current_apk: Path,
    config: dict[str, Any],
    report_dir: Path,
) -> dict[str, Any]:
    if not PACKAGE_RE.fullmatch(package_id):
        raise ValueError("invalid package id")
    if not current_apk.is_file():
        raise ValueError("current APK is missing")
    report_dir.mkdir(parents=True, exist_ok=True)

    base_payload = {
        "schema_version": 1,
        "upgrade_lab_version": "0.7.5",
        "package_id": package_id,
        "config": config,
        "baseline": {},
        "current": apk_identity(current_apk),
        "findings": [],
        "errors": 0,
        "warnings": 0,
    }
    if not config["enabled"]:
        return {**base_payload, "result": "SKIPPED"}
    if baseline_apk is None or not baseline_apk.is_file():
        return {**base_payload, "result": "NO_BASELINE"}

    baseline_identity = apk_identity(baseline_apk)
    current_identity = base_payload["current"]
    base_payload["baseline"] = baseline_identity

    baseline_package = baseline_identity.get("package_id", "")
    current_package = current_identity.get("package_id", "")
    if baseline_package and baseline_package != package_id:
        severity = "error" if config["required"] else "warning"
        finding = Finding(
            severity,
            "baseline_package_mismatch",
            "Previous PASS APK uses a different package id.",
            {"baseline": baseline_package, "expected": package_id},
        )
        return {
            **base_payload,
            "result": "FAIL" if severity == "error" else "WARN",
            "findings": [asdict(finding)],
            "errors": 1 if severity == "error" else 0,
            "warnings": 0 if severity == "error" else 1,
        }
    if current_package and current_package != package_id:
        raise ValueError("current APK package id does not match verifier package id")

    findings: list[Finding] = []
    with tempfile.TemporaryDirectory(prefix="applab-upgrade-") as raw:
        temp = Path(raw)
        keystore = temp / "applab-upgrade.jks"
        old_signed = temp / "baseline-signed.apk"
        new_signed = temp / "current-signed.apk"
        try:
            generate_keystore(keystore)
            sign_apk(baseline_apk, old_signed, keystore)
            sign_apk(current_apk, new_signed, keystore)
        except RuntimeError as exc:
            severity = "error" if config["required"] else "warning"
            findings.append(
                Finding(
                    severity,
                    "test_signing_unavailable",
                    "AppLab could not prepare same-key APK copies for upgrade testing.",
                    {"reason": str(exc)},
                )
            )
            errors = sum(x.severity == "error" for x in findings)
            warnings = sum(x.severity == "warning" for x in findings)
            return {
                **base_payload,
                "result": "FAIL" if errors else "WARN",
                "findings": [asdict(x) for x in findings],
                "errors": errors,
                "warnings": warnings,
            }

        adb("uninstall", package_id, timeout=30)
        adb("logcat", "-b", "all", "-c", timeout=20)
        install_old = adb("install", "-t", str(old_signed), timeout=120)
        if install_old.returncode != 0:
            findings.append(
                Finding(
                    "error",
                    "baseline_install_failed",
                    "Previous PASS APK could not be installed.",
                    {"output": install_old.stdout[-3000:]},
                )
            )
        old_pid = launch(package_id) if install_old.returncode == 0 else ""
        time.sleep(config["settle_seconds"])
        old_unhealthy = runtime_unhealthy(package_id) if old_pid else "application did not launch"
        old_ui = dump_ui(report_dir, "upgrade-before") if old_pid else ""
        capture(report_dir, "upgrade-before")
        if old_unhealthy:
            findings.append(
                Finding(
                    "error",
                    "baseline_runtime_unhealthy",
                    "Previous PASS APK was unhealthy before upgrade.",
                    {"reason": old_unhealthy},
                )
            )

        adb("logcat", "-b", "all", "-c", timeout=20)
        upgrade = adb("install", "-r", "-t", str(new_signed), timeout=120)
        if upgrade.returncode != 0:
            findings.append(
                Finding(
                    "error",
                    "upgrade_install_failed",
                    "Current APK could not replace the previous PASS APK in place.",
                    {"output": upgrade.stdout[-3000:]},
                )
            )
        new_pid = launch(package_id) if upgrade.returncode == 0 else ""
        time.sleep(config["settle_seconds"])
        new_unhealthy = runtime_unhealthy(package_id) if new_pid else "application did not launch"
        new_ui = dump_ui(report_dir, "upgrade-after") if new_pid else ""
        capture(report_dir, "upgrade-after")
        if new_unhealthy:
            findings.append(
                Finding(
                    "error",
                    "upgraded_runtime_unhealthy",
                    "Application was unhealthy after in-place upgrade.",
                    {"reason": new_unhealthy},
                )
            )
        if not new_ui:
            findings.append(
                Finding(
                    "error" if config["required"] else "warning",
                    "post_upgrade_ui_missing",
                    "UI hierarchy could not be captured after upgrade.",
                    {},
                )
            )
        else:
            findings.extend(check_text_policy(new_ui, config))

    errors = sum(1 for x in findings if x.severity == "error")
    warnings = sum(1 for x in findings if x.severity == "warning")
    result = "FAIL" if errors else ("WARN" if warnings else "PASS")
    return {
        **base_payload,
        "result": result,
        "baseline": baseline_identity,
        "current": current_identity,
        "upgrade": {
            "baseline_pid": old_pid if "old_pid" in locals() else "",
            "current_pid": new_pid if "new_pid" in locals() else "",
            "in_place_install_succeeded": bool(
                "upgrade" in locals() and upgrade.returncode == 0
            ),
            "baseline_ui_captured": bool(old_ui) if "old_ui" in locals() else False,
            "current_ui_captured": bool(new_ui) if "new_ui" in locals() else False,
        },
        "findings": [asdict(x) for x in findings],
        "errors": errors,
        "warnings": warnings,
    }


def write_report(payload: dict[str, Any], report_dir: Path) -> None:
    (report_dir / "upgrade-lab.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Upgrade & Migration Lab",
        "",
        f"- Result: {payload['result']}",
        f"- Package: {payload['package_id']}",
        f"- Previous version: {payload.get('baseline', {}).get('version_name') or 'unknown'}",
        f"- Current version: {payload.get('current', {}).get('version_name') or 'unknown'}",
        f"- Errors: {payload.get('errors', 0)}",
        f"- Warnings: {payload.get('warnings', 0)}",
        "",
    ]
    for item in payload.get("findings", []):
        lines.append(f"- {item['severity'].upper()} {item['code']}: {item['message']}")
    (report_dir / "upgrade-lab.md").write_text(
        "\n".join(lines).rstrip() + "\n",
        encoding="utf-8",
    )


def self_test() -> None:
    cfg = load_config(None)
    assert cfg["enabled"] is True
    assert cfg["required"] is False
    assert cfg["expected_text_regex"] == []
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "policy.json"
        path.write_text(
            json.dumps({
                "schema_version": 1,
                "required": True,
                "settle_seconds": 1,
                "expected_text_regex": ["Home"],
                "forbidden_text_regex": ["Fatal"],
            }),
            encoding="utf-8",
        )
        parsed = load_config(path)
        assert parsed["required"] is True
        assert not check_text_policy('<node text="Home"/>', parsed)
        findings = check_text_policy('<node text="Fatal"/>', parsed)
        assert len(findings) == 2
    print("AppLab Upgrade & Migration Lab self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id")
    parser.add_argument("--baseline-apk")
    parser.add_argument("--current-apk")
    parser.add_argument("--report-dir", default="applab-report")
    parser.add_argument("--config")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.package_id or not args.current_apk:
        parser.error("--package-id and --current-apk are required")
    config = load_config(Path(args.config) if args.config else None)
    baseline = Path(args.baseline_apk) if args.baseline_apk else None
    report_dir = Path(args.report_dir)
    payload = evaluate(
        args.package_id,
        baseline,
        Path(args.current_apk),
        config,
        report_dir,
    )
    write_report(payload, report_dir)
    print(
        f"AppLab Upgrade & Migration Lab: {payload['result']} "
        f"(errors={payload['errors']}, warnings={payload['warnings']})"
    )
    return 1 if payload["result"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
