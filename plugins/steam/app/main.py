import os
import time
import logging
import httpx
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("trakt.plugin.steam")

app = FastAPI(
    title="Trakt Plugin - Steam Web API Microservice",
    description="Live Steam Web API integration fetching real player summaries, owned games, recent 2-week playtime, and in-game telemetry.",
    version="1.0.0"
)

# Mount static directory
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

STEAM_API_KEY = os.getenv("STEAM_API_KEY", "8F28EB726EC9374B02C8BB7753FA30A5")
STEAM_ID_64 = os.getenv("STEAM_ID_64", "76561199053737486")

class GameScrobblePayload(BaseModel):
    game_title: str = Field(..., description="Name of the game")
    app_id: int = Field(..., description="Steam App ID")
    playtime_mins: int = Field(45, description="Playtime in current session")
    total_playtime_hours: float = Field(124.5, description="Total lifetime hours")
    is_playing: bool = Field(True, description="Whether currently playing")
    header_image: Optional[str] = Field(None, description="Game header banner URL")

# In-memory session override cache
scrobble_override: Dict[str, Any] = {}

@app.get("/health")
async def health_check():
    """Health check for Steam plugin."""
    return {
        "status": "ok",
        "plugin": "steam-web-api-microservice",
        "version": "1.0.0",
        "steam_id_configured": bool(STEAM_ID_64),
        "timestamp": time.time()
    }

@app.get("/ui")
async def get_plugin_ui():
    """Serve Steam Gaming web UI."""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"error": "UI index.html not found"}

@app.get("/telemetry/now-playing")
async def get_now_playing_game(api_key: Optional[str] = None, steam_id: Optional[str] = None):
    """Get live currently playing game on Steam from Steam Web API."""
    key = api_key or STEAM_API_KEY
    sid = steam_id or STEAM_ID_64

    if scrobble_override and scrobble_override.get("is_playing"):
        return scrobble_override

    if key and sid:
        try:
            url = f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={key}&steamids={sid}"
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    players = resp.json().get("response", {}).get("players", [])
                    if players:
                        p = players[0]
                        game_title = p.get("gameextrainfo")
                        game_id = p.get("gameid")
                        is_playing = bool(game_title)
                        return {
                            "player_name": p.get("personaname", "muncher"),
                            "avatar_url": p.get("avatarfull", ""),
                            "profile_url": p.get("profileurl", ""),
                            "game_title": game_title or "Offline / Not in-game",
                            "app_id": int(game_id) if game_id and str(game_id).isdigit() else 0,
                            "is_playing": is_playing,
                            "header_image": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{game_id}/header.jpg" if game_id else ""
                        }
        except Exception as e:
            logger.warning(f"Failed to fetch live Steam player summary: {e}")

    return {
        "player_name": "muncher",
        "game_title": "Offline / Not in-game",
        "app_id": 0,
        "is_playing": False,
        "header_image": ""
    }

@app.get("/telemetry/summary")
async def get_steam_summary(api_key: Optional[str] = None, steam_id: Optional[str] = None):
    """Get real-time aggregated Steam gaming telemetry directly from Steam Web API."""
    key = api_key or STEAM_API_KEY
    sid = steam_id or STEAM_ID_64

    now_playing = await get_now_playing_game(key, sid)
    games_owned_cnt = 0
    total_hours_played = 0.0
    recent_2weeks_hours = 0.0
    top_games: List[Dict[str, Any]] = []
    recent_games: List[Dict[str, Any]] = []

    if key and sid:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # 1. Fetch Owned Games
            try:
                owned_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={key}&steamid={sid}&format=json&include_appinfo=1&include_played_free_games=1"
                resp = await client.get(owned_url)
                if resp.status_code == 200:
                    owned_data = resp.json().get("response", {})
                    games_owned_cnt = owned_data.get("game_count", 0)
                    all_games = owned_data.get("games", [])

                    # Calculate total lifetime hours
                    total_mins = sum(g.get("playtime_forever", 0) for g in all_games)
                    total_hours_played = round(total_mins / 60.0, 1)

                    # Sort top games by playtime_forever
                    sorted_games = sorted(all_games, key=lambda g: g.get("playtime_forever", 0), reverse=True)
                    for g in sorted_games[:6]:
                        hrs = round(g.get("playtime_forever", 0) / 60.0, 1)
                        if hrs > 0:
                            top_games.append({
                                "game_title": g.get("name"),
                                "app_id": g.get("appid"),
                                "hours": hrs,
                                "header_image": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{g.get('appid')}/header.jpg"
                            })
            except Exception as e:
                logger.warning(f"Failed to fetch Steam owned games: {e}")

            # 2. Fetch Recently Played Games (2-week telemetry)
            try:
                recent_url = f"https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/?key={key}&steamid={sid}"
                resp_rec = await client.get(recent_url)
                if resp_rec.status_code == 200:
                    rec_games_raw = resp_rec.json().get("response", {}).get("games", [])
                    rec_2w_mins = sum(rg.get("playtime_2weeks", 0) for rg in rec_games_raw)
                    recent_2weeks_hours = round(rec_2w_mins / 60.0, 1)

                    for rg in rec_games_raw:
                        h_2w = round(rg.get("playtime_2weeks", 0) / 60.0, 1)
                        h_tot = round(rg.get("playtime_forever", 0) / 60.0, 1)
                        recent_games.append({
                            "game_title": rg.get("name"),
                            "app_id": rg.get("appid"),
                            "playtime_2weeks_hours": h_2w,
                            "total_hours": h_tot,
                            "header_image": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{rg.get('appid')}/header.jpg",
                            "last_played": "Recent (Past 2 Weeks)"
                        })
            except Exception as e:
                logger.warning(f"Failed to fetch Steam recently played games: {e}")

    return {
        "plugin": "steam-web-api-v1",
        "steam_id": sid,
        "timestamp": time.time(),
        "now_playing": now_playing,
        "stats": {
            "games_owned": games_owned_cnt,
            "total_hours_played": total_hours_played,
            "recent_2weeks_hours": recent_2weeks_hours,
            "top_games": top_games
        },
        "recent_games": recent_games
    }

@app.post("/telemetry/scrobble")
async def scrobble_game_session(payload: GameScrobblePayload):
    """Receive live game session telemetry from Steam API sync or desktop daemon."""
    global scrobble_override
    now_item = {
        "game_title": payload.game_title,
        "app_id": payload.app_id,
        "is_playing": payload.is_playing,
        "session_playtime_mins": payload.playtime_mins,
        "total_playtime_hours": payload.total_playtime_hours,
        "header_image": payload.header_image or f"https://cdn.cloudflare.steamstatic.com/steam/apps/{payload.app_id}/header.jpg"
    }
    scrobble_override = now_item

    return {
        "status": "success",
        "message": f"Scrobbled session for '{payload.game_title}' ({payload.playtime_mins} mins)",
        "now_playing": now_item
    }

@app.post("/telemetry/flush")
async def flush_telemetry():
    """Flush session overrides."""
    global scrobble_override
    scrobble_override = {}
    return {"status": "flushed"}
