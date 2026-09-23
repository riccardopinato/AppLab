from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class MaestroError(RuntimeError):
    pass


_SAFE_FLOW = re.compile(r"^[A-Za-z0-9._-]+$")


class MaestroRunner:
    def __init__(self) -> None:
        self.flow_dir = Path(os.getenv("APPLAB_FLOW_DIR", "/app/flows"))
        self.output_dir = Path(os.getenv("APPLAB_TEST_OUTPUT_DIR", "/tmp/applab-maestro"))

    @property
    def available(self) -> bool:
        return shutil.which("maestro") is not None

    def flows(self) -> list[str]:
        names = ["generic-smoke"]
        if self.flow_dir.exists():
            for path in sorted(self.flow_dir.iterdir()):
                if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}:
                    names.append(path.name)
        return names

    def _resolve_flow(self, flow: str, package_id: str, temp_dir: Path) -> Path:
        if flow == "generic-smoke":
            path = temp_dir / "generic-smoke.yaml"
            path.write_text(
                f"""appId: {package_id}
---
- launchApp:
    clearState: false
- pressKey: HOME
- launchApp:
    clearState: false
""",
                encoding="utf-8",
            )
            return path

        if not _SAFE_FLOW.fullmatch(flow):
            raise MaestroError("Invalid Maestro flow name.")

        candidate = (self.flow_dir / flow).resolve()
        root = self.flow_dir.resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise MaestroError(f"Unknown Maestro flow: {flow}")
        return candidate

    def run(self, package_id: str, flow: str = "generic-smoke") -> dict[str, Any]:
        if not self.available:
            raise MaestroError("Maestro is not installed on the AppLab controller.")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="applab-flow-") as tmp:
            flow_path = self._resolve_flow(flow, package_id, Path(tmp))
            report_dir = self.output_dir / "latest"
            if report_dir.exists():
                shutil.rmtree(report_dir)
            report_dir.mkdir(parents=True, exist_ok=True)

            result = subprocess.run(
                [
                    "maestro",
                    "test",
                    str(flow_path),
                    "--test-output-dir",
                    str(report_dir),
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
                env={**os.environ, "APP_ID": package_id},
            )

        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        return {
            "ok": result.returncode == 0,
            "flow": flow,
            "returncode": result.returncode,
            "output": output,
        }
