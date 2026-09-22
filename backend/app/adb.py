from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class AdbError(RuntimeError):
    pass


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


class AdbController:
    def __init__(self, serial: str | None = None) -> None:
        self.serial = (serial if serial is not None else os.getenv("ADB_SERIAL", "")).strip()

    def _base(self) -> list[str]:
        command = ["adb"]
        if self.serial:
            command += ["-s", self.serial]
        return command

    def _run(
        self,
        args: Iterable[str],
        *,
        timeout: int = 60,
        check: bool = True,
        text: bool = True,
    ) -> subprocess.CompletedProcess:
        command = [*self._base(), *list(args)]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=text,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AdbError(str(exc)) from exc

        if check and result.returncode != 0:
            stderr = result.stderr if text else repr(result.stderr)
            stdout = result.stdout if text else repr(result.stdout)
            raise AdbError(f"ADB command failed ({result.returncode}): {stderr or stdout}")
        return result

    def connect_if_remote(self) -> None:
        if self.serial and ":" in self.serial and not self.serial.startswith("emulator-"):
            result = subprocess.run(
                ["adb", "connect", self.serial],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                raise AdbError(result.stderr or result.stdout)

    def devices(self) -> str:
        result = subprocess.run(
            ["adb", "devices", "-l"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode != 0:
            raise AdbError(result.stderr or result.stdout)
        return result.stdout

    def shell(self, *args: str, timeout: int = 60) -> str:
        return self._run(["shell", *args], timeout=timeout).stdout

    def install(self, apk: Path) -> str:
        return self._run(["install", "-r", "-t", str(apk)], timeout=180).stdout

    def launch(self, package_id: str) -> str:
        self.shell("am", "force-stop", package_id)
        return self.shell(
            "monkey", "-p", package_id,
            "-c", "android.intent.category.LAUNCHER", "1",
        )

    def stop(self, package_id: str) -> str:
        return self.shell("am", "force-stop", package_id)

    def clear(self, package_id: str) -> str:
        return self.shell("pm", "clear", package_id)

    def key(self, key_code: str) -> str:
        return self.shell("input", "keyevent", key_code)

    def screenshot(self) -> bytes:
        result = self._run(["exec-out", "screencap", "-p"], timeout=30, text=False)
        return bytes(result.stdout)

    def logcat(self, lines: int = 400) -> str:
        return self._run([
            "logcat", "-d", "-t", str(max(1, min(lines, 5000))), "-v", "threadtime"
        ]).stdout

    def clear_logcat(self) -> None:
        self._run(["logcat", "-c"])

    def device_info(self) -> dict[str, str]:
        return {
            "serial": self.serial,
            "model": self.shell("getprop", "ro.product.model").strip(),
            "manufacturer": self.shell("getprop", "ro.product.manufacturer").strip(),
            "android": self.shell("getprop", "ro.build.version.release").strip(),
            "sdk": self.shell("getprop", "ro.build.version.sdk").strip(),
            "boot_completed": self.shell("getprop", "sys.boot_completed").strip(),
        }
