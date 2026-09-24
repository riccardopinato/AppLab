#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ANR_SUFFIXES = (" isn't responding", " is not responding")
KNOWN_INFRASTRUCTURE = {
    "pixel launcher",
    "system ui",
    "android system",
    "google play services",
    "google services framework",
}
PACKAGE_LIKE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")
BOUNDS_RE = re.compile(r"\[(\-?\d+),(\-?\d+)\]\[(\-?\d+),(\-?\d+)\]")

def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

def anr_subject(title: str) -> str:
    lowered = title.strip().lower()
    for suffix in ANR_SUFFIXES:
        if lowered.endswith(suffix):
            return title.strip()[: -len(suffix)].strip()
    return ""

def is_foreign_infrastructure(subject: str, package_id: str) -> bool:
    normalized = subject.strip()
    lowered = normalized.lower()
    if not normalized or normalized == package_id:
        return False
    if lowered in KNOWN_INFRASTRUCTURE:
        return True
    return bool(PACKAGE_LIKE.fullmatch(normalized) and normalized != package_id)

def bounds_center(raw: str) -> tuple[int, int] | None:
    match = BOUNDS_RE.fullmatch(raw.strip())
    if not match:
        return None
    x1, y1, x2, y2 = (int(value) for value in match.groups())
    if x2 <= x1 or y2 <= y1:
        return None
    return ((x1 + x2) // 2, (y1 + y2) // 2)

def dismiss_foreign_anr(package_id: str, max_attempts: int = 3) -> int:
    dismissed = 0
    with tempfile.TemporaryDirectory(prefix="applab-anr-") as raw:
        local = Path(raw) / "window.xml"
        remote = "/sdcard/applab-anr-window.xml"

        for _ in range(max_attempts):
            if run(["adb", "shell", "uiautomator", "dump", remote]).returncode != 0:
                return dismissed
            pull = run(["adb", "pull", remote, str(local)])
            if pull.returncode != 0 or not local.is_file():
                return dismissed
            try:
                root = ET.parse(local).getroot()
            except ET.ParseError:
                return dismissed

            title = ""
            close_bounds = ""
            for node in root.iter("node"):
                resource_id = node.attrib.get("resource-id", "")
                if resource_id == "android:id/alertTitle":
                    title = node.attrib.get("text", "")
                elif resource_id == "android:id/aerr_close":
                    close_bounds = node.attrib.get("bounds", "")

            subject = anr_subject(title)
            if not is_foreign_infrastructure(subject, package_id):
                return dismissed

            center = bounds_center(close_bounds)
            if center is None:
                return dismissed

            print(f"[AppLab] dismissing foreign emulator ANR: {subject}", flush=True)
            run(["adb", "shell", "input", "tap", str(center[0]), str(center[1])])
            dismissed += 1
            time.sleep(1)

    return dismissed

def self_test() -> None:
    assert anr_subject("Pixel Launcher isn't responding") == "Pixel Launcher"
    assert anr_subject("com.google.android.googlesdksetup isn't responding") == "com.google.android.googlesdksetup"
    assert is_foreign_infrastructure("Pixel Launcher", "com.example.app")
    assert is_foreign_infrastructure("com.google.android.googlesdksetup", "com.example.app")
    assert not is_foreign_infrastructure("com.example.app", "com.example.app")
    assert not is_foreign_infrastructure("Battery Guard", "com.example.app")
    assert bounds_center("[10,20][110,220]") == (60, 120)
    print("AppLab foreign ANR filter self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.package_id.strip():
        raise SystemExit("--package-id is required")
    dismiss_foreign_anr(args.package_id.strip())
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as exc:
        print(f"AppLab foreign ANR filter failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
