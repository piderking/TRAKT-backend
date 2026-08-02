import pytest
import asyncio
from typing import Dict, Any, Optional
from app.core.storage import TieredStorageEngine


class MockRedis:
    """Mock Redis client implementing async redis.asyncio interface for testing."""
    def __init__(self):
        self.store: Dict[str, str] = {}
        self.ttls: Dict[str, Optional[int]] = {}

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> Optional[str]:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        self.store[key] = value
        self.ttls[key] = ex
        return True

    async def delete(self, key: str) -> bool:
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return True

    async def keys(self, pattern: str = "*") -> list:
        return list(self.store.keys())

    async def close(self) -> None:
        pass


class MockDbConn:
    """Mock AsyncPG database connection."""
    def __init__(self, db_store: Dict[str, Dict[str, Any]]):
        self.db_store = db_store

    async def execute(self, query: str, *args) -> str:
        if "INSERT INTO trakt_cold_storage" in query or "ON CONFLICT" in query:
            if len(args) >= 3:
                key, payload, size_bytes = args[0], args[1], args[2]
                self.db_store[key] = {
                    "key": key,
                    "payload": payload,
                    "size_bytes": size_bytes
                }
        elif "DELETE FROM trakt_cold_storage" in query:
            if args:
                key = args[0]
                self.db_store.pop(key, None)
        return "OK"

    async def fetchrow(self, query: str, *args) -> Optional[Dict[str, Any]]:
        if "SELECT payload FROM trakt_cold_storage WHERE key =" in query:
            if args:
                key = args[0]
                if key in self.db_store:
                    return {"payload": self.db_store[key]["payload"]}
        return None

    async def fetch(self, query: str, *args) -> list:
        if "SELECT key FROM trakt_cold_storage" in query:
            return [{"key": k} for k in self.db_store.keys()]
        return []


class MockDbPoolContext:
    def __init__(self, conn: MockDbConn):
        self.conn = conn

    async def __aenter__(self) -> MockDbConn:
        return self.conn

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


class MockDbPool:
    """Mock AsyncPG Pool."""
    def __init__(self):
        self.db_store: Dict[str, Dict[str, Any]] = {}

    def acquire(self) -> MockDbPoolContext:
        return MockDbPoolContext(MockDbConn(self.db_store))

    async def close(self) -> None:
        pass


@pytest.fixture
def mock_redis():
    return MockRedis()


@pytest.fixture
def mock_db_pool():
    return MockDbPool()


@pytest.fixture
def mock_storage_engine(mock_redis, mock_db_pool):
    """Fixture providing a TieredStorageEngine configured with mock Redis and Postgres."""
    engine = TieredStorageEngine(redis_url="redis://mock:6379", db_url="postgresql://mock:5432/trakt")
    engine.redis = mock_redis
    engine.db_pool = mock_db_pool
    engine.is_connected = True
    return engine
