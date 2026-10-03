#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ENGINE_VERSION = "4.1.0"
RUNTIME_LANES = {"FAST_RUNTIME", "FULL_RUNTIME", "CERTIFICATION"}


def _safe(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    return normalized[:48] or "default"


def _bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return fallback


def read_plan(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read analysis plan: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("analysis plan must be a JSON object")
    return payload


def build_execution_plan(
    *,
    analysis_plan: dict[str, Any],
    repository: str,
    resolved_sha: str,
    engine: str,
    history_key: str,
    working_directory: str,
    build_command: str,
    apk_path: str,
    contract_fingerprint: str,
    config_fingerprint: str,
    toolchain: list[str],
) -> dict[str, Any]:
    sha = resolved_sha.lower().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("resolved_sha must be a 40-character commit SHA")

    lane = _safe(analysis_plan.get("lane")) or "FULL_RUNTIME"
    mode = _safe(analysis_plan.get("mode")) or _safe(analysis_plan.get("requested_mode")) or "full"
    selected_labs = (
        analysis_plan.get("selected_labs")
        if isinstance(analysis_plan.get("selected_labs"), dict)
        else {}
    )

    default_run_static = lane != "NO_RUNTIME_CHANGE"
    default_run_build = lane in RUNTIME_LANES
    default_run_runtime = lane in RUNTIME_LANES
    run_static = _bool(analysis_plan.get("run_static"), default_run_static)
    run_build = _bool(analysis_plan.get("run_build"), default_run_build)
    run_runtime = _bool(analysis_plan.get("run_runtime"), default_run_runtime)

    identity = {
        "repository": repository.strip().lower(),
        "resolved_sha": sha,
        "engine": engine.strip().lower(),
        "history_key": history_key.strip(),
        "working_directory": working_directory.strip() or ".",
        "build_command": build_command.strip(),
        "apk_path": apk_path.strip(),
        "mode": mode,
        "lane": lane,
        "contract_fingerprint": contract_fingerprint.strip(),
        "config_fingerprint": config_fingerprint.strip(),
        "toolchain": sorted(value.strip() for value in toolchain if value.strip()),
        "analysis_plan_sha256": hashlib.sha256(
            json.dumps(analysis_plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    execution_key = hashlib.sha256(encoded).hexdigest()
    artifact_name = f"applab-build-v41-{_slug(history_key)}-{execution_key[:24]}"

    nodes: list[dict[str, Any]] = [
        {"id": "impact-plan", "state": "RUN", "depends_on": []},
    ]
    if run_static:
        nodes.append({"id": "quality", "state": "RUN", "depends_on": ["impact-plan"]})
    else:
        nodes.append({"id": "quality", "state": "SKIP", "depends_on": ["impact-plan"]})

    if run_build:
        nodes.extend(
            [
                {
                    "id": "build-contract",
                    "state": "RESTORE_OR_BUILD",
                    "depends_on": ["quality"],
                    "cache_key": artifact_name,
                },
                {
                    "id": "trusted-runtime",
                    "state": "RUN" if run_runtime else "SKIP",
                    "depends_on": ["build-contract"],
                },
            ]
        )
    else:
        nodes.extend(
            [
                {"id": "build-contract", "state": "SKIP", "depends_on": ["quality"]},
                {"id": "trusted-runtime", "state": "SKIP", "depends_on": ["build-contract"]},
            ]
        )

    selected = sorted(
        key for key, value in selected_labs.items() if bool(value)
    )
    for lab in selected:
        nodes.append(
            {
                "id": f"lab:{lab}",
                "state": "RUN" if run_runtime else "SKIP",
                "depends_on": ["trusted-runtime"],
            }
        )

    nodes.append(
        {
            "id": "final-evidence",
            "state": "RUN",
            "depends_on": (
                [f"lab:{lab}" for lab in selected]
                if selected and run_runtime
                else ["trusted-runtime" if run_runtime else "quality"]
            ),
        }
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "execution_key": execution_key,
        "artifact_name": artifact_name,
        "repository": repository,
        "resolved_sha": sha,
        "engine": engine,
        "mode": mode,
        "lane": lane,
        "run_static": run_static,
        "run_build": run_build,
        "run_runtime": run_runtime,
        "selected_labs": selected,
        "selected_lab_count": len(selected),
        "identity": identity,
        "dag": {
            "nodes": nodes,
            "cancel_stale_same_ref": True,
            "build_once_verify_many": True,
            "content_addressed_build_contract": True,
        },
        "guardrails": {
            "cache_hit_requires_contract_validation": True,
            "cached_build_is_not_trusted_runtime_evidence": True,
            "certification_authority_unchanged": True,
            "failed_builds_are_not_cacheable": True,
        },
    }


def write_github_output(path: Path, report: dict[str, Any]) -> None:
    values = {
        "execution_key": report["execution_key"],
        "artifact_name": report["artifact_name"],
        "lane": report["lane"],
        "run_static": str(report["run_static"]).lower(),
        "run_build": str(report["run_build"]).lower(),
        "run_runtime": str(report["run_runtime"]).lower(),
        "selected_lab_count": str(report["selected_lab_count"]),
    }
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def self_test() -> None:
    plan = {
        "mode": "fast",
        "lane": "FAST_RUNTIME",
        "run_static": True,
        "run_build": True,
        "run_runtime": True,
        "selected_labs": {"network": True, "storage": False, "persistence": True},
    }
    first = build_execution_plan(
        analysis_plan=plan,
        repository="owner/app",
        resolved_sha="a" * 40,
        engine="flutter",
        history_key="demo",
        working_directory=".",
        build_command="flutter build apk --debug",
        apk_path="build/app.apk",
        contract_fingerprint="contract-1",
        config_fingerprint="config-1",
        toolchain=["flutter:3.35.0", "java:17"],
    )
    second = build_execution_plan(
        analysis_plan=plan,
        repository="owner/app",
        resolved_sha="a" * 40,
        engine="flutter",
        history_key="demo",
        working_directory=".",
        build_command="flutter build apk --debug",
        apk_path="build/app.apk",
        contract_fingerprint="contract-1",
        config_fingerprint="config-1",
        toolchain=["java:17", "flutter:3.35.0"],
    )
    assert first["execution_key"] == second["execution_key"]
    assert first["artifact_name"] == second["artifact_name"]
    assert first["selected_labs"] == ["network", "persistence"]
    assert first["dag"]["build_once_verify_many"] is True

    changed = build_execution_plan(
        analysis_plan=plan,
        repository="owner/app",
        resolved_sha="a" * 40,
        engine="flutter",
        history_key="demo",
        working_directory=".",
        build_command="flutter build apk --release",
        apk_path="build/app.apk",
        contract_fingerprint="contract-1",
        config_fingerprint="config-1",
        toolchain=["java:17", "flutter:3.35.0"],
    )
    assert changed["execution_key"] != first["execution_key"]

    docs = build_execution_plan(
        analysis_plan={"mode": "fast", "lane": "NO_RUNTIME_CHANGE", "selected_labs": {}},
        repository="owner/app",
        resolved_sha="b" * 40,
        engine="flutter",
        history_key="demo",
        working_directory=".",
        build_command="flutter build apk --debug",
        apk_path="build/app.apk",
        contract_fingerprint="contract-1",
        config_fingerprint="config-1",
        toolchain=[],
    )
    assert docs["run_build"] is False
    assert docs["run_runtime"] is False
    assert next(row for row in docs["dag"]["nodes"] if row["id"] == "build-contract")["state"] == "SKIP"
    print("AppLab Execution Acceleration self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis-plan")
    parser.add_argument("--repository")
    parser.add_argument("--resolved-sha")
    parser.add_argument("--engine")
    parser.add_argument("--history-key", default="external")
    parser.add_argument("--working-directory", default=".")
    parser.add_argument("--build-command", default="")
    parser.add_argument("--apk-path", default="")
    parser.add_argument("--contract-fingerprint", default="")
    parser.add_argument("--config-fingerprint", default="")
    parser.add_argument("--toolchain", action="append", default=[])
    parser.add_argument("--output", default="execution-plan.json")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    required = {
        "--analysis-plan": args.analysis_plan,
        "--repository": args.repository,
        "--resolved-sha": args.resolved_sha,
        "--engine": args.engine,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit("missing required arguments: " + ", ".join(missing))

    try:
        plan = read_plan(Path(args.analysis_plan))
        report = build_execution_plan(
            analysis_plan=plan,
            repository=args.repository,
            resolved_sha=args.resolved_sha,
            engine=args.engine,
            history_key=args.history_key,
            working_directory=args.working_directory,
            build_command=args.build_command,
            apk_path=args.apk_path,
            contract_fingerprint=args.contract_fingerprint,
            config_fingerprint=args.config_fingerprint,
            toolchain=args.toolchain,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.github_output:
        write_github_output(Path(args.github_output), report)

    print(
        json.dumps(
            {
                "engine_version": ENGINE_VERSION,
                "lane": report["lane"],
                "artifact_name": report["artifact_name"],
                "run_build": report["run_build"],
                "run_runtime": report["run_runtime"],
                "selected_lab_count": report["selected_lab_count"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
