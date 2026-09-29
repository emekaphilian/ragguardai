import asyncio
from datetime import datetime, timedelta, timezone

from ragguard.events.bus import InMemoryRecoveryEventBus
from ragguard.events.recovery_events import RecoveryEvent
from ragguard.observability.recovery_audit import RecoveryEventType


def test_event_bus_publishes_to_async_subscribers():
    async def scenario():
        bus = InMemoryRecoveryEventBus()
        stream = bus.subscribe()
        pending_event = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        event = RecoveryEvent.create(
            "recovery-1",
            RecoveryEventType.REPAIR_STARTED,
            attempt=1,
            strategy="RERANK",
        )

        await bus.publish(event)
        assert await pending_event == event
        assert bus.recent() == (event,)
        await stream.aclose()

    asyncio.run(scenario())


def test_event_bus_discards_expired_events_from_recent_buffer():
    async def scenario():
        bus = InMemoryRecoveryEventBus(event_retention_days=30)
        expired = RecoveryEvent.create(
            "old-recovery",
            RecoveryEventType.ESCALATED,
        )
        object.__setattr__(
            expired,
            "timestamp",
            datetime.now(timezone.utc) - timedelta(days=31),
        )

        await bus.publish(expired)

        assert bus.recent() == ()

    asyncio.run(scenario())
