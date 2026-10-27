#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import execution_acceleration as acceleration  # noqa: E402
import sensor_mesh_v60h as mesh  # noqa: E402


def expect_error(callback, contains: str) -> None:
    try:
        callback()
    except (mesh.SensorMeshError, ValueError) as exc:
        assert contains in str(exc), (contains, str(exc))
    else:
        raise AssertionError(f"expected error containing {contains!r}")


def main() -> int:
    contract = mesh.load_contract()
    assert contract["authority"] == "EVIDENCE_ROUTING_ONLY"
    assert contract["sensors"]["SEMGREP"]["reviewed_version"] == "1.182.0"
    assert contract["sensors"]["TRIVY"]["reviewed_version"] == "0.76.1"
    assert contract["sensors"]["MOBSF"]["reviewed_version"] == "4.5.3"

    low = mesh.plan_sensors(
        {
            "repository": "owner/app",
            "resolved_sha": "a" * 40,
            "risk_score": 10,
            "selected_labs": {},
            "changed_files": ["lib/presentation/home.dart"],
        },
        {
            "project_type": "flutter",
            "physical_validation": {"required": False, "capabilities": []},
        },
    )
    assert low["selected_sensor_ids"] == []
    assert low["no_sensor_selected"] is True

    dependency = mesh.plan_sensors(
        {
            "repository": "owner/app",
            "resolved_sha": "b" * 40,
            "risk_score": 25,
            "selected_labs": {},
            "changed_files": ["pubspec.lock"],
        },
        {"project_type": "flutter"},
    )
    assert dependency["selected_sensor_ids"] == ["TRIVY"]

    execution_payload = acceleration.build_execution_plan(
        analysis_plan={
            "mode": "fast",
            "lane": "FAST_RUNTIME",
            "run_static": True,
            "run_build": True,
            "run_runtime": True,
            "risk_score": 80,
            "risk_reasons": ["network auth surface"],
            "selected_labs": {"network": True},
            "changed_files": ["lib/auth/oauth_client.dart"],
        },
        repository="owner/app",
        resolved_sha="d" * 40,
        engine="flutter",
        history_key="sensor-contract",
        working_directory=".",
        build_command="flutter build apk --debug",
        apk_path="build/app.apk",
        contract_fingerprint="contract-1",
        config_fingerprint="config-1",
        toolchain=["flutter:test"],
        build_inputs=["prepare:"],
    )
    execution_plan = mesh.plan_sensors(
        execution_payload,
        {"project_type": "flutter"},
    )
    assert set(execution_plan["selected_sensor_ids"]) >= {
        "HETTY",
        "MOBSF",
        "SEMGREP",
        "TRIVY",
    }

    expect_error(
        lambda: mesh.plan_sensors(
            {
                "repository": "owner/app",
                "resolved_sha": "d" * 40,
                "execution_key": "legacy",
                "dag": {"nodes": []},
                "selected_labs": ["network"],
            },
            {"project_type": "flutter"},
        ),
        "missing sensor risk inputs",
    )

    security = mesh.plan_sensors(
        {
            "repository": "owner/app",
            "resolved_sha": "c" * 40,
            "risk_score": 80,
            "selected_labs": {"network": True, "resource_pressure": True},
            "changed_files": [
                "android/app/src/main/AndroidManifest.xml",
                "lib/auth/oauth_client.dart",
                "pubspec.lock",
            ],
        },
        {
            "project_type": "flutter",
            "physical_validation": {
                "required": True,
                "capabilities": ["notifications", "biometrics"],
            },
        },
    )
    assert set(security["selected_sensor_ids"]) == {
        "HETTY",
        "LEAKCANARY",
        "MOBSF",
        "SCRCPY_CAPTURE",
        "SEMGREP",
        "TRIVY",
    }

    expect_error(
        lambda: mesh.normalize_sensor_evidence({
            "producer": "SCRCPY_CAPTURE",
            "repository": "owner/app",
            "source_sha": "a" * 40,
            "artifact_sha256": "1" * 64,
            "physical_device": False,
            "evidence_refs": ["video://capture"],
        }),
        "physical",
    )
    expect_error(
        lambda: mesh.normalize_sensor_evidence({
            "producer": "HETTY",
            "repository": "owner/app",
            "source_sha": "a" * 40,
            "evidence_refs": ["har://capture"],
        }),
        "artifact",
    )

    sem = mesh.normalize_sensor_evidence({
        "producer": "SEMGREP",
        "repository": "owner/app",
        "source_sha": "a" * 40,
        "evidence_refs": ["report://semgrep"],
    })
    trivy = mesh.normalize_sensor_evidence({
        "producer": "TRIVY",
        "repository": "owner/app",
        "source_sha": "a" * 40,
        "evidence_refs": ["report://trivy"],
    })
    aggregate = mesh.aggregate(security, [sem, trivy])
    assert aggregate["complete"] is False
    missing = {
        row["sensor"]
        for row in aggregate["sensors"]
        if row["state"] == "SELECTED_REQUIRES_EXECUTOR"
    }
    assert "SCRCPY_CAPTURE" in missing
    assert "MOBSF" in missing
    assert aggregate["missing_evidence_is_pass"] is False

    foreign_sem = mesh.normalize_sensor_evidence({
        "producer": "SEMGREP",
        "repository": "other/app",
        "source_sha": "f" * 40,
        "evidence_refs": ["report://foreign-semgrep"],
    })
    foreign_trivy = mesh.normalize_sensor_evidence({
        "producer": "TRIVY",
        "repository": "owner/app",
        "source_sha": "f" * 40,
        "evidence_refs": ["report://stale-trivy"],
    })
    identity_plan = mesh.plan_sensors(
        {
            "repository": "owner/app",
            "resolved_sha": "e" * 40,
            "risk_score": 70,
            "selected_labs": {},
            "changed_files": ["pubspec.lock"],
        },
        {"project_type": "flutter"},
    )
    foreign_aggregate = mesh.aggregate(identity_plan, [foreign_sem, foreign_trivy])
    assert foreign_aggregate["complete"] is False
    assert all(
        row["state"] == "SELECTED_REQUIRES_EXECUTOR"
        for row in foreign_aggregate["sensors"]
    )

    mesh.self_test()
    print("AppLab v6.0H sensor mesh contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
