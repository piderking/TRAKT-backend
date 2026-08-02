import os
import time
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import httpx

logger = logging.getLogger("trakt.plugin.wakatime")

app = FastAPI(
    title="Trakt Plugin - WakaTime & Antigravity Token Telemetry Microservice",
    description="Microservice tracking WakaTime coding metrics and Antigravity CLI model token usage.",
    version="1.0.0"
)

# Static files mounting
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Models
class TokenUsagePayload(BaseModel):
    session_id: str = Field(..., description="Antigravity session ID")
    model: str = Field("gemini-3.6-flash", description="AI Model used")
    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
    total_tokens: int = Field(..., ge=0)
    project_name: Optional[str] = "TRAKT"
    language: Optional[str] = "Python"

class HeartbeatPayload(BaseModel):
    user_id: str
    entity: str = Field(..., description="File or symbol being edited")
    type: str = Field("file", description="file, app, domain")
    category: str = Field("coding", description="coding, building, debugging")
    project: str = "TRAKT"
    branch: Optional[str] = "main"
    language: Optional[str] = "Python"
    time: float = Field(default_factory=time.time)

# In-memory telemetry cache
telemetry_store: Dict[str, Any] = {
    "total_prompt_tokens": 142500,
    "total_completion_tokens": 48200,
    "total_tokens": 190700,
    "sessions_tracked": 12,
    "wakatime_today_seconds": 18420,  # 5h 7m
    "models": {
        "gemini-3.6-flash": {"prompt": 110000, "completion": 35000},
        "gemini-3.6-pro": {"prompt": 32500, "completion": 13200}
    },
    "recent_heartbeats": [
        {
            "timestamp": "2026-08-01T19:50:00Z",
            "project": "TRAKT-backend",
            "entity": "app/main.py",
            "language": "Python",
            "tokens": 1850
        },
        {
            "timestamp": "2026-08-01T19:45:00Z",
            "project": "TRAKT-frontend",
            "entity": "src/app/page.tsx",
            "language": "TypeScript",
            "tokens": 3400
        }
    ]
}

@app.get("/health")
async def health_check():
    """Health check endpoint for WakaTime & Antigravity plugin."""
    return {
        "status": "ok",
        "plugin": "wakatime-antigravity-telemetry",
        "version": "1.0.0",
        "timestamp": time.time()
    }

@app.get("/ui")
async def get_plugin_ui():
    """Serve plugin telemetry web dashboard."""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"error": "UI index.html not found"}

@app.get("/telemetry/summary")
async def get_telemetry_summary():
    """Return aggregated token and coding metrics."""
    return {
        "plugin": "wakatime-antigravity-v1",
        "timestamp": time.time(),
        "token_metrics": {
            "prompt_tokens": telemetry_store["total_prompt_tokens"],
            "completion_tokens": telemetry_store["total_completion_tokens"],
            "total_tokens": telemetry_store["total_tokens"],
            "models_breakdown": telemetry_store["models"],
            "sessions_count": telemetry_store["sessions_tracked"]
        },
        "wakatime_metrics": {
            "today_seconds": telemetry_store["wakatime_today_seconds"],
            "today_formatted": f"{telemetry_store['wakatime_today_seconds'] // 3600}h {(telemetry_store['wakatime_today_seconds'] % 3600) // 60}m",
            "active_project": "TRAKT",
            "top_languages": [
                {"name": "Python", "pct": 52.4},
                {"name": "TypeScript", "pct": 38.1},
                {"name": "Docker", "pct": 9.5}
            ]
        },
        "recent_activity": telemetry_store["recent_heartbeats"]
    }

@app.post("/telemetry/token")
async def track_token_usage(payload: TokenUsagePayload):
    """Track token consumption from Antigravity CLI session."""
    telemetry_store["total_prompt_tokens"] += payload.prompt_tokens
    telemetry_store["total_completion_tokens"] += payload.completion_tokens
    telemetry_store["total_tokens"] += payload.total_tokens
    telemetry_store["sessions_tracked"] += 1

    model_key = payload.model
    if model_key not in telemetry_store["models"]:
        telemetry_store["models"][model_key] = {"prompt": 0, "completion": 0}

    telemetry_store["models"][model_key]["prompt"] += payload.prompt_tokens
    telemetry_store["models"][model_key]["completion"] += payload.completion_tokens

    heartbeat_entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project": payload.project_name,
        "entity": f"Session:{payload.session_id[:8]}",
        "language": payload.language,
        "tokens": payload.total_tokens
    }
    telemetry_store["recent_heartbeats"].insert(0, heartbeat_entry)
    if len(telemetry_store["recent_heartbeats"]) > 20:
        telemetry_store["recent_heartbeats"].pop()

    return {"status": "recorded", "session_id": payload.session_id, "total_tokens": payload.total_tokens}

@app.get("/telemetry/wakatime/stats")
async def get_wakatime_live_stats(wakatime_api_key: Optional[str] = Query(None)):
    """
    Fetch live statistics from WakaTime API v1.
    Uses query param `wakatime_api_key` or `WAKATIME_API_KEY` env var if present.
    """
    api_key = wakatime_api_key or os.getenv("WAKATIME_API_KEY")
    if not api_key:
        return {
            "source": "cached_fallback",
            "message": "WAKATIME_API_KEY not configured; returning telemetry store data.",
            "data": {
                "human_readable_total": "5 hrs 7 mins",
                "daily_average": "4 hrs 12 mins",
                "languages": [
                    {"name": "Python", "percent": 52.4},
                    {"name": "TypeScript", "percent": 38.1},
                    {"name": "Docker", "percent": 9.5}
                ]
            }
        }

    url = "https://wakatime.com/api/v1/users/current/stats/last_7_days"
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, headers=headers, timeout=5.0)
            if res.status_code == 200:
                return {"source": "wakatime_api_v1", "data": res.json().get("data", {})}
            else:
                return {"source": "wakatime_api_error", "status_code": res.status_code, "detail": res.text}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"WakaTime API unreachable: {str(e)}")
