"""sse_broker.py - In-memory pub/sub for Server-Sent Events.

Per-job subscriber queues. SSE clients subscribe to a job_id, and the
pipeline runner publishes events to all subscribers of that job.
"""
import asyncio
from collections import defaultdict
from typing import AsyncIterator, Dict, List


class SSEBroker:
    def __init__(self):
        self._subscribers: Dict[str, List[asyncio.Queue]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def subscribe(self, job_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers[job_id].append(q)
        return q

    async def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        async with self._lock:
            if q in self._subscribers[job_id]:
                self._subscribers[job_id].remove(q)

    def publish(self, job_id: str, message: dict) -> None:
        """Push a message to all subscribers of this job (sync, fire-and-forget)."""
        # asyncio.Queue is not thread-safe; bridge to the loop.
        for q in list(self._subscribers.get(job_id, [])):
            try:
                q.put_nowait(message)
            except Exception:
                pass

    def close(self, job_id: str) -> None:
        """Signal all subscribers to disconnect (used on job end)."""
        for q in list(self._subscribers.get(job_id, [])):
            try:
                q.put_nowait(None)
            except Exception:
                pass


broker = SSEBroker()
