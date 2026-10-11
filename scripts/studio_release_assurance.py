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


def project_from_directory(project_dir: Path) -> dict[str, Any] | None:
    payload = _read(project_dir / "release-assurance.json")
    if not payload:
        return None
    next_stage = payload.get("next_required_stage")
    next_stage = next_stage if isinstance(next_stage, dict) else {}
    rows = payload.get("stages")
    rows = rows if isinstance(rows, list) else []
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
        "required_total": sum(
            1 for row in rows if isinstance(row, dict) and row.get("required") is True
        ),
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
        (root / "release-assurance.json").write_text(
            json.dumps(
                {
                    "state": "BLOCKED",
                    "release_id": "r1",
                    "assurance_digest": "a" * 64,
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
            ),
            encoding="utf-8",
        )
        projection = project_from_directory(root)
        assert projection is not None
        assert projection["state"] == "BLOCKED"
        assert projection["required_passed"] == 1
        assert projection["required_total"] == 2
        summary = portfolio_summary([{"release_assurance": projection}])
        assert summary["with_release_assurance"] == 1
        assert summary["release_assurance_blocked"] == 1
    print("AppLab Release Assurance Studio projection self-test PASS")


if __name__ == "__main__":
    self_test()
