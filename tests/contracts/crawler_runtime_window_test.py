#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import interaction_crawler as crawler  # noqa: E402

PACKAGE = "com.example.app"
UI = """<hierarchy>
  <node package="com.example.app" class="android.widget.Button"
    text="Settings" content-desc="" clickable="true" enabled="true"
    bounds="[10,10][210,90]"/>
</hierarchy>"""


class FakeRuntime:
    def __init__(self, *, stale_anr: bool, fail_on_tap: bool) -> None:
        self.logcat = [f"ANR in {PACKAGE}"] if stale_anr else []
        self.fail_on_tap = fail_on_tap
        self.clear_count = 0

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        stdout = ""
        if args == ("adb", "logcat", "-b", "all", "-c"):
            self.logcat.clear()
            self.clear_count += 1
        elif args[:3] == ("adb", "shell", "pidof"):
            stdout = "123\n"
        elif args[:6] == ("adb", "logcat", "-b", "all", "-d", "-v"):
            stdout = "\n".join(self.logcat)
        elif args[:4] == ("adb", "shell", "input", "tap") and self.fail_on_tap:
            self.logcat.append(f"ANR in {PACKAGE}")
        return subprocess.CompletedProcess(list(args), 0, stdout=stdout, stderr="")


def fake_capture(output_dir: Path, prefix: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    screenshot = output_dir / f"{prefix}.png"
    hierarchy = output_dir / f"{prefix}.xml"
    screenshot.write_bytes(b"png")
    hierarchy.write_text(UI, encoding="utf-8")
    return screenshot, hierarchy


def run_case(*, stale_anr: bool, fail_on_tap: bool) -> tuple[dict, FakeRuntime]:
    fake = FakeRuntime(stale_anr=stale_anr, fail_on_tap=fail_on_tap)
    original_run = crawler.run
    original_capture = crawler.adb_capture
    original_sleep = crawler.time.sleep
    try:
        crawler.run = fake.run
        crawler.adb_capture = fake_capture
        crawler.time.sleep = lambda _seconds: None
        with tempfile.TemporaryDirectory() as raw:
            report = crawler.crawl(
                PACKAGE,
                Path(raw),
                max_actions=1,
                settle=0.5,
            )
        return report, fake
    finally:
        crawler.run = original_run
        crawler.adb_capture = original_capture
        crawler.time.sleep = original_sleep


def main() -> int:
    stale_report, stale_runtime = run_case(stale_anr=True, fail_on_tap=False)
    assert stale_report["result"] == "PASS", stale_report
    assert stale_report["failures"] == 0, stale_report
    assert stale_runtime.clear_count >= 3, stale_runtime.clear_count
    assert (
        stale_report["runtime_window_strategy"]
        == "reset-before-relaunch-and-each-action"
    )

    fresh_report, _ = run_case(stale_anr=True, fail_on_tap=True)
    assert fresh_report["result"] == "FAIL", fresh_report
    assert fresh_report["failures"] == 1, fresh_report
    assert any(row.get("reason") == "ANR detected" for row in fresh_report["actions"])

    print("AppLab crawler runtime-window regression PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
