#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import release_assurance


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


def _validated_record(
    project_dir: Path,
    payload: dict[str, Any],
) -> tuple[bool, list[str], list[dict[str, Any]], str, list[str]]:
    errors: list[str] = []
    if payload.get("schema_version") != release_assurance.SCHEMA_VERSION:
        errors.append("schema_version")
    if str(payload.get("applab_version", "")).strip() != release_assurance.APPLAB_VERSION:
        errors.append("applab_version")
    if str(payload.get("record_type", "")).strip() != release_assurance.RECORD_TYPE:
        errors.append("record_type")
    if str(payload.get("authority", "")).strip() != release_assurance.AUTHORITY:
        errors.append("authority")

    identity = payload.get("identity")
    if not isinstance(identity, dict):
        identity = {}
        errors.append("identity")

    rows_raw = payload.get("stages")
    rows = [row for row in rows_raw if isinstance(row, dict)] if isinstance(rows_raw, list) else []
    if not rows or len(rows) != len(rows_raw or []):
        errors.append("stages")
    keys = [str(row.get("key", "")).strip() for row in rows]
    if (
        tuple(keys) != release_assurance.CANONICAL_STAGE_KEYS
        or len(keys) != len(set(keys))
    ):
        errors.append("canonical_stage_set")
    stage_structure_valid = True
    for row in rows:
        key = str(row.get("key", "")).strip()
        state = str(row.get("state", "")).strip().upper()
        if not key:
            errors.append("stage_key")
            stage_structure_valid = False
        required = row.get("required")
        if type(required) is not bool:
            errors.append("stage_required")
            stage_structure_valid = False
        if key in release_assurance.ALWAYS_REQUIRED_STAGE_KEYS and required is not True:
            errors.append("canonical_required_flag")
        if key in release_assurance.CONDITIONAL_STAGE_KEYS:
            if required is False and state != release_assurance.NOT_APPLICABLE:
                errors.append("conditional_stage_state")
            if required is True and state == release_assurance.NOT_APPLICABLE:
                errors.append("required_stage_na")
        elif required is True and state == release_assurance.NOT_APPLICABLE:
            errors.append("required_stage_na")
        if state not in release_assurance.ALLOWED:
            errors.append("stage_state")
            stage_structure_valid = False

    declared_state = str(payload.get("state", "")).strip().upper()
    derived_state = release_assurance.overall_state(rows) if rows else release_assurance.BLOCKED
    if declared_state not in {
        release_assurance.PASS,
        release_assurance.FAIL,
        release_assurance.BLOCKED,
        release_assurance.NOT_VERIFIED,
    }:
        errors.append("state")
    elif declared_state != derived_state:
        errors.append("state_mismatch")

    expected_digest = str(payload.get("assurance_digest", "")).strip().lower()
    if identity and rows and stage_structure_valid:
        try:
            actual_digest = release_assurance.digest(identity, rows)
        except (KeyError, TypeError, ValueError):
            errors.append("assurance_digest")
        else:
            if expected_digest != actual_digest:
                errors.append("assurance_digest")
    else:
        errors.append("assurance_digest")

    identity_match, identity_mismatches = _identity_match(project_dir, payload)
    if not identity_match:
        errors.append("release_identity")

    return not errors, sorted(set(errors)), rows, derived_state, identity_mismatches


def _blocked_projection(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    reason: str,
    validation_errors: list[str],
    identity_mismatches: list[str],
) -> dict[str, Any]:
    required_total = sum(
        1 for row in rows if isinstance(row, dict) and row.get("required") is True
    )
    return {
        "state": "BLOCKED",
        "release_id": str(payload.get("release_id", "")),
        "assurance_digest": str(payload.get("assurance_digest", "")),
        "blockers": max(1, sum(
            1
            for row in rows
            if row.get("required") is True
            and str(row.get("state", "")).upper()
            in {release_assurance.BLOCKED, release_assurance.NOT_VERIFIED, release_assurance.NOT_APPLICABLE}
        )),
        "failures": sum(
            1
            for row in rows
            if row.get("required") is True
            and str(row.get("state", "")).upper() == release_assurance.FAIL
        ),
        "next_required_stage": reason,
        "certification_status": "NOT_VERIFIED",
        "required_passed": 0,
        "required_total": required_total,
        "identity_match": not identity_mismatches,
        "identity_mismatches": identity_mismatches,
        "record_valid": False,
        "validation_errors": validation_errors,
    }


