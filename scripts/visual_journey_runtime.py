#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import visual_journey
import dismiss_foreign_anr


TRANSIENT_RE = re.compile(
    r"Broken pipe|Failure calling service package|device offline|device not found|"
    r"connection reset|closed.*transport|transport.*error",
    re.IGNORECASE,
)


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def ensure_process(package_id: str) -> None:
    result = run(["adb", "shell", "pidof", package_id], capture=True)
    if result.returncode != 0 or not (result.stdout or "").strip():
        raise RuntimeError(f"Application process is not running: {package_id}")


def capture_checkpoint(report_dir: Path, name: str) -> None:
    checkpoint = report_dir / "visual-journey" / "current" / name
    checkpoint.mkdir(parents=True, exist_ok=True)

    screenshot = checkpoint / "screenshot.png"
    with screenshot.open("wb") as handle:
        result = subprocess.run(
            ["adb", "exec-out", "screencap", "-p"],
            check=False,
            stdout=handle,
        )
    if result.returncode != 0 or screenshot.stat().st_size == 0:
        raise RuntimeError(f"Unable to capture screenshot for checkpoint {name}")

    remote = f"/sdcard/applab-journey-{name}.xml"
    dump = run(["adb", "shell", "uiautomator", "dump", remote], capture=True)
    (checkpoint / "uiautomator.txt").write_text(
        dump.stdout or "",
        encoding="utf-8",
    )
    pull = run(["adb", "pull", remote, str(checkpoint / "window.xml")], capture=True)
    hierarchy = checkpoint / "window.xml"
    if pull.returncode != 0 or not hierarchy.is_file() or hierarchy.stat().st_size == 0:
        raise RuntimeError(f"Unable to capture UI hierarchy for checkpoint {name}")


def run_flow(flow: Path, output_dir: Path, name: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        attempt_dir = output_dir / f"{name}-attempt-{attempt}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        result = run(
            [
                "maestro",
                "test",
                str(flow),
                "--test-output-dir",
                str(attempt_dir),
            ],
            capture=True,
        )
        log = output_dir / f"{name}-attempt-{attempt}.log"
        log.write_text(result.stdout or "", encoding="utf-8")
        if result.returncode == 0:
            return
        if not TRANSIENT_RE.search(result.stdout or ""):
            raise RuntimeError(
                f"Maestro checkpoint flow failed: {name}. See {log}."
            )
        run(["adb", "wait-for-device"])
        time.sleep(3)

    raise RuntimeError(f"Maestro checkpoint flow failed after retries: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-root", required=True)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--manifest", default="")
    args = parser.parse_args()

    target_root = Path(args.target_root).resolve()
    report_dir = Path(args.report_dir).resolve()
    manifest = Path(args.manifest).resolve() if args.manifest else (
        target_root / ".maestro" / "applab-journey.json"
    )

    if not manifest.is_file():
        print("AppLab Visual Journey: no custom manifest")
        return 0

    payload = visual_journey.validate_manifest(manifest)
    journey_root = report_dir / "visual-journey"
    journey_root.mkdir(parents=True, exist_ok=True)
    (journey_root / "manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    maestro_root = report_dir / "maestro" / "journey"
    for checkpoint in payload["checkpoints"]:
        name = checkpoint["name"]
        flow = (target_root / checkpoint["flow"]).resolve()
        try:
            flow.relative_to(target_root)
        except ValueError as exc:
            raise RuntimeError(
                f"Checkpoint flow escapes target repository: {flow}"
            ) from exc
        if not flow.is_file():
            raise RuntimeError(f"Checkpoint flow not found: {flow}")

        print(f"[AppLab] Visual Journey checkpoint: {name}")
        dismiss_foreign_anr.dismiss_foreign_anr(args.package_id)
        run_flow(flow, maestro_root, name)
        time.sleep(1)
        ensure_process(args.package_id)
        dismiss_foreign_anr.dismiss_foreign_anr(args.package_id)
        capture_checkpoint(report_dir, name)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"AppLab Visual Journey runtime failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
