import os
import time
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("trakt.plugin.spotify")

app = FastAPI(
    title="Trakt Plugin - Spotify API Scrobbler Microservice",
    description="Microservice tracking live Spotify currently playing tracks, listening history, top artists, and audio feature telemetry.",
    version="1.0.0"
)

# Mount static directory
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

class ScrobblePayload(BaseModel):
    track_name: str = Field(..., description="Track title")
    artist_name: str = Field(..., description="Artist name")
    album_name: str = Field("Single", description="Album name")
    duration_ms: int = Field(210000, description="Duration in milliseconds")
    progress_ms: int = Field(145000, description="Current progress")
    is_playing: bool = Field(True, description="Playback status")
    album_art_url: Optional[str] = Field(None, description="Album artwork URL")
    spotify_uri: Optional[str] = Field(None, description="Spotify URI")
    timestamp: float = Field(default_factory=time.time)

spotify_store: Dict[str, Any] = {
    "now_playing": {
        "track_name": "Starboy",
        "artist_name": "The Weeknd ft. Daft Punk",
        "album_name": "Starboy",
        "duration_ms": 230400,
        "progress_ms": 142000,
        "is_playing": True,
        "album_art_url": "https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?w=500&q=80",
        "spotify_uri": "spotify:track:7qiZ28P1WUZyWq23A8q1D3",
        "audio_features": {
            "bpm": 186,
            "energy": 0.82,
            "danceability": 0.68,
            "valence": 0.54
        }
    },
    "stats": {
        "tracks_played_today": 34,
        "total_listening_minutes": 118,
        "top_artists": [
          {"name": "The Weeknd", "play_count": 14},
          {"name": "Daft Punk", "play_count": 8},
          {"name": "Kendrick Lamar", "play_count": 6},
          {"name": "Frank Ocean", "play_count": 4}
        ],
        "top_genres": ["Alternative R&B", "Synthwave", "Hip-Hop", "Indie Electronic"]
    },
    "history": [
        {
            "track_name": "Blinding Lights",
            "artist_name": "The Weeknd",
            "album_name": "After Hours",
            "played_at": "11:05 AM",
            "duration_formatted": "3:20"
        },
        {
            "track_name": "Get Lucky",
            "artist_name": "Daft Punk ft. Pharrell Williams",
            "album_name": "Random Access Memories",
            "played_at": "10:42 AM",
            "duration_formatted": "4:08"
        },
        {
            "track_name": "N95",
            "artist_name": "Kendrick Lamar",
            "album_name": "Mr. Morale & the Big Steppers",
            "played_at": "10:15 AM",
            "duration_formatted": "3:15"
        }
    ]
}

@app.get("/health")
async def health_check():
    """Health check for Spotify plugin."""
    return {
        "status": "ok",
        "plugin": "spotify-scrobbler-microservice",
        "version": "1.0.0",
        "timestamp": time.time()
    }

@app.get("/ui")
async def get_plugin_ui():
    """Serve Spotify scrobbler web UI."""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"error": "UI index.html not found"}

@app.get("/telemetry/now-playing")
async def get_now_playing():
    """Get live currently playing track details."""
    return spotify_store["now_playing"]

@app.get("/telemetry/summary")
async def get_spotify_summary():
    """Get aggregated Spotify listening stats, now playing, and history."""
    return {
        "plugin": "spotify-scrobbler-v1",
        "timestamp": time.time(),
        "now_playing": spotify_store["now_playing"],
        "stats": spotify_store["stats"],
        "history": spotify_store["history"]
    }

@app.post("/telemetry/scrobble")
async def scrobble_track(payload: ScrobblePayload):
    """Receive live track scrobble from Spotify API webhook or mobile daemon."""
    now_item = {
        "track_name": payload.track_name,
        "artist_name": payload.artist_name,
        "album_name": payload.album_name,
        "duration_ms": payload.duration_ms,
        "progress_ms": payload.progress_ms,
        "is_playing": payload.is_playing,
        "album_art_url": payload.album_art_url or "https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?w=500&q=80",
        "spotify_uri": payload.spotify_uri or "spotify:track:demo",
        "audio_features": {
            "bpm": 128,
            "energy": 0.75,
            "danceability": 0.70,
            "valence": 0.60
        }
    }
    spotify_store["now_playing"] = now_item

    # Record in history
    mins = payload.duration_ms // 60000
    secs = (payload.duration_ms % 60000) // 1000
    history_entry = {
        "track_name": payload.track_name,
        "artist_name": payload.artist_name,
        "album_name": payload.album_name,
        "played_at": time.strftime("%I:%M %p"),
        "duration_formatted": f"{mins}:{secs:02d}"
    }
    spotify_store["history"].insert(0, history_entry)
    if len(spotify_store["history"]) > 20:
        spotify_store["history"].pop()

    spotify_store["stats"]["tracks_played_today"] += 1
    spotify_store["stats"]["total_listening_minutes"] += max(1, mins)

    return {
        "status": "success",
        "message": f"Scrobbled '{payload.track_name}' by '{payload.artist_name}'",
        "now_playing": now_item
    }
