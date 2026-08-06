import os
import time
import logging
import io
import csv
import zipfile
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException, Depends, Body, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx

from app.core.storage import TieredStorageEngine
from app.core.oauth_server import oauth_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trakt.gateway")

# Environment configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:secret@postgres:5432/trakt")
PLUGIN_MOVIES_URL = os.getenv("PLUGIN_MOVIES_URL", "http://plugin-movies:8000")
PLUGIN_WAKATIME_URL = os.getenv("PLUGIN_WAKATIME_URL", "http://plugin-wakatime:8000")
PLUGIN_HEALTH_URL = os.getenv("PLUGIN_HEALTH_URL", "http://plugin-health:8000")
PLUGIN_LETTERBOXD_URL = os.getenv("PLUGIN_LETTERBOXD_URL", "http://plugin-letterboxd:8000")
PLUGIN_SPOTIFY_URL = os.getenv("PLUGIN_SPOTIFY_URL", "http://plugin-spotify:8000")
PLUGIN_STEAM_URL = os.getenv("PLUGIN_STEAM_URL", "http://plugin-steam:8000")
from app.core.plugin_engine import PluginEngine

storage_engine = TieredStorageEngine(redis_url=REDIS_URL, db_url=DATABASE_URL)
START_TIME = time.time()

plugins_base_path = os.path.join(os.path.dirname(__file__), "..", "plugins")
universal_entities_store: List[Dict[str, Any]] = []
plugin_engine = PluginEngine(plugins_base_path, storage_engine, universal_entities_store)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Trakt Gateway Core Services & Dynamic Plugin Engine...")
    await storage_engine.connect()
    
    # Load entities from disk/database cache
    cached_entities = await storage_engine.get("universal:entities")
    if cached_entities and "items" in cached_entities:
        universal_entities_store.extend(cached_entities["items"])

    plugin_engine.scan_and_load_plugins()
    await plugin_engine.start_background_fetchers()
    yield
    logger.info("Shutting down Trakt Gateway Core Services...")
    await plugin_engine.stop_background_fetchers()
    await storage_engine.disconnect()

app = FastAPI(
    title="Trakt Gateway API",
    description="Core API Gateway & Dynamic Plugin Engine for Trakt Modular Ecosystem",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class DeviceCodeRequest(BaseModel):
    client_id: Optional[str] = Field(default=None, description="Trakt application client ID")

class DeviceTokenRequest(BaseModel):
    code: Optional[str] = Field(default=None, description="Device code or user code")
    client_id: Optional[str] = Field(default=None, description="Client ID")
    client_secret: Optional[str] = Field(default=None, description="Client Secret")

@app.get("/api/v1/plugins/discovered")
async def get_discovered_plugins():
    """List all dynamically scanned plugin directories, schemas, and background fetcher statuses."""
    return {
        "status": "success",
        "fetcher_loop_running": plugin_engine.is_running,
        "count": len(plugin_engine.discovered_plugins),
        "plugins": plugin_engine.get_plugins_status()
    }

class CustomPluginRegisterRequest(BaseModel):
    plugin_id: str = Field(..., description="Unique plugin folder ID")
    name: str = Field(..., description="Plugin Name")
    domain: str = Field("custom", description="Entity domain")
    fetch_url: str = Field(..., description="Background fetcher URL endpoint")
    schema_fields: Dict[str, Any] = Field(default_factory=dict, description="Database entity JSON schema")

@app.post("/api/v1/plugins/register")
async def register_custom_plugin_directory(req: CustomPluginRegisterRequest):
    """Dynamically register a new plugin directory with schema and background fetcher URL."""
    p_obj = plugin_engine.register_custom_plugin(
        plugin_id=req.plugin_id,
        domain=req.domain,
        name=req.name,
        fetch_url=req.fetch_url,
        schema=req.schema_fields
    )
    return {"status": "registered", "plugin": p_obj.id, "fetch_url": p_obj.fetch_url}

@app.post("/api/v1/plugins/toggle/{plugin_id}")
async def toggle_plugin_fetcher(plugin_id: str):
    """Toggle background fetcher loop for a specific plugin."""
    p = plugin_engine.discovered_plugins.get(plugin_id.lower())
    if not p:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    p.enabled = not p.enabled
    return {"status": "toggled", "plugin": p.id, "enabled": p.enabled}

from app.core.events import event_bus, event_generator

@app.get("/api/v1/events/stream")
async def stream_reactive_events():
    """Real-Time Reactive Server-Sent Events (SSE) stream broadcasting instant DB mutations."""
    q = event_bus.subscribe()
    return StreamingResponse(event_generator(q), media_type="text/event-stream")

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "trakt-gateway",
        "uptime_seconds": round(time.time() - START_TIME, 2),
        "timestamp": time.time()
    }

@app.get("/api/v1/system/status")
async def system_status():
    """Get system operational status, storage stats, and microservice connectivity."""
    storage_stats = await storage_engine.get_status()
    
    # Check Plugin Movies health
    plugin_movies_status = "offline"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{PLUGIN_MOVIES_URL}/health")
            if resp.status_code == 200:
                plugin_movies_status = "online"
    except Exception:
        plugin_movies_status = "fallback/offline"

    return {
        "service": "trakt-core-gateway",
        "status": "healthy",
        "uptime": round(time.time() - START_TIME, 2),
        "storage_engine": storage_stats,
        "plugins": {
            "movies": {
                "url": PLUGIN_MOVIES_URL,
                "status": plugin_movies_status
            }
        },
        "environment": {
            "redis_configured": bool(REDIS_URL),
            "database_configured": bool(DATABASE_URL)
        }
    }

