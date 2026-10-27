from __future__ import annotations

import json
import os

from aiohttp import web
from videobridge_gateway import gateway_server


_original_handle_status = gateway_server.handle_status


def _display_config() -> dict[str, str]:
    width = os.getenv("APPLAB_EMULATOR_DISPLAY_WIDTH", "").strip()
    height = os.getenv("APPLAB_EMULATOR_DISPLAY_HEIGHT", "").strip()
    if not width.isdigit() or not height.isdigit():
        return {}
    if int(width) <= 0 or int(height) <= 0:
        return {}
    return {
        "hw.lcd.width": width,
        "hw.lcd.height": height,
    }


async def handle_status(request):
    response = await _original_handle_status(request)
    if response.status != 200:
        return response

    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        return response
    if not isinstance(payload, dict):
        return response

    fallback = _display_config()
    if not fallback:
        return response

    hardware = payload.get("hardwareConfig")
    platform = payload.get("platformConfig")
    hardware = dict(hardware) if isinstance(hardware, dict) else {}
    platform = dict(platform) if isinstance(platform, dict) else {}

    for key, value in fallback.items():
        hardware.setdefault(key, value)
        platform.setdefault(key, value)

    payload["hardwareConfig"] = hardware
    payload["platformConfig"] = platform
    return web.json_response(payload)


def main() -> None:
    gateway_server.handle_status = handle_status
    gateway_server.run_main()


if __name__ == "__main__":
    main()
