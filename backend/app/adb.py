from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable


class AdbError(RuntimeError):
    pass


_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")


def validate_package_id(package_id: str) -> str:
    value = package_id.strip()
    if not _PACKAGE_RE.fullmatch(value):
        raise AdbError(f"Invalid package id: {package_id!r}")
    return value


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

    def installed_packages(self) -> list[str]:
        output = self.shell("pm", "list", "packages", "-3")
        return sorted(
            line.removeprefix("package:").strip()
            for line in output.splitlines()
            if line.startswith("package:")
        )

    def package_exists(self, package_id: str) -> bool:
        package_id = validate_package_id(package_id)
        return self.shell("pm", "path", package_id).strip().startswith("package:")

    def detect_package_id(self, apk: Path) -> str | None:
        for tool_name in ("apkanalyzer", "aapt2", "aapt"):
            tool = shutil.which(tool_name)
            if not tool:
                continue

            if tool_name == "apkanalyzer":
                command = [tool, "manifest", "application-id", str(apk)]
            else:
                command = [tool, "dump", "badging", str(apk)]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                continue

            if tool_name == "apkanalyzer":
                candidate = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
            else:
                match = re.search(r"package:\s+name='([^']+)'", result.stdout)
                candidate = match.group(1) if match else ""

            if candidate and _PACKAGE_RE.fullmatch(candidate):
                return candidate
        return None

    def install(self, apk: Path) -> str:
        return self._run(["install", "-r", "-t", str(apk)], timeout=180).stdout

    def launch(self, package_id: str) -> str:
        package_id = validate_package_id(package_id)
        self.stop(package_id)
        return self.shell(
            "monkey",
            "-p",
            package_id,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )

    def stop(self, package_id: str) -> str:
        package_id = validate_package_id(package_id)
        return self.shell("am", "force-stop", package_id)

    def restart(self, package_id: str) -> str:
        package_id = validate_package_id(package_id)
        self.stop(package_id)
        return self.launch(package_id)

    def clear(self, package_id: str) -> str:
        package_id = validate_package_id(package_id)
        return self.shell("pm", "clear", package_id)

    def uninstall(self, package_id: str) -> str:
        package_id = validate_package_id(package_id)
        return self._run(["uninstall", package_id], timeout=90).stdout

    def pid(self, package_id: str) -> str:
        package_id = validate_package_id(package_id)
        return self.shell("pidof", package_id).strip().split(" ")[0]

    def app_status(self, package_id: str) -> dict[str, object]:
        package_id = validate_package_id(package_id)
        installed = self.package_exists(package_id)
        if not installed:
            return {
                "package_id": package_id,
                "installed": False,
                "running": False,
                "foreground": False,
                "pid": "",
            }

        pid = self.pid(package_id)
        activity_dump = self.shell("dumpsys", "activity", "activities", timeout=30)
        foreground = any(
            package_id in line
            for line in activity_dump.splitlines()
            if "mResumedActivity" in line
            or "topResumedActivity" in line
            or "ResumedActivity" in line
        )
        return {
            "package_id": package_id,
            "installed": True,
            "running": bool(pid),
            "foreground": foreground,
            "pid": pid,
        }

    def key(self, key_code: str) -> str:
        return self.shell("input", "keyevent", key_code)

    def screenshot(self) -> bytes:
        result = self._run(["exec-out", "screencap", "-p"], timeout=30, text=False)
        return bytes(result.stdout)

    def logcat(self, lines: int = 400, package_id: str | None = None) -> str:
        count = str(max(1, min(lines, 5000)))
        if package_id:
            package_id = validate_package_id(package_id)
            pid = self.pid(package_id)
            if pid:
                try:
                    return self._run(
                        ["logcat", "--pid", pid, "-d", "-t", count, "-v", "threadtime"],
                        timeout=30,
                    ).stdout
                except AdbError:
                    pass
        return self._run(
            ["logcat", "-d", "-t", count, "-v", "threadtime"],
            timeout=30,
        ).stdout

    def clear_logcat(self) -> None:
        self._run(["logcat", "-c"])

    def device_info(self) -> dict[str, str]:
        serial = self.serial or self.shell("getprop", "ro.serialno").strip()
        return {
            "serial": serial,
            "model": self.shell("getprop", "ro.product.model").strip(),
            "manufacturer": self.shell("getprop", "ro.product.manufacturer").strip(),
            "android": self.shell("getprop", "ro.build.version.release").strip(),
            "sdk": self.shell("getprop", "ro.build.version.sdk").strip(),
            "boot_completed": self.shell("getprop", "sys.boot_completed").strip(),
        }