@app.post("/api/v1/auth/device/code")
async def generate_device_code(payload: Optional[DeviceCodeRequest] = None):
    """Generate Trakt device code for authentication flow."""
    user_code = "TRKT-" + os.urandom(2).hex().upper()
    device_code = "dev_code_" + os.urandom(8).hex()
    
    code_data = {
        "user_code": user_code,
        "device_code": device_code,
        "verification_url": "https://trakt.tv/activate",
        "expires_in": 600,
        "interval": 5,
        "created_at": time.time()
    }
    
    await storage_engine.set(f"device_code:{device_code}", code_data, ttl=600)
    
    return {
        "user_code": user_code,
        "device_code": device_code,
        "verification_url": "https://trakt.tv/activate",
        "expires_in": 600,
        "interval": 5
    }

@app.post("/api/v1/auth/device/token")
async def exchange_device_token(payload: Optional[DeviceTokenRequest] = None):
    """Exchange device authorization code for access token."""
    access_token = "trakt_at_" + os.urandom(12).hex()
    refresh_token = "trakt_rt_" + os.urandom(12).hex()
    
    token_response = {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 7200,
        "refresh_token": refresh_token,
        "scope": "public",
        "created_at": int(time.time())
    }
    
    await storage_engine.set(f"session:{access_token}", token_response, ttl=7200)
    return token_response

@app.get("/api/v1/user/up-next")
async def get_user_up_next():
    """Proxy up-next watch list requests to the Plugin Movies microservice with fallback caching."""
    cache_key = "user:up_next_feed"
    
    # Attempt to fetch from plugin microservice
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{PLUGIN_MOVIES_URL}/up-next")
            if resp.status_code == 200:
                data = resp.json()
                # Cache full list in TieredStorageEngine
                await storage_engine.set(cache_key, data, ttl=300)
                return data
    except Exception as e:
        logger.warning(f"Plugin Movies unreachable: {e}. Attempting cached fallback...")

    # Cache fallback
    cached = await storage_engine.get(cache_key)
    if cached:
        return cached

    # Built-in fallback payload if service & cache miss
    fallback_payload = {
        "source": "fallback-gateway-cache",
        "up_next": [
            {
                "id": "m1",
                "title": "Dune: Part Two",
                "type": "movie",
                "year": 2024,
                "progress_pct": 0,
                "runtime_min": 166,
                "rating": 8.6,
                "poster": "https://images.unsplash.com/photo-1534447677768-be436bb09401?w=400&q=80",
                "backdrop": "https://images.unsplash.com/photo-1534447677768-be436bb09401?w=1200&q=80",
                "genre": ["Sci-Fi", "Adventure"],
                "next_episode": None
            },
            {
                "id": "s1",
                "title": "Severance",
                "type": "show",
                "year": 2022,
                "progress_pct": 75,
                "runtime_min": 55,
                "rating": 8.7,
                "poster": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=400&q=80",
                "backdrop": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=1200&q=80",
                "genre": ["Sci-Fi", "Thriller"],
                "next_episode": {
                    "season": 2,
                    "number": 1,
                    "title": "Hello Ms. Cobel"
                }
            }
        ]
    }
    await storage_engine.set(cache_key, fallback_payload, ttl=300)
    return fallback_payload

@app.get("/api/v1/telemetry/summary")
async def get_telemetry_summary():
    """Proxy telemetry summary to the WakaTime & Antigravity token microservice."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{PLUGIN_WAKATIME_URL}/telemetry/summary")
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning(f"Plugin WakaTime unreachable: {e}. Returning cached/fallback telemetry...")

    return {
        "source": "gateway-telemetry-fallback",
        "token_metrics": {
            "prompt_tokens": 142500,
            "completion_tokens": 48200,
            "total_tokens": 190700,
            "models_breakdown": {
                "gemini-3.6-flash": {"prompt": 110000, "completion": 35000},
                "gemini-3.6-pro": {"prompt": 32500, "completion": 13200}
            },
            "sessions_count": 12
        },
        "wakatime_metrics": {
            "today_seconds": 18420,
            "today_formatted": "5h 7m",
            "active_project": "TRAKT",
            "top_languages": [
                {"name": "Python", "pct": 52.4},
                {"name": "TypeScript", "pct": 38.1}
            ]
        }
    }

@app.get("/api/v1/health/summary")
async def get_health_summary():
    """Proxy health biometrics summary request to the Health microservice."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{PLUGIN_HEALTH_URL}/telemetry/summary")
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning(f"Plugin Health unreachable: {e}. Returning cached/fallback biometrics...")

    return {
        "source": "gateway-health-fallback",
        "biometrics": {
            "heart_rate": {"current_bpm": 74, "resting_bpm": 58},
            "activity": {"steps_today": 8840, "step_goal": 10000, "goal_pct": 88.4, "calories_active_kcal": 465},
            "recovery": {"sleep_hours": 7.8, "spo2_percentage": 99.0}
        }
    }

@app.post("/api/v1/health/sync")
async def sync_health_telemetry(payload: Dict[str, Any] = Body(...)):
    """Proxy biometric telemetry batch from Android Health Connect Daemon to Health plugin & Tiered Storage."""
    cache_key = f"health:user:{payload.get('user_id', 'default')}:latest"
    await storage_engine.set(cache_key, payload, ttl=86400)

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(f"{PLUGIN_HEALTH_URL}/telemetry/sync", json=payload)
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning(f"Plugin Health unreachable: {e}. Telemetry saved to Tiered Storage Engine.")

    return {
        "status": "success",
        "source": "gateway-tiered-storage",
        "message": "Biometrics stored in TieredStorageEngine"
    }

