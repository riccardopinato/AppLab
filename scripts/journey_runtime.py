#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import project_adapter

SCHEMA_VERSION = 1
ENGINE_VERSION = "5.9B"
TRANSIENT_RE = re.compile(
    r"Broken pipe|Failure calling service package|device offline|device not found|"
    r"connection reset|closed.*transport|transport.*error",
    re.IGNORECASE,
)
SYSTEM_TRANSIENT_RE = re.compile(
    r"DeadSystemException|registerUiTestAutomationService.*null object reference|"
    r"UiAutomationConnection.*NullPointerException|system_server.*(died|crash|restarting)|"
    r"ServiceManager.*(dead|Bad file descriptor)",
    re.IGNORECASE,
)


class LegacyFallback(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LegacyFallback(f"unreadable JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise LegacyFallback(f"JSON object required: {path}")
    return payload


def pilot_repositories(root: Path) -> set[str]:
    payload = read_json(root / "config" / "journey-runtime-pilots.json")
    if payload.get("schema_version") != 1:
        raise LegacyFallback("unsupported journey pilot config")
    values = payload.get("repositories")
    if not isinstance(values, list) or len(values) > 64:
        raise LegacyFallback("invalid journey pilot repository list")
    result: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
            raise LegacyFallback("invalid journey pilot repository")
        result.add(value.lower())
    return result


def selected_catalog(
    *,
    target_root: Path,
    plan: dict[str, Any],
    repository: str,
    trusted_root: Path,
) -> list[tuple[str, Path]]:
    if repository.lower() not in pilot_repositories(trusted_root):
        raise LegacyFallback("repository is not admitted to atomic journey execution")

    selection = plan.get("journey_selection")
    selected = plan.get("selected_journeys")
    if not isinstance(selection, dict) or not isinstance(selected, list):
        raise LegacyFallback("journey planning evidence is absent")
    if not selected or len(selected) > project_adapter.MAX_JOURNEY_CATALOG:
        raise LegacyFallback("no bounded journey selection")
    if not all(isinstance(value, str) for value in selected):
        raise LegacyFallback("invalid selected journey id")
    lane = str(plan.get("lane", ""))
    if lane == "FAST_RUNTIME":
        if selection.get("enforcement_eligible") is not True:
            raise LegacyFallback("FAST journey selection is not enforcement eligible")
        if selection.get("unmatched_paths"):
            raise LegacyFallback("FAST journey selection has uncovered runtime paths")
    elif lane not in {"FULL_RUNTIME", "CERTIFICATION"}:
        raise LegacyFallback(f"unsupported runtime lane: {lane}")

    config, _ = project_adapter.load_config(target_root)
    journeys = config.get("journeys", {}) if isinstance(config, dict) else {}
    if not isinstance(journeys, dict):
        raise LegacyFallback("journeys config is invalid")
    catalog = project_adapter.normalize_journey_catalog(
        target_root,
        journeys.get("catalog", {}),
    )
    if not catalog:
        raise LegacyFallback("journey catalog is absent")
    if lane in {"FULL_RUNTIME", "CERTIFICATION"} and set(selected) != set(catalog):
        raise LegacyFallback("FULL/CERTIFICATION must select the complete journey catalog")
    unknown = [value for value in selected if value not in catalog]
    if unknown:
        raise LegacyFallback("selected journey is not present in catalog")

    result: list[tuple[str, Path]] = []
    root = target_root.resolve()
    for journey_id in selected:
        flow = (target_root / catalog[journey_id]["flow"]).resolve()
        try:
            flow.relative_to(root)
        except ValueError as exc:
            raise LegacyFallback("journey flow escapes target evidence root") from exc
        if not flow.is_file():
            raise LegacyFallback(f"journey flow is missing: {journey_id}")
        result.append((journey_id, flow))
    return result


def adb(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["adb", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def relaunch(package_id: str) -> None:
    adb("wait-for-device", timeout=60)
    adb("shell", "am", "force-stop", package_id)
    adb(
        "shell", "monkey", "-p", package_id,
        "-c", "android.intent.category.LAUNCHER", "1",
        timeout=30,
    )
    time.sleep(2)


def system_transient(report_dir: Path, journey_id: str, attempt: int) -> bool:
    log = adb("logcat", "-b", "all", "-d", "-v", "threadtime", timeout=30)
    path = report_dir / "journeys" / journey_id / f"attempt-{attempt}-system-logcat.txt"
    path.write_text((log.stdout or "") + (log.stderr or ""), encoding="utf-8")
    return bool(SYSTEM_TRANSIENT_RE.search(path.read_text(encoding="utf-8", errors="ignore")))


def recover(package_id: str) -> None:
    adb("wait-for-device", timeout=60)
    for _ in range(30):
        boot = adb("shell", "getprop", "sys.boot_completed", timeout=10)
        packages = adb("shell", "cmd", "package", "list", "packages", "android", timeout=10)
        accessibility = adb("shell", "service", "check", "accessibility", timeout=10)
        if boot.stdout.strip() == "1" and packages.returncode == 0 and accessibility.returncode == 0:
            break
        time.sleep(2)
    relaunch(package_id)
    adb("logcat", "-b", "all", "-c", timeout=10)


def wrapper_text(package_id: str, flow: Path) -> str:
    flow_value = json.dumps(str(flow))
    return (
        f"appId: {package_id}\n---\n"
        "- runFlow:\n"
        '    when:\n      visible: "Pixel Launcher isn\'t responding"\n'
        "    commands:\n"
        '      - tapOn:\n          text: "Close app"\n          optional: true\n'
        "- runFlow:\n"
        f"    file: {flow_value}\n"
    )


def run_journey(
    *,
    journey_id: str,
    flow: Path,
    package_id: str,
    report_dir: Path,
    max_attempts: int,
) -> dict[str, Any]:
    root = report_dir / "journeys" / journey_id
    root.mkdir(parents=True, exist_ok=True)
    wrapper = root / "wrapper.yaml"
    wrapper.write_text(wrapper_text(package_id, flow), encoding="utf-8")
    started = time.monotonic()
    attempts: list[dict[str, Any]] = []

    for attempt in range(1, max_attempts + 1):
        relaunch(package_id)
        output_dir = root / f"attempt-{attempt}"
        output_dir.mkdir(parents=True, exist_ok=True)
        console = root / f"attempt-{attempt}.log"
        run_started = time.monotonic()
        completed = subprocess.run(
            ["maestro", "test", str(wrapper), "--test-output-dir", str(output_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        text = (completed.stdout or "") + (completed.stderr or "")
        console.write_text(text, encoding="utf-8")
        transient = bool(TRANSIENT_RE.search(text))
        if completed.returncode != 0 and not transient:
            transient = system_transient(report_dir, journey_id, attempt)
        attempts.append(
            {
                "attempt": attempt,
                "result": "PASS" if completed.returncode == 0 else "FAIL",
                "transient": transient,
                "seconds": round(time.monotonic() - run_started, 3),
                "log": str(console.relative_to(report_dir)),
            }
        )
        if completed.returncode == 0:
            return {
                "id": journey_id,
                "flow": str(flow),
                "result": "PASS",
                "attempts": attempts,
                "seconds": round(time.monotonic() - started, 3),
            }
        if not transient:
            return {
                "id": journey_id,
                "flow": str(flow),
                "result": "FAIL",
                "attempts": attempts,
                "seconds": round(time.monotonic() - started, 3),
                "reason": "functional Maestro failure; not retried",
            }
        if attempt < max_attempts:
            recover(package_id)

    return {
        "id": journey_id,
        "flow": str(flow),
        "result": "FAIL",
        "attempts": attempts,
        "seconds": round(time.monotonic() - started, 3),
        "reason": "transient infrastructure retries exhausted",
    }


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def execute(args: argparse.Namespace) -> int:
    report_dir = Path(args.report_dir).resolve()
    output = report_dir / "journey-runtime.json"
    trusted_root = Path(args.trusted_root).resolve()
    target_root = Path(args.target_root).resolve()
    plan = read_json(Path(args.plan).resolve())
    started = time.monotonic()
    try:
        journeys = selected_catalog(
            target_root=target_root,
            plan=plan,
            repository=args.repository,
            trusted_root=trusted_root,
        )
    except LegacyFallback as exc:
        write_report(
            output,
            {
                "schema_version": SCHEMA_VERSION,
                "engine_version": ENGINE_VERSION,
                "result": "LEGACY_FALLBACK",
                "repository": args.repository,
                "coverage_reduction_enabled": False,
                "reason": str(exc),
                "journeys": [],
            },
        )
        return 3

    rows: list[dict[str, Any]] = []
    for journey_id, flow in journeys:
        row = run_journey(
            journey_id=journey_id,
            flow=flow,
            package_id=args.package_id,
            report_dir=report_dir,
            max_attempts=args.max_attempts,
        )
        rows.append(row)
        if row["result"] != "PASS":
            write_report(
                output,
                {
                    "schema_version": SCHEMA_VERSION,
                    "engine_version": ENGINE_VERSION,
                    "result": "FAIL",
                    "repository": args.repository,
                    "coverage_reduction_enabled": True,
                    "selected_journeys": [value for value, _ in journeys],
                    "journeys": rows,
                    "seconds": round(time.monotonic() - started, 3),
                },
            )
            return 1

    write_report(
        output,
        {
            "schema_version": SCHEMA_VERSION,
            "engine_version": ENGINE_VERSION,
            "result": "PASS",
            "repository": args.repository,
            "coverage_reduction_enabled": True,
            "selected_journeys": [value for value, _ in journeys],
            "journeys": rows,
            "seconds": round(time.monotonic() - started, 3),
        },
    )
    return 0


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        trusted = root / "trusted"
        target = root / "target"
        (trusted / "config").mkdir(parents=True)
        (target / ".maestro").mkdir(parents=True)
        (trusted / "config" / "journey-runtime-pilots.json").write_text(
            json.dumps({"schema_version": 1, "repositories": ["owner/app"]}),
            encoding="utf-8",
        )
        (target / ".maestro" / "shell.yaml").write_text("appId: demo\n", encoding="utf-8")
        (target / "applab.project.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "journeys": {
                        "catalog": {
                            "shell": {
                                "flow": ".maestro/shell.yaml",
                                "paths": ["lib/**"],
                                "labs": [],
                                "surfaces": ["home"],
                                "capabilities": ["navigation"],
                                "risk_class": "core",
                                "always_fast": True,
                            }
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        plan = {
            "lane": "FAST_RUNTIME",
            "selected_journeys": ["shell"],
            "journey_selection": {
                "enforcement_eligible": True,
                "unmatched_paths": [],
            },
        }
        selected = selected_catalog(
            target_root=target,
            plan=plan,
            repository="owner/app",
            trusted_root=trusted,
        )
        assert selected[0][0] == "shell"
        try:
            selected_catalog(
                target_root=target,
                plan=plan,
                repository="owner/not-pilot",
                trusted_root=trusted,
            )
        except LegacyFallback:
            pass
        else:
            raise AssertionError("non-pilot repository must fall back")
        plan["journey_selection"]["unmatched_paths"] = ["lib/unknown.dart"]
        try:
            selected_catalog(
                target_root=target,
                plan=plan,
                repository="owner/app",
                trusted_root=trusted,
            )
        except LegacyFallback:
            pass
        else:
            raise AssertionError("unmatched FAST path must fall back")
    print("AppLab v5.9B journey runtime self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-root", default="")
    parser.add_argument("--trusted-root", default="")
    parser.add_argument("--plan", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--package-id", default="")
    parser.add_argument("--report-dir", default="applab-report")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.target_root, args.trusted_root, args.plan, args.repository, args.package_id)):
        parser.error("runtime execution requires target/trusted roots, plan, repository and package id")
    if not 1 <= args.max_attempts <= 3:
        parser.error("--max-attempts must be between 1 and 3")
    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
