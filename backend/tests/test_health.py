from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["ok"] is True
    assert payload["service"] == "applab-controller"
    assert payload["version"] == "0.6.3"
    assert "diagnostics" in payload["features"]
    assert "webrtc-live-runtime" in payload["features"]
    assert "emulator-lifecycle" in payload["features"]
    assert "browser-webrtc-e2e" in payload["features"]
    assert "ui-hierarchy" in payload["features"]
    assert "smart-visual-qa" in payload["features"]
    assert "visual-regression" in payload["features"]
    assert "multi-screen-journey" in payload["features"]
