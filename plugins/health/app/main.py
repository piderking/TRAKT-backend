import os
import time
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("trakt.plugin.health")

app = FastAPI(
    title="Trakt Plugin - Health & Biometrics Microservice",
    description="Microservice capturing Android Health Connect telemetry (Heart Rate, Steps, Calories, Sleep, SpO2).",
    version="1.0.0"
)

# Mount static directory
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Biometric Models
class BiometricsPayload(BaseModel):
    user_id: str = Field(..., description="Trakt User ID")
    device_name: str = Field("Pixel 8 Pro", description="Android Device Model")
    heart_rate_bpm: int = Field(72, ge=30, le=240, description="Current Heart Rate BPM")
    resting_hr_bpm: int = Field(58, ge=30, le=120, description="Resting Heart Rate")
    step_count_today: int = Field(8450, ge=0, description="Daily steps from Health Connect")
    calories_burned_active: int = Field(420, ge=0, description="Active kcal burned")
    sleep_duration_hours: float = Field(7.5, ge=0.0, le=24.0, description="Sleep duration in hours")
    spo2_percentage: float = Field(98.5, ge=70.0, le=100.0, description="Blood Oxygen saturation")
    distance_meters: float = Field(6200.0, ge=0.0)
    timestamp: float = Field(default_factory=time.time)

# In-memory biometrics store
health_store: Dict[str, Any] = {
    "current_bpm": 74,
    "resting_bpm": 58,
    "steps_today": 8840,
    "step_goal": 10000,
    "calories_active": 465,
    "sleep_hours": 7.8,
    "spo2_pct": 99.0,
    "distance_km": 6.4,
    "last_sync": time.time(),
    "bpm_history": [
        {"time": "08:00", "bpm": 62},
        {"time": "10:30", "bpm": 78},
        {"time": "13:15", "bpm": 85},
        {"time": "16:00", "bpm": 110}, # Exercise
        {"time": "18:45", "bpm": 74}
    ],
    "recent_syncs": [
        {
            "device": "Pixel 8 Pro (Health Connect)",
            "timestamp": "2026-08-02T12:45:00Z",
            "hr": 74,
            "steps": 8840,
            "status": "synced"
        }
    ]
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
    """Serve health biometrics web dashboard UI."""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"error": "UI index.html not found"}

@app.get("/telemetry/summary")
async def get_health_summary():
    """Return aggregated biometric metrics."""
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
                "goal_pct": min(100.0, round((health_store["steps_today"] / health_store["step_goal"]) * 100, 1)),
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
async def sync_biometrics(payload: BiometricsPayload):
    """Receive biometric telemetry batch from Android Health Connect Daemon."""
    health_store["current_bpm"] = payload.heart_rate_bpm
    health_store["resting_bpm"] = payload.resting_hr_bpm
    health_store["steps_today"] = payload.step_count_today
    health_store["calories_active"] = payload.calories_burned_active
    health_store["sleep_hours"] = payload.sleep_duration_hours
    health_store["spo2_pct"] = payload.spo2_percentage
    health_store["distance_km"] = round(payload.distance_meters / 1000.0, 2)
    health_store["last_sync"] = time.time()

    sync_entry = {
        "device": f"{payload.device_name} (Health Connect)",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hr": payload.heart_rate_bpm,
        "steps": payload.step_count_today,
        "status": "synced"
    }
    health_store["recent_syncs"].insert(0, sync_entry)
    if len(health_store["recent_syncs"]) > 15:
        health_store["recent_syncs"].pop()

    return {
        "status": "success",
        "message": "Biometrics synced to Tiered Storage Engine",
        "user_id": payload.user_id,
        "timestamp": time.time()
    }