# --- Built-in OAuth 2.0 Authorization Server Endpoints ---

class OAuthClientRegisterRequest(BaseModel):
    client_name: str
    redirect_uris: list[str]
    scopes: list[str] = ["read", "write", "scrobble"]

class OAuthTokenRequest(BaseModel):
    grant_type: str = "authorization_code"
    code: Optional[str] = None
    client_id: str
    client_secret: str
    redirect_uri: Optional[str] = None

@app.post("/oauth/clients/register")
async def register_oauth_client(payload: OAuthClientRegisterRequest):
    """Register a new client application with the OAuth 2.0 Authorization Server."""
    client = oauth_server.register_client(
        client_name=payload.client_name,
        redirect_uris=payload.redirect_uris,
        scopes=payload.scopes
    )
    return client

@app.post("/oauth/authorize/code")
async def request_oauth_code(client_id: str, redirect_uri: str, scope: str = "read"):
    """Request an OAuth 2.0 Authorization Code."""
    try:
        code = oauth_server.create_authorization_code(client_id=client_id, redirect_uri=redirect_uri, scope=scope)
        return {"authorization_code": code, "expires_in": 600}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/oauth/token")
async def issue_oauth_token(payload: OAuthTokenRequest):
    """Exchange authorization code or credentials for a JWT Access Token."""
    if payload.grant_type == "authorization_code" and payload.code:
        try:
            tokens = oauth_server.exchange_code_for_tokens(
                code=payload.code,
                client_id=payload.client_id,
                client_secret=payload.client_secret
            )
            return tokens
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        raise HTTPException(status_code=400, detail="Unsupported grant_type or missing code")

@app.get("/oauth/userinfo")
async def get_oauth_userinfo(token: str):
    """Verify JWT Access Token and return authenticated user details."""
    try:
        payload = oauth_server.verify_jwt_token(token)
        return {"sub": payload.get("sub"), "client_id": payload.get("client_id"), "scope": payload.get("scope")}
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

# --- Plugin Configuration & API Keys Settings Endpoints ---

@app.get("/api/v1/plugins/config")
@app.get("/api/v1/plugins/config/{plugin_id}")
async def get_plugin_config(plugin_id: str):
    """Get stored API keys and configuration credentials for a plugin."""
    config = oauth_server.get_plugin_config(plugin_id)
    return {"plugin_id": plugin_id, "config": config}

@app.post("/api/v1/plugins/config")
@app.post("/api/v1/plugins/config/{plugin_id}")
async def set_plugin_config(plugin_id: str, config: Dict[str, str] = Body(...)):
    """Save API keys (e.g., WAKATIME_API_KEY, TRAKT_CLIENT_ID) for a plugin."""
    updated = oauth_server.set_plugin_config(plugin_id, config)
    # Also sync to TieredStorageEngine for persistence
    await storage_engine.set(f"plugin:config:{plugin_id}", updated, ttl=86400 * 30)
    return {"status": "saved", "plugin_id": plugin_id, "config": updated}

@app.post("/api/v1/system/flush")
async def flush_all_dummy_data():
    """Flush all dummy seed data across Gateway and Microservice Plugins."""
    global movie_diary_store
    movie_diary_store.clear()
    
    # Notify microservices if reachable
    for plugin_url in [PLUGIN_STEAM_URL, PLUGIN_SPOTIFY_URL, PLUGIN_HEALTH_URL, PLUGIN_WAKATIME_URL]:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.post(f"{plugin_url}/telemetry/flush")
        except Exception:
            pass

    return {"status": "flushed", "message": "All ecosystem dummy data flushed. Ready for live user data."}

# --- Letterboxd Data Export Zip Importer Proxy Endpoints ---

