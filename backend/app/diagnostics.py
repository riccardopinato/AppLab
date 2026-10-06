from __future__ import annotations

import re
from typing import Any


_BRIEF_ANDROID_RUNTIME = re.compile(
    r"^[VDIWEF]/AndroidRuntime(?:\\(\\s*(\\d+)\\))?:\\s*(.*)$"
)
_THREADTIME_ANDROID_RUNTIME = re.compile(
    r"^\\S+\\s+\\S+\\s+(\\d+)\\s+\\d+\\s+[VDIWEF]\\s+AndroidRuntime:\\s*(.*)$"
)
_PROCESS_LINE = re.compile(r"^Process:\\s*([^,\\s]+)(?:,\\s*PID:\\s*(\\d+))?")


def _android_runtime_entry(line: str) -> tuple[str | None, str] | None:
    match = _BRIEF_ANDROID_RUNTIME.match(line.strip())
    if match:
        return match.group(1), match.group(2)
    match = _THREADTIME_ANDROID_RUNTIME.match(line.strip())
    if match:
        return match.group(1), match.group(2)
    return None


def _target_fatal(logcat: str, package_id: str) -> bool:
    lines = logcat.splitlines()
    entries = [_android_runtime_entry(line) for line in lines]
    for index, entry in enumerate(entries):
        if entry is None:
            continue
        emitter_pid, message = entry
        if not message.startswith("FATAL EXCEPTION:"):
            continue
        for detail_index in range(index + 1, min(len(lines), index + 24)):
            detail = entries[detail_index]
            if detail is None:
                continue
            detail_pid, detail_message = detail
            if detail_message.startswith("FATAL EXCEPTION:"):
                if emitter_pid is None or detail_pid == emitter_pid:
                    break
                continue
            if (
                emitter_pid is not None
                and detail_pid is not None
                and detail_pid != emitter_pid
            ):
                continue
            process = _PROCESS_LINE.match(detail_message)
            if process is None:
                continue
            if process.group(1) != package_id:
                break
            process_pid = process.group(2)
            if (
                emitter_pid is not None
                and process_pid is not None
                and emitter_pid != process_pid
            ):
                break
            return True
    return False


_FLUTTER_PATTERNS = (
    re.compile(r"Unhandled Exception:", re.IGNORECASE),
    re.compile(r"EXCEPTION CAUGHT BY .* LIBRARY", re.IGNORECASE),
    re.compile(r"Failed assertion:", re.IGNORECASE),
    re.compile(r"Another exception was thrown", re.IGNORECASE),
)


def analyze_logcat(
    logcat: str,
    *,
    package_id: str,
    running: bool,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []

    if not running:
        issues.append(
            {
                "code": "PROCESS_NOT_RUNNING",
                "severity": "error",
                "message": "Application process is not running.",
            }
        )

    if f"ANR in {package_id}" in logcat:
        issues.append(
            {
                "code": "ANR",
                "severity": "error",
                "message": f"ANR detected for {package_id}.",
            }
        )

    if _target_fatal(logcat, package_id):
        issues.append(
            {
                "code": "FATAL_EXCEPTION",
                "severity": "error",
                "message": "Fatal Android exception detected.",
            }
        )

    if any(pattern.search(logcat) for pattern in _FLUTTER_PATTERNS):
        issues.append(
            {
                "code": "FLUTTER_EXCEPTION",
                "severity": "error",
                "message": "Unhandled Flutter/framework exception detected.",
            }
        )

    return {
        "result": "PASS" if not issues else "FAIL",
        "package_id": package_id,
        "running": running,
        "issue_count": len(issues),
        "issues": issues,
    }
