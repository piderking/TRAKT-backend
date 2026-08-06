import pytest
from fastapi.testclient import TestClient
from plugins.health.app.main import app

client = TestClient(app)

def test_health_plugin_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["plugin"] == "health-biometrics-microservice"

def test_health_telemetry_summary():
    response = client.get("/telemetry/summary")
    assert response.status_code == 200
    data = response.json()
    assert "biometrics" in data
    assert "heart_rate" in data["biometrics"]
    assert "activity" in data["biometrics"]
    assert data["biometrics"]["heart_rate"]["current_bpm"] >= 0

def test_health_sync_payload():
    payload = {
        "user_id": "usr_test_android",
        "device_name": "Pixel 8 Pro Test",
        "heart_rate_bpm": 82,
        "resting_hr_bpm": 60,
        "step_count_today": 9200,
        "calories_burned_active": 510,
        "sleep_duration_hours": 8.0,
        "spo2_percentage": 98.5,
        "distance_meters": 7100.0
    }
    response = client.post("/telemetry/sync", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
