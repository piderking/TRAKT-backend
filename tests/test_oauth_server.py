import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_oauth_client_registration():
    payload = {
        "client_name": "Test Mobile App",
        "redirect_uris": ["https://myapp.com/callback"],
        "scopes": ["read", "write"]
    }
    response = client.post("/oauth/clients/register", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "client_id" in data
    assert "client_secret" in data
    assert data["client_name"] == "Test Mobile App"

def test_oauth_auth_code_and_token_exchange():
    # 1. Register client
    reg_res = client.post("/oauth/clients/register", json={
        "client_name": "Daemon App",
        "redirect_uris": ["https://daemon.com/callback"],
        "scopes": ["read", "scrobble"]
    })
    client_data = reg_res.json()
    c_id = client_data["client_id"]
    c_sec = client_data["client_secret"]

    # 2. Request Auth Code
    code_res = client.post(f"/oauth/authorize/code?client_id={c_id}&redirect_uri=https://daemon.com/callback&scope=read")
    assert code_res.status_code == 200
    code = code_res.json()["authorization_code"]

    # 3. Exchange code for JWT token
    token_res = client.post("/oauth/token", json={
        "grant_type": "authorization_code",
        "code": code,
        "client_id": c_id,
        "client_secret": c_sec
    })
    assert token_res.status_code == 200
    token_data = token_res.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "Bearer"

    # 4. Verify UserInfo with JWT
    access_token = token_data["access_token"]
    user_res = client.get(f"/oauth/userinfo?token={access_token}")
    assert user_res.status_code == 200
    assert user_res.json()["client_id"] == c_id

def test_plugin_config_save_and_get():
    # Save WakaTime API key
    save_res = client.post("/api/v1/plugins/config?plugin_id=wakatime", json={
        "wakatime_api_key": "waka_sec_test_key_12345",
        "sync_interval_mins": "10"
    })
    assert save_res.status_code == 200
    assert save_res.json()["status"] == "saved"

    # Get WakaTime config
    get_res = client.get("/api/v1/plugins/config?plugin_id=wakatime")
    assert get_res.status_code == 200
    config_data = get_res.json()["config"]
    assert config_data["wakatime_api_key"] == "waka_sec_test_key_12345"
