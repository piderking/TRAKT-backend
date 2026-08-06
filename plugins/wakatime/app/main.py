import os
import time
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("trakt.plugin.wakatime")

app = FastAPI(
    title="Trakt Plugin - WakaTime & Token Telemetry Microservice",
    description="Microservice capturing developer productivity telemetry from WakaTime API and AI model token consumption.",
    version="1.0.0"
)

# Mount static directory
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

class TokenTelemetryPayload(BaseModel):
    session_id: str = Field(..., description="Unique AI coding session ID")
    model_name: str = Field(..., description="AI model name, e.g. gemini-3.6-pro")
    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
    project_name: Optional[str] = Field("default", description="Associated coding project")
    language: Optional[str] = Field("Python", description="Primary coding language")

telemetry_store: Dict[str, Any] = {
    "total_prompt_tokens": 0,
    "total_completion_tokens": 0,
    "total_tokens": 0,
    "sessions_tracked": 0,
    "wakatime_today_seconds": 0,
    "models": {},
    "recent_heartbeats": []
}

@app.get("/health")
async def health_check():
    """Health check for WakaTime plugin."""
    return {
        "status": "ok",
        "plugin": "wakatime-token-telemetry-microservice",
        "version": "1.0.0",
        "timestamp": time.time()
    }

@app.get("/ui")
async def get_plugin_ui():
    """Serve WakaTime telemetry web UI."""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"error": "UI index.html not found"}

@app.get("/telemetry/summary")
async def get_telemetry_summary():
    """Get aggregated token usage and WakaTime coding telemetry."""
    hrs = telemetry_store["wakatime_today_seconds"] // 3600
    mins = (telemetry_store["wakatime_today_seconds"] % 3600) // 60

    return {
        "plugin": "wakatime-token-telemetry-v1",
        "timestamp": time.time(),
        "token_metrics": {
            "prompt_tokens": telemetry_store["total_prompt_tokens"],
            "completion_tokens": telemetry_store["total_completion_tokens"],
            "total_tokens": telemetry_store["total_tokens"],
            "sessions_count": telemetry_store["sessions_tracked"],
            "models_breakdown": telemetry_store["models"]
        },
        "wakatime_metrics": {
            "today_seconds": telemetry_store["wakatime_today_seconds"],
            "today_formatted": f"{hrs}h {mins}m",
            "active_project": "TRAKT",
            "top_languages": [
                {"name": "Python", "pct": 52.4},
                {"name": "TypeScript", "pct": 38.1},
                {"name": "CSS/HTML", "pct": 9.5}
            ]
        },
        "recent_heartbeats": telemetry_store["recent_heartbeats"]
    }

@app.post("/telemetry/heartbeat")
async def log_token_heartbeat(payload: TokenTelemetryPayload):
    """Receive live AI model token consumption telemetry from Antigravity CLI or WakaTime scrobbler."""
    prompt = payload.prompt_tokens
    comp = payload.completion_tokens
    total = prompt + comp

    telemetry_store["total_prompt_tokens"] += prompt
    telemetry_store["total_completion_tokens"] += comp
    telemetry_store["total_tokens"] += total
    telemetry_store["sessions_tracked"] += 1

    model = payload.model_name
    if model not in telemetry_store["models"]:
        telemetry_store["models"][model] = {"prompt": 0, "completion": 0}
    telemetry_store["models"][model]["prompt"] += prompt
    telemetry_store["models"][model]["completion"] += comp

    heartbeat_entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project": payload.project_name or "default",
        "entity": f"session-{payload.session_id[:8]}",
        "language": payload.language or "Python",
        "tokens": total
    }
    telemetry_store["recent_heartbeats"].insert(0, heartbeat_entry)
    if len(telemetry_store["recent_heartbeats"]) > 15:
        telemetry_store["recent_heartbeats"].pop()

    return {
        "status": "success",
        "message": f"Logged {total} tokens for model {payload.model_name}",
        "session_id": payload.session_id
    }
