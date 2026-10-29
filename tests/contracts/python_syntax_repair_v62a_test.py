#!/usr/bin/env python3
"""Negative and positive fixtures do not certify autonomous production repairs."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from python_syntax_repair_v62a import generate, NotRepairable


def run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "scripts").mkdir()
        target = root / "scripts" / "broken.py"
        target.write_text("def broken()\n    return 3\n", encoding="utf-8")
        for command in (("git", "init", "-q"), ("git", "config", "user.name", "CI"),
                        ("git", "config", "user.email", "ci@example.invalid"),
                        ("git", "add", "."), ("git", "commit", "-qm", "fixture")):
            subprocess.run(command, cwd=root, check=True)
        diagnostic = 'File "/repo/scripts/broken.py", line 1\nSyntaxError: expected \':\''
        observed = subprocess.run(
            ("python", "-m", "compileall", "-q", "scripts"),
            cwd=root, capture_output=True, text=True, check=False)
        assert observed.returncode != 0
        emitted = observed.stdout + observed.stderr
        triage, plan, patch = generate(root, emitted)
        _, _, patch_absolute = generate(root, diagnostic)
        assert patch == patch_absolute
        assert triage["classification"] == "BUILD_OR_QUALITY_FAILURE"
        assert plan["changed_files"] == ["scripts/broken.py"]
        assert "+def broken():" in patch
        patch_file = root / "fix.patch"
        patch_file.write_text(patch, encoding="utf-8")
        subprocess.run(("git", "apply", "--check", str(patch_file)), cwd=root, check=True)
        for invalid in ("no failure", diagnostic.replace("line 1", "line 2")):
            try:
                generate(root, invalid)
            except NotRepairable:
                pass
            else:
                raise AssertionError("bad diagnostic accepted")
        target.write_text("def broken()\n    return 3", encoding="utf-8")
        try:
            generate(root, diagnostic)
        except NotRepairable:
            pass
        else:
            raise AssertionError("unterminated source accepted")


if __name__ == "__main__":
    run()
    print("v6.2A diagnostic-to-git-patch fixture PASS; real repairs 0")
