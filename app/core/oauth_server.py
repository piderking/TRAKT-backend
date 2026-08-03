import time
import secrets
import hashlib
import jwt
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

SECRET_KEY = secrets.token_hex(32)
ALGORITHM = "HS256"

class OAuthClient(BaseModel):
    client_id: str
    client_secret: str
    client_name: str
    redirect_uris: List[str]
    scopes: List[str] = ["read", "write", "scrobble"]
    created_at: float = Field(default_factory=time.time)

class OAuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: str
    scope: str

class OAuthServerEngine:
    """
    Built-in OAuth 2.0 Authorization Server for Trakt Core Gateway.
    Handles client app registration, authorization codes, and JWT access token issuance.
    """

    def __init__(self):
        self.clients: Dict[str, OAuthClient] = {
            "android_daemon_default": OAuthClient(
                client_id="android_daemon_default",
                client_secret=secrets.token_hex(16),
                client_name="Trakt Android Daemon",
                redirect_uris=["https://trakt.tv/activate", "trakt://oauth/callback"],
                scopes=["read", "write", "scrobble", "health"]
            )
        }
        self.auth_codes: Dict[str, Dict[str, Any]] = {}
        self.plugin_configs: Dict[str, Dict[str, str]] = {
            "wakatime": {
                "wakatime_api_key": "waka_sec_demo_key_99812",
                "sync_interval_mins": "15"
            },
            "movies": {
                "trakt_client_id": "demo_trakt_id",
                "trakt_client_secret": "demo_trakt_secret"
            },
            "health": {
                "health_connect_sync_token": "hc_token_demo_3341"
            }
        }

    def register_client(self, client_name: str, redirect_uris: List[str], scopes: List[str]) -> OAuthClient:
        """Register a new OAuth 2.0 client application."""
        client_id = f"client_{secrets.token_hex(8)}"
        client_secret = f"secret_{secrets.token_hex(16)}"
        
        client = OAuthClient(
            client_id=client_id,
            client_secret=client_secret,
            client_name=client_name,
            redirect_uris=redirect_uris,
            scopes=scopes
        )
        self.clients[client_id] = client
        return client

    def create_authorization_code(self, client_id: str, redirect_uri: str, scope: str, user_id: str = "default_user") -> str:
        """Generate an Authorization Code valid for 10 minutes."""
        if client_id not in self.clients:
            raise ValueError("Invalid client_id")

        code = f"auth_code_{secrets.token_hex(16)}"
        self.auth_codes[code] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "user_id": user_id,
            "expires_at": time.time() + 600
        }
        return code

    def exchange_code_for_tokens(self, code: str, client_id: str, client_secret: str) -> OAuthTokenResponse:
        """Exchange Authorization Code for JWT Access Token and Refresh Token."""
        client = self.clients.get(client_id)
        if not client or client.client_secret != client_secret:
            raise ValueError("Invalid client credentials")

        code_data = self.auth_codes.get(code)
        if not code_data:
            raise ValueError("Invalid authorization code")

        if time.time() > code_data["expires_at"]:
            del self.auth_codes[code]
            raise ValueError("Authorization code expired")

        del self.auth_codes[code]

        user_id = code_data["user_id"]
        scope = code_data["scope"]

        # Issue JWT Access Token
        payload = {
            "sub": user_id,
            "client_id": client_id,
            "scope": scope,
            "iat": time.time(),
            "exp": time.time() + 3600
        }
        access_token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
        refresh_token = f"ref_{secrets.token_hex(24)}"

        return OAuthTokenResponse(
            access_token=access_token,
            token_type="Bearer",
            expires_in=3600,
            refresh_token=refresh_token,
            scope=scope
        )

    def verify_jwt_token(self, token: str) -> Dict[str, Any]:
        """Verify and decode a JWT Access Token."""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except Exception as e:
            raise ValueError(f"Invalid token: {str(e)}")

    def set_plugin_config(self, plugin_id: str, config: Dict[str, str]) -> Dict[str, str]:
        """Save API keys or credentials for a specific plugin."""
        if plugin_id not in self.plugin_configs:
            self.plugin_configs[plugin_id] = {}
        self.plugin_configs[plugin_id].update(config)
        return self.plugin_configs[plugin_id]

    def get_plugin_config(self, plugin_id: str) -> Dict[str, str]:
        """Get API keys or credentials for a specific plugin."""
        return self.plugin_configs.get(plugin_id, {})

oauth_server = OAuthServerEngine()
