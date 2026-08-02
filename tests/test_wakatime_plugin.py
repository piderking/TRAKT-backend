import pytest
from fastapi.testclient import TestClient
from plugins.wakatime.app.main import app

client = TestClient(app)

def test_wakatime_plugin_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["plugin"] == "wakatime-antigravity-telemetry"

def test_telemetry_summary():
    response = client.get("/telemetry/summary")
    assert response.status_code == 200
    data = response.json()
    assert "token_metrics" in data
    assert "wakatime_metrics" in data
    assert data["token_metrics"]["total_tokens"] > 0

def test_post_token_usage():
    payload = {
        "session_id": "test-session-1234",
        "model": "gemini-3.6-pro",
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "total_tokens": 1500,
        "project_name": "TRAKT-test",
        "language": "Python"
    }
    response = client.post("/telemetry/token", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "recorded"
    assert data["total_tokens"] == 1500

def test_wakatime_stats_cached():
    response = client.get("/telemetry/wakatime/stats")
    assert response.status_code == 200
    data = response.json()
    assert "source" in data
    assert "data" in data
