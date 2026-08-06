import os
import time
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("trakt.plugin.steam")

app = FastAPI(
    title="Trakt Plugin - Steam Web API Microservice",
    description="Microservice tracking live Steam currently playing game status, total library hours, achievements, and gaming telemetry.",
    version="1.0.0"
)

# Mount static directory
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

class GameScrobblePayload(BaseModel):
    game_title: str = Field(..., description="Name of the game")
    app_id: int = Field(..., description="Steam App ID")
    playtime_mins: int = Field(45, description="Playtime in current session")
    total_playtime_hours: float = Field(124.5, description="Total lifetime hours")
    is_playing: bool = Field(True, description="Whether currently playing")
    header_image: Optional[str] = Field(None, description="Game header banner URL")

steam_store: Dict[str, Any] = {
    "now_playing": {
        "game_title": "None",
        "app_id": 0,
        "is_playing": False,
        "session_playtime_mins": 0,
        "total_playtime_hours": 0.0,
        "header_image": "",
        "achievements_unlocked_today": 0
    },
    "stats": {
        "games_owned": 0,
        "total_hours_played": 0.0,
        "recent_2weeks_hours": 0.0,
        "total_achievements": 0,
        "top_games": []
    },
    "recent_games": []
}

@app.get("/health")
async def health_check():
    """Health check for Steam plugin."""
    return {
        "status": "ok",
        "plugin": "steam-web-api-microservice",
        "version": "1.0.0",
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
async def get_now_playing_game():
    """Get live currently playing game on Steam."""
    return steam_store["now_playing"]

@app.get("/telemetry/summary")
async def get_steam_summary():
    """Get aggregated Steam gaming telemetry."""
    return {
        "plugin": "steam-web-api-v1",
        "timestamp": time.time(),
        "now_playing": steam_store["now_playing"],
        "stats": steam_store["stats"],
        "recent_games": steam_store["recent_games"]
    }

@app.post("/telemetry/scrobble")
async def scrobble_game_session(payload: GameScrobblePayload):
    """Receive live game session telemetry from Steam API sync or desktop daemon."""
    now_item = {
        "game_title": payload.game_title,
        "app_id": payload.app_id,
        "is_playing": payload.is_playing,
        "session_playtime_mins": payload.playtime_mins,
        "total_playtime_hours": payload.total_playtime_hours,
        "header_image": payload.header_image or "https://images.unsplash.com/photo-1542751371-adc38448a05e?w=600&q=80",
        "achievements_unlocked_today": 1
    }
    steam_store["now_playing"] = now_item
    steam_store["stats"]["total_hours_played"] += payload.playtime_mins / 60.0
    steam_store["stats"]["recent_2weeks_hours"] += payload.playtime_mins / 60.0

    return {
        "status": "success",
        "message": f"Scrobbled session for '{payload.game_title}' ({payload.playtime_mins} mins)",
        "now_playing": now_item
    }
