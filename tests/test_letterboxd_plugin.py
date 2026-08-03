import io
import zipfile
import pytest
from fastapi.testclient import TestClient
from plugins.letterboxd.app.main import app

client = TestClient(app)

def test_letterboxd_plugin_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["plugin"] == "letterboxd-zip-importer"

def test_letterboxd_import_summary():
    response = client.get("/import/summary")
    assert response.status_code == 200
    data = response.json()
    assert "stats" in data
    assert data["stats"]["movies_watched"] >= 0

def test_letterboxd_zip_upload():
    # Build in-memory zip containing watched.csv and ratings.csv
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("watched.csv", "Date,Name,Year,Letterboxd URI\n2026-01-10,Dune: Part Two,2024,https://boxd.it/test1\n")
        zf.writestr("ratings.csv", "Date,Name,Year,Letterboxd URI,Rating\n2026-01-10,Dune: Part Two,2024,https://boxd.it/test1,4.5\n")

    zip_buffer.seek(0)
    files = {"file": ("letterboxd-export-test.zip", zip_buffer.getvalue(), "application/zip")}

    response = client.post("/import/upload", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["imported_counts"]["watched"] == 1
    assert data["imported_counts"]["ratings"] == 1
