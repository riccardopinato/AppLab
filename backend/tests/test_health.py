from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["ok"] is True
    assert payload["service"] == "applab-controller"
    assert payload["version"] == "0.3.0"
    assert "diagnostics" in payload["features"]
    assert "webrtc-live-runtime" in payload["features"]
    assert "emulator-lifecycle" in payload["features"]
