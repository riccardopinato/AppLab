#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    details: dict[str, Any]


STARTUP_WARN_MS = 3000
PSS_WARN_KB = 512 * 1024
JANK_WARN_PERCENT = 20.0

REGRESSION_RATIO = 1.35
STARTUP_REGRESSION_ABS_MS = 500
PSS_REGRESSION_ABS_KB = 64 * 1024
JANK_REGRESSION_ABS_PERCENT = 10.0
APK_REGRESSION_RATIO = 1.35
APK_REGRESSION_ABS_BYTES = 1 * 1024 * 1024


def run(*args: str, timeout: int = 30, check: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n{result.stdout}"
        )
    return result


def adb(*args: str, timeout: int = 30, check: bool = False) -> subprocess.CompletedProcess[str]:
    return run("adb", *args, timeout=timeout, check=check)


def parse_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, re.MULTILINE)
    return int(match.group(1)) if match else None


def parse_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.MULTILINE)
    return float(match.group(1)) if match else None


def launcher_component(package_id: str) -> str | None:
    result = adb(
        "shell",
        "cmd",
        "package",
        "resolve-activity",
        "--brief",
        "-a",
        "android.intent.action.MAIN",
        "-c",
        "android.intent.category.LAUNCHER",
        package_id,
        timeout=20,
    )
    candidates = [
        line.strip()
        for line in result.stdout.splitlines()
        if "/" in line and "No activity found" not in line
    ]
    return candidates[-1] if candidates else None


def start_metric(component: str, *, cold: bool) -> dict[str, Any]:
    if cold:
        package_id = component.split("/", 1)[0]
        adb("shell", "am", "force-stop", package_id, timeout=15)
    result = adb(
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        component,
        timeout=45,
    )
    output = result.stdout
    return {
        "returncode": result.returncode,
        "status": (re.search(r"^Status:\s*(.+)$", output, re.MULTILINE) or [None, ""])[1].strip(),
        "launch_state": (re.search(r"^LaunchState:\s*(.+)$", output, re.MULTILINE) or [None, ""])[1].strip(),
        "this_time_ms": parse_int(r"^ThisTime:\s*(\d+)", output),
        "total_time_ms": parse_int(r"^TotalTime:\s*(\d+)", output),
        "wait_time_ms": parse_int(r"^WaitTime:\s*(\d+)", output),
        "raw": output[-4000:],
    }


def memory_metric(package_id: str) -> dict[str, Any]:
    result = adb("shell", "dumpsys", "meminfo", package_id, timeout=30)
    text = result.stdout
    total_pss = parse_int(r"TOTAL PSS:\s*(\d+)", text)
    total_rss = parse_int(r"TOTAL RSS:\s*(\d+)", text)
    total_swap = parse_int(r"TOTAL SWAP PSS:\s*(\d+)", text)

    if total_pss is None:
        match = re.search(r"^\s*TOTAL\s+(\d+)\s+", text, re.MULTILINE)
        if match:
            total_pss = int(match.group(1))

    return {
        "pss_kb": total_pss,
        "rss_kb": total_rss,
        "swap_pss_kb": total_swap,
    }


def gfx_metric(package_id: str) -> dict[str, Any]:
    result = adb("shell", "dumpsys", "gfxinfo", package_id, timeout=30)
    text = result.stdout
    return {
        "total_frames": parse_int(r"Total frames rendered:\s*(\d+)", text),
        "janky_frames": parse_int(r"Janky frames:\s*(\d+)", text),
        "janky_percent": parse_float(r"Janky frames:\s*\d+\s*\(([\d.]+)%\)", text),
        "percentile_90_ms": parse_int(r"90th percentile:\s*(\d+)ms", text),
        "percentile_95_ms": parse_int(r"95th percentile:\s*(\d+)ms", text),
        "percentile_99_ms": parse_int(r"99th percentile:\s*(\d+)ms", text),
    }


def installed_apk_bytes(package_id: str) -> int | None:
    result = adb("shell", "pm", "path", package_id, timeout=20)
    paths = [
        line.split("package:", 1)[1].strip()
        for line in result.stdout.splitlines()
        if line.startswith("package:")
    ]
    for path in paths:
        stat = adb("shell", "stat", "-c", "%s", path, timeout=20)
        value = stat.stdout.strip()
        if stat.returncode == 0 and value.isdigit():
            return int(value)
    return None


def cpu_metric(package_id: str) -> dict[str, Any]:
    pid_result = adb("shell", "pidof", package_id, timeout=10)
    pid = pid_result.stdout.strip().split()
    if not pid:
        return {"pid": None, "cpu_percent": None}
    process_id = pid[0]
    top = adb("shell", "top", "-b", "-n", "1", "-p", process_id, timeout=20)
    cpu = None
    for line in top.stdout.splitlines():
        if process_id not in line:
            continue
        parts = line.split()
        for token in parts:
            if token.endswith("%"):
                try:
                    cpu = float(token.rstrip("%"))
                    break
                except ValueError:
                    pass
        if cpu is not None:
            break
    return {"pid": int(process_id), "cpu_percent": cpu}


