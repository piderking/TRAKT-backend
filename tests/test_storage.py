import pytest
import pytest_asyncio
from app.core.storage import TieredStorageEngine

@pytest.mark.asyncio
async def test_tiered_storage_memory_fallback():
    engine = TieredStorageEngine(redis_url="redis://invalid-host:6379", db_url="postgresql://invalid:5432/test")
    await engine.connect()
    
    # 1. Test basic set & get (fallback mode)
    key = "user:123:history"
    data = {"movie": "Inception", "rating": 9.5}
    
    success = await engine.set(key, data)
    assert success is True
    
    retrieved = await engine.get(key)
    assert retrieved == data
    assert engine.stats["fallback_hits"] >= 1
    
    # 2. Test big object flag
    big_key = "user:123:big_payload"
    big_data = {"items": ["item_" + str(i) for i in range(1000)]}
    
    await engine.set(big_key, big_data, is_big_object=True)
    big_retrieved = await engine.get(big_key)
    assert big_retrieved == big_data
    
    # 3. Test list keys and delete
    keys = await engine.list_keys()
    assert key in keys
    assert big_key in keys
    
    await engine.delete(key)
    assert await engine.get(key) is None
    
    await engine.disconnect()