@app.get("/api/v1/import/letterboxd/summary")
async def get_letterboxd_import_summary():
    """Proxy Letterboxd import summary to Letterboxd microservice plugin."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{PLUGIN_LETTERBOXD_URL}/import/summary")
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning(f"Plugin Letterboxd unreachable: {e}. Returning fallback summary...")

    return {
        "source": "gateway-letterboxd-fallback",
        "stats": {"total_imports": 1, "movies_watched": 428, "ratings": 312, "diary_entries": 185, "watchlist": 94}
    }

def parse_letterboxd_csv_bytes(content_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    """Parse Letterboxd CSV bytes with UTF-8 BOM handling and flexible column mapping."""
    try:
        text = content_bytes.decode("utf-8-sig", errors="ignore")
    except Exception:
        text = content_bytes.decode("latin-1", errors="ignore")

    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for raw_row in reader:
        clean_row = {}
        for k, v in raw_row.items():
            if k is not None:
                clean_k = k.strip().lstrip('\ufeff')
                clean_row[clean_k] = v.strip() if v else ""

        title = clean_row.get("Name") or clean_row.get("Title") or clean_row.get("Film") or ""
        year = clean_row.get("Year") or clean_row.get("Release Year") or "2024"
        date_watched = clean_row.get("Date") or clean_row.get("Watched Date") or time.strftime("%Y-%m-%d")
        rating_raw = clean_row.get("Rating") or ""
        uri = clean_row.get("Letterboxd URI") or clean_row.get("URI") or clean_row.get("URL") or ""
        rewatch = clean_row.get("Rewatch") or ""
        review = clean_row.get("Review") or ""
        tags = clean_row.get("Tags") or ""

        rating_num = 8.0
        if rating_raw:
            try:
                r_val = float(rating_raw)
                rating_num = r_val * 2.0 if r_val <= 5.0 else r_val
            except ValueError:
                rating_num = 8.0

        if title:
            rows.append({
                "id": f"lb_{len(rows)+1}_{int(time.time())}",
                "movie_title": title,
                "release_year": int(year) if str(year).isdigit() else 2024,
                "watched_date": date_watched,
                "rating": rating_num,
                "is_rewatch": rewatch.lower() in ["yes", "true", "1", "r"],
                "liked": rating_num >= 8.0,
                "review": review,
                "tags": [t.strip() for t in tags.split(",") if t.strip()],
                "letterboxd_uri": uri,
                "poster_url": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=500&q=80"
            })
    return rows

@app.post("/api/v1/import/letterboxd")
async def upload_letterboxd_zip_export(file: UploadFile = File(...)):
    """Parse Letterboxd zip export (watched.csv, ratings.csv, diary.csv, watchlist.csv) and auto-populate movie diary."""
    global movie_diary_store
    filename = file.filename or "letterboxd-export.zip"
    content = await file.read()

    # Try microservice first
    try:
        files_payload = {"file": (filename, content, file.content_type or "application/zip")}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{PLUGIN_LETTERBOXD_URL}/import/upload", files=files_payload)
            if resp.status_code == 200:
                res_data = resp.json()
                if res_data.get("watched_count", 0) > 0 or res_data.get("ratings_count", 0) > 0:
                    return res_data
    except Exception as e:
        logger.warning(f"Plugin Letterboxd unreachable: {e}. Parsing zip directly in gateway...")

    # Direct Zip Parsing in Gateway
    watched_items, ratings_items, diary_items, watchlist_items = [], [], [], []
    if filename.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for name in zf.namelist():
                    lower_name = name.lower()
                    file_bytes = zf.read(name)
                    if lower_name.endswith("watched.csv"):
                        watched_items = parse_letterboxd_csv_bytes(file_bytes, name)
                    elif lower_name.endswith("ratings.csv"):
                        ratings_items = parse_letterboxd_csv_bytes(file_bytes, name)
                    elif lower_name.endswith("diary.csv"):
                        diary_items = parse_letterboxd_csv_bytes(file_bytes, name)
                    elif lower_name.endswith("watchlist.csv"):
                        watchlist_items = parse_letterboxd_csv_bytes(file_bytes, name)
        except Exception as err:
            raise HTTPException(status_code=400, detail=f"Failed to extract Letterboxd zip archive: {str(err)}")
    elif filename.endswith(".csv"):
        watched_items = parse_letterboxd_csv_bytes(content, filename)

    # Ingest into movie_diary_store
    all_imported = diary_items or watched_items or ratings_items
    for item in all_imported:
        # Avoid duplicate titles if already logged
        if not any(existing.get("movie_title") == item.get("movie_title") for existing in movie_diary_store):
            movie_diary_store.append(item)

    w_cnt = len(watched_items) or len(all_imported)
    r_cnt = len(ratings_items)
    d_cnt = len(diary_items)
    wl_cnt = len(watchlist_items)

    return {
        "status": "success",
        "source": "gateway-direct-zip-ingest",
        "filename": filename,
        "watched_count": w_cnt,
        "ratings_count": r_cnt,
        "diary_count": d_cnt,
        "watchlist_count": wl_cnt,
        "total_imported": len(all_imported),
        "message": f"Successfully imported {len(all_imported)} movies from '{filename}' into Trakt Diary."
    }

# --- Letterboxd-Style Movie Logger & Diary Endpoints ---

class MovieLogRequest(BaseModel):
    movie_title: str = Field(..., description="Title of the movie")
    release_year: Optional[int] = Field(2024, description="Release year")
    watched_date: str = Field(..., description="Date watched (YYYY-MM-DD)")
    rating: float = Field(8.0, ge=1.0, le=10.0, description="Rating from 1.0 to 10.0")
    is_rewatch: bool = Field(False, description="Whether this is a rewatch")
    liked: bool = Field(False, description="Heart / Like toggle")
    review: Optional[str] = Field("", description="Journal review or notes")
    tags: list[str] = Field(default_factory=list, description="Custom tags")
    poster_url: Optional[str] = Field(None, description="Movie poster URL")

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")

TRENDING_MOVIES_CATALOG = [
    {
        "id": 823464,
        "title": "Dune: Part Two",
        "release_year": 2024,
        "rating": 8.6,
        "overview": "Paul Atreides unites with Chani and the Fremen while seeking revenge against the conspirators who destroyed his family.",
        "poster_url": "https://images.unsplash.com/photo-1534447677768-be436bb09401?w=500&q=80",
        "genre": "Sci-Fi / Adventure"
    },
    {
        "id": 872585,
        "title": "Oppenheimer",
        "release_year": 2023,
        "rating": 8.9,
        "overview": "The story of American scientist J. Robert Oppenheimer and his role in the development of the atomic bomb.",
        "poster_url": "https://images.unsplash.com/photo-1440404653325-ab127d49abc1?w=500&q=80",
        "genre": "Biography / Drama"
    },
    {
        "id": 157336,
        "title": "Interstellar",
        "release_year": 2014,
        "rating": 8.7,
        "overview": "A team of explorers travel through a wormhole in space in an attempt to ensure humanity's survival.",
        "poster_url": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=500&q=80",
        "genre": "Sci-Fi / Drama"
    },
    {
        "id": 533535,
        "title": "Deadpool & Wolverine",
        "release_year": 2024,
        "rating": 7.9,
        "overview": "Wolverine is recovering from his injuries when he crosses paths with the loudmouth Deadpool.",
        "poster_url": "https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?w=500&q=80",
        "genre": "Action / Comedy"
    },
    {
        "id": 945961,
        "title": "Alien: Romulus",
        "release_year": 2024,
        "rating": 7.3,
        "overview": "While scavenging the deep ends of a derelict space station, a group of young space colonizers come face to face with the most terrifying life form in the universe.",
        "poster_url": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=500&q=80",
        "genre": "Sci-Fi / Horror"
    },
    {
        "id": 558449,
        "title": "Gladiator II",
        "release_year": 2024,
        "rating": 7.5,
        "overview": "Years after witnessing the death of Maximus at the hands of his uncle, Lucius must enter the Colosseum after his home is conquered by the tyrannical Emperors.",
        "poster_url": "https://images.unsplash.com/photo-1579783902614-a3fb3927b675?w=500&q=80",
        "genre": "Action / History"
    },
    {
        "id": 335984,
        "title": "Blade Runner 2049",
        "release_year": 2017,
        "rating": 8.0,
        "overview": "Young Blade Runner K's discovery of a long-buried secret leads him to track down former Blade Runner Rick Deckard.",
        "poster_url": "https://images.unsplash.com/photo-1509198397868-475647b2a1e5?w=500&q=80",
        "genre": "Sci-Fi / Mystery"
    },
    {
        "id": 496243,
        "title": "Parasite",
        "release_year": 2019,
        "rating": 8.5,
        "overview": "Greed and class discrimination threaten the newly formed symbiotic relationship between the wealthy Park family and the destitute Kim clan.",
        "poster_url": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=500&q=80",
        "genre": "Thriller / Drama"
    }
]

movie_diary_store: list[dict[str, Any]] = []

@app.get("/api/v1/movies/trending")
async def get_trending_movies():
    """Fetch new and trending movies for discovery and quick logging."""
    if TMDB_API_KEY:
        try:
            url = f"https://api.themoviedb.org/3/trending/movie/week?api_key={TMDB_API_KEY}"
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    formatted = []
                    for m in results[:10]:
                        formatted.append({
                            "id": m.get("id"),
                            "title": m.get("title"),
                            "release_year": int(m.get("release_date", "2024")[:4]) if m.get("release_date") else 2024,
                            "rating": round(m.get("vote_average", 8.0), 1),
                            "overview": m.get("overview", ""),
                            "poster_url": f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}" if m.get("poster_path") else "https://images.unsplash.com/photo-1534447677768-be436bb09401?w=500&q=80",
                            "genre": "Trending"
                        })
                    return {"status": "success", "source": "tmdb-api", "movies": formatted}
        except Exception as e:
            logger.warning(f"TMDB trending API fetch failed: {e}")

    return {"status": "success", "source": "trakt-catalog", "movies": TRENDING_MOVIES_CATALOG}

@app.get("/api/v1/movies/search")
async def search_movies(q: str = ""):
    """Search movies by title using OMDb or TMDB Live Movie API for adaptive lookup and auto-fill."""
    query = q.strip().lower()
    if not query:
        return await get_trending_movies()

    # 1. Try TMDB API if key provided
    if TMDB_API_KEY:
        try:
            url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={query}"
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    if results:
                        formatted = []
                        for m in results[:10]:
                            formatted.append({
                                "id": m.get("id"),
                                "title": m.get("title"),
                                "release_year": int(m.get("release_date", "2024")[:4]) if m.get("release_date") else 2024,
                                "rating": round(m.get("vote_average", 8.0), 1),
                                "overview": m.get("overview", ""),
                                "poster_url": f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}" if m.get("poster_path") else "https://images.unsplash.com/photo-1534447677768-be436bb09401?w=500&q=80",
                                "director": "Featured Director",
                                "genre": "Cinema"
                            })
                        return {"status": "success", "query": q, "source": "tmdb-api", "results": formatted}
        except Exception as e:
            logger.warning(f"TMDB search API fetch failed: {e}")

    # 2. Live OMDb Movie Search API (Free, high quality, real posters & directors)
    try:
        omdb_key = os.getenv("OMDB_API_KEY", "trilogy")
        url = f"http://www.omdbapi.com/?apikey={omdb_key}&s={query}&type=movie"
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                raw_data = resp.json()
                results = raw_data.get("Search", [])
                if results:
                    formatted = []
                    for m in results[:10]:
                        yr = m.get("Year", "2024")
                        try:
                            release_year = int(yr[:4])
                        except Exception:
                            release_year = 2024
                        poster = m.get("Poster")
                        if not poster or poster == "N/A":
                            poster = "https://images.unsplash.com/photo-1534447677768-be436bb09401?w=500&q=80"
                        
                        formatted.append({
                            "id": m.get("imdbID"),
                            "title": m.get("Title"),
                            "release_year": release_year,
                            "rating": 8.5,
                            "overview": f"Movie entry '{m.get('Title')}' fetched live.",
                            "poster_url": poster,
                            "director": "Director Track",
                            "genre": "Cinema"
                        })
                    return {"status": "success", "query": q, "source": "omdb-live-api", "results": formatted}
    except Exception as ex:
        logger.warning(f"OMDb Movie Search API failed: {ex}")

    # Fallback search against catalog
    filtered = [m for m in TRENDING_MOVIES_CATALOG if query in m.get("title", "").lower()]
    return {"status": "success", "query": q, "source": "trakt-catalog", "results": filtered}

@app.get("/api/v1/movies/diary")
async def get_movie_diary():
    """Retrieve Letterboxd-style movie log diary entries and rating statistics."""
    total_logs = len(movie_diary_store)
    rewatch_count = sum(1 for item in movie_diary_store if item.get("is_rewatch"))
    liked_count = sum(1 for item in movie_diary_store if item.get("liked"))
    
    # Calculate rating distribution (1 to 10 scale)
    ratings_dist = {str(i): 0 for i in range(1, 11)}
    for item in movie_diary_store:
        r_bucket = str(min(10, max(1, int(round(item.get("rating", 8.0))))))
        ratings_dist[r_bucket] += 1

    return {
        "status": "success",
        "stats": {
            "total_logged": total_logs,
            "rewatch_count": rewatch_count,
            "liked_count": liked_count,
            "rating_distribution": ratings_dist
        },
        "diary": movie_diary_store
    }

@app.post("/api/v1/movies/log")
async def create_movie_log(payload: MovieLogRequest):
    """Log a new movie entry into the user's Trakt Letterboxd-style diary."""
    import secrets
    log_id = f"log_{secrets.token_hex(6)}"
    
    entry = {
        "id": log_id,
        "movie_title": payload.movie_title,
        "release_year": payload.release_year or 2024,
        "watched_date": payload.watched_date,
        "rating": payload.rating,
        "is_rewatch": payload.is_rewatch,
        "liked": payload.liked,
        "review": payload.review or "",
        "tags": payload.tags,
        "poster_url": payload.poster_url or "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=500&q=80",
        "timestamp": time.time()
    }
    
    movie_diary_store.insert(0, entry)

    # Cache to Tiered Storage Engine
    await storage_engine.set(f"movie:log:{log_id}", entry, ttl=86400 * 30)

    return {
        "status": "success",
        "message": f"Successfully logged '{payload.movie_title}' into Trakt Diary",
        "entry": entry
    }

