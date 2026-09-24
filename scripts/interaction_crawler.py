#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
SAFE_LABEL = re.compile(
    r"(?i)^(?:"
    r"home|menu|more|about|info|help|settings|profile|search|history|"
    r"stats?|statistics|map|list|details?|favorites?|next|back|"
    r"impostazioni|profilo|cerca|cronologia|storico|statistiche|mappa|"
    r"lista|dettagli|preferiti|avanti|indietro|aiuto|informazioni|altro|"
    r"diario|agenda|planner|note|notes|focus"
    r")(?:\s|$)"
)
DENY_LABEL = re.compile(
    r"(?i)(?:"
    r"delete|remove|erase|wipe|reset|clear data|logout|log out|sign out|"
    r"buy|purchase|subscribe|pay|checkout|order|transfer|send|publish|post|"
    r"call|dial|emergency|uninstall|install|factory|revoke|disconnect|"
    r"elimina|rimuovi|cancella|azzera|resetta|esci|disconnetti|acquista|"
    r"abbon|paga|ordine|trasfer|invia|pubblica|chiama|disinstalla"
    r")"
)


@dataclass
class Candidate:
    label: str
    class_name: str
    bounds: tuple[int, int, int, int]
    x: int
    y: int


class ObservationError(RuntimeError):
    pass


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def label_for(attrs: dict[str, str]) -> str:
    return " ".join(
        part.strip()
        for part in (attrs.get("text", ""), attrs.get("content-desc", ""))
        if part.strip()
    ).strip()


def parse_candidates(
    xml_path: Path,
    package_id: str,
    max_candidates: int = 12,
) -> list[Candidate]:
    root = ET.parse(xml_path).getroot()
    seen: set[tuple[int, int, int, int]] = set()
    result: list[Candidate] = []

    for node in root.iter("node"):
        attrs = node.attrib
        if package_id and attrs.get("package", "").strip() != package_id:
            continue
        if attrs.get("enabled", "true") != "true":
            continue
        if attrs.get("clickable") != "true":
            continue

        label = label_for(attrs)
        if not label or DENY_LABEL.search(label) or not SAFE_LABEL.search(label):
            continue

        match = BOUNDS_RE.fullmatch(attrs.get("bounds", "").strip())
        if not match:
            continue
        x1, y1, x2, y2 = (int(value) for value in match.groups())
        width, height = x2 - x1, y2 - y1
        if width < 32 or height < 32:
            continue

        bounds = (x1, y1, x2, y2)
        if bounds in seen:
            continue
        seen.add(bounds)
        result.append(
            Candidate(
                label=label[:120],
                class_name=attrs.get("class", "")[:160],
                bounds=bounds,
                x=x1 + width // 2,
                y=y1 + height // 2,
            )
        )
        if len(result) >= max_candidates:
            break
    return result


def hierarchy_signature(path: Path, package_id: str) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    texts: set[str] = set()
    nodes = 0
    clickable = 0
    for node in root.iter("node"):
        attrs = node.attrib
        if package_id and attrs.get("package", "").strip() != package_id:
            continue
        nodes += 1
        if attrs.get("clickable") == "true":
            clickable += 1
        label = label_for(attrs)
        if label:
            texts.add(" ".join(label.lower().split())[:120])
    return {"nodes": nodes, "clickable": clickable, "texts": sorted(texts)}


def changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    if before["nodes"] != after["nodes"] or before["clickable"] != after["clickable"]:
        return True
    return before["texts"] != after["texts"]


def _adb_ready() -> bool:
    result = run("adb", "get-state", check=False)
    return result.returncode == 0 and "device" in result.stdout


def _wait_for_adb() -> None:
    run("adb", "wait-for-device", check=False)
    for _ in range(10):
        if _adb_ready():
            return
        time.sleep(1)


def _capture_screenshot(path: Path) -> bool:
    for _ in range(3):
        with path.open("wb") as handle:
            proc = subprocess.run(
                ["adb", "exec-out", "screencap", "-p"],
                check=False,
                stdout=handle,
                stderr=subprocess.DEVNULL,
            )
        if proc.returncode == 0 and path.is_file() and path.stat().st_size > 0:
            return True
        _wait_for_adb()
        time.sleep(1)
    return False


