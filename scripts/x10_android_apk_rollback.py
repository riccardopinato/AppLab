#!/usr/bin/env python3
"""X10-032: destructive TEST-FIXTURE-ONLY downgrade rehearsal on a hosted emulator.

Never run against a personal phone, a production package, or real user data.
Produces untrusted emulator evidence, not a physical/Play/Golden receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

PACKAGE = "dev.applab.selftest"
CANARY = "X10_EMULATOR_ONLY_SYNTHETIC_DATA_v1"
RELATIVE_CANARY = "files/x10_rollback_canary.txt"


def run(*cmd: str, expected_success: bool = True) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(list(cmd), capture_output=True, text=True, check=False, timeout=180)
    if expected_success and p.returncode != 0:
        raise RuntimeError(f"COMMAND_FAILED:{cmd[0]}:{p.stderr[:350]}:{p.stdout[:350]}")
    return p


def apk_metadata(apk: Path, code: int, tools: Path) -> dict[str, str | int]:
    if not apk.is_file() or apk.stat().st_size == 0:
        raise ValueError("APK_MISSING")
    badging = run(str(tools / "aapt"), "dump", "badging", str(apk)).stdout
    match = re.search(r"^package: name='([^']+)' versionCode='(\d+)'", badging, re.M)
    if not match or match.group(1) != PACKAGE or int(match.group(2)) != code:
        raise ValueError("TEST_PACKAGE_OR_VERSION_MISMATCH")
    cert = run(str(tools / "apksigner"), "verify", "--print-certs", str(apk)).stdout
    match = re.search(r"Signer #1 certificate SHA-256 digest:\s*([0-9a-fA-F]{64})", cert)
    if not match:
        raise ValueError("APK_SIGNATURE_NOT_VERIFIED")
    return {"version_code": code, "sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
            "signer_sha256": match.group(1).lower()}


def assert_emulator() -> dict[str, str]:
    serial = run("adb", "-e", "get-serialno").stdout.strip()
    qemu = run("adb", "-e", "shell", "getprop", "ro.kernel.qemu").stdout.strip()
    if not serial.startswith("emulator-") or qemu != "1":
        raise RuntimeError("REAL_DEVICE_FORBIDDEN")
    return {"serial_type": "emulator", "android_api": run(
        "adb", "-e", "shell", "getprop", "ro.build.version.sdk").stdout.strip(),
        "build_fingerprint": run(
        "adb", "-e", "shell", "getprop", "ro.build.fingerprint").stdout.strip()}


def adb(*args: str, expected_success: bool = True) -> subprocess.CompletedProcess[str]:
    return run("adb", "-e", *args, expected_success=expected_success)


def installed_version() -> int:
    output = adb("shell", "dumpsys", "package", PACKAGE).stdout
    found = re.search(r"\bversionCode=(\d+)\b", output)
    if not found:
        raise RuntimeError("INSTALLED_VERSION_NOT_FOUND")
    return int(found.group(1))


def canary_read() -> str:
    value = adb("shell", "run-as", PACKAGE, "cat", RELATIVE_CANARY).stdout.strip()
    if value != CANARY:
        raise RuntimeError("PERSISTED_CANARY_MISMATCH")
    return value


def stage(apk: Path, expected: int) -> None:
    adb("install", "-r", str(apk))
    if installed_version() != expected:
        raise RuntimeError("APK_INSTALL_VERSION_MISMATCH")
    adb("shell", "am", "start", "-n", f"{PACKAGE}/.MainActivity")


def rehearse(old: Path, new: Path, tools: Path) -> dict:
    checked_out = run("git", "rev-parse", "HEAD").stdout.strip()
    expected = os.environ.get("X10_EXPECTED_SOURCE_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", checked_out) or checked_out != expected:
        raise RuntimeError("EXACT_SOURCE_SHA_MISMATCH")
    before = apk_metadata(old, 101, tools)
    after = apk_metadata(new, 102, tools)
    if before["sha256"] == after["sha256"] or before["signer_sha256"] != after["signer_sha256"]:
        raise ValueError("SIGNATURE_OR_VERSION_BINARY_MISMATCH")
    device = assert_emulator()  # must happen BEFORE even fixture-only uninstall
    adb("uninstall", PACKAGE, expected_success=False)  # disposable emulator package only
    stage(old, 101)
    adb("shell", f"run-as {PACKAGE} sh -c 'mkdir -p files && echo {CANARY} > {RELATIVE_CANARY}'")
    canary_read()
    stage(new, 102)
    canary_read()
    forbidden = adb("install", "-r", str(old), expected_success=False)
    if forbidden.returncode == 0 or "INSTALL_FAILED_VERSION_DOWNGRADE" not in (
        forbidden.stdout + forbidden.stderr):
        raise RuntimeError("NORMAL_DOWNGRADE_NOT_REJECTED_AS_EXPECTED")
    if installed_version() != 102:
        raise RuntimeError("REJECTED_DOWNGRADE_CHANGED_VERSION")
    canary_read()
    # -d is a debug/test-only rehearsal. Do not offer this for signed production APKs.
    accepted = adb("install", "-r", "-d", str(old), expected_success=False)
    if accepted.returncode != 0:
        raise RuntimeError("DEBUG_DOWNGRADE_NOT_SUPPORTED_BY_EMULATOR")
    if installed_version() != 101:
        raise RuntimeError("DEBUG_DOWNGRADE_VERSION_MISMATCH")
    adb("shell", "am", "start", "-n", f"{PACKAGE}/.MainActivity")
    canary_read()
    return {"schema_version": 1, "result": "EMULATOR_DEBUG_ROLLBACK_PASS",
            "factory_baseline": "c5adc147046beb7024629466d10eeb799c3c2619",
            "source_sha": checked_out,
            "workflow_run_id": os.environ.get("GITHUB_RUN_ID", ""),
            "test_package": PACKAGE, "build_type": "debug",
            "old_apk": before, "new_apk": after, "device": device,
            "checks": ["same_signer", "version_101_install", "synthetic_file_written",
                       "version_102_upgrade", "synthetic_file_retained",
                       "unflagged_downgrade_rejected_without_state_change",
                       "debug_downgrade_101", "synthetic_file_retained_after_downgrade"],
            "physical_device_verified": False, "real_app_data_verified": False,
            "signed_release_rollback_verified": False, "play_verified": False,
            "golden_admission": False}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--old", type=Path, required=True)
    p.add_argument("--new", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    root = os.environ.get("ANDROID_HOME", "")
    if not root:
        raise RuntimeError("ANDROID_HOME_REQUIRED")
    proof = rehearse(a.old, a.new, Path(root) / "build-tools/36.0.0")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
    print("PASS: isolated emulator DEBUG APK upgrade -> rejected normal downgrade "
          "-> debug-only rollback, synthetic data retained. NOT DEVICE/PLAY/GOLDEN.")


if __name__ == "__main__":
    main()
