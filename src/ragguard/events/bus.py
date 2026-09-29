from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Protocol

from ragguard.events.recovery_events import RecoveryEvent


class RecoveryEventBus(Protocol):
    async def publish(self, event: RecoveryEvent) -> None:
        ...

    async def subscribe(self) -> AsyncIterator[RecoveryEvent]:
        ...


class InMemoryRecoveryEventBus:
    """Async in-process fan-out bus with a bounded recent-event buffer."""

    def __init__(
        self,
        *,
        event_retention_days: int | None = None,
        max_buffer_size: int = 10_000,
    ) -> None:
        if event_retention_days is None:
            from ragguard.config import load_settings

            event_retention_days = load_settings().event_retention_days
        if event_retention_days < 1:
            raise ValueError("event_retention_days must be greater than zero")
        if max_buffer_size < 1:
            raise ValueError("max_buffer_size must be greater than zero")
        self.event_retention_days = event_retention_days
        self.max_buffer_size = max_buffer_size
        self._recent: deque[RecoveryEvent] = deque(maxlen=max_buffer_size)
        self._subscribers: dict[
            asyncio.Queue[RecoveryEvent],
            asyncio.AbstractEventLoop,
        ] = {}
        self._lock = Lock()

    async def publish(self, event: RecoveryEvent) -> None:
        self.publish_from_sync(event)

    def publish_from_sync(self, event: RecoveryEvent) -> None:
        self._discard_expired()
        with self._lock:
            self._recent.append(event)
            subscribers = tuple(self._subscribers.items())
        for subscriber, loop in subscribers:
            if not loop.is_closed():
                loop.call_soon_threadsafe(self._enqueue, subscriber, event)

    async def subscribe(self) -> AsyncIterator[RecoveryEvent]:
        queue: asyncio.Queue[RecoveryEvent] = asyncio.Queue(maxsize=self.max_buffer_size)
        loop = asyncio.get_running_loop()
        with self._lock:
            self._subscribers[queue] = loop
        try:
            while True:
                yield await queue.get()
        finally:
            with self._lock:
                self._subscribers.pop(queue, None)

    def recent(self) -> tuple[RecoveryEvent, ...]:
        self._discard_expired()
        with self._lock:
            return tuple(self._recent)

    @staticmethod
    def _enqueue(queue: asyncio.Queue[RecoveryEvent], event: RecoveryEvent) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)

    def _discard_expired(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.event_retention_days)
        with self._lock:
            while self._recent and self._recent[0].timestamp < cutoff:
                self._recent.popleft()
