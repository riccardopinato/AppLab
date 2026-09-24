import json
from pathlib import Path

from app.control_center import load_snapshot


def test_control_center_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "control-center.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-09-24T12:00:00+00:00",
                "summary": {
                    "projects": 1,
                    "pass": 1,
                    "fail": 0,
                    "not_run": 0,
                },
                "projects": [
                    {
                        "repository": "owner/repo",
                        "result": "PASS",
                        "resolved_sha": "abcdef123456",
                    }
                ],
                "recent": [
                    {
                        "repository": "owner/repo",
                        "result": "PASS",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = load_snapshot(source)

    assert payload["available"] is True
    assert payload["summary"]["projects"] == 1
    assert payload["summary"]["pass"] == 1
    assert payload["projects"][0]["repository"] == "owner/repo"


def test_control_center_missing_snapshot(tmp_path: Path) -> None:
    payload = load_snapshot(tmp_path / "missing.json")

    assert payload["available"] is False
    assert payload["projects"] == []
    assert payload["summary"]["projects"] == 0