@app.delete("/api/v1/movies/log/{log_id}")
async def delete_movie_log(log_id: str):
    """Delete a movie diary log entry."""
    global movie_diary_store
    movie_diary_store = [m for m in movie_diary_store if m["id"] != log_id]
    return {"status": "deleted", "log_id": log_id}

# --- Spotify API Scrobbler Endpoints ---

@app.get("/api/v1/spotify/summary")
async def get_spotify_summary():
    """Proxy Spotify scrobbler summary to Spotify microservice plugin."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{PLUGIN_SPOTIFY_URL}/telemetry/summary")
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning(f"Plugin Spotify unreachable: {e}. Fetching directly from Spotify Web API...")

    spotify_access_token = os.getenv("SPOTIFY_ACCESS_TOKEN", "")
    if spotify_access_token:
        try:
            headers = {"Authorization": f"Bearer {spotify_access_token}"}
            async with httpx.AsyncClient(timeout=4.0) as client:
                np_resp = await client.get("https://api.spotify.com/v1/me/player/currently-playing", headers=headers)
                rec_resp = await client.get("https://api.spotify.com/v1/me/player/recently-played?limit=10", headers=headers)

                now_playing = {"track_name": "No Track Playing", "artist_name": "", "is_playing": False}
                if np_resp.status_code == 200 and np_resp.content:
                    np_data = np_resp.json()
                    item = np_data.get("item") or {}
                    artists = item.get("artists", [])
                    imgs = item.get("album", {}).get("images", [])
                    now_playing = {
                        "track_name": item.get("name", "No Track Playing"),
                        "artist_name": ", ".join(a.get("name") for a in artists) if artists else "",
                        "album_name": item.get("album", {}).get("name", ""),
                        "duration_ms": item.get("duration_ms", 0),
                        "progress_ms": np_data.get("progress_ms", 0),
                        "is_playing": np_data.get("is_playing", False),
                        "album_art_url": imgs[0].get("url") if imgs else "",
                        "spotify_uri": item.get("uri", "")
                    }

                history = []
                if rec_resp.status_code == 200:
                    for it in rec_resp.json().get("items", []):
                        tr = it.get("track", {})
                        art = ", ".join(a.get("name") for a in tr.get("artists", []))
                        dur_ms = tr.get("duration_ms", 0)
                        imgs = tr.get("album", {}).get("images", [])
                        history.append({
                            "track_name": tr.get("name"),
                            "artist_name": art,
                            "album_name": tr.get("album", {}).get("name"),
                            "album_art_url": imgs[0].get("url") if imgs else "",
                            "played_at": it.get("played_at", "")[:16].replace("T", " "),
                            "duration_formatted": f"{dur_ms//60000}:{(dur_ms%60000)//1000:02d}"
                        })

                return {
                    "source": "gateway-direct-spotify-api",
                    "now_playing": now_playing,
                    "stats": {"tracks_played_today": len(history), "total_listening_minutes": 0},
                    "history": history
                }
        except Exception as ex:
            logger.error(f"Direct Spotify API fetch failed: {ex}")

    return {
        "source": "gateway-spotify-clean-initial",
        "now_playing": {
            "track_name": "No Track Playing",
            "artist_name": "",
            "album_name": "",
            "is_playing": False,
            "audio_features": {"bpm": 0, "energy": 0.0}
        },
        "stats": {"tracks_played_today": 0, "total_listening_minutes": 0},
        "history": []
    }

@app.get("/api/v1/spotify/now-playing")
async def get_spotify_now_playing():
    """Proxy live Spotify now playing status."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{PLUGIN_SPOTIFY_URL}/telemetry/now-playing")
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning(f"Plugin Spotify unreachable: {e}")

    return {"is_playing": False, "track_name": "No Track Playing", "artist_name": ""}

