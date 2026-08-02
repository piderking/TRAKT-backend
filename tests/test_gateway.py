import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "trakt-gateway"

def test_system_status_endpoint():
    response = client.get("/api/v1/system/status")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "storage_engine" in data

def test_device_code_request():
    response = client.post("/api/v1/auth/device/code")
    assert response.status_code == 200
    data = response.json()
    assert "user_code" in data
    assert "device_code" in data
    assert "verification_url" in data

def test_up_next_proxy():
    response = client.get("/api/v1/user/up-next?user_id=test_user_1")
    assert response.status_code == 200
    data = response.json()
    assert "source" in data
    items = data.get("items") or data.get("up_next")
    assert items is not None
    assert len(items) > 0

