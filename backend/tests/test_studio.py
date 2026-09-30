import json
from pathlib import Path

from app.studio import empty_studio_snapshot, load_studio_snapshot


def test_empty_studio_snapshot(tmp_path: Path) -> None:
    payload = load_studio_snapshot(tmp_path / "missing.json")
    assert payload == empty_studio_snapshot()
    assert payload["available"] is False


def test_load_studio_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "studio.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-09-28T00:00:00Z",
                "summary": {
                    "projects": 2,
                    "with_market": 1,
                    "manual_review": 1,
                    "recurrent_patterns": 3,
                    "with_analyst_reports": 2,
                    "analyst_attention": 1,
                    "planned_experiments": 4,
                    "trusted_runtime_reviews": 2,
                },
                "projects": [{"project_id": "one"}, {"project_id": "two"}],
                "portfolio": {"project_count": 2},
            }
        ),
        encoding="utf-8",
    )
    payload = load_studio_snapshot(source)
    assert payload["available"] is True
    assert payload["summary"]["projects"] == 2
    assert payload["summary"]["recurrent_patterns"] == 3
    assert payload["summary"]["with_analyst_reports"] == 2
    assert payload["summary"]["analyst_attention"] == 1
    assert payload["summary"]["planned_experiments"] == 4
    assert payload["summary"]["trusted_runtime_reviews"] == 2
    assert len(payload["projects"]) == 2
    assert payload["portfolio"]["project_count"] == 2