@app.post("/api/v1/spotify/scrobble")
async def scrobble_spotify_track(payload: Dict[str, Any] = Body(...)):
    """Proxy live track scrobble to Spotify microservice plugin & Tiered Storage."""
    await storage_engine.set("spotify:now_playing", payload, ttl=86400)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(f"{PLUGIN_SPOTIFY_URL}/telemetry/scrobble", json=payload)
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning(f"Plugin Spotify unreachable during scrobble: {e}")

    return {"status": "success", "source": "gateway-tiered-storage", "message": "Scrobbled to Tiered Storage"}

# --- Steam Web API Gaming Endpoints ---

@app.get("/api/v1/steam/summary")
async def get_steam_summary():
    """Proxy Steam gaming summary to Steam microservice plugin."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{PLUGIN_STEAM_URL}/telemetry/summary")
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning(f"Plugin Steam unreachable: {e}. Fetching directly from Steam Web API...")

    # Direct Steam Web API query fallback using dynamic DB config
    steam_cfg = plugin_config_store.get("steam", {})
    key = steam_cfg.get("steam_api_key") or os.getenv("STEAM_API_KEY", "")
    sid = steam_cfg.get("steam_profile_id") or os.getenv("STEAM_ID_64", "")

    if not key or not sid:
        return {
            "source": "gateway-steam-unconfigured",
            "now_playing": {"player_name": "", "game_title": "Steam Unconfigured", "app_id": 0, "is_playing": False},
            "stats": {"games_owned": 0, "total_hours_played": 0.0, "recent_2weeks_hours": 0.0, "top_games": []},
            "recent_games": []
        }

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            sum_resp = await client.get(f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={key}&steamids={sid}")
            own_resp = await client.get(f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={key}&steamid={sid}&format=json&include_appinfo=1&include_played_free_games=1")
            rec_resp = await client.get(f"https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/?key={key}&steamid={sid}")

            p_data = sum_resp.json().get("response", {}).get("players", [{}])[0] if sum_resp.status_code == 200 else {}
            o_data = own_resp.json().get("response", {}) if own_resp.status_code == 200 else {}
            r_data = rec_resp.json().get("response", {}) if rec_resp.status_code == 200 else {}

            all_games = o_data.get("games", [])
            tot_mins = sum(g.get("playtime_forever", 0) for g in all_games)
            rec_games_raw = r_data.get("games", [])
            rec_2w_mins = sum(rg.get("playtime_2weeks", 0) for rg in rec_games_raw)

            sorted_games = sorted(all_games, key=lambda g: g.get("playtime_forever", 0), reverse=True)
            top_games = [
                {
                    "game_title": g.get("name"),
                    "app_id": g.get("appid"),
                    "hours": round(g.get("playtime_forever", 0) / 60.0, 1),
                    "header_image": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{g.get('appid')}/header.jpg"
                } for g in sorted_games[:6] if g.get("playtime_forever", 0) > 0
            ]

            recent_games = [
                {
                    "game_title": rg.get("name"),
                    "app_id": rg.get("appid"),
                    "playtime_2weeks_hours": round(rg.get("playtime_2weeks", 0) / 60.0, 1),
                    "total_hours": round(rg.get("playtime_forever", 0) / 60.0, 1),
                    "header_image": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{rg.get('appid')}/header.jpg",
                    "last_played": "Recent (Past 2 Weeks)"
                } for rg in rec_games_raw
            ]

            game_title = p_data.get("gameextrainfo")
            game_id = p_data.get("gameid")

            return {
                "source": "gateway-direct-steam-api",
                "steam_id": sid,
                "now_playing": {
                    "player_name": p_data.get("personaname", "muncher"),
                    "avatar_url": p_data.get("avatarfull", ""),
                    "profile_url": p_data.get("profileurl", ""),
                    "game_title": game_title or "Offline / Not in-game",
                    "app_id": int(game_id) if game_id and str(game_id).isdigit() else 0,
                    "is_playing": bool(game_title),
                    "header_image": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{game_id}/header.jpg" if game_id else ""
                },
                "stats": {
                    "games_owned": o_data.get("game_count", len(all_games)),
                    "total_hours_played": round(tot_mins / 60.0, 1),
                    "recent_2weeks_hours": round(rec_2w_mins / 60.0, 1),
                    "top_games": top_games
                },
                "recent_games": recent_games
            }
    except Exception as ex:
        logger.error(f"Direct Steam API query failed: {ex}")

# --- Universal Interconnected Life Activity Entity Architecture ---

class UniversalEntityRequest(BaseModel):
    domain: str = Field("movie", description="Entity domain: music, movie, gaming, health, coding, custom")
    title: str = Field(..., description="Entity title")
    subtitle: Optional[str] = Field(None, description="Artist, Director, Developer, etc.")
    timestamp: Optional[float] = Field(default_factory=time.time)
    tags: List[str] = Field(default_factory=list, description="Tags, e.g. ['spotify'], ['theatre', 'imax'], ['steam']")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Custom key-value properties (location, director, rating, bpm, hours)")
    relations: List[str] = Field(default_factory=list, description="Linked entity IDs")
    image_url: Optional[str] = Field(None, description="Banner / poster image URL")

universal_entities_store: List[Dict[str, Any]] = []

@app.get("/api/v1/entities")
async def get_universal_entities(domain: Optional[str] = None, tag: Optional[str] = None, q: Optional[str] = None):
    """Query interconnected universal life activity entities with domain, tag, and search filtering."""
    results = universal_entities_store
    
    if domain and domain.lower() != "all":
        results = [e for e in results if e.get("domain", "").lower() == domain.lower()]
        
    if tag:
        tag_clean = tag.strip().lower()
        results = [e for e in results if any(tag_clean in t.lower() for t in e.get("tags", []))]
        
    if q:
        q_clean = q.strip().lower()
        results = [
            e for e in results 
            if q_clean in e.get("title", "").lower() 
            or q_clean in e.get("subtitle", "").lower()
            or any(q_clean in t.lower() for t in e.get("tags", []))
            or any(q_clean in str(v).lower() for v in e.get("properties", {}).values())
        ]
        
    return {
        "status": "success",
        "count": len(results),
        "entities": sorted(results, key=lambda e: e.get("timestamp", 0), reverse=True)
    }

@app.post("/api/v1/entities")
async def create_universal_entity(req: UniversalEntityRequest):
    """Create a new interconnected activity entity with tags and custom properties."""
    new_id = f"ent_{len(universal_entities_store)+101}_{int(time.time())}"
    entity_data = {
        "id": new_id,
        "domain": req.domain.lower(),
        "title": req.title,
        "subtitle": req.subtitle or "",
        "timestamp": req.timestamp or time.time(),
        "tags": [t.strip().lower() for t in req.tags if t.strip()],
        "properties": req.properties,
        "relations": req.relations,
        "image_url": req.image_url or "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=500&q=80"
    }
    universal_entities_store.insert(0, entity_data)
    await storage_engine.set("universal:entities", {"items": universal_entities_store})
    await event_bus.publish("ENTITY_CREATED", entity_data)
    return {"status": "success", "entity": entity_data}

@app.put("/api/v1/entities/{entity_id}")
async def update_universal_entity(entity_id: str, req: UniversalEntityRequest):
    """Update an existing entity's tags, properties, title, subtitle, or domain."""
    global universal_entities_store
    for e in universal_entities_store:
        if e.get("id") == entity_id:
            e["domain"] = req.domain.lower()
            e["title"] = req.title
            e["subtitle"] = req.subtitle or ""
            e["tags"] = [t.strip().lower() for t in req.tags if t.strip()]
            e["properties"] = req.properties
            e["relations"] = req.relations
            if req.image_url:
                e["image_url"] = req.image_url
            await storage_engine.set("universal:entities", {"items": universal_entities_store})
            return {"status": "updated", "entity": e}
    raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")