def load_baseline(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def regression_findings(current: dict[str, Any], baseline: dict[str, Any] | None) -> list[Finding]:
    if not baseline:
        return []

    findings: list[Finding] = []
    current_metrics = current.get("metrics", {})
    baseline_metrics = baseline.get("metrics", {})

    current_cold = current_metrics.get("startup", {}).get("cold", {}).get("total_time_ms")
    baseline_cold = baseline_metrics.get("startup", {}).get("cold", {}).get("total_time_ms")
    if isinstance(current_cold, (int, float)) and isinstance(baseline_cold, (int, float)) and baseline_cold > 0:
        delta = current_cold - baseline_cold
        if current_cold >= baseline_cold * REGRESSION_RATIO and delta >= STARTUP_REGRESSION_ABS_MS:
            findings.append(
                Finding(
                    "warning",
                    "startup_regression",
                    "Cold startup is materially slower than the previous passing baseline.",
                    {
                        "current_ms": current_cold,
                        "baseline_ms": baseline_cold,
                        "delta_ms": delta,
                    },
                )
            )

    current_pss = current_metrics.get("memory", {}).get("pss_kb")
    baseline_pss = baseline_metrics.get("memory", {}).get("pss_kb")
    if isinstance(current_pss, (int, float)) and isinstance(baseline_pss, (int, float)) and baseline_pss > 0:
        delta = current_pss - baseline_pss
        if current_pss >= baseline_pss * REGRESSION_RATIO and delta >= PSS_REGRESSION_ABS_KB:
            findings.append(
                Finding(
                    "warning",
                    "memory_regression",
                    "Process PSS is materially higher than the previous passing baseline.",
                    {
                        "current_kb": current_pss,
                        "baseline_kb": baseline_pss,
                        "delta_kb": delta,
                    },
                )
            )

    current_apk = current_metrics.get("apk", {}).get("host_apk_bytes")
    baseline_apk = baseline_metrics.get("apk", {}).get("host_apk_bytes")
    if isinstance(current_apk, (int, float)) and isinstance(baseline_apk, (int, float)) and baseline_apk > 0:
        delta = current_apk - baseline_apk
        if current_apk >= baseline_apk * APK_REGRESSION_RATIO and delta >= APK_REGRESSION_ABS_BYTES:
            findings.append(
                Finding(
                    "warning",
                    "apk_size_regression",
                    "APK size increased materially from the previous passing baseline.",
                    {
                        "current_bytes": current_apk,
                        "baseline_bytes": baseline_apk,
                        "delta_bytes": delta,
                        "ratio": current_apk / baseline_apk,
                    },
                )
            )

    current_jank = current_metrics.get("gfx", {}).get("janky_percent")
    baseline_jank = baseline_metrics.get("gfx", {}).get("janky_percent")
    if isinstance(current_jank, (int, float)) and isinstance(baseline_jank, (int, float)):
        delta = current_jank - baseline_jank
        if delta >= JANK_REGRESSION_ABS_PERCENT:
            findings.append(
                Finding(
                    "warning",
                    "jank_regression",
                    "Janky-frame percentage increased materially from the previous passing baseline.",
                    {
                        "current_percent": current_jank,
                        "baseline_percent": baseline_jank,
                        "delta_percentage_points": round(delta, 2),
                    },
                )
            )

    return findings


def evaluate(
    package_id: str,
    apk_path: Path,
    baseline_path: Path | None = None,
) -> dict[str, Any]:
    component = launcher_component(package_id)
    findings: list[Finding] = []

    if component:
        cold = start_metric(component, cold=True)
        warm = start_metric(component, cold=False)
    else:
        cold = {"total_time_ms": None, "status": "", "launch_state": "", "raw": ""}
        warm = {"total_time_ms": None, "status": "", "launch_state": "", "raw": ""}
        findings.append(
            Finding(
                "warning",
                "launcher_unresolved",
                "Unable to resolve launcher activity for startup timing.",
                {},
            )
        )

    memory = memory_metric(package_id)
    gfx = gfx_metric(package_id)
    cpu = cpu_metric(package_id)
    host_apk_bytes = apk_path.stat().st_size if apk_path.is_file() else None
    installed_bytes = installed_apk_bytes(package_id)

    cold_ms = cold.get("total_time_ms")
    if isinstance(cold_ms, (int, float)) and cold_ms >= STARTUP_WARN_MS:
        findings.append(
            Finding(
                "warning",
                "slow_cold_start",
                "Cold startup exceeded the initial AppLab advisory threshold.",
                {"cold_start_ms": cold_ms, "threshold_ms": STARTUP_WARN_MS},
            )
        )

    pss = memory.get("pss_kb")
    if isinstance(pss, (int, float)) and pss >= PSS_WARN_KB:
        findings.append(
            Finding(
                "warning",
                "high_memory_pss",
                "Process PSS exceeded the initial AppLab advisory threshold.",
                {"pss_kb": pss, "threshold_kb": PSS_WARN_KB},
            )
        )

    jank = gfx.get("janky_percent")
    if isinstance(jank, (int, float)) and jank >= JANK_WARN_PERCENT:
        findings.append(
            Finding(
                "warning",
                "high_jank",
                "Janky-frame percentage exceeded the initial AppLab advisory threshold.",
                {"janky_percent": jank, "threshold_percent": JANK_WARN_PERCENT},
            )
        )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "performance_lab_version": "0.9.0",
        "result": "PASS",
        "package_id": package_id,
        "baseline": "AVAILABLE" if baseline_path and baseline_path.is_file() else "NO_BASELINE",
        "metrics": {
            "startup": {"cold": cold, "warm": warm},
            "memory": memory,
            "gfx": gfx,
            "cpu": cpu,
            "apk": {
                "host_apk_bytes": host_apk_bytes,
                "installed_base_apk_bytes": installed_bytes,
            },
        },
        "findings": [],
    }

    findings.extend(regression_findings(payload, load_baseline(baseline_path)))
    payload["findings"] = [asdict(item) for item in findings]
    payload["warnings"] = sum(1 for item in findings if item.severity == "warning")
    payload["result"] = "WARN" if payload["warnings"] else "PASS"
    return payload


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    metrics = report.get("metrics", {})
    startup = metrics.get("startup", {})
    memory = metrics.get("memory", {})
    gfx = metrics.get("gfx", {})
    apk = metrics.get("apk", {})
    cpu = metrics.get("cpu", {})

    lines = [
        "# AppLab Performance Lab",
        "",
        f"- Result: **{report.get('result', 'UNKNOWN')}**",
        f"- Baseline: **{report.get('baseline', 'NO_BASELINE')}**",
        f"- Package: `{report.get('package_id', '')}`",
        "",
        "## Metrics",
        "",
        f"- Cold startup: {startup.get('cold', {}).get('total_time_ms', '—')} ms",
        f"- Warm startup: {startup.get('warm', {}).get('total_time_ms', '—')} ms",
        f"- PSS: {memory.get('pss_kb', '—')} KB",
        f"- RSS: {memory.get('rss_kb', '—')} KB",
        f"- Janky frames: {gfx.get('janky_percent', '—')}%",
        f"- 90th percentile frame: {gfx.get('percentile_90_ms', '—')} ms",
        f"- CPU snapshot: {cpu.get('cpu_percent', '—')}%",
        f"- APK: {apk.get('host_apk_bytes', '—')} bytes",
        "",
    ]

    findings = report.get("findings", [])
    if findings:
        lines.extend(["## Findings", ""])
        for finding in findings:
            lines.append(
                f"- **{finding.get('severity', 'info').upper()} — "
                f"{finding.get('code', 'finding')}**: "
                f"{finding.get('message', '')}"
            )
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def self_test() -> None:
    baseline = {
        "metrics": {
            "startup": {"cold": {"total_time_ms": 1000}},
            "memory": {"pss_kb": 100000},
            "gfx": {"janky_percent": 5.0},
        }
    }
    current = {
        "metrics": {
            "startup": {"cold": {"total_time_ms": 1800}},
            "memory": {"pss_kb": 180000},
            "gfx": {"janky_percent": 18.0},
        }
    }
    findings = regression_findings(current, baseline)
    codes = {item.code for item in findings}
    assert "startup_regression" in codes
    assert "memory_regression" in codes
    assert "jank_regression" in codes

    assert not regression_findings(
        {
            "metrics": {
                "startup": {"cold": {"total_time_ms": 1100}},
                "memory": {"pss_kb": 110000},
                "gfx": {"janky_percent": 7.0},
            }
        },
        baseline,
    )
    print("AppLab Performance Lab self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id")
    parser.add_argument("--apk")
    parser.add_argument("--report-dir")
    parser.add_argument("--baseline-json", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.package_id or not args.apk or not args.report_dir:
        raise SystemExit("--package-id, --apk and --report-dir are required")

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report = evaluate(
        args.package_id.strip(),
        Path(args.apk),
        Path(args.baseline_json) if args.baseline_json else None,
    )
    (report_dir / "performance-lab.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_markdown(report_dir / "performance-lab.md", report)
    print(
        f"AppLab Performance Lab: {report['result']} "
        f"(baseline={report['baseline']})"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"AppLab Performance Lab warning: {exc}", file=sys.stderr)
        raise SystemExit(0)
