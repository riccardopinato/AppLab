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
                     "needs.finalize.result == 'success'",
                     "needs.admit.outputs.dispatch == 'true'"):
        assert required in gate, required
    assert set(job["needs"]) == {"admit", "verify", "finalize"}
    assert job["permissions"]["contents"] == "read"
    assert job["permissions"]["actions"] == "read"
    assert "pull-requests" not in job["permissions"]
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "scripts/autonomous_repair_v62a.py" in commands
    assert "--publish" not in commands
    assert "gh api" in commands
    assert "GITHUB_SHA" in commands
    assert "v61a-closed-loop.json" in content
    assert "promotion_counted" not in commands


if __name__ == "__main__":
    check()
    print("v6.2A read-only causal canary workflow contract PASS")
