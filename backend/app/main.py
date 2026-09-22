from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from .adb import AdbController, AdbError


app = FastAPI(title="AppLab Controller", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PackageRequest(BaseModel):
    package_id: str


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


def adb_guard(fn):
    try:
        return fn()
    except AdbError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "applab-controller", "version": "0.1.0"}


@app.get("/api/devices")
def devices() -> dict:
    ctl = controller()
    return {"devices": adb_guard(ctl.devices)}


@app.get("/api/device")
def device() -> dict:
    ctl = controller()
    return adb_guard(ctl.device_info)


@app.post("/api/apk/install")
async def install_apk(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".apk"):
        raise HTTPException(status_code=400, detail="An .apk file is required.")
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="APK is empty.")

    ctl = controller()
    with tempfile.TemporaryDirectory(prefix="applab-") as tmp:
        path = Path(tmp) / "app.apk"
        path.write_bytes(payload)
        output = adb_guard(lambda: ctl.install(path))
    return {"ok": True, "output": output}


@app.post("/api/app/launch")
def launch(request: PackageRequest) -> dict:
    ctl = controller()
    return {"ok": True, "output": adb_guard(lambda: ctl.launch(request.package_id))}


@app.post("/api/app/stop")
def stop(request: PackageRequest) -> dict:
    ctl = controller()
    return {"ok": True, "output": adb_guard(lambda: ctl.stop(request.package_id))}


@app.post("/api/app/clear")
def clear(request: PackageRequest) -> dict:
    ctl = controller()
    return {"ok": True, "output": adb_guard(lambda: ctl.clear(request.package_id))}


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
    return Response(content=payload, media_type="image/png")


@app.get("/api/logcat")
def logcat(lines: int = Query(default=400, ge=1, le=5000)) -> dict:
    ctl = controller()
    return {"logcat": adb_guard(lambda: ctl.logcat(lines))}


@app.post("/api/logcat/clear")
def clear_logcat() -> dict:
    ctl = controller()
    adb_guard(ctl.clear_logcat)
    return {"ok": True}
