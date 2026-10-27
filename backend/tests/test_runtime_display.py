from __future__ import annotations

import subprocess

from app.runtime import LiveRuntimeManager


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["adb"], returncode, stdout=stdout, stderr="")


def test_display_size_uses_physical_size(monkeypatch) -> None:
    manager = LiveRuntimeManager()
    monkeypatch.setattr(
        manager,
        "_adb",
        lambda *args, **kwargs: _completed("Physical size: 1080x1920\n"),
    )
    assert manager._display_size() == (1080, 1920)


def test_display_size_prefers_override(monkeypatch) -> None:
    manager = LiveRuntimeManager()
    monkeypatch.setattr(
        manager,
        "_adb",
        lambda *args, **kwargs: _completed(
            "Physical size: 1080x1920\nOverride size: 720x1280\n"
        ),
    )
    assert manager._display_size() == (720, 1280)


def test_display_size_fails_closed_on_missing_or_invalid_output(monkeypatch) -> None:
    manager = LiveRuntimeManager()
    monkeypatch.setattr(
        manager,
        "_adb",
        lambda *args, **kwargs: _completed(""),
    )
    assert manager._display_size() is None

    monkeypatch.setattr(
        manager,
        "_adb",
        lambda *args, **kwargs: _completed("Physical size: 1080x1920\n", returncode=1),
    )
    assert manager._display_size() is None