def project_from_directory(project_dir: Path) -> dict[str, Any] | None:
    assurance_path = project_dir / "release-assurance.json"
    if not assurance_path.is_file():
        return None
    payload = _read(assurance_path)
    if payload is None or not payload:
        return _blocked_projection(
            payload or {},
            [],
            reason="ASSURANCE_RECORD_INVALID",
            validation_errors=["unreadable_or_empty_record"],
            identity_mismatches=[],
        )

    valid, validation_errors, rows, derived_state, identity_mismatches = _validated_record(
        project_dir, payload
    )
    if not valid:
        reason = "IDENTITY_MISMATCH" if identity_mismatches else "ASSURANCE_RECORD_INVALID"
        return _blocked_projection(
            payload,
            rows,
            reason=reason,
            validation_errors=validation_errors,
            identity_mismatches=identity_mismatches,
        )

    next_required = next(
        (
            row
            for row in rows
            if row.get("required") is True
            and str(row.get("state", "")).strip().upper() != release_assurance.PASS
        ),
        None,
    )
    certification = payload.get("certification")
    certification = certification if isinstance(certification, dict) else {}
    failures = [
        row
        for row in rows
        if row.get("required") is True
        and str(row.get("state", "")).strip().upper() == release_assurance.FAIL
    ]
    blockers = [
        row
        for row in rows
        if row.get("required") is True
        and str(row.get("state", "")).strip().upper()
        in {release_assurance.BLOCKED, release_assurance.NOT_VERIFIED}
    ]
    return {
        "state": derived_state,
        "release_id": str(payload.get("release_id", "")),
        "assurance_digest": str(payload.get("assurance_digest", "")),
        "blockers": len(blockers),
        "failures": len(failures),
        "next_required_stage": str(next_required.get("key", "")) if next_required else "",
        "certification_status": str(certification.get("status", "NOT_VERIFIED")),
        "required_passed": sum(
            1
            for row in rows
            if row.get("required") is True
            and str(row.get("state", "")).strip().upper() == release_assurance.PASS
        ),
        "required_total": sum(
            1 for row in rows if row.get("required") is True
        ),
        "identity_match": True,
        "identity_mismatches": [],
        "record_valid": True,
        "validation_errors": [],
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
        rows = [
            {"key": "SOURCE_BUILD_BOUND", "required": True, "state": "PASS"},
            {"key": "STATIC_BUILD_ASSURANCE", "required": True, "state": "PASS"},
            {"key": "TRUSTED_RUNTIME", "required": True, "state": "PASS"},
            {"key": "EVIDENCE_GRAPH", "required": True, "state": "PASS"},
            {"key": "RISK_BASED_VALIDATION", "required": True, "state": "PASS"},
            {"key": "PHYSICAL_EVIDENCE", "required": False, "state": "N/A"},
            {"key": "DISTRIBUTION_EVIDENCE", "required": True, "state": "BLOCKED"},
            {"key": "CROSS_APP", "required": False, "state": "N/A"},
            {"key": "CERTIFICATION", "required": True, "state": "PASS"},
        ]
        payload = {
            "schema_version": release_assurance.SCHEMA_VERSION,
            "applab_version": release_assurance.APPLAB_VERSION,
            "record_type": release_assurance.RECORD_TYPE,
            "authority": release_assurance.AUTHORITY,
            "state": "BLOCKED",
            "release_id": "r1",
            "identity": identity,
            "blockers": [{"key": "DISTRIBUTION_EVIDENCE"}],
            "failures": [],
            "next_required_stage": {"key": "DISTRIBUTION_EVIDENCE"},
            "certification": {"status": "CERTIFIED"},
            "stages": rows,
        }
        payload["assurance_digest"] = release_assurance.digest(identity, rows)
        (root / "release-assurance.json").write_text(json.dumps(payload), encoding="utf-8")
        projection = project_from_directory(root)
        assert projection is not None
        assert projection["state"] == "BLOCKED"
        assert projection["record_valid"] is True
        assert projection["identity_match"] is True
        assert projection["required_passed"] == 6
        assert projection["required_total"] == 7

        stale = json.loads(json.dumps(payload))
        stale["identity"]["artifact_sha256"] = "d" * 64
        stale["assurance_digest"] = release_assurance.digest(stale["identity"], rows)
        (root / "release-assurance.json").write_text(json.dumps(stale), encoding="utf-8")
        blocked = project_from_directory(root)
        assert blocked is not None
        assert blocked["state"] == "BLOCKED"
        assert blocked["identity_match"] is False
        assert blocked["next_required_stage"] == "IDENTITY_MISMATCH"

        inconsistent = json.loads(json.dumps(payload))
        inconsistent["state"] = "PASS"
        (root / "release-assurance.json").write_text(json.dumps(inconsistent), encoding="utf-8")
        blocked = project_from_directory(root)
        assert blocked is not None
        assert blocked["state"] == "BLOCKED"
        assert blocked["record_valid"] is False
        assert "state_mismatch" in blocked["validation_errors"]

        bad_digest = json.loads(json.dumps(payload))
        bad_digest["assurance_digest"] = "f" * 64
        (root / "release-assurance.json").write_text(json.dumps(bad_digest), encoding="utf-8")
        blocked = project_from_directory(root)
        assert blocked is not None
        assert "assurance_digest" in blocked["validation_errors"]

        bad_authority = json.loads(json.dumps(payload))
        bad_authority["authority"] = "OTHER"
        (root / "release-assurance.json").write_text(json.dumps(bad_authority), encoding="utf-8")
        blocked = project_from_directory(root)
        assert blocked is not None
        assert "authority" in blocked["validation_errors"]

        fake_stage = json.loads(json.dumps(payload))
        fake_stage["stages"] = [{"key": "FAKE", "required": True, "state": "PASS"}]
        fake_stage["state"] = "PASS"
        fake_stage["assurance_digest"] = release_assurance.digest(
            fake_stage["identity"], fake_stage["stages"]
        )
        (root / "release-assurance.json").write_text(json.dumps(fake_stage), encoding="utf-8")
        blocked = project_from_directory(root)
        assert blocked is not None
        assert blocked["state"] == "BLOCKED"
        assert "canonical_stage_set" in blocked["validation_errors"]

        malformed = json.loads(json.dumps(payload))
        malformed["stages"][0].pop("required")
        (root / "release-assurance.json").write_text(json.dumps(malformed), encoding="utf-8")
        blocked = project_from_directory(root)
        assert blocked is not None
        assert blocked["state"] == "BLOCKED"
        assert "stage_required" in blocked["validation_errors"]
        assert "assurance_digest" in blocked["validation_errors"]

        int_required = json.loads(json.dumps(payload))
        for row in int_required["stages"]:
            if row["key"] == "CROSS_APP":
                row["required"] = 1
                row["state"] = "FAIL"
        int_required["state"] = "PASS"
        (root / "release-assurance.json").write_text(json.dumps(int_required), encoding="utf-8")
        blocked = project_from_directory(root)
        assert blocked is not None
        assert blocked["state"] == "BLOCKED"
        assert "stage_required" in blocked["validation_errors"]

        (root / "release-assurance.json").write_text("{truncated", encoding="utf-8")
        blocked = project_from_directory(root)
        assert blocked is not None
        assert blocked["state"] == "BLOCKED"
        assert blocked["record_valid"] is False
        assert "unreadable_or_empty_record" in blocked["validation_errors"]

        (root / "release-assurance.json").write_text("{}", encoding="utf-8")
        blocked = project_from_directory(root)
        assert blocked is not None
        assert blocked["state"] == "BLOCKED"
        assert "unreadable_or_empty_record" in blocked["validation_errors"]

        summary = portfolio_summary([{"release_assurance": blocked}])
        assert summary["with_release_assurance"] == 1
        assert summary["release_assurance_blocked"] == 1
    print("AppLab Release Assurance Studio projection self-test PASS")


if __name__ == "__main__":
    self_test()
