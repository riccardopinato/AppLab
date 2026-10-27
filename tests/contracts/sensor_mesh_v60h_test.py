#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

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

    mesh.self_test()
    print("AppLab v6.0H sensor mesh contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
