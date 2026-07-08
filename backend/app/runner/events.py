"""
Per-job event buffer for SSE progress streaming.

JobEventBuffer holds the event backlog for one job and fans published events
out to all active SSE subscribers. subscribe() snapshots the backlog AND
registers the new asyncio.Queue under one lock, guaranteeing no event is lost
between the backlog read and the live queue setup.

Thread-safety contract:
- publish() is called from the background worker THREAD.
- subscribe()/unsubscribe() are called from the event LOOP (GET handler).
- The threading.Lock guards _backlog, _subscribers, and _closed together
  so a concurrent publish+subscribe never misses an event.
"""

import asyncio
import threading
from typing import List, Optional, Tuple

from app.runner.models import ProgressEvent

_TERMINAL_EVENTS = frozenset({"completed", "failed"})


class JobEventBuffer:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._lock = threading.Lock()
        self._backlog: List[ProgressEvent] = []
        self._subscribers: List[asyncio.Queue] = []
        self._closed: bool = False

    def publish(self, event: ProgressEvent) -> None:
        """Append event to backlog and fan out to live subscribers (worker thread)."""
        with self._lock:
            self._backlog.append(event)
            if event.event in _TERMINAL_EVENTS:
                self._closed = True
            queues = list(self._subscribers)

        for q in queues:
            self._loop.call_soon_threadsafe(q.put_nowait, event)

    def subscribe(self) -> Tuple[List[ProgressEvent], Optional[asyncio.Queue], bool]:
        """Snapshot backlog and register a live queue atomically.

        Returns:
            (backlog_snapshot, queue_or_None, closed)
            queue is None when the job is already finished (no live events coming).
        """
        with self._lock:
            backlog = list(self._backlog)
            closed = self._closed
            if closed:
                return backlog, None, True
            q: asyncio.Queue = asyncio.Queue()
            self._subscribers.append(q)
            return backlog, q, False

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove queue from subscribers (client disconnected)."""
        with self._lock:
            try:
                self._subscribers.remove(queue)
            except ValueError:
                pass