# Track API Route Aliases (Renamed from Scrobble to Track)

@app.post("/api/v1/spotify/track")
async def track_spotify_item(payload: Dict[str, Any] = Body(...)):
    """Track live Spotify track/session (renamed from scrobble)."""
    return await scrobble_spotify_track(payload)

@app.post("/api/v1/steam/track")
async def track_steam_session(payload: Dict[str, Any] = Body(...)):
    """Track live Steam gaming session (renamed from scrobble)."""
    return await scrobble_steam_game(payload)

@app.get("/api/v1/entities")
async def get_universal_entities(domain: Optional[str] = None, tag: Optional[str] = None, q: Optional[str] = None):
    """Query interconnected universal life activity entities with domain, tag, and search filtering."""
    results = universal_entities_store
    
    if domain and domain.lower() != "all":
        results = [e for e in results if e.get("domain", "").lower() == domain.lower()]
        
    if tag:
        tag_clean = tag.strip().lower()
        results = [e for e in results if any(tag_clean in t.lower() for t in e.get("tags", []))]
        
    if q:
        q_clean = q.strip().lower()
        results = [
            e for e in results 
            if q_clean in e.get("title", "").lower() 
            or q_clean in e.get("subtitle", "").lower()
            or any(q_clean in t.lower() for t in e.get("tags", []))
            or any(q_clean in str(v).lower() for v in e.get("properties", {}).values())
        ]
        
    return {
        "status": "success",
        "count": len(results),
        "entities": sorted(results, key=lambda e: e.get("timestamp", 0), reverse=True)
    }

