#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import advanced_hardening_v56e as registry


class SensorMeshError(ValueError):
    pass


def plan_sensors(payload: dict[str, Any]) -> dict[str, Any]:
    repository = str(payload.get("repository") or "")
    source_sha = str(payload.get("source_sha") or "").lower()
    risk = str(payload.get("risk") or "NORMAL").upper()
    changed = [str(x) for x in payload.get("changed_files", []) if str(x)]
    failed_labs = {str(x) for x in payload.get("failed_labs", []) if str(x)}
    physical = bool(payload.get("physical_validation_required"))
    artifact = bool(payload.get("artifact_sha256"))
    release_candidate = bool(payload.get("release_candidate"))
    network_replay_allowed = bool(payload.get("network_replay_allowed"))

    selected: dict[str, dict[str, Any]] = {}

    def add(name: str, reason: str) -> None:
        selected[name] = {
            "producer": name,
            "reason": reason,
            "authority": "EVIDENCE_ONLY",
            "required": True,
        }

    if physical:
        add("SCRCPY_CAPTURE", "PHYSICAL_VALIDATION_REQUIRED")
    if "resource_pressure" in failed_labs or any(
        token in path.lower() for path in changed for token in ("memory", "cache", "image")
    ):
        add("LEAKCANARY", "MEMORY_RESOURCE_SIGNAL")
    if risk in {"HIGH", "SECURITY"} or any(
        path.endswith((".py", ".dart", ".kt", ".java", ".js", ".ts", ".tsx"))
        for path in changed
    ):
        add("SEMGREP", "SOURCE_SECURITY_SIGNAL")
    if any(
        token in path.lower()
        for path in changed
        for token in ("lock", "pubspec", "requirements", "package.json", "gradle", "docker")
    ):
        add("TRIVY", "DEPENDENCY_OR_CONTAINER_SIGNAL")
    if artifact and (risk in {"HIGH", "SECURITY"} or release_candidate):
        add("MOBSF", "ANDROID_ARTIFACT_SECURITY_SIGNAL")
    if network_replay_allowed and (
        "network" in failed_labs
        or any(token in path.lower() for path in changed for token in ("api", "network", "sync", "http"))
    ):
        add("HETTY", "NETWORK_REPLAY_SIGNAL")

    return {
        "schema_version": 1,
        "record_type": "SENSOR_MESH_PLAN_V60H",
        "authority": "EVIDENCE_SELECTION_ONLY",
        "repository": repository,
        "source_sha": source_sha,
        "risk": risk,
        "selected_producers": list(selected.values()),
        "producer_count": len(selected),
        "can_mint_pass": False,
        "can_mint_certified": False,
        "verification_authority": "UNCHANGED",
    }


def tool_availability() -> dict[str, bool]:
    return {
        "SEMGREP": shutil.which("semgrep") is not None,
        "TRIVY": shutil.which("trivy") is not None,
        "SCRCPY_CAPTURE": shutil.which("scrcpy") is not None,
        "LEAKCANARY": False,
        "MOBSF": False,
        "HETTY": False,
    }


def run_cli_sensor(
    producer: str,
    *,
    target_root: Path,
    output: Path,
) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    if producer == "SEMGREP":
        cmd = ["semgrep", "scan", "--config", "auto", "--json", "--output", str(output), str(target_root)]
    elif producer == "TRIVY":
        cmd = ["trivy", "fs", "--format", "json", "--output", str(output), str(target_root)]
    else:
        raise SensorMeshError(f"producer {producer} is not a generic hosted CLI sensor")
    if shutil.which(cmd[0]) is None:
        return {
            "producer": producer,
            "state": "BLOCKED",
            "reason": "SENSOR_BINARY_NOT_AVAILABLE",
            "output": str(output),
        }
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=900)
    if proc.returncode != 0:
        return {
            "producer": producer,
            "state": "BLOCKED",
            "reason": "SENSOR_EXECUTION_FAILED",
            "returncode": proc.returncode,
            "stderr_tail": (proc.stderr or "")[-2000:],
            "output": str(output),
        }
    if not output.is_file():
        return {
            "producer": producer,
            "state": "BLOCKED",
            "reason": "SENSOR_OUTPUT_MISSING",
            "output": str(output),
        }
    return {
        "producer": producer,
        "state": "EVIDENCE_PRODUCED",
        "reason": "OK",
        "output": str(output),
    }


def normalize_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = registry.normalize(payload)
    normalized["record_type"] = "SENSOR_MESH_EVIDENCE_V60H"
    normalized["sensor_mesh"] = {
        "authority": "EVIDENCE_ONLY",
        "risk_triggered": True,
        "can_mint_pass": False,
        "can_mint_certified": False,
    }
    return normalized


def self_test() -> None:
    plan = plan_sensors(
        {
            "repository": "owner/app",
            "source_sha": "a" * 40,
            "risk": "SECURITY",
            "changed_files": ["lib/api_client.dart", "pubspec.lock"],
            "failed_labs": ["network"],
            "artifact_sha256": "1" * 64,
            "release_candidate": True,
            "network_replay_allowed": True,
            "physical_validation_required": True,
        }
    )
    names = {row["producer"] for row in plan["selected_producers"]}
    assert {"SCRCPY_CAPTURE", "SEMGREP", "TRIVY", "MOBSF", "HETTY"} <= names
    assert plan["can_mint_pass"] is False

    sem = normalize_evidence(
        {
            "producer": "SEMGREP",
            "repository": "owner/app",
            "source_sha": "a" * 40,
            "evidence_refs": ["artifact://semgrep/report.json"],
        }
    )
    assert sem["authority"] == "EVIDENCE_ONLY"
    assert sem["sensor_mesh"]["can_mint_certified"] is False

    hetty = normalize_evidence(
        {
            "producer": "HETTY",
            "repository": "owner/app",
            "source_sha": "a" * 40,
            "evidence_refs": ["artifact://hetty/session.json"],
        }
    )
    assert hetty["artifact_role"] == "NETWORK_REPLAY"

    blocked = run_cli_sensor(
        "SEMGREP",
        target_root=ROOT,
        output=ROOT / ".nonexistent-selftest" / "semgrep.json",
    )
    assert blocked["state"] in {"BLOCKED", "EVIDENCE_PRODUCED"}
    if (ROOT / ".nonexistent-selftest").exists():
        import shutil as _shutil
        _shutil.rmtree(ROOT / ".nonexistent-selftest")
    print("AppLab v6.0H sensor mesh self-test PASS")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--plan-input", default="")
    p.add_argument("--normalize-input", default="")
    p.add_argument("--producer", default="")
    p.add_argument("--target-root", default=".")
    p.add_argument("--output", default="")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        self_test()
        return 0
    if a.plan_input:
        payload = json.loads(Path(a.plan_input).read_text(encoding="utf-8"))
        result = plan_sensors(payload)
    elif a.normalize_input:
        payload = json.loads(Path(a.normalize_input).read_text(encoding="utf-8"))
        result = normalize_evidence(payload)
    elif a.producer:
        if not a.output:
            raise SystemExit("--output required for CLI sensor execution")
        result = run_cli_sensor(
            a.producer.upper(),
            target_root=Path(a.target_root).resolve(),
            output=Path(a.output).resolve(),
        )
    else:
        raise SystemExit("--plan-input, --normalize-input or --producer is required")
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if a.output and not a.producer:
        Path(a.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
