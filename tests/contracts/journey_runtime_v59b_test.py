#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import journey_runtime  # noqa: E402


def executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    trusted = root / "trusted"
    target = root / "target"
    report = root / "report"
    plan_path = root / "plan.json"
    (trusted / "config").mkdir(parents=True)
    (target / ".maestro").mkdir(parents=True)
    (trusted / "config" / "journey-runtime-pilots.json").write_text(
        json.dumps({"schema_version": 1, "repositories": ["owner/app"]}),
        encoding="utf-8",
    )
    (target / ".maestro" / "shell.yaml").write_text(
        "appId: com.example.app\n---\n- assertVisible: Home\n",
        encoding="utf-8",
    )
    (target / "applab.project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "journeys": {
                    "catalog": {
                        "shell": {
                            "flow": ".maestro/shell.yaml",
                            "paths": ["lib/**"],
                            "labs": [],
                            "surfaces": ["home"],
                            "capabilities": ["navigation"],
                            "risk_class": "core",
                            "always_fast": True,
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    plan_path.write_text(
        json.dumps(
            {
                "lane": "FAST_RUNTIME",
                "selected_journeys": ["shell"],
                "journey_selection": {
                    "enforcement_eligible": True,
                    "unmatched_paths": [],
                },
            }
        ),
        encoding="utf-8",
    )
    return trusted, target, report, plan_path


def args(trusted: Path, target: Path, report: Path, plan: Path, repository: str = "owner/app") -> argparse.Namespace:
    return argparse.Namespace(
        target_root=str(target),
        trusted_root=str(trusted),
        plan=str(plan),
        repository=repository,
        package_id="com.example.app",
        report_dir=str(report),
        max_attempts=3,
        self_test=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        trusted, target, report, plan = fixture(root)
        fake_bin = root / "bin"
        fake_bin.mkdir()
        count = root / "maestro-count.txt"
        executable(
            fake_bin / "maestro",
            """#!/usr/bin/env bash
set -euo pipefail
count_file="${FAKE_MAESTRO_COUNT:?}"
count=0
[[ -f "$count_file" ]] && count="$(cat "$count_file")"
count=$((count+1))
echo "$count" > "$count_file"
if [[ "$count" -eq 1 ]]; then
  echo "device offline" >&2
  exit 1
fi
exit 0
""",
        )
        executable(
            fake_bin / "adb",
            """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"getprop sys_boot_completed"* ]]; then
  echo 1
fi
exit 0
""",
        )
        original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{fake_bin}:{original_path}"
        os.environ["FAKE_MAESTRO_COUNT"] = str(count)
        try:
            status = journey_runtime.execute(args(trusted, target, report, plan))
        finally:
            os.environ["PATH"] = original_path
            os.environ.pop("FAKE_MAESTRO_COUNT", None)

        assert status == 0
        payload = json.loads((report / "journey-runtime.json").read_text(encoding="utf-8"))
        assert payload["result"] == "PASS"
        assert payload["coverage_reduction_enabled"] is True
        assert payload["selected_journeys"] == ["shell"]
        assert len(payload["journeys"]) == 1
        assert len(payload["journeys"][0]["attempts"]) == 2
        assert payload["journeys"][0]["attempts"][0]["transient"] is True
        assert payload["journeys"][0]["attempts"][1]["result"] == "PASS"
        assert int(count.read_text(encoding="utf-8")) == 2

        fallback_report = root / "fallback-report"
        fallback = journey_runtime.execute(
            args(trusted, target, fallback_report, plan, repository="owner/not-pilot")
        )
        assert fallback == 3
        fallback_payload = json.loads(
            (fallback_report / "journey-runtime.json").read_text(encoding="utf-8")
        )
        assert fallback_payload["result"] == "LEGACY_FALLBACK"
        assert fallback_payload["coverage_reduction_enabled"] is False

    print("AppLab v5.9B independent atomic journey runtime PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
