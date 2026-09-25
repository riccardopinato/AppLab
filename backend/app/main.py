from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, TypeVar

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, field_validator

from .adb import AdbController, AdbError, validate_package_id
from .control_center import load_snapshot
from .diagnostics import analyze_logcat
from .journal import SessionJournal
from .maestro import MaestroError, MaestroRunner
from .runtime import LiveRuntimeError, LiveRuntimeManager


APP_VERSION = "0.7.10"
MAX_APK_BYTES = int(os.getenv("APPLAB_MAX_APK_BYTES", str(512 * 1024 * 1024)))
CORS_ORIGINS = [
    item.strip()
    for item in os.getenv(
        "APPLAB_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if item.strip()
]

app = FastAPI(title="AppLab Controller", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

journal = SessionJournal()
maestro = MaestroRunner()
live_runtime = LiveRuntimeManager()
T = TypeVar("T")


class PackageRequest(BaseModel):
    package_id: str

    @field_validator("package_id")
    @classmethod
    def package_is_valid(cls, value: str) -> str:
        try:
            return validate_package_id(value)
        except AdbError as exc:
            raise ValueError(str(exc)) from exc


class TestRequest(PackageRequest):
    flow: str = "generic-smoke"


class KeyRequest(BaseModel):
    key: str


KEYS = {
    "home": "KEYCODE_HOME",
    "back": "KEYCODE_BACK",
    "power": "KEYCODE_POWER",
    "recent": "KEYCODE_APP_SWITCH",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN",
}


def controller() -> AdbController:
    ctl = AdbController()
    try:
        ctl.connect_if_remote()
    except AdbError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ctl


def adb_guard(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except AdbError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def record_action(
    action: str,
    status: str,
    package_id: str | None = None,
    **details: object,
) -> None:
    journal.append(
        action,
        status,
        package_id=package_id,
        details={key: value for key, value in details.items() if value is not None},
    )


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "applab-controller",
        "version": APP_VERSION,
        "features": [
            "adb-control",
            "diagnostics",
            "maestro",
            "session-history",
            "webrtc-live-runtime",
            "emulator-lifecycle",
            "browser-webrtc-e2e",
            "ui-hierarchy",
            "smart-visual-qa",
            "visual-regression",
            "multi-screen-journey",
            "repo-watcher",
            "control-center",
            "performance-lab",
            "network-offline-lab",
            "persistence-restart-lab",
            "upgrade-migration-lab",
            "configuration-lifecycle-stress-lab",
            "resource-pressure-process-death-lab",
            "background-doze-recovery-lab",
            "storage-data-integrity-lab",
            "fast-analysis-smart-orchestration",
        ],
    }


@app.get("/api/runtime")
def runtime_status() -> dict:
    return live_runtime.status()


@app.post("/api/runtime/start")
def runtime_start() -> dict:
    try:
        result = live_runtime.start()
    except LiveRuntimeError as exc:
        record_action("runtime-start", "FAIL", error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    record_action("runtime-start", "PASS", image=result["image"])
    return result


@app.post("/api/runtime/stop")
def runtime_stop() -> dict:
    try:
        result = live_runtime.stop()
    except LiveRuntimeError as exc:
        record_action("runtime-stop", "FAIL", error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    record_action("runtime-stop", "PASS")
    return result


@app.post("/api/runtime/restart")
def runtime_restart() -> dict:
    try:
        result = live_runtime.restart()
    except LiveRuntimeError as exc:
        record_action("runtime-restart", "FAIL", error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    record_action("runtime-restart", "PASS", image=result["image"])
    return result


@app.get("/api/devices")
def devices() -> dict:
    ctl = controller()
    return {"devices": adb_guard(ctl.devices)}


@app.get("/api/device")
def device() -> dict:
    ctl = controller()
    return adb_guard(ctl.device_info)


@app.get("/api/apps")
def apps() -> dict:
    ctl = controller()
    return {"packages": adb_guard(ctl.installed_packages)}


@app.get("/api/app/status")
def app_status(package_id: str = Query(...)) -> dict:
    ctl = controller()
    return adb_guard(lambda: ctl.app_status(package_id))


@app.post("/api/apk/install")
async def install_apk(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".apk"):
        raise HTTPException(status_code=400, detail="An .apk file is required.")

    ctl = controller()
    before = set(adb_guard(ctl.installed_packages))

    with tempfile.TemporaryDirectory(prefix="applab-") as tmp:
        path = Path(tmp) / "app.apk"
        total = 0
        with path.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_APK_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "APK exceeds AppLab upload limit "
                            f"({MAX_APK_BYTES // (1024 * 1024)} MiB)."
                        ),
                    )
                handle.write(chunk)

        if total == 0:
            raise HTTPException(status_code=400, detail="APK is empty.")

        package_id = ctl.detect_package_id(path)
        output = adb_guard(lambda: ctl.install(path))

    if not package_id:
        after = set(adb_guard(ctl.installed_packages))
        added = sorted(after - before)
        package_id = added[0] if len(added) == 1 else None

    record_action(
        "install",
        "PASS",
        package_id,
        filename=file.filename,
    )
    return {
        "ok": True,
        "output": output,
        "filename": file.filename,
        "package_id": package_id,
    }


@app.post("/api/app/launch")
def launch(request: PackageRequest) -> dict:
    ctl = controller()
    output = adb_guard(lambda: ctl.launch(request.package_id))
    record_action("launch", "PASS", request.package_id)
    return {"ok": True, "output": output}


@app.post("/api/app/stop")
def stop(request: PackageRequest) -> dict:
    ctl = controller()
    output = adb_guard(lambda: ctl.stop(request.package_id))
    record_action("stop", "PASS", request.package_id)
    return {"ok": True, "output": output}


@app.post("/api/app/restart")
def restart(request: PackageRequest) -> dict:
    ctl = controller()
    output = adb_guard(lambda: ctl.restart(request.package_id))
    record_action("restart", "PASS", request.package_id)
    return {"ok": True, "output": output}


@app.post("/api/app/clear")
def clear(request: PackageRequest) -> dict:
    ctl = controller()
    output = adb_guard(lambda: ctl.clear(request.package_id))
    record_action("clear-data", "PASS", request.package_id)
    return {"ok": True, "output": output}


@app.post("/api/app/uninstall")
def uninstall(request: PackageRequest) -> dict:
    ctl = controller()
    output = adb_guard(lambda: ctl.uninstall(request.package_id))
    record_action("uninstall", "PASS", request.package_id)
    return {"ok": True, "output": output}


@app.post("/api/device/key")
def key(request: KeyRequest) -> dict:
    normalized = request.key.strip().lower()
    if normalized not in KEYS:
        raise HTTPException(status_code=400, detail=f"Unsupported key: {request.key}")
    ctl = controller()
    return {"ok": True, "output": adb_guard(lambda: ctl.key(KEYS[normalized]))}


@app.get("/api/screenshot")
def screenshot() -> Response:
    ctl = controller()
    payload = adb_guard(ctl.screenshot)
    return Response(
        content=payload,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/ui/hierarchy")
def ui_hierarchy() -> dict:
    ctl = controller()
    return {"xml": adb_guard(ctl.ui_hierarchy)}


@app.get("/api/logcat")
def logcat(
    lines: int = Query(default=700, ge=1, le=5000),
    package_id: str | None = Query(default=None),
) -> dict:
    ctl = controller()
    return {
        "logcat": adb_guard(lambda: ctl.logcat(lines, package_id)),
        "package_id": package_id or "",
    }


@app.post("/api/logcat/clear")
def clear_logcat() -> dict:
    ctl = controller()
    adb_guard(ctl.clear_logcat)
    record_action("clear-logcat", "PASS")
    return {"ok": True}


@app.get("/api/report")
def report(package_id: str = Query(...)) -> dict:
    ctl = controller()
    status = adb_guard(lambda: ctl.app_status(package_id))
    logs = adb_guard(lambda: ctl.logcat(1500, package_id))
    diagnostic = analyze_logcat(
        logs,
        package_id=package_id,
        running=bool(status["running"]),
    )
    return {
        **diagnostic,
        "status": status,
        "device": adb_guard(ctl.device_info),
    }


@app.get("/api/tests")
def tests() -> dict:
    return {
        "available": maestro.available,
        "flows": maestro.flows(),
    }


@app.post("/api/tests/run")
def run_test(request: TestRequest) -> dict:
    ctl = controller()
    status = adb_guard(lambda: ctl.app_status(request.package_id))
    if not status["installed"]:
        raise HTTPException(status_code=404, detail="Package is not installed.")

    try:
        result = maestro.run(request.package_id, request.flow)
    except MaestroError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    record_action(
        "maestro-test",
        "PASS" if result["ok"] else "FAIL",
        request.package_id,
        flow=request.flow,
    )
    return result


@app.get("/api/history")
def history(limit: int = Query(default=30, ge=1, le=200)) -> dict:
    return {"entries": journal.recent(limit)}


@app.get("/api/control-center")
def control_center() -> dict:
    return load_snapshot()
