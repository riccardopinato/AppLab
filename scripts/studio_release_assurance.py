#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _identity_match(
    project_dir: Path,
    assurance: dict[str, Any],
) -> tuple[bool, list[str]]:
    reality = _read(project_dir / "release-reality.json")
    identity = assurance.get("identity")
    if not isinstance(reality, dict) or not isinstance(identity, dict):
        return False, ["missing_identity_source"]

    source = reality.get("source") if isinstance(reality.get("source"), dict) else {}
    artifact = reality.get("artifact") if isinstance(reality.get("artifact"), dict) else {}
    expected = {
        "repository": str(source.get("repository", "")).strip(),
        "resolved_sha": str(source.get("resolved_sha", "")).strip().lower(),
        "artifact_sha256": str(artifact.get("sha256", "")).strip().lower(),
        "package_id": str(artifact.get("package_id", "")).strip(),
        "version_name": str(artifact.get("version_name", "")).strip(),
        "version_code": str(artifact.get("version_code", "")).strip(),
    }
    observed = {
        "repository": str(identity.get("repository", "")).strip(),
        "resolved_sha": str(identity.get("resolved_sha", "")).strip().lower(),
        "artifact_sha256": str(identity.get("artifact_sha256", "")).strip().lower(),
        "package_id": str(identity.get("package_id", "")).strip(),
        "version_name": str(identity.get("version_name", "")).strip(),
        "version_code": str(identity.get("version_code", "")).strip(),
    }
    mismatches = [
        key
        for key, expected_value in expected.items()
        if not expected_value or observed.get(key) != expected_value
    ]
    return not mismatches, mismatches


def project_from_directory(project_dir: Path) -> dict[str, Any] | None:
    payload = _read(project_dir / "release-assurance.json")
    if not payload:
        return None
    next_stage = payload.get("next_required_stage")
    next_stage = next_stage if isinstance(next_stage, dict) else {}
    rows = payload.get("stages")
    rows = rows if isinstance(rows, list) else []
    required_total = sum(
        1 for row in rows if isinstance(row, dict) and row.get("required") is True
    )
    identity_match, identity_mismatches = _identity_match(project_dir, payload)
    if not identity_match:
        return {
            "state": "BLOCKED",
            "release_id": str(payload.get("release_id", "")),
            "assurance_digest": str(payload.get("assurance_digest", "")),
            "blockers": max(1, len(payload.get("blockers") or [])),
            "failures": len(payload.get("failures") or []),
            "next_required_stage": "IDENTITY_MISMATCH",
            "certification_status": "NOT_VERIFIED",
            "required_passed": 0,
            "required_total": required_total,
            "identity_match": False,
            "identity_mismatches": identity_mismatches,
        }

    certification = payload.get("certification")
    certification = certification if isinstance(certification, dict) else {}
    return {
        "state": str(payload.get("state", "NOT_VERIFIED")),
        "release_id": str(payload.get("release_id", "")),
        "assurance_digest": str(payload.get("assurance_digest", "")),
        "blockers": len(payload.get("blockers") or []),
        "failures": len(payload.get("failures") or []),
        "next_required_stage": str(next_stage.get("key", "")),
        "certification_status": str(certification.get("status", "NOT_VERIFIED")),
        "required_passed": sum(
            1
            for row in rows
            if isinstance(row, dict)
            and row.get("required") is True
            and row.get("state") == "PASS"
        ),
        "required_total": required_total,
        "identity_match": True,
        "identity_mismatches": [],
    }


def portfolio_summary(projects: list[dict[str, Any]]) -> dict[str, int]:
    rows = [
        row.get("release_assurance")
        for row in projects
        if isinstance(row.get("release_assurance"), dict)
    ]
    return {
        "with_release_assurance": len(rows),
        "release_assurance_pass": sum(1 for row in rows if row.get("state") == "PASS"),
        "release_assurance_blocked": sum(1 for row in rows if row.get("state") == "BLOCKED"),
        "release_assurance_fail": sum(1 for row in rows if row.get("state") == "FAIL"),
    }


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        identity = {
            "repository": "owner/demo",
            "resolved_sha": "a" * 40,
            "artifact_sha256": "b" * 64,
            "package_id": "com.example.demo",
            "version_name": "1.0.0",
            "version_code": "1",
        }
        (root / "release-reality.json").write_text(
            json.dumps(
                {
                    "source": {
                        "repository": identity["repository"],
                        "resolved_sha": identity["resolved_sha"],
                    },
                    "artifact": {
                        "sha256": identity["artifact_sha256"],
                        "package_id": identity["package_id"],
                        "version_name": identity["version_name"],
                        "version_code": identity["version_code"],
                    },
                }
            ),
            encoding="utf-8",
        )
        payload = {
            "state": "BLOCKED",
            "release_id": "r1",
            "assurance_digest": "c" * 64,
            "identity": identity,
            "blockers": [{"key": "DISTRIBUTION_EVIDENCE"}],
            "failures": [],
            "next_required_stage": {"key": "DISTRIBUTION_EVIDENCE"},
            "certification": {"status": "CERTIFIED"},
            "stages": [
                {"required": True, "state": "PASS"},
                {"required": True, "state": "BLOCKED"},
                {"required": False, "state": "N/A"},
            ],
        }
        (root / "release-assurance.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        projection = project_from_directory(root)
        assert projection is not None
        assert projection["state"] == "BLOCKED"
        assert projection["identity_match"] is True
        assert projection["required_passed"] == 1
        assert projection["required_total"] == 2

        stale = json.loads(json.dumps(payload))
        stale["identity"]["artifact_sha256"] = "d" * 64
        stale["state"] = "PASS"
        (root / "release-assurance.json").write_text(
            json.dumps(stale),
            encoding="utf-8",
        )
        blocked = project_from_directory(root)
        assert blocked is not None
        assert blocked["state"] == "BLOCKED"
        assert blocked["identity_match"] is False
        assert blocked["next_required_stage"] == "IDENTITY_MISMATCH"
        assert "artifact_sha256" in blocked["identity_mismatches"]
        assert blocked["certification_status"] == "NOT_VERIFIED"

        summary = portfolio_summary([{"release_assurance": blocked}])
        assert summary["with_release_assurance"] == 1
        assert summary["release_assurance_blocked"] == 1
    print("AppLab Release Assurance Studio projection self-test PASS")


if __name__ == "__main__":
    self_test()
