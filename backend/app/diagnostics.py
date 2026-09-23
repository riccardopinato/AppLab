from __future__ import annotations

import re
from typing import Any


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

    fatal_blocks = re.findall(
        r"FATAL EXCEPTION.*?(?=\n\S|\Z)",
        logcat,
        flags=re.IGNORECASE | re.DOTALL,
    )
    fatal_for_package = any(
        package_id in block or "AndroidRuntime" in block
        for block in fatal_blocks
    )
    if fatal_for_package:
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
