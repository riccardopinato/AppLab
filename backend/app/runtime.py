from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import docker
from docker.errors import APIError, BuildError, DockerException, ImageNotFound, NotFound


class LiveRuntimeError(RuntimeError):
    pass


class LiveRuntimeManager:
    def __init__(self) -> None:
        self.container_name = os.getenv("APPLAB_EMULATOR_CONTAINER", "applab-emulator")
        self.image = os.getenv(
            "APPLAB_EMULATOR_IMAGE",
            "applab-emulator-runtime:0.3.1",
        )
        self.base_image = os.getenv(
            "APPLAB_EMULATOR_BASE_IMAGE",
            "us-docker.pkg.dev/android-emulator-268719/images/30-google-x64-no-metrics:7148297",
        )
        self.build_context = Path(
            os.getenv("APPLAB_EMULATOR_BUILD_CONTEXT", "/opt/applab/emulator-runtime")
        )
        self.adb_serial = os.getenv("APPLAB_LIVE_ADB_SERIAL", "127.0.0.1:5555")
        self.grpc_port = int(os.getenv("APPLAB_EMULATOR_GRPC_PORT", "8554"))
        self.gateway_port = int(os.getenv("APPLAB_GATEWAY_PORT", "8080"))
        self.data_dir = Path(os.getenv("APPLAB_DATA_DIR", "/data"))
        self.adb_key = self.data_dir / "adbkey"
        self.discovery_file = self.data_dir / "emulator-discovery.ini"
        self.gateway_log = self.data_dir / "gateway.log"
        self.emulator_log = self.data_dir / "emulator-last.log"
        self.emulator_params = os.getenv(
            "APPLAB_EMULATOR_PARAMS",
            "-no-window -no-audio -no-boot-anim -gpu swiftshader_indirect",
        )
        self.boot_timeout = int(os.getenv("APPLAB_BOOT_TIMEOUT", "240"))
        self.docker_timeout = int(os.getenv("APPLAB_DOCKER_TIMEOUT", "1200"))
        self._lock = threading.RLock()
        self._gateway: subprocess.Popen[str] | None = None
        self._gateway_log_handle = None

    def _docker(self):
        try:
            client = docker.from_env(timeout=self.docker_timeout)
            client.ping()
            return client
        except DockerException as exc:
            raise LiveRuntimeError(
                "Docker Engine is not reachable. Start AppLab with docker-compose.live.yml."
            ) from exc

    def _container(self):
        try:
            return self._docker().containers.get(self.container_name)
        except NotFound:
            return None
        except DockerException as exc:
            raise LiveRuntimeError(str(exc)) from exc

    def _ensure_image(self, client) -> None:
        try:
            client.images.get(self.image)
            return
        except ImageNotFound:
            pass

        if self.build_context.is_dir():
            try:
                client.images.build(
                    path=str(self.build_context),
                    tag=self.image,
                    rm=True,
                    forcerm=True,
                    pull=True,
                    buildargs={
                        "EMULATOR_BASE_IMAGE": self.base_image,
                    },
                )
                return
            except (BuildError, APIError, DockerException) as exc:
                raise LiveRuntimeError(
                    f"Unable to build WebRTC-capable emulator image {self.image}: {exc}"
                ) from exc

        try:
            client.images.pull(self.image)
        except (APIError, DockerException) as exc:
            raise LiveRuntimeError(
                f"Emulator image {self.image} is unavailable and build context "
                f"{self.build_context} is not mounted: {exc}"
            ) from exc

    def _ensure_host_capabilities(self) -> None:
        if not Path("/dev/kvm").exists():
            raise LiveRuntimeError(
                "/dev/kvm is unavailable. AppLab Live requires a Linux KVM host "
                "or a VM with nested virtualization."
            )
        if shutil.which("adb") is None:
            raise LiveRuntimeError("adb is not installed in the AppLab controller.")
        if shutil.which("videobridge-gateway") is None:
            raise LiveRuntimeError(
                "videobridge-gateway is not installed in the AppLab controller image."
            )

    def _ensure_adb_key(self) -> str:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.adb_key.exists():
            result = subprocess.run(
                ["adb", "keygen", str(self.adb_key)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode != 0 or not self.adb_key.exists():
                raise LiveRuntimeError(result.stderr or result.stdout or "Unable to create ADB key.")
        try:
            os.chmod(self.adb_key, 0o600)
        except OSError:
            pass
        return self.adb_key.read_text(encoding="utf-8").strip()

    def _adb(self, *args: str, timeout: int = 30, check: bool = False) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["ADB_VENDOR_KEYS"] = str(self.data_dir)
        return subprocess.run(
            ["adb", "-s", self.adb_serial, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
            env=env,
        )

    def _connect_adb(self) -> None:
        env = dict(os.environ)
        env["ADB_VENDOR_KEYS"] = str(self.data_dir)
        subprocess.run(
            ["adb", "connect", self.adb_serial],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            env=env,
        )

    def _wait_for_boot(self) -> None:
        deadline = time.monotonic() + self.boot_timeout
        last_error = ""
        while time.monotonic() < deadline:
            self._connect_adb()
            try:
                result = self._adb("shell", "getprop", "sys.boot_completed", timeout=12)
                if result.returncode == 0 and result.stdout.strip() == "1":
                    return
                last_error = result.stderr.strip() or result.stdout.strip()
            except (OSError, subprocess.TimeoutExpired) as exc:
                last_error = str(exc)
            time.sleep(2)
        raise LiveRuntimeError(
            f"Android emulator did not finish booting within {self.boot_timeout}s. {last_error}".strip()
        )

    def _gateway_alive(self) -> bool:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.gateway_port}/api/v1/emulator/status",
                timeout=2,
            ) as response:
                return 200 <= response.status < 300
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def _stop_gateway(self) -> None:
        process = self._gateway
        self._gateway = None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if self._gateway_log_handle:
            try:
                self._gateway_log_handle.close()
            except OSError:
                pass
            self._gateway_log_handle = None

    def _start_gateway(self) -> None:
        self._stop_gateway()
        self.discovery_file.write_text(
            f"grpc.port={self.grpc_port}\n",
            encoding="utf-8",
        )
        self._gateway_log_handle = self.gateway_log.open("a", encoding="utf-8")
        self._gateway = subprocess.Popen(
            [
                "videobridge-gateway",
                f"--port={self.gateway_port}",
                f"--discovery_file={self.discovery_file}",
            ],
            stdout=self._gateway_log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=dict(os.environ),
        )

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self._gateway.poll() is not None:
                raise LiveRuntimeError(
                    f"WebRTC gateway exited with code {self._gateway.returncode}. "
                    f"See {self.gateway_log}."
                )
            if self._gateway_alive():
                return
            time.sleep(1)
        raise LiveRuntimeError("WebRTC gateway did not become ready within 30s.")

    def start(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_host_capabilities()
            client = self._docker()
            existing = self._container()
            if existing is not None:
                existing.reload()
                if existing.status == "running":
                    self._connect_adb()
                    self._wait_for_boot()
                    if not self._gateway_alive():
                        self._start_gateway()
                    return self.status()
                try:
                    existing.remove(force=True)
                except DockerException as exc:
                    raise LiveRuntimeError(f"Unable to replace stale emulator container: {exc}") from exc

            adb_key = self._ensure_adb_key()
            try:
                self._ensure_image(client)

                client.containers.run(
                    self.image,
                    name=self.container_name,
                    detach=True,
                    environment={
                        "ADBKEY": adb_key,
                        "EMULATOR_PARAMS": self.emulator_params,
                    },
                    devices=["/dev/kvm:/dev/kvm:rwm"],
                    network_mode="host",
                    shm_size="2g",
                    labels={
                        "dev.applab.role": "android-emulator",
                        "dev.applab.managed": "true",
                    },
                )
            except (APIError, DockerException) as exc:
                raise LiveRuntimeError(f"Unable to start Android emulator container: {exc}") from exc

            try:
                self._wait_for_boot()
                self._start_gateway()
            except Exception:
                container = self._container()
                if container is not None:
                    try:
                        logs = container.logs(stdout=True, stderr=True, tail=2000)
                        self.emulator_log.write_bytes(logs)
                    except (DockerException, OSError):
                        pass
                    try:
                        container.remove(force=True)
                    except DockerException:
                        pass
                self._stop_gateway()
                raise

            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop_gateway()
            try:
                container = self._container()
                if container is not None:
                    container.remove(force=True)
            except DockerException as exc:
                raise LiveRuntimeError(f"Unable to stop emulator container: {exc}") from exc

            env = dict(os.environ)
            env["ADB_VENDOR_KEYS"] = str(self.data_dir)
            subprocess.run(
                ["adb", "disconnect", self.adb_serial],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                env=env,
            )
            return self.status()

    def restart(self) -> dict[str, Any]:
        with self._lock:
            self.stop()
            return self.start()

    def status(self) -> dict[str, Any]:
        docker_available = True
        docker_error = ""
        container_state = "missing"
        container_id = ""

        try:
            container = self._container()
            if container is not None:
                container.reload()
                container_state = container.status
                container_id = container.short_id
        except LiveRuntimeError as exc:
            docker_available = False
            docker_error = str(exc)

        adb_ready = False
        boot_completed = False
        if container_state == "running":
            self._connect_adb()
            try:
                state = self._adb("get-state", timeout=5)
                adb_ready = state.returncode == 0 and "device" in state.stdout
                if adb_ready:
                    boot = self._adb("shell", "getprop", "sys.boot_completed", timeout=5)
                    boot_completed = boot.returncode == 0 and boot.stdout.strip() == "1"
            except (OSError, subprocess.TimeoutExpired):
                pass

        gateway_ready = self._gateway_alive()
        return {
            "docker_available": docker_available,
            "docker_error": docker_error,
            "kvm_available": Path("/dev/kvm").exists(),
            "image": self.image,
            "base_image": self.base_image,
            "build_context": str(self.build_context),
            "build_context_available": self.build_context.is_dir(),
            "container_name": self.container_name,
            "container_id": container_id,
            "container_state": container_state,
            "adb_serial": self.adb_serial,
            "adb_ready": adb_ready,
            "boot_completed": boot_completed,
            "gateway_ready": gateway_ready,
            "gateway_uri": f"localhost:{self.gateway_port}",
            "gateway_log": str(self.gateway_log),
            "emulator_log": str(self.emulator_log),
            "live_ready": container_state == "running"
            and adb_ready
            and boot_completed
            and gateway_ready,
        }
