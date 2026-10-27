#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import advanced_hardening_v56e as hardening

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = (
    ROOT
    / "integration"
    / "orchestration"
    / "contracts"
    / "sensor-mesh-v1.json"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

DEPENDENCY_NAMES = {
    "pubspec.yaml",
    "pubspec.lock",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "requirements.txt",
    "pyproject.toml",
    "poetry.lock",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "gradle.lockfile",
    "Dockerfile",
}

NETWORK_TOKENS = ("network", "api", "sync", "http", "auth", "oauth", "supabase", "firebase")
NATIVE_TOKENS = ("android", "manifest", "permission", "native", "kotlin", "java")
MEMORY_TOKENS = ("memory", "lifecycle", "resource", "leak", "process")
PHYSICAL_CAPABILITIES = {
    "biometrics", "gps", "location", "notifications", "background",
    "camera", "bluetooth", "ble", "nfc", "sensors", "battery",
}


class SensorMeshError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise SensorMeshError("unsupported sensor mesh contract version")
    if payload.get("contract_name") != "APPLAB_SENSOR_MESH":
        raise SensorMeshError("unexpected sensor mesh contract")
    if payload.get("authority") != "EVIDENCE_ROUTING_ONLY":
        raise SensorMeshError("sensor mesh authority mismatch")
    return payload


def _strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _plan_labs(plan: dict[str, Any]) -> set[str]:
    labs = plan.get("selected_labs")
    if isinstance(labs, dict):
        return {
            str(name)
            for name, selected in labs.items()
            if selected is True
        }
    if isinstance(labs, list):
        return set(_strings(labs))
    values = plan.get("selected_specialist_labs")
    return set(_strings(values))


def _changed_files(plan: dict[str, Any]) -> list[str]:
    files = _strings(plan.get("changed_files"))
    changes = plan.get("changes")
    if isinstance(changes, list):
        for row in changes:
            if not isinstance(row, dict):
                continue
            for field in ("path", "previous_path"):
                value = str(row.get(field) or "").strip()
                if value:
                    files.append(value)
    return sorted(dict.fromkeys(path.replace("\\", "/") for path in files))


def _tokens(plan: dict[str, Any], project: dict[str, Any]) -> set[str]:
    values: list[str] = []
    values.extend(_changed_files(plan))
    values.extend(_strings(plan.get("risk_reasons")))
    values.extend(_strings(plan.get("capabilities")))
    values.extend(_strings(project.get("capabilities")))
    physical = project.get("physical_validation")
    if isinstance(physical, dict):
        values.extend(_strings(physical.get("capabilities")))
    text = " ".join(values).lower()
    return set(re.findall(r"[a-z][a-z0-9_-]{2,}", text))


def _contains_any(tokens: set[str], needles: tuple[str, ...] | set[str]) -> bool:
    return any(
        needle in token or token in needle
        for token in tokens
        for needle in needles
    )


def _dependency_changed(files: list[str]) -> bool:
    for path in files:
        name = Path(path).name
        if name in DEPENDENCY_NAMES or ".github/dependabot" in path:
            return True
    return False


def plan_sensors(
    plan: dict[str, Any],
    project: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    repository = str(plan.get("repository") or project.get("repository") or "").strip()
    resolved_sha = str(plan.get("resolved_sha") or "").lower()
    if "/" not in repository or not SHA_RE.fullmatch(resolved_sha):
        raise SensorMeshError("sensor plan requires exact repository/source identity")
    labs = _plan_labs(plan)
    files = _changed_files(plan)
    tokens = _tokens(plan, project)
    risk = int(plan.get("risk_score", 0) or 0)
    project_type = str(project.get("project_type") or plan.get("project_type") or "").lower()
    physical = project.get("physical_validation")
    physical_required = isinstance(physical, dict) and physical.get("required") is True
    physical_caps = set(_strings(physical.get("capabilities"))) if isinstance(physical, dict) else set()

    thresholds = contract["risk_thresholds"]
    selected: dict[str, dict[str, Any]] = {}

    def add(sensor: str, reason: str) -> None:
        rule = contract["sensors"][sensor]
        row = selected.setdefault(
            sensor,
            {
                "sensor": sensor,
                "wave": rule["wave"],
                "artifact_role": rule["artifact_role"],
                "execution": rule["execution"],
                "reasons": [],
                "provider_sensitive": bool(rule.get("provider_sensitive")),
                "reviewed_version": str(rule.get("reviewed_version") or ""),
                "reviewed_at": str(rule.get("reviewed_at") or ""),
            },
        )
        if reason not in row["reasons"]:
            row["reasons"].append(reason)

    if physical_required or physical_caps & PHYSICAL_CAPABILITIES:
        add("SCRCPY_CAPTURE", "PHYSICAL_VALIDATION_REQUIRED")
    if {"system", "background", "configuration"} & labs and physical_required:
        add("SCRCPY_CAPTURE", "PHYSICAL_SPECIALIST_LAB")

    if "resource_pressure" in labs or _contains_any(tokens, MEMORY_TOKENS):
        add("LEAKCANARY", "MEMORY_LIFECYCLE_RISK")

    security_like = _contains_any(tokens, ("security", "auth", "secret", "crypto", "network", "native"))
    if risk >= int(thresholds["first_wave_security"]) or security_like:
        add("SEMGREP", "SOURCE_SECURITY_RISK")

    if _dependency_changed(files) or risk >= int(thresholds["first_wave_security"]):
        add("TRIVY", "DEPENDENCY_OR_HIGH_RISK")

    android_like = (
        project_type in {"flutter", "native_android", "android"}
        or _contains_any(tokens, NATIVE_TOKENS)
    )
    manifest_sensitive = any(
        path.endswith("AndroidManifest.xml") or "/android/" in f"/{path.lower()}/"
        for path in files
    )
    if android_like and (
        risk >= int(thresholds["second_wave_mobile"])
        or manifest_sensitive
        or _contains_any(tokens, ("permission", "manifest", "native"))
    ):
        add("MOBSF", "ANDROID_SECURITY_DEEP_DIVE")

    network_risk = (
        "network" in labs
        or _contains_any(tokens, NETWORK_TOKENS)
    )
    if network_risk and risk >= int(thresholds["network_replay"]):
        add("HETTY", "NETWORK_REPLAY_HIGH_RISK")

    rows = [selected[name] for name in sorted(selected)]
    return {
        "schema_version": 1,
        "record_type": "SENSOR_MESH_PLAN_V60H",
        "authority": "EVIDENCE_ROUTING_ONLY",
        "repository": repository,
        "resolved_sha": resolved_sha,
        "risk_score": risk,
        "selected_labs": sorted(labs),
        "changed_files": files,
        "selected_sensors": rows,
        "selected_sensor_ids": [row["sensor"] for row in rows],
        "no_sensor_selected": not rows,
        "guardrails": {
            "can_mint_pass": False,
            "can_mint_certified": False,
            "can_replace_trusted_runtime": False,
            "can_claim_physical_without_evidence": False,
            "missing_executor_is_not_pass": True,
        },
    }


def normalize_sensor_evidence(
    payload: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    producer = str(payload.get("producer") or "").upper()
    if producer not in contract["sensors"]:
        raise SensorMeshError("unsupported sensor producer")
    repository = str(payload.get("repository") or "").strip()
    source_sha = str(payload.get("source_sha") or "").lower()
    if "/" not in repository or not SHA_RE.fullmatch(source_sha):
        raise SensorMeshError("invalid repository/source identity")
    rule = contract["sensors"][producer]
    artifact = str(payload.get("artifact_sha256") or "").lower()
    if rule.get("requires_artifact_sha256") and not HASH_RE.fullmatch(artifact):
        raise SensorMeshError("sensor requires exact artifact SHA-256")
    if artifact and not HASH_RE.fullmatch(artifact):
        raise SensorMeshError("invalid artifact SHA-256")
    if rule.get("requires_physical_device") and payload.get("physical_device") is not True:
        raise SensorMeshError("sensor requires explicit physical-device evidence")

    # Reuse the v5.6E evidence-only truth contract for the existing producers.
    normalized = hardening.normalize(payload)
    normalized["record_type"] = "SENSOR_MESH_EVIDENCE_V60H"
    normalized["mesh_execution"] = rule["execution"]
    normalized["provider_sensitive"] = bool(rule.get("provider_sensitive"))
    normalized["reviewed_version"] = str(rule.get("reviewed_version") or "")
    normalized["reviewed_at"] = str(rule.get("reviewed_at") or "")
    normalized["can_mint_pass"] = False
    normalized["can_mint_certified"] = False
    normalized["can_replace_trusted_runtime"] = False
    normalized["can_claim_store_distribution"] = False
    return normalized


def aggregate(
    plan: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    selected = set(_strings(plan.get("selected_sensor_ids")))
    repository = str(plan.get("repository") or "").strip()
    resolved_sha = str(plan.get("resolved_sha") or "").lower()
    by_producer = {
        str(row.get("producer") or "").upper(): row
        for row in evidence
        if (
            isinstance(row, dict)
            and str(row.get("repository") or "").strip() == repository
            and str(row.get("source_sha") or "").lower() == resolved_sha
        )
    }
    states = []
    for sensor in sorted(selected):
        if sensor in by_producer:
            states.append({
                "sensor": sensor,
                "state": "EVIDENCE_AVAILABLE",
                "evidence_refs": by_producer[sensor].get("evidence_refs", []),
            })
        else:
            states.append({
                "sensor": sensor,
                "state": "SELECTED_REQUIRES_EXECUTOR",
                "evidence_refs": [],
            })
    return {
        "schema_version": 1,
        "record_type": "SENSOR_MESH_AGGREGATE_V60H",
        "authority": "EVIDENCE_ROUTING_ONLY",
        "sensors": states,
        "complete": all(row["state"] == "EVIDENCE_AVAILABLE" for row in states),
        "missing_evidence_is_pass": False,
        "can_mint_pass": False,
        "can_mint_certified": False,
    }


def self_test() -> None:
    project = {
        "project_type": "flutter",
        "physical_validation": {
            "required": True,
            "capabilities": ["notifications"],
        },
    }
    planned = plan_sensors(
        {
            "repository": "owner/app",
            "resolved_sha": "a" * 40,
            "risk_score": 80,
            "selected_labs": {"network": True, "resource_pressure": True},
            "changed_files": [
                "android/app/src/main/AndroidManifest.xml",
                "pubspec.lock",
            ],
        },
        project,
    )
    ids = set(planned["selected_sensor_ids"])
    assert {"SCRCPY_CAPTURE", "LEAKCANARY", "SEMGREP", "TRIVY", "MOBSF", "HETTY"} <= ids
    assert planned["guardrails"]["can_mint_pass"] is False

    semgrep = normalize_sensor_evidence({
        "producer": "SEMGREP",
        "repository": "owner/app",
        "source_sha": "a" * 40,
        "evidence_refs": ["report://semgrep.json"],
    })
    assert semgrep["authority"] == "EVIDENCE_ONLY"
    assert semgrep["reviewed_version"] == "1.182.0"

    aggregate_report = aggregate(planned, [semgrep])
    assert aggregate_report["complete"] is False
    assert aggregate_report["missing_evidence_is_pass"] is False
    print("AppLab v6.0H sensor mesh self-test PASS")


def _read_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SensorMeshError(f"JSON root must be object: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="")
    parser.add_argument("--project", default="")
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--normalize", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.normalize:
        report = normalize_sensor_evidence(_read_json(args.normalize))
    else:
        if not args.plan or not args.project:
            raise SystemExit("--plan and --project are required")
        mesh_plan = plan_sensors(_read_json(args.plan), _read_json(args.project))
        if args.evidence:
            normalized = [
                normalize_sensor_evidence(_read_json(path))
                for path in args.evidence
            ]
            report = {
                "plan": mesh_plan,
                "aggregate": aggregate(mesh_plan, normalized),
            }
        else:
            report = mesh_plan
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
