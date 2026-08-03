import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_get_movie_diary():
    response = client.get("/api/v1/movies/diary")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "stats" in data
    assert "diary" in data
    assert len(data["diary"]) >= 2

def test_create_movie_log():
    payload = {
        "movie_title": "Interstellar",
        "release_year": 2014,
        "watched_date": "2026-08-03",
        "rating": 10.0,
        "is_rewatch": True,
        "liked": True,
        "review": "Mind-bending masterpiece of time, gravity, and love.",
        "tags": ["sci-fi", "favorite", "nolan"]
    }
    response = client.post("/api/v1/movies/log", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["entry"]["movie_title"] == "Interstellar"
    assert data["entry"]["rating"] == 10.0
    assert data["entry"]["is_rewatch"] is True

def test_delete_movie_log():
    # First create
    res = client.post("/api/v1/movies/log", json={
        "movie_title": "Temp Movie",
        "watched_date": "2026-08-03",
        "rating": 7.0
    })
    log_id = res.json()["entry"]["id"]

    # Delete
    del_res = client.delete(f"/api/v1/movies/log/{log_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"
