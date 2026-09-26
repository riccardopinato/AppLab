from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["ok"] is True
    assert payload["service"] == "applab-controller"
    assert payload["version"] == "0.9.0"
    assert "diagnostics" in payload["features"]
    assert "webrtc-live-runtime" in payload["features"]
    assert "emulator-lifecycle" in payload["features"]
    assert "browser-webrtc-e2e" in payload["features"]
    assert "ui-hierarchy" in payload["features"]
    assert "smart-visual-qa" in payload["features"]
    assert "visual-regression" in payload["features"]
    assert "multi-screen-journey" in payload["features"]

    assert "control-center" in payload["features"]
    assert "performance-lab" in payload["features"]
    assert "network-offline-lab" in payload["features"]
    assert "persistence-restart-lab" in payload["features"]
    assert "upgrade-migration-lab" in payload["features"]
    assert "configuration-lifecycle-stress-lab" in payload["features"]
    assert "resource-pressure-process-death-lab" in payload["features"]
    assert "background-doze-recovery-lab" in payload["features"]
    assert "storage-data-integrity-lab" in payload["features"]
    assert "fast-analysis-smart-orchestration" in payload["features"]
    assert "production-certification-gate" in payload["features"]
    assert "certification-integrity-hardening" in payload["features"]

    assert "adaptive-impact-analysis" in payload["features"]
    assert "risk-confidence-engine" in payload["features"]
    assert "incremental-verification-lanes" in payload["features"]
    assert "shadow-full-calibration" in payload["features"]
    assert "domain-scoped-cache" in payload["features"]
    assert "verification-telemetry" in payload["features"]
