import pytest
from fastapi.testclient import TestClient
from plugins.steam.app.main import app

client = TestClient(app)

def test_steam_plugin_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["plugin"] == "steam-web-api-microservice"

def test_steam_now_playing():
    response = client.get("/telemetry/now-playing")
    assert response.status_code == 200
    data = response.json()
    assert "game_title" in data
    assert data["is_playing"] is True

def test_steam_telemetry_summary():
    response = client.get("/telemetry/summary")
    assert response.status_code == 200
    data = response.json()
    assert "now_playing" in data
    assert "stats" in data
    assert "recent_games" in data
    assert data["stats"]["games_owned"] >= 0

def test_steam_scrobble_session():
    payload = {
        "game_title": "Elden Ring",
        "app_id": 1245620,
        "playtime_mins": 60,
        "total_playtime_hours": 211.4,
        "is_playing": True
    }
    response = client.post("/telemetry/scrobble", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["now_playing"]["game_title"] == "Elden Ring"
