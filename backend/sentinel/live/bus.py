"""In-process pub/sub for live events. Publishers are ordinary threads (webhook handler,
simulator); subscribers are asyncio tasks (SSE connections). One bounded queue per subscriber,
scoped per business: a subscriber only ever receives its own business's events. A slow consumer
drops events (counted) instead of blocking the scorer."""
import asyncio
import threading
from collections import defaultdict


class Subscription:
    def __init__(self, bus: "EventBus", business_id: str, loop: asyncio.AbstractEventLoop, maxsize: int):
        self._bus, self.business_id, self.loop = bus, business_id, loop
        self.queue: asyncio.Queue = asyncio.Queue(maxsize)

    def _put(self, event: dict) -> None:  # always runs on the subscriber's loop
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self._bus._count_drop()

    async def get(self) -> dict:
        return await self.queue.get()

    def close(self) -> None:
        self._bus._remove(self)


class EventBus:
    def __init__(self, maxsize: int = 1000):
        self._maxsize = maxsize
        self._subs: dict[str, set[Subscription]] = defaultdict(set)
        self._lock = threading.Lock()
        self.dropped = 0

    def subscribe(self, business_id: str) -> Subscription:
        """Call from inside a running event loop (the SSE handler)."""
        sub = Subscription(self, business_id, asyncio.get_running_loop(), self._maxsize)
        with self._lock:
            self._subs[business_id].add(sub)
        return sub

    def publish(self, business_id: str, event: dict) -> None:
        with self._lock:
            subs = list(self._subs.get(business_id, ()))
        for sub in subs:
            try:
                sub.loop.call_soon_threadsafe(sub._put, event)
            except RuntimeError:  # the subscriber's loop is gone: forget it
                self._remove(sub)

    def subscriber_count(self, business_id: str) -> int:
        with self._lock:
            return len(self._subs.get(business_id, ()))

    def _remove(self, sub: Subscription) -> None:
        with self._lock:
            self._subs[sub.business_id].discard(sub)

    def _count_drop(self) -> None:
        with self._lock:
            self.dropped += 1
