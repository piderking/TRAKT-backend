import asyncio
import json
import logging
from typing import Set, Dict, Any
from fastapi.responses import StreamingResponse

logger = logging.getLogger("trakt.events")

class ReactiveEventBus:
    """
    Real-Time Reactive Event Bus for Trakt Database Mutations.
    Broadcasts real-time events (Server-Sent Events) whenever any entity or token
    is created, updated, deleted, or fetched by background fetchers.
    """
    def __init__(self):
        self.subscribers: Set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.add(queue)
        logger.info(f"New client subscribed to Reactive Event Bus. Total subscribers: {len(self.subscribers)}")
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        self.subscribers.discard(queue)
        logger.info(f"Client unsubscribed from Reactive Event Bus. Total subscribers: {len(self.subscribers)}")

    async def publish(self, event_type: str, data: Dict[str, Any]):
        """Publish a reactive database event to all active SSE subscribers."""
        payload = {
            "event": event_type,
            "timestamp": asyncio.get_event_loop().time(),
            "data": data
        }
        json_str = json.dumps(payload)
        dead_queues = set()

        for q in self.subscribers:
            try:
                q.put_nowait(json_str)
            except Exception:
                dead_queues.add(q)

        for dq in dead_queues:
            self.unsubscribe(dq)

event_bus = ReactiveEventBus()

async def event_generator(queue: asyncio.Queue):
    """Generator streaming real-time Server-Sent Events (SSE)."""
    try:
        # Initial connection keep-alive
        yield f"data: {json.dumps({'event': 'CONNECTED', 'message': 'Reactive Event Stream Active'})}\n\n"
        while True:
            msg = await queue.get()
            yield f"data: {msg}\n\n"
    except asyncio.CancelledError:
        pass
