import os
import time
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("trakt.plugin.health")

app = FastAPI(
    title="Trakt Plugin - Android Health & Biometrics Microservice",
    description="Microservice capturing biometrics from Android Health Connect (Heart Rate, Steps, Active Calories, Sleep, SpO2).",
    version="1.0.0"
)

# Mount static directory
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

class HealthSyncPayload(BaseModel):
    user_id: str = Field("default_user", description="Trakt User ID")
    device_name: str = Field("Android Device", description="Android Device Model")
    heart_rate_bpm: int = Field(0, ge=0, le=240, description="Current Heart Rate BPM")
    resting_hr_bpm: int = Field(0, ge=0, le=120, description="Resting Heart Rate")
    step_count_today: int = Field(0, ge=0, description="Daily steps from Health Connect")
    calories_burned_active: int = Field(0, ge=0, description="Active kcal burned")
    sleep_duration_hours: float = Field(0.0, ge=0.0, le=24.0, description="Sleep duration in hours")
    spo2_percentage: float = Field(0.0, ge=0.0, le=100.0, description="Blood Oxygen saturation")
    distance_meters: float = Field(0.0, ge=0.0)
    timestamp: float = Field(default_factory=time.time)

# In-memory biometrics store (Clean initialized state for user data)
health_store: Dict[str, Any] = {
    "current_bpm": 0,
    "resting_bpm": 0,
    "steps_today": 0,
    "step_goal": 10000,
    "calories_active": 0,
    "sleep_hours": 0.0,
    "spo2_pct": 0.0,
    "distance_km": 0.0,
    "last_sync": 0,
    "bpm_history": [],
    "recent_syncs": []
}

@app.get("/health")
async def health_check():
    """Health check for Health plugin."""
    return {
        "status": "ok",
        "plugin": "health-biometrics-microservice",
        "version": "1.0.0",
        "timestamp": time.time()
    }

@app.get("/ui")
async def get_plugin_ui():
    """Serve Health biometrics web UI."""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"error": "UI index.html not found"}

@app.get("/telemetry/summary")
async def get_health_summary():
    """Get aggregated biometrics summary for Trakt Gateway dashboard."""
    goal_pct = min(100.0, round((health_store["steps_today"] / health_store["step_goal"]) * 100, 1))
    return {
        "plugin": "health-biometrics-v1",
        "timestamp": time.time(),
        "biometrics": {
            "heart_rate": {
                "current_bpm": health_store["current_bpm"],
                "resting_bpm": health_store["resting_bpm"],
                "history": health_store["bpm_history"]
            },
            "activity": {
                "steps_today": health_store["steps_today"],
                "step_goal": health_store["step_goal"],
                "goal_pct": goal_pct,
                "calories_active_kcal": health_store["calories_active"],
                "distance_km": health_store["distance_km"]
            },
            "recovery": {
                "sleep_hours": health_store["sleep_hours"],
                "spo2_percentage": health_store["spo2_pct"]
            }
        },
        "recent_syncs": health_store["recent_syncs"]
    }

@app.post("/telemetry/sync")
async def sync_health_connect(payload: HealthSyncPayload):
    """Receive live biometrics sync payload from Android Health Connect daemon app."""
    health_store["current_bpm"] = payload.heart_rate_bpm
    health_store["resting_bpm"] = payload.resting_hr_bpm
    health_store["steps_today"] = payload.step_count_today
    health_store["calories_active"] = payload.calories_burned_active
    health_store["sleep_hours"] = payload.sleep_duration_hours
    health_store["spo2_pct"] = payload.spo2_percentage
    health_store["distance_km"] = round(payload.distance_meters / 1000.0, 2)
    health_store["last_sync"] = payload.timestamp

    if payload.heart_rate_bpm > 0:
        time_str = time.strftime("%H:%M", time.localtime(payload.timestamp))
        health_store["bpm_history"].append({"time": time_str, "bpm": payload.heart_rate_bpm})
        if len(health_store["bpm_history"]) > 20:
            health_store["bpm_history"].pop(0)

    sync_record = {
        "device": payload.device_name,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(payload.timestamp)),
        "hr": payload.heart_rate_bpm,
        "steps": payload.step_count_today,
        "status": "synced"
    }
    health_store["recent_syncs"].insert(0, sync_record)
    if len(health_store["recent_syncs"]) > 10:
        health_store["recent_syncs"].pop()

    return {
        "status": "success",
        "message": f"Successfully ingested Health Connect sync from '{payload.device_name}'",
        "synced_at": sync_record["timestamp"]
    }
