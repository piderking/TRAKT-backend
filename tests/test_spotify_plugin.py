import pytest
from fastapi.testclient import TestClient
from plugins.spotify.app.main import app

client = TestClient(app)

def test_spotify_plugin_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["plugin"] == "spotify-scrobbler-microservice"

def test_spotify_now_playing():
    response = client.get("/telemetry/now-playing")
    assert response.status_code == 200
    data = response.json()
    assert "track_name" in data
    assert data["is_playing"] is True

def test_spotify_telemetry_summary():
    response = client.get("/telemetry/summary")
    assert response.status_code == 200
    data = response.json()
    assert "now_playing" in data
    assert "stats" in data
    assert "history" in data
    assert data["stats"]["tracks_played_today"] >= 0

def test_spotify_scrobble_track():
    payload = {
        "track_name": "Levitating",
        "artist_name": "Dua Lipa",
        "album_name": "Future Nostalgia",
        "duration_ms": 203000,
        "progress_ms": 120000,
        "is_playing": True
    }
    response = client.post("/telemetry/scrobble", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["now_playing"]["track_name"] == "Levitating"