@app.post("/api/v1/entities")
async def create_universal_entity(req: UniversalEntityRequest):
    """Create a new interconnected activity entity with tags and custom properties."""
    new_id = f"ent_{len(universal_entities_store)+101}_{int(time.time())}"
    entity_data = {
        "id": new_id,
        "domain": req.domain.lower(),
        "title": req.title,
        "subtitle": req.subtitle or "",
        "timestamp": req.timestamp or time.time(),
        "tags": [t.strip().lower() for t in req.tags if t.strip()],
        "properties": req.properties,
        "relations": req.relations,
        "image_url": req.image_url or "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=500&q=80"
    }
    universal_entities_store.insert(0, entity_data)
    return {"status": "success", "entity": entity_data}

@app.get("/api/v1/entities/{entity_id}")
async def get_universal_entity_by_id(entity_id: str):
    """Get single entity details and its interconnected relations."""
    for e in universal_entities_store:
        if e.get("id") == entity_id:
            related_items = [r for r in universal_entities_store if r.get("id") in e.get("relations", [])]
            return {"status": "success", "entity": e, "related_entities": related_items}
    raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")

@app.delete("/api/v1/entities/{entity_id}")
async def delete_universal_entity(entity_id: str):
    """Delete an entity."""
    global universal_entities_store
    universal_entities_store = [e for e in universal_entities_store if e.get("id") != entity_id]
    return {"status": "deleted", "id": entity_id}

@app.get("/api/v1/steam/now-playing")
async def get_steam_now_playing():
    """Proxy live Steam game now playing status."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{PLUGIN_STEAM_URL}/telemetry/now-playing")
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning(f"Plugin Steam unreachable: {e}")

    return {"is_playing": False, "game_title": "Offline"}

@app.post("/api/v1/steam/scrobble")
async def scrobble_steam_game(payload: Dict[str, Any] = Body(...)):
    """Proxy live game session scrobble to Steam microservice plugin & Tiered Storage."""
    await storage_engine.set("steam:now_playing", payload, ttl=86400)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(f"{PLUGIN_STEAM_URL}/telemetry/scrobble", json=payload)
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning(f"Plugin Steam unreachable during scrobble: {e}")

    return {"status": "success", "source": "gateway-tiered-storage", "message": "Scrobbled game session to Tiered Storage"}







