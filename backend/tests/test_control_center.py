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
                    "certified_current": 1,
                    "lanes": {"FULL_RUNTIME": 1},
                    "shadow_false_negatives": 0,
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
                "agent_operations": {
                    "schema_version": 1,
                    "record_type": "AGENTIC_OPERATIONS_STUDIO_V60I",
                    "authority": "READ_ONLY_PROJECTION",
                    "available": True,
                    "summary": {
                        "work_items": 1,
                        "active": 1,
                        "complete": 0,
                        "stopped_or_blocked": 0,
                        "draft_prs": 0,
                        "evidence_records": 2,
                    },
                    "work_items": [{"work_item_id": "wrk_api"}],
                    "source_of_truth": "DURABLE_BRAIN_AND_EVIDENCE_RECORDS",
                    "merge_authority": "NONE",
                    "release_authority": "NONE",
                },
            }
        ),
        encoding="utf-8",
    )

    payload = load_snapshot(source)

    assert payload["available"] is True
    assert payload["summary"]["projects"] == 1
    assert payload["summary"]["pass"] == 1
    assert payload["summary"]["certified_current"] == 1
    assert payload["summary"]["lanes"]["FULL_RUNTIME"] == 1
    assert payload["summary"]["shadow_false_negatives"] == 0
    assert payload["projects"][0]["repository"] == "owner/repo"
    assert payload["agent_operations"]["available"] is True
    assert payload["agent_operations"]["summary"]["work_items"] == 1
    assert payload["agent_operations"]["work_items"][0]["work_item_id"] == "wrk_api"


def test_control_center_missing_snapshot(tmp_path: Path) -> None:
    payload = load_snapshot(tmp_path / "missing.json")

    assert payload["available"] is False
    assert payload["projects"] == []
    assert payload["summary"]["projects"] == 0
    assert payload["agent_operations"]["available"] is False
    assert payload["agent_operations"]["work_items"] == []
