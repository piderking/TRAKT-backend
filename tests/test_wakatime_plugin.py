import pytest
from fastapi.testclient import TestClient
from plugins.wakatime.app.main import app

client = TestClient(app)

def test_wakatime_plugin_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "wakatime" in data["plugin"]

def test_telemetry_summary():
    response = client.get("/telemetry/summary")
    assert response.status_code == 200
    data = response.json()
    assert "token_metrics" in data
    assert "wakatime_metrics" in data
    assert data["token_metrics"]["total_tokens"] >= 0

def test_post_token_usage():
    payload = {
        "session_id": "test-session-1234",
        "model_name": "gemini-3.6-pro",
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "project_name": "TRAKT-test",
        "language": "Python"
    }
    response = client.post("/telemetry/heartbeat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
