#!/usr/bin/env python3
"""Production gate: a failed canary may investigate, never self-publish."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]


def check() -> None:
    file = ROOT / ".github/workflows/controlled-event-pilot.yml"
    content = file.read_text(encoding="utf-8")
    doc = yaml.safe_load(content)
    jobs = doc["jobs"]
    job = jobs["repair_intake"]
    gate = str(job["if"])
    for required in ("always()", "github.event_name == 'push'",
                     "needs.verify.result == 'failure'",
                     "needs.python_quality.result == 'failure'",
                     "github.run_attempt == 1",
                     "needs.finalize.result == 'success'",
                     "needs.admit.outputs.dispatch == 'true'"):
        assert required in gate, required
    assert set(job["needs"]) == {"admit", "verify", "finalize", "python_quality"}
    python_job = jobs["python_quality"]
    assert python_job["permissions"]["contents"] == "read"
    assert "python -m compileall -q scripts" in python_job["steps"][-1]["run"]
    assert job["permissions"]["contents"] == "read"
    assert job["permissions"]["actions"] == "read"
    assert "pull-requests" not in job["permissions"]
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "scripts/autonomous_repair_v62a.py" in commands
    assert "--patch-output v62a-candidate.patch" in commands
    artifact = job["steps"][-1]["with"]["path"]
    assert "v62a-local-repair.json" in artifact
    assert "v62a-candidate.patch" in artifact
    assert "--publish" not in commands
    assert "gh api" in commands
    assert "GITHUB_SHA" in commands
    assert "v61a-closed-loop.json" in content
    assert "promotion_counted" not in commands
    draft = jobs["repair_draft_pr"]
    assert set(draft["needs"]) == {"admit", "verify", "finalize", "python_quality", "repair_intake"}
    publish_gate = str(draft["if"])
    for expected in ("github.event_name == 'push'", "github.ref == 'refs/heads/main'",
                     "github.run_attempt == 1",
                     "needs.repair_intake.result == 'success'",
                     "needs.admit.outputs.dispatch == 'true'"):
        assert expected in publish_gate, expected
    assert draft["permissions"]["contents"] == "write"
    assert draft["permissions"]["pull-requests"] == "write"
    assert draft["permissions"]["actions"] == "read"
    publish_commands = "\\n".join(step.get("run", "") for step in draft["steps"])
    for required in ("v62a-local-repair.json", "v62a-candidate.patch",
                     "sha256sum v62a-candidate.patch", "--publish",
                     "--expected-patch-sha256", "GITHUB_SHA",
                     "refs/heads/main", "DRAFT_PR_CREATED"):
        assert required in publish_commands, required
    assert "gh pr merge" not in publish_commands
    assert "gh pr review" not in publish_commands
    assert ".promotion_counted == false" in publish_commands



if __name__ == "__main__":
    check()
    print("v6.2A read-only causal canary workflow contract PASS")
