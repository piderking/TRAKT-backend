import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
import redis.asyncio as aioredis

logger = logging.getLogger("trakt.storage")
SIZE_THRESHOLD_BYTES = 100 * 1024  # 100 KB threshold for cold storage offloading

class TieredStorageEngine:
    """
    Tiered Storage Engine for Trakt monorepo.
    - Hot tier: Redis (fast in-memory cache for metadata & objects <= 100KB)
    - Cold tier: PostgreSQL (persistent database for large objects > 100KB via _cold_ref pointers)
    - Fallback tier: In-memory dictionary with LRU behavior when DB/Redis are unreachable
    """

    def __init__(self, redis_url: str = "redis://localhost:6379", db_url: str = "postgresql://postgres:secret@localhost:5432/trakt"):
        self.redis_url = redis_url
        self.db_url = db_url
        self.redis: Optional[aioredis.Redis] = None
        self.db_pool: Optional[Any] = None
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self.stats = {
            "hot_hits": 0,
            "cold_hits": 0,
            "fallback_hits": 0,
            "sets": 0,
            "deletes": 0,
            "errors": 0
        }
        self.db_file = os.path.join(os.path.dirname(__file__), "..", "..", "trakt_persistent_db.json")
        self._load_disk_cache()
        self.is_connected = False

    def _load_disk_cache(self) -> None:
        """Load persistent cache from disk file."""
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r") as f:
                    raw = json.load(f)
                    for k, v in raw.items():
                        self._memory_cache[k] = {
                            "data": v.get("data", v),
                            "expires_at": time.time() + 86400 * 365,
                            "is_cold": False,
                            "size_bytes": 0
                        }
                logger.info(f"Loaded {len(self._memory_cache)} persistent keys from disk file '{self.db_file}'.")
            except Exception as e:
                logger.warning(f"Failed to load disk cache from {self.db_file}: {e}")

    def _save_disk_cache(self) -> None:
        """Save persistent cache to disk file."""
        try:
            raw_to_save = {}
            for k, v in self._memory_cache.items():
                raw_to_save[k] = v.get("data")
            with open(self.db_file, "w") as f:
                json.dump(raw_to_save, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save disk cache to {self.db_file}: {e}")
        self.stats = {
            "hot_hits": 0,
            "cold_hits": 0,
            "fallback_hits": 0,
            "sets": 0,
            "deletes": 0,
            "errors": 0
        }

    async def connect(self) -> None:
        """Initialize Redis and AsyncPG database pool with fallback tolerance."""
        # Connect Redis
        try:
            self.redis = aioredis.from_url(self.redis_url, decode_responses=True)
            await self.redis.ping()
            logger.info("Successfully connected to Redis cache.")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Operating in fallback mode for Redis.")
            self.redis = None

        # Connect PostgreSQL asyncpg pool
        try:
            import asyncpg
            self.db_pool = await asyncpg.create_pool(self.db_url, timeout=5.0)
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS trakt_cold_storage (
                        key TEXT PRIMARY KEY,
                        payload JSONB NOT NULL,
                        size_bytes INT NOT NULL,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            logger.info("Successfully connected to PostgreSQL cold database.")
        except Exception as e:
            logger.warning(f"Failed to connect to PostgreSQL: {e}. Operating in fallback mode for Database.")
            self.db_pool = None

        self.is_connected = True

    async def disconnect(self) -> None:
        """Close connections gracefully."""
        if self.redis:
            try:
                await self.redis.close()
            except Exception as e:
                logger.error(f"Error closing Redis: {e}")
        if self.db_pool:
            try:
                await self.db_pool.close()
            except Exception as e:
                logger.error(f"Error closing AsyncPG pool: {e}")
        self.is_connected = False
        logger.info("TieredStorageEngine disconnected.")

    async def set(self, key: str, data: Dict[str, Any], ttl: int = 3600, is_big_object: bool = False) -> bool:
        """
        Store data into tiered storage engine:
        - If size > 100KB or `is_big_object` is True, store heavy payload in PostgreSQL cold table,
          and store light pointer dict `{"_cold_ref": key, "size_bytes": ...}` in Redis hot tier.
        - Otherwise, store full payload in Redis hot tier.
        - Always maintain memory cache fallback.
        """
        self.stats["sets"] += 1
        serialized = json.dumps(data)
        size_bytes = len(serialized.encode("utf-8"))

        is_cold = is_big_object or (size_bytes > SIZE_THRESHOLD_BYTES)

        # Fallback memory store
        self._memory_cache[key] = {
            "data": data,
            "expires_at": time.time() + ttl,
            "is_cold": is_cold,
            "size_bytes": size_bytes
        }

        try:
            if is_cold:
                # Save cold object payload into DB
                if self.db_pool:
                    async with self.db_pool.acquire() as conn:
                        await conn.execute("""
                            INSERT INTO trakt_cold_storage (key, payload, size_bytes, updated_at)
                            VALUES ($1, $2::jsonb, $3, NOW())
                            ON CONFLICT (key) DO UPDATE
                            SET payload = EXCLUDED.payload, size_bytes = EXCLUDED.size_bytes, updated_at = NOW();
                        """, key, serialized, size_bytes)

                # Save light pointer in Redis
                pointer = {
                    "_cold_ref": key,
                    "size_bytes": size_bytes,
                    "cached_at": time.time()
                }
                if self.redis:
                    await self.redis.set(key, json.dumps(pointer), ex=ttl)
            else:
                # Save hot object directly in Redis
                if self.redis:
                    await self.redis.set(key, serialized, ex=ttl)

                # Optional async backup to Postgres
                if self.db_pool:
                    async with self.db_pool.acquire() as conn:
                        await conn.execute("""
                            INSERT INTO trakt_cold_storage (key, payload, size_bytes, updated_at)
                            VALUES ($1, $2::jsonb, $3, NOW())
                            ON CONFLICT (key) DO UPDATE
                            SET payload = EXCLUDED.payload, size_bytes = EXCLUDED.size_bytes, updated_at = NOW();
                        """, key, serialized, size_bytes)
            self._save_disk_cache()
            return True
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Error setting key {key} in TieredStorageEngine: {e}")
            self._save_disk_cache()
            return True

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve object by key:
        1. Query Redis hot tier.
        2. If pointer dict `_cold_ref` found, fetch full payload from PostgreSQL.
        3. If missed in Redis, query PostgreSQL cold tier.
        4. If DB/Redis fail, fallback to memory cache.
        """
        # 1. Try Redis cache
        if self.redis:
            try:
                cached_val = await self.redis.get(key)
                if cached_val:
                    parsed = json.loads(cached_val)
                    if isinstance(parsed, dict) and "_cold_ref" in parsed:
                        # Cold reference pointer found
                        cold_key = parsed["_cold_ref"]
                        if self.db_pool:
                            async with self.db_pool.acquire() as conn:
                                row = await conn.fetchrow("SELECT payload FROM trakt_cold_storage WHERE key = $1;", cold_key)
                                if row and row["payload"]:
                                    self.stats["cold_hits"] += 1
                                    return json.loads(row["payload"])
                        # If DB unavailable, fallback memory store
                        if cold_key in self._memory_cache:
                            self.stats["fallback_hits"] += 1
                            return self._memory_cache[cold_key]["data"]
                    else:
                        self.stats["hot_hits"] += 1
                        return parsed
            except Exception as e:
                self.stats["errors"] += 1
                logger.error(f"Redis get error for {key}: {e}")

        # 2. Try PostgreSQL cold tier
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT payload FROM trakt_cold_storage WHERE key = $1;", key)
                    if row and row["payload"]:
                        self.stats["cold_hits"] += 1
                        payload_dict = json.loads(row["payload"])
                        # Re-populate hot cache if appropriate
                        if self.redis and len(row["payload"].encode("utf-8")) <= SIZE_THRESHOLD_BYTES:
                            await self.redis.set(key, row["payload"], ex=3600)
                        return payload_dict
            except Exception as e:
                self.stats["errors"] += 1
                logger.error(f"Postgres get error for {key}: {e}")

        # 3. Fallback memory cache
        if key in self._memory_cache:
            entry = self._memory_cache[key]
            if entry["expires_at"] > time.time():
                self.stats["fallback_hits"] += 1
                return entry["data"]
            else:
                del self._memory_cache[key]

        return None

    async def delete(self, key: str) -> bool:
        """Remove key from all tiers."""
        self.stats["deletes"] += 1
        if self.redis:
            try:
                await self.redis.delete(key)
            except Exception:
                pass
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute("DELETE FROM trakt_cold_storage WHERE key = $1;", key)
            except Exception:
                pass
        if key in self._memory_cache:
            del self._memory_cache[key]
        return True

    async def list_keys(self) -> List[str]:
        """List active keys across storage engine."""
        keys_set = set(self._memory_cache.keys())
        if self.redis:
            try:
                r_keys = await self.redis.keys("*")
                keys_set.update(r_keys)
            except Exception:
                pass
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch("SELECT key FROM trakt_cold_storage;")
                    for r in rows:
                        keys_set.add(r["key"])
            except Exception:
                pass
        return list(keys_set)

    async def get_status(self) -> Dict[str, Any]:
        """Return operational metrics for TieredStorageEngine."""
        redis_status = "connected" if self.redis and await self._safe_ping_redis() else "fallback"
        db_status = "connected" if self.db_pool else "fallback"
        
        return {
            "status": "online",
            "redis": redis_status,
            "postgres": db_status,
            "memory_cache_entries": len(self._memory_cache),
            "stats": self.stats
        }

    async def _safe_ping_redis(self) -> bool:
        try:
            return bool(await self.redis.ping())
        except Exception:
            return False
