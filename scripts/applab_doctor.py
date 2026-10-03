#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
from pathlib import Path
from typing import Callable

ENGINE_VERSION = "4.1.0"

PROFILES = {
    "core": {
        "required": ["git", "python"],
        "optional": ["gh", "docker", "node", "npm"],
    },
    "android": {
        "required": ["git", "python", "java", "adb"],
        "optional": ["gh", "docker", "sdkmanager", "gradle"],
    },
    "flutter": {
        "required": ["git", "python", "java", "adb", "flutter", "dart"],
        "optional": ["gh", "docker", "sdkmanager", "gradle", "node", "npm"],
    },
    "full": {
        "required": ["git", "python", "java", "adb", "docker", "gh"],
        "optional": ["flutter", "dart", "sdkmanager", "gradle", "node", "npm"],
    },
}


def probe_commands(
    profile: str,
    resolver: Callable[[str], str | None] = shutil.which,
) -> list[dict[str, object]]:
    spec = PROFILES[profile]
    rows: list[dict[str, object]] = []
    for level in ("required", "optional"):
        for command in spec[level]:
            found = resolver(command)
            rows.append(
                {
                    "kind": "command",
                    "name": command,
                    "required": level == "required",
                    "ok": bool(found),
                    "path": found or "",
                }
            )
    return rows


def build_report(profile: str) -> dict[str, object]:
    rows = probe_commands(profile)
    if platform.system().lower() == "linux":
        kvm = Path("/dev/kvm")
        rows.append(
            {
                "kind": "device",
                "name": "/dev/kvm",
                "required": profile == "full",
                "ok": kvm.exists() and os.access(kvm, os.R_OK | os.W_OK),
                "path": str(kvm) if kvm.exists() else "",
            }
        )
    docker_socket = Path("/var/run/docker.sock")
    rows.append(
        {
            "kind": "device",
            "name": "docker-socket",
            "required": False,
            "ok": docker_socket.exists(),
            "path": str(docker_socket) if docker_socket.exists() else "",
        }
    )
    missing_required = [row["name"] for row in rows if row["required"] and not row["ok"]]
    return {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "profile": profile,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "state": "READY" if not missing_required else "BLOCKED",
        "checks": rows,
        "missing_required": missing_required,
        "summary": {
            "checks": len(rows),
            "passed": sum(1 for row in rows if row["ok"]),
            "missing_required": len(missing_required),
            "missing_optional": sum(1 for row in rows if not row["required"] and not row["ok"]),
        },
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# AppLab Doctor",
        "",
        f"- Profile: **{report['profile']}**",
        f"- State: **{report['state']}**",
        "",
        "| Check | Required | State |",
        "| --- | --- | --- |",
    ]
    for row in report["checks"]:  # type: ignore[index]
        lines.append(
            f"| {row['name']} | {'yes' if row['required'] else 'no'} | {'PASS' if row['ok'] else 'MISSING'} |"
        )
    if report["missing_required"]:  # type: ignore[index]
        lines.extend(["", "Missing required: " + ", ".join(report["missing_required"])])  # type: ignore[index]
    return "\n".join(lines) + "\n"


def self_test() -> None:
    available = {"git": "/usr/bin/git", "python": "/usr/bin/python", "java": "/usr/bin/java", "adb": "/usr/bin/adb"}
    rows = probe_commands("android", resolver=lambda name: available.get(name))
    required = [row for row in rows if row["required"]]
    assert all(row["ok"] for row in required)
    assert next(row for row in rows if row["name"] == "docker")["required"] is False

    rows_missing = probe_commands("flutter", resolver=lambda name: available.get(name))
    missing = [row["name"] for row in rows_missing if row["required"] and not row["ok"]]
    assert "flutter" in missing and "dart" in missing
    print("AppLab Doctor self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=sorted(PROFILES), default="core")
    parser.add_argument("--output", default="")
    parser.add_argument("--markdown", default="")
    parser.add_argument("--advisory", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    report = build_report(args.profile)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown:
        path = Path(args.markdown)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown(report), encoding="utf-8")

    print(json.dumps(report, indent=2, sort_keys=True))
    if report["state"] != "READY" and not args.advisory:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
