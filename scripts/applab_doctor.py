#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

ENGINE_VERSION = "4.1.0"

PROFILES = {
    "core": {
        "required": ["git"],
        "optional": ["gh", "docker", "node", "npm"],
    },
    "android": {
        "required": ["git", "java", "adb"],
        "optional": ["gh", "docker", "sdkmanager", "gradle"],
    },
    "flutter": {
        "required": ["git", "java", "adb", "flutter", "dart"],
        "optional": ["gh", "docker", "sdkmanager", "gradle", "node", "npm"],
    },
    "full": {
        "required": ["git", "java", "adb", "docker", "gh"],
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


def probe_docker_daemon(
    docker_path: str,
    runner: Callable[..., object] = subprocess.run,
) -> dict[str, object]:
    if not docker_path:
        return {
            "kind": "service",
            "name": "docker-daemon",
            "required": False,
            "ok": False,
            "path": "",
            "detail": "docker client unavailable",
        }
    try:
        completed = runner(
            [docker_path, "info", "--format", "{{json .ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return_code = int(getattr(completed, "returncode", 1))
        stderr = str(getattr(completed, "stderr", "") or "").strip()
        stdout = str(getattr(completed, "stdout", "") or "").strip()
        return {
            "kind": "service",
            "name": "docker-daemon",
            "required": False,
            "ok": return_code == 0 and bool(stdout),
            "path": docker_path,
            "detail": stdout if return_code == 0 else stderr[:240],
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "kind": "service",
            "name": "docker-daemon",
            "required": False,
            "ok": False,
            "path": docker_path,
            "detail": str(exc)[:240],
        }


def probe_docker_compose(
    docker_path: str,
    runner: Callable[..., object] = subprocess.run,
) -> dict[str, object]:
    if not docker_path:
        return {
            "kind": "command",
            "name": "docker-compose-v2",
            "required": False,
            "ok": False,
            "path": "",
            "detail": "docker client unavailable",
        }
    try:
        completed = runner(
            [docker_path, "compose", "version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return_code = int(getattr(completed, "returncode", 1))
        stdout = str(getattr(completed, "stdout", "") or "").strip()
        stderr = str(getattr(completed, "stderr", "") or "").strip()
        return {
            "kind": "command",
            "name": "docker-compose-v2",
            "required": False,
            "ok": return_code == 0 and bool(stdout),
            "path": docker_path,
            "detail": stdout if return_code == 0 else stderr[:240],
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "kind": "command",
            "name": "docker-compose-v2",
            "required": False,
            "ok": False,
            "path": docker_path,
            "detail": str(exc)[:240],
        }


def build_report(profile: str) -> dict[str, object]:
    rows = probe_commands(profile)
    rows.append(
        {
            "kind": "runtime",
            "name": "python-runtime",
            "required": True,
            "ok": bool(sys.executable),
            "path": sys.executable,
            "detail": platform.python_version(),
        }
    )
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
    docker_row = next((row for row in rows if row["name"] == "docker"), None)
    docker_path = str(docker_row.get("path", "")) if docker_row else ""
    docker_daemon = probe_docker_daemon(docker_path)
    docker_daemon["required"] = profile == "full"
    rows.append(docker_daemon)

    docker_compose = probe_docker_compose(docker_path)
    docker_compose["required"] = profile == "full"
    rows.append(docker_compose)

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
    available = {"git": "/usr/bin/git", "java": "/usr/bin/java", "adb": "/usr/bin/adb"}
    rows = probe_commands("android", resolver=lambda name: available.get(name))
    required = [row for row in rows if row["required"]]
    assert all(row["ok"] for row in required)
    assert next(row for row in rows if row["name"] == "docker")["required"] is False

    rows_missing = probe_commands("flutter", resolver=lambda name: available.get(name))
    missing = [row["name"] for row in rows_missing if row["required"] and not row["ok"]]
    assert "flutter" in missing and "dart" in missing

    ready = probe_docker_daemon(
        "/usr/bin/docker",
        runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout='"27.5.1"\n', stderr=""
        ),
    )
    assert ready["ok"] is True
    blocked = probe_docker_daemon(
        "/usr/bin/docker",
        runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="Cannot connect to the Docker daemon"
        ),
    )
    assert blocked["ok"] is False

    compose_ready = probe_docker_compose(
        "/usr/bin/docker",
        runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="Docker Compose version v2.40.0\n", stderr=""
        ),
    )
    assert compose_ready["ok"] is True
    compose_missing = probe_docker_compose(
        "/usr/bin/docker",
        runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="docker: 'compose' is not a docker command"
        ),
    )
    assert compose_missing["ok"] is False
    assert sys.executable
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
