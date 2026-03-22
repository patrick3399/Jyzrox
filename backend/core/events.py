"""Unified event bus — publishes structured events via Redis Pub/Sub."""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """All system event types."""

    # Download
    DOWNLOAD_ENQUEUED = "download.enqueued"
    DOWNLOAD_STARTED = "download.started"
    DOWNLOAD_PROGRESS = "download.progress"
    DOWNLOAD_COMPLETED = "download.completed"
    DOWNLOAD_FAILED = "download.failed"
    DOWNLOAD_CANCELLED = "download.cancelled"
    DOWNLOAD_PAUSED = "download.paused"
    SEMAPHORE_CHANGED = "semaphore.changed"

    # Gallery
    GALLERY_UPDATED = "gallery.updated"
    GALLERY_DELETED = "gallery.deleted"
    GALLERY_RESTORED = "gallery.restored"
    GALLERY_BATCH_UPDATED = "gallery.batch_updated"
    GALLERY_DISCOVERED = "gallery.discovered"
    GALLERY_TAGGED = "gallery.tagged"

    # Import
    IMPORT_COMPLETED = "import.completed"
    IMPORT_FAILED = "import.failed"

    # Subscription
    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_DELETED = "subscription.deleted"
    SUBSCRIPTION_CHECKED = "subscription.checked"
    SUBSCRIPTION_GROUP_UPDATED = "subscription_group.updated"
    SUBSCRIPTION_GROUP_COMPLETED = "subscription_group.completed"

    # Collection
    COLLECTION_UPDATED = "collection.updated"

    # Tags
    TAGS_UPDATED = "tags.updated"

    # Dedup
    DEDUP_SCAN_STARTED = "dedup.scan_started"
    DEDUP_SCAN_COMPLETED = "dedup.scan_completed"
    DEDUP_PAIR_RESOLVED = "dedup.pair_resolved"

    # Thumbnails
    THUMBNAILS_GENERATED = "thumbnails.generated"

    # System maintenance
    TRASH_CLEANED = "trash.cleaned"
    RESCAN_COMPLETED = "rescan.completed"
    RETRY_PROCESSED = "retry.processed"
    EHTAG_SYNC_COMPLETED = "ehtag.sync_completed"
    RECONCILIATION_COMPLETED = "reconciliation.completed"
    SYSTEM_GDL_UPGRADED = "system.gdl_upgraded"
    SYSTEM_WORKER_RECOVERED = "system.worker_recovered"

    # System alerts
    SYSTEM_ALERT = "system.alert"
    SYSTEM_DISK_LOW = "system.disk_low"
    ADAPTIVE_BLOCKED = "adaptive.blocked"

    # System config
    LOG_LEVEL_CHANGED = "system.log_level_changed"


@dataclass
class Event:
    """Structured event payload."""

    event_type: EventType
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    actor_user_id: int | None = None
    resource_type: str | None = None
    resource_id: int | str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "actor_user_id": self.actor_user_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "data": self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class EventBus:
    """Central event bus — publishes to Redis Pub/Sub channels and maintains a recent events list."""

    RECENT_KEY = "events:recent"
    RECENT_MAX = 200

    _trim_counter: int = 0

    async def emit(self, event: Event) -> None:
        """Publish event to Redis channels and store in recent list."""
        try:
            from core.redis_client import get_redis

            r = get_redis()
            payload = event.to_json()
            pipe = r.pipeline(transaction=False)
            pipe.publish(f"events:{event.event_type.value}", payload)
            pipe.publish("events:all", payload)
            pipe.lpush(self.RECENT_KEY, payload)
            # Amortize ltrim: only trim every 50 emits instead of every emit
            self._trim_counter += 1
            if self._trim_counter >= 50:
                pipe.ltrim(self.RECENT_KEY, 0, self.RECENT_MAX - 1)
                self._trim_counter = 0
            await pipe.execute()
        except Exception as exc:
            logger.warning("EventBus.emit failed: %s", exc)

    async def get_recent(self, limit: int = 50) -> list[dict]:
        """Return recent events from Redis list."""
        try:
            from core.redis_client import get_redis

            r = get_redis()
            raw_list = await r.lrange(self.RECENT_KEY, 0, limit - 1)
            events = []
            for raw in raw_list:
                if isinstance(raw, bytes):
                    raw = raw.decode()
                try:
                    events.append(json.loads(raw))
                except json.JSONDecodeError, TypeError:
                    pass
            return events
        except Exception as exc:
            logger.warning("EventBus.get_recent failed: %s", exc)
            return []


# Singleton
event_bus = EventBus()


async def emit(
    event_type: EventType,
    *,
    actor_user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: int | str | None = None,
    **data: Any,
) -> None:
    """Convenience function — build Event and publish."""
    event = Event(
        event_type=event_type,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        data=data,
    )
    await event_bus.emit(event)


async def emit_safe(
    event_type: EventType,
    *,
    actor_user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: int | str | None = None,
    **data: Any,
) -> None:
    """Fire-and-forget emit — swallows all errors so callers are never interrupted."""
    try:
        await emit(
            event_type,
            actor_user_id=actor_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            **data,
        )
    except Exception:
        pass