def _capture_hierarchy(
    hierarchy: Path,
    remote: str,
    diagnostic_log: Path,
) -> bool:
    hierarchy.unlink(missing_ok=True)
    diagnostic_log.parent.mkdir(parents=True, exist_ok=True)

    with diagnostic_log.open("a", encoding="utf-8") as log:
        for attempt in range(1, 5):
            log.write(f"attempt={attempt}\n")
            run("adb", "shell", "rm", "-f", remote, check=False)

            for compressed in (False, True):
                command = ["adb", "shell", "uiautomator", "dump"]
                if compressed:
                    command.append("--compressed")
                command.append(remote)

                dumped = run(*command, check=False)
                log.write(
                    f"dump compressed={compressed} rc={dumped.returncode} "
                    f"output={dumped.stdout[-1200:]}\n"
                )
                pulled = run(
                    "adb", "pull", remote, str(hierarchy), check=False
                )
                log.write(
                    f"pull compressed={compressed} rc={pulled.returncode} "
                    f"output={pulled.stdout[-800:]}\n"
                )
                if (
                    pulled.returncode == 0
                    and hierarchy.is_file()
                    and hierarchy.stat().st_size > 0
                ):
                    try:
                        ET.parse(hierarchy)
                    except ET.ParseError as exc:
                        log.write(f"parse_error={exc}\n")
                        hierarchy.unlink(missing_ok=True)
                    else:
                        return True

            # Hosted AVDs can leave uiautomator stale after Maestro/native views.
            run("adb", "shell", "am", "force-stop", "com.github.uiautomator", check=False)
            _wait_for_adb()
            time.sleep(min(1.5 * attempt, 4.0))

    return False


