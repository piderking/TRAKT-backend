import os
import json
import time
import asyncio
import logging
import httpx
from typing import Dict, Any, List, Optional
from app.core.events import event_bus

logger = logging.getLogger("trakt.plugin_engine")

class DynamicPlugin:
    def __init__(self, plugin_dir: str, manifest: Dict[str, Any]):
        self.plugin_dir = plugin_dir
        self.id = manifest.get("id", os.path.basename(plugin_dir))
        self.name = manifest.get("name", self.id.capitalize())
        self.domain = manifest.get("domain", "custom")
        self.version = manifest.get("version", "1.0.0")
        self.fetch_interval_seconds = manifest.get("fetch_interval_seconds", 30)
        self.schema = manifest.get("schema", {})
        self.tags = manifest.get("tags", [self.id])
        self.fetch_url = manifest.get("fetch_url", f"/api/v1/{self.id}/summary")
        self.enabled = manifest.get("enabled", True)
        self.last_fetch_time: Optional[float] = None
        self.last_fetch_status: str = "initialized"
        self.items_fetched_count: int = 0

class PluginEngine:
    """
    Dynamic Microservice Plugin Engine & Background Fetcher Manager.
    - Scans plugins/ directory for plugin manifests (plugin.json).
    - Automatically discovers schemas and registers background fetchers.
    - Periodically fetches data from microservices/APIs and plugs results into Database Storage.
    """
    def __init__(self, plugins_base_dir: str, storage_engine: Any, universal_store_ref: List[Dict[str, Any]]):
        self.plugins_base_dir = plugins_base_dir
        self.storage_engine = storage_engine
        self.universal_store = universal_store_ref
        self.discovered_plugins: Dict[str, DynamicPlugin] = {}
        self.is_running = False
        self._bg_task: Optional[asyncio.Task] = None

    def scan_and_load_plugins(self) -> Dict[str, Any]:
        """Scan plugins directory and load manifest schemas."""
        if not os.path.exists(self.plugins_base_dir):
            os.makedirs(self.plugins_base_dir, exist_ok=True)
            return {"scanned": 0, "plugins": []}

        count = 0
        for entry in os.listdir(self.plugins_base_dir):
            p_dir = os.path.join(self.plugins_base_dir, entry)
            if os.path.isdir(p_dir):
                manifest_path = os.path.join(p_dir, "plugin.json")
                if not os.path.exists(manifest_path):
                    # Auto-generate manifest schema for discovered directory
                    default_manifest = {
                        "id": entry.lower(),
                        "name": f"{entry.capitalize()} Telemetry Plugin",
                        "domain": entry.lower() if entry.lower() in ["spotify", "steam", "health", "wakatime", "movies"] else "custom",
                        "version": "1.0.0",
                        "fetch_interval_seconds": 30,
                        "schema": {"title": "string", "timestamp": "number", "properties": "object"},
                        "tags": [entry.lower()],
                        "fetch_url": f"/api/v1/{entry.lower()}/summary",
                        "enabled": True
                    }
                    try:
                        with open(manifest_path, "w") as f:
                            json.dump(default_manifest, f, indent=2)
                    except Exception as e:
                        logger.warning(f"Could not auto-write plugin.json to {p_dir}: {e}")
                    manifest_data = default_manifest
                else:
                    try:
                        with open(manifest_path, "r") as f:
                            manifest_data = json.load(f)
                    except Exception as e:
                        logger.error(f"Error reading plugin.json in {p_dir}: {e}")
                        continue

                plugin_obj = DynamicPlugin(p_dir, manifest_data)
                self.discovered_plugins[plugin_obj.id] = plugin_obj
                count += 1

        logger.info(f"Plugin Engine scanned {count} plugin directories from '{self.plugins_base_dir}'.")
        return {"scanned": count, "plugins": [p.id for p in self.discovered_plugins.values()]}

    def register_custom_plugin(self, plugin_id: str, domain: str, name: str, fetch_url: str, schema: Dict[str, Any]) -> DynamicPlugin:
        """Register a new plugin directory and schema dynamically."""
        p_dir = os.path.join(self.plugins_base_dir, plugin_id.lower())
        os.makedirs(p_dir, exist_ok=True)
        manifest_data = {
            "id": plugin_id.lower(),
            "name": name,
            "domain": domain.lower(),
            "version": "1.0.0",
            "fetch_interval_seconds": 30,
            "schema": schema,
            "tags": [plugin_id.lower(), domain.lower()],
            "fetch_url": fetch_url,
            "enabled": True
        }
        with open(os.path.join(p_dir, "plugin.json"), "w") as f:
            json.dump(manifest_data, f, indent=2)

        plugin_obj = DynamicPlugin(p_dir, manifest_data)
        self.discovered_plugins[plugin_obj.id] = plugin_obj
        return plugin_obj

    async def start_background_fetchers(self, base_backend_url: str = "http://127.0.0.1:8000"):
        """Start async background fetcher loop."""
        if self.is_running:
            return
        self.is_running = True
        self._bg_task = asyncio.create_task(self._fetcher_loop(base_backend_url))
        logger.info("Started background fetcher loop for all registered plugins.")

    async def stop_background_fetchers(self):
        """Stop background fetcher loop."""
        self.is_running = False
        if self._bg_task:
            self._bg_task.cancel()
            self._bg_task = None
        logger.info("Stopped background fetchers.")

    async def _fetcher_loop(self, base_backend_url: str):
        """Background loop executing active plugin fetchers periodically."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            while self.is_running:
                try:
                    for p_id, plugin in list(self.discovered_plugins.items()):
                        if not plugin.enabled:
                            continue

                        now = time.time()
                        if plugin.last_fetch_time is None or (now - plugin.last_fetch_time) >= plugin.fetch_interval_seconds:
                            plugin.last_fetch_time = now
                            target_url = plugin.fetch_url
                            if not target_url.startswith("http"):
                                target_url = f"{base_backend_url}{target_url}"

                            try:
                                resp = await client.get(target_url)
                                if resp.status_code == 200:
                                    data = resp.json()
                                    plugin.last_fetch_status = "success"
                                    await self._process_fetched_data(plugin, data)
                                else:
                                    plugin.last_fetch_status = f"http_{resp.status_code}"
                            except Exception as ex:
                                plugin.last_fetch_status = f"error: {str(ex)}"

                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in background fetcher loop: {e}")
                    await asyncio.sleep(5)

    async def _process_fetched_data(self, plugin: DynamicPlugin, data: Dict[str, Any]):
        """Convert fetched payload into database entity and store in persistent storage."""
        # Handle Spotify payload
        if plugin.domain == "music" and "now_playing" in data:
            np = data["now_playing"]
            if np.get("is_playing") and np.get("track_name") and np.get("track_name") != "No Track Playing":
                entity_id = f"ent_music_{hash(np['track_name'] + np.get('artist_name', ''))}"
                if not any(e["id"] == entity_id for e in self.universal_store):
                    new_ent = {
                        "id": entity_id,
                        "domain": "music",
                        "title": np["track_name"],
                        "subtitle": np.get("artist_name", ""),
                        "timestamp": time.time(),
                        "tags": plugin.tags + ["now-playing"],
                        "properties": {
                            "album": np.get("album_name", ""),
                            "bpm": np.get("audio_features", {}).get("bpm", 0),
                            "platform": "Spotify Web API"
                        },
                        "relations": [],
                        "image_url": np.get("album_art_url") or "https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?w=500&q=80"
                    }
                    self.universal_store.insert(0, new_ent)
                    plugin.items_fetched_count += 1
                    await self.storage_engine.set("universal:entities", {"items": self.universal_store})
                    await event_bus.publish("DB_MUTATION", new_ent)

        # Handle Steam payload
        elif plugin.domain == "gaming" and "now_playing" in data:
            np = data["now_playing"]
            if np.get("is_playing") and np.get("game_title") and np.get("game_title") != "Offline / Not in-game":
                entity_id = f"ent_steam_{np.get('app_id', hash(np['game_title']))}"
                if not any(e["id"] == entity_id for e in self.universal_store):
                    new_ent = {
                        "id": entity_id,
                        "domain": "gaming",
                        "title": np["game_title"],
                        "subtitle": f"Steam • {data.get('stats', {}).get('total_hours_played', 0)} hrs total",
                        "timestamp": time.time(),
                        "tags": plugin.tags + ["in-game"],
                        "properties": {
                            "app_id": np.get("app_id", 0),
                            "player_name": np.get("player_name", "muncher"),
                            "location": "Gaming PC Setup"
                        },
                        "relations": [],
                        "image_url": np.get("header_image") or "https://cdn.cloudflare.steamstatic.com/steam/apps/2767030/header.jpg"
                    }
                    self.universal_store.insert(0, new_ent)
                    plugin.items_fetched_count += 1
                    await self.storage_engine.set("universal:entities", {"items": self.universal_store})

        # Handle Health Connect payload
        elif plugin.domain == "health" and "summary" in data:
            s = data["summary"]
            if s.get("heart_rate_bpm") or s.get("step_count_today"):
                entity_id = f"ent_health_{int(time.time() // 300)}"
                if not any(e["id"] == entity_id for e in self.universal_store):
                    new_ent = {
                        "id": entity_id,
                        "domain": "health",
                        "title": "Android Health Connect Biometrics",
                        "subtitle": "Pixel 8 Pro Daemon",
                        "timestamp": time.time(),
                        "tags": plugin.tags + ["vitals"],
                        "properties": {
                            "steps": s.get("step_count_today", 0),
                            "heart_rate_bpm": s.get("heart_rate_bpm", 72),
                            "sleep_hours": s.get("sleep_duration_hours", 7.5),
                            "spo2": s.get("spo2_percentage", 99.0)
                        },
                        "relations": [],
                        "image_url": "https://images.unsplash.com/photo-1505751172876-fa1923c5c528?w=500&q=80"
                    }
                    self.universal_store.insert(0, new_ent)
                    plugin.items_fetched_count += 1
                    await self.storage_engine.set("universal:entities", {"items": self.universal_store})

    def get_plugins_status(self) -> List[Dict[str, Any]]:
        """Return status list for all discovered plugins & fetchers."""
        return [
            {
                "id": p.id,
                "name": p.name,
                "domain": p.domain,
                "version": p.version,
                "enabled": p.enabled,
                "fetch_interval_seconds": p.fetch_interval_seconds,
                "fetch_url": p.fetch_url,
                "last_fetch_time": p.last_fetch_time,
                "last_fetch_status": p.last_fetch_status,
                "items_fetched_count": p.items_fetched_count,
                "schema": p.schema,
                "tags": p.tags
            }
            for p in self.discovered_plugins.values()
        ]