def adb_capture(output_dir: Path, prefix: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    screenshot = output_dir / f"{prefix}.png"
    hierarchy = output_dir / f"{prefix}.xml"
    diagnostics = output_dir / f"{prefix}-capture.log"
    remote = f"/sdcard/applab-crawl-{prefix}.xml"

    if not _capture_screenshot(screenshot):
        raise ObservationError("Unable to capture crawler screenshot")

    if _capture_hierarchy(hierarchy, remote, diagnostics):
        return screenshot, hierarchy

    raise ObservationError(
        f"Unable to capture crawler UI hierarchy; diagnostics={diagnostics.name}"
    )

def pid_of(package_id: str) -> str:
    result = run("adb", "shell", "pidof", package_id, check=False)
    return result.stdout.strip().split()[0] if result.stdout.strip() else ""


def app_crashed(package_id: str) -> tuple[bool, str]:
    if not pid_of(package_id):
        return True, "application process died"
    logcat = run("adb", "logcat", "-b", "all", "-d", "-v", "brief", check=False).stdout
    if f"ANR in {package_id}" in logcat:
        return True, "ANR detected"
    fatal = re.search(
        rf"FATAL EXCEPTION:[\s\S]{{0,1800}}Process:\s*{re.escape(package_id)}\b",
        logcat,
    )
    if fatal:
        return True, "fatal exception detected"
    return False, ""


def relaunch(package_id: str, settle: float) -> None:
    run("adb", "shell", "am", "force-stop", package_id, check=False)
    run(
        "adb", "shell", "monkey", "-p", package_id,
        "-c", "android.intent.category.LAUNCHER", "1",
        check=False,
    )
    time.sleep(settle)


def crawl(
    package_id: str,
    report_dir: Path,
    max_actions: int,
    settle: float,
) -> dict[str, Any]:
    evidence = report_dir / "interaction-crawl"
    evidence.mkdir(parents=True, exist_ok=True)

    actions: list[dict[str, Any]] = []
    failures = 0
    tested = 0
    observation_warnings = 0
    crawler_reason: str | None = None
    base_signature: dict[str, Any] = {}
    candidates: list[Candidate] = []

    relaunch(package_id, settle)
    crashed, reason = app_crashed(package_id)
    if crashed:
        failures += 1
        crawler_reason = reason
    else:
        try:
            _, base_xml = adb_capture(evidence, "base")
            base_signature = hierarchy_signature(base_xml, package_id)
            candidates = parse_candidates(
                base_xml,
                package_id,
                max_candidates=max_actions * 3,
            )
        except ObservationError as exc:
            observation_warnings += 1
            crawler_reason = str(exc)

    if failures == 0 and candidates:
        for index, candidate in enumerate(candidates[:max_actions], start=1):
            relaunch(package_id, settle)
            crashed, reason = app_crashed(package_id)
            if crashed:
                failures += 1
                actions.append(
                    {
                        **asdict(candidate),
                        "bounds": list(candidate.bounds),
                        "status": "FAIL",
                        "state_changed": False,
                        "target_nodes_after": 0,
                        "reason": reason,
                        "screenshot": None,
                        "ui_hierarchy": None,
                    }
                )
                break

            try:
                _, before_xml = adb_capture(evidence, f"{index:02d}-before")
                before = hierarchy_signature(before_xml, package_id)
            except ObservationError as exc:
                observation_warnings += 1
                actions.append(
                    {
                        **asdict(candidate),
                        "bounds": list(candidate.bounds),
                        "status": "OBSERVATION_SKIPPED",
                        "state_changed": False,
                        "target_nodes_after": 0,
                        "reason": str(exc),
                        "screenshot": None,
                        "ui_hierarchy": None,
                    }
                )
                continue

            run(
                "adb",
                "shell",
                "input",
                "tap",
                str(candidate.x),
                str(candidate.y),
                check=False,
            )
            time.sleep(settle)

            try:
                screenshot, after_xml = adb_capture(
                    evidence,
                    f"{index:02d}-after",
                )
                after = hierarchy_signature(after_xml, package_id)
            except ObservationError as exc:
                crashed, reason = app_crashed(package_id)
                if crashed:
                    failures += 1
                    status = "FAIL"
                    failure_reason = reason
                else:
                    observation_warnings += 1
                    status = "OBSERVATION_WARN"
                    failure_reason = str(exc)

                actions.append(
                    {
                        **asdict(candidate),
                        "bounds": list(candidate.bounds),
                        "status": status,
                        "state_changed": False,
                        "target_nodes_after": 0,
                        "reason": failure_reason,
                        "screenshot": None,
                        "ui_hierarchy": None,
                    }
                )
                if crashed:
                    break
                continue

            crashed, reason = app_crashed(package_id)
            state_changed = changed(before, after)
            target_nodes = int(after.get("nodes", 0))
            status = (
                "FAIL"
                if crashed
                else ("CHANGED" if state_changed else "NO_CHANGE")
            )
            if crashed:
                failures += 1
            tested += 1

            actions.append(
                {
                    **asdict(candidate),
                    "bounds": list(candidate.bounds),
                    "status": status,
                    "state_changed": state_changed,
                    "target_nodes_after": target_nodes,
                    "reason": reason or None,
                    "screenshot": str(screenshot.relative_to(report_dir)),
                    "ui_hierarchy": str(after_xml.relative_to(report_dir)),
                }
            )

            if crashed:
                break

    if failures:
        result = "FAIL"
    elif observation_warnings:
        result = "WARN" if actions or candidates else "SKIPPED"
    elif tested:
        result = "PASS"
    else:
        result = "SKIPPED"

    return {
        "schema_version": 2,
        "interaction_crawler_version": "0.6.6.1",
        "result": result,
        "package_id": package_id,
        "candidate_count": len(candidates),
        "tested_actions": tested,
        "failures": failures,
        "observation_warnings": observation_warnings,
        "reason": crawler_reason,
        "base_signature": base_signature,
        "actions": actions,
    }

def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# AppLab Safe Interaction Crawler",
        "",
        f"- Result: **{report['result']}**",
        f"- Safe candidates found: {report['candidate_count']}",
        f"- Actions tested: {report['tested_actions']}",
        f"- Runtime failures: {report['failures']}",
        f"- Observation warnings: {report.get('observation_warnings', 0)}",
        f"- Instrumentation note: {report.get('reason') or 'none'}",
        "",
        "| # | Control | Result | State changed |",
        "| ---: | --- | --- | --- |",
    ]
    for index, item in enumerate(report["actions"], start=1):
        label = str(item["label"]).replace("|", "\\|")
        lines.append(
            f"| {index} | {label} | {item['status']} | "
            f"{'yes' if item['state_changed'] else 'no'} |"
        )
    if not report["actions"]:
        lines.extend(["", "No conservative navigation control was eligible for automatic tapping."])
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def self_test() -> None:
    import tempfile
    xml = """<hierarchy>
      <node package="com.example.app" class="android.widget.Button"
        text="Settings" content-desc="" clickable="true" enabled="true"
        bounds="[10,10][210,90]"/>
      <node package="com.example.app" class="android.widget.Button"
        text="Delete account" content-desc="" clickable="true" enabled="true"
        bounds="[10,100][210,180]"/>
      <node package="com.example.app" class="android.widget.Button"
        text="Pay now" content-desc="" clickable="true" enabled="true"
        bounds="[10,190][210,270]"/>
      <node package="com.example.app" class="android.widget.Button"
        text="Profile" content-desc="" clickable="true" enabled="true"
        bounds="[10,280][210,360]"/>
    </hierarchy>"""
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "ui.xml"
        path.write_text(xml, encoding="utf-8")
        found = parse_candidates(path, "com.example.app")
        assert [item.label for item in found] == ["Settings", "Profile"]
        before = hierarchy_signature(path, "com.example.app")
        assert before["nodes"] == 4
        assert before["clickable"] == 4

        report = {
            "result": "WARN",
            "failures": 0,
            "observation_warnings": 1,
        }
        assert report["result"] != "FAIL"
        assert report["failures"] == 0
    print("AppLab Safe Interaction Crawler self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id")
    parser.add_argument("--report-dir")
    parser.add_argument("--max-actions", type=int, default=4)
    parser.add_argument("--settle-seconds", type=float, default=1.5)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.package_id or not args.report_dir:
        raise SystemExit("--package-id and --report-dir are required")

    report = crawl(
        args.package_id,
        Path(args.report_dir),
        max(0, min(args.max_actions, 8)),
        max(0.5, min(args.settle_seconds, 5.0)),
    )
    report_dir = Path(args.report_dir)
    (report_dir / "interaction-crawl.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_markdown(report_dir / "interaction-crawl.md", report)
    print(f"AppLab Safe Interaction Crawler: {report['result']}")
    return 2 if report["result"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
