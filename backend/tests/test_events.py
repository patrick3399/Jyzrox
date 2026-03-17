"""
Tests for core.events — EventBus, Event, EventType, and the emit() convenience function.

Covers:
- EventType is a str Enum
- Event.to_dict() shape
- Event.to_json() produces valid JSON
- Event timestamp is auto-generated as ISO8601
- EventBus.emit() publishes to correct Redis channels and stores in recent list
- EventBus.emit() swallows Redis errors
- EventBus.get_recent() returns parsed events
- EventBus.get_recent() returns [] on error
- emit() convenience function builds and publishes correct Event
- emit() passes **kwargs as data dict
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.events import Event, EventBus, EventType, emit, event_bus


# ---------------------------------------------------------------------------
# EventType
# ---------------------------------------------------------------------------


def test_event_type_is_string_enum():
    """EventType values must be plain strings (str Enum)."""
    assert isinstance(EventType.DOWNLOAD_COMPLETED, str)
    assert EventType.DOWNLOAD_COMPLETED == "download.completed"
    assert EventType.SUBSCRIPTION_CHECKED == "subscription.checked"
    assert EventType.GALLERY_UPDATED == "gallery.updated"


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------


def test_event_to_dict_contains_all_fields():
    """Event.to_dict() must return a dict with all expected keys and correct values."""
    ev = Event(
        event_type=EventType.GALLERY_UPDATED,
        actor_user_id=42,
        resource_type="gallery",
        resource_id=7,
        data={"title": "test"},
    )
    d = ev.to_dict()
    assert d["event_type"] == "gallery.updated"
    assert d["actor_user_id"] == 42
    assert d["resource_type"] == "gallery"
    assert d["resource_id"] == 7
    assert d["data"] == {"title": "test"}
    assert "timestamp" in d


def test_event_to_json_is_valid_json():
    """Event.to_json() must produce parseable JSON with correct event_type."""
    ev = Event(event_type=EventType.DOWNLOAD_FAILED, data={"reason": "timeout"})
    raw = ev.to_json()
    parsed = json.loads(raw)
    assert parsed["event_type"] == "download.failed"
    assert parsed["data"]["reason"] == "timeout"


def test_event_timestamp_auto_generated():
    """Event.timestamp must be automatically populated as an ISO8601 string."""
    ev = Event(event_type=EventType.SYSTEM_ALERT)
    assert ev.timestamp is not None
    assert isinstance(ev.timestamp, str)
    # Basic ISO8601 check: must contain date/time separator
    assert "T" in ev.timestamp
    # Must include UTC offset marker
    assert "+" in ev.timestamp or ev.timestamp.endswith("Z") or "UTC" in ev.timestamp or ev.timestamp.endswith("+00:00")


# ---------------------------------------------------------------------------
# Helpers to build a mock Redis with pipeline support
# ---------------------------------------------------------------------------


def _make_mock_redis():
    mock_redis = AsyncMock()
    mock_pipe = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)
    mock_pipe.publish = MagicMock(return_value=mock_pipe)
    mock_pipe.lpush = MagicMock(return_value=mock_pipe)
    mock_pipe.ltrim = MagicMock(return_value=mock_pipe)
    mock_pipe.execute = AsyncMock(return_value=[1, 1, 1, True])
    return mock_redis, mock_pipe


# ---------------------------------------------------------------------------
# EventBus.emit()
# ---------------------------------------------------------------------------


async def test_event_bus_emit_publishes_to_channels():
    """EventBus.emit() must publish to events:{type} and events:all channels."""
    mock_redis, mock_pipe = _make_mock_redis()

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        bus = EventBus()
        ev = Event(event_type=EventType.DOWNLOAD_COMPLETED, resource_id="job-1")
        await bus.emit(ev)

    # pipeline() must be called with transaction=False
    mock_redis.pipeline.assert_called_once_with(transaction=False)

    # Collect all publish calls (they return mock_pipe for chaining)
    publish_calls = mock_pipe.publish.call_args_list
    channels = [call.args[0] for call in publish_calls]
    assert "events:download.completed" in channels
    assert "events:all" in channels


async def test_event_bus_emit_stores_in_recent_list():
    """EventBus.emit() must call lpush to maintain the recent events list."""
    mock_redis, mock_pipe = _make_mock_redis()

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        bus = EventBus()
        ev = Event(event_type=EventType.GALLERY_TAGGED)
        await bus.emit(ev)

    mock_pipe.lpush.assert_called_once()
    lpush_args = mock_pipe.lpush.call_args.args
    assert lpush_args[0] == EventBus.RECENT_KEY
    payload = json.loads(lpush_args[1])
    assert payload["event_type"] == "gallery.tagged"
    # ltrim is amortized — not called on every emit, only every 50th
    assert mock_pipe.ltrim.call_count == 0


async def test_event_bus_emit_swallows_redis_errors():
    """EventBus.emit() must not raise when Redis pipeline raises an exception."""
    mock_redis = AsyncMock()
    mock_redis.pipeline = MagicMock(side_effect=ConnectionError("Redis down"))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        bus = EventBus()
        ev = Event(event_type=EventType.SYSTEM_ALERT)
        # Must not raise
        await bus.emit(ev)


# ---------------------------------------------------------------------------
# EventBus.get_recent()
# ---------------------------------------------------------------------------


async def test_event_bus_get_recent_returns_parsed_events():
    """EventBus.get_recent() must parse JSON strings from lrange and return list of dicts."""
    ev1 = Event(event_type=EventType.DOWNLOAD_STARTED, resource_id="job-a")
    ev2 = Event(event_type=EventType.IMPORT_COMPLETED)

    # Simulate bytes as returned by redis-py
    raw1 = ev1.to_json().encode()
    raw2 = ev2.to_json().encode()

    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[raw1, raw2])

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        bus = EventBus()
        result = await bus.get_recent(limit=10)

    assert len(result) == 2
    assert result[0]["event_type"] == "download.started"
    assert result[1]["event_type"] == "import.completed"
    mock_redis.lrange.assert_awaited_once_with(EventBus.RECENT_KEY, 0, 9)


async def test_event_bus_get_recent_returns_empty_on_error():
    """EventBus.get_recent() must return [] when Redis raises an exception."""
    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(side_effect=ConnectionError("Redis down"))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        bus = EventBus()
        result = await bus.get_recent()

    assert result == []


async def test_event_bus_get_recent_skips_invalid_json():
    """EventBus.get_recent() must silently skip entries that are not valid JSON."""
    valid = Event(event_type=EventType.TRASH_CLEANED).to_json().encode()
    invalid = b"not-json-at-all"

    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[valid, invalid])

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        bus = EventBus()
        result = await bus.get_recent()

    assert len(result) == 1
    assert result[0]["event_type"] == "trash.cleaned"


# ---------------------------------------------------------------------------
# emit() convenience function
# ---------------------------------------------------------------------------


async def test_emit_convenience_builds_and_publishes_event():
    """emit() must create an Event with the correct type and call event_bus.emit()."""
    with patch.object(event_bus, "emit", new_callable=AsyncMock) as mock_emit:
        await emit(
            EventType.GALLERY_DELETED,
            actor_user_id=5,
            resource_type="gallery",
            resource_id=99,
        )

    mock_emit.assert_awaited_once()
    published: Event = mock_emit.call_args.args[0]
    assert isinstance(published, Event)
    assert published.event_type == EventType.GALLERY_DELETED
    assert published.actor_user_id == 5
    assert published.resource_type == "gallery"
    assert published.resource_id == 99


async def test_emit_passes_kwargs_as_data_dict():
    """emit() must capture all extra keyword arguments into Event.data."""
    with patch.object(event_bus, "emit", new_callable=AsyncMock) as mock_emit:
        await emit(
            EventType.DOWNLOAD_PROGRESS,
            resource_id="job-x",
            percent=75,
            current=75,
            total=100,
        )

    mock_emit.assert_awaited_once()
    published: Event = mock_emit.call_args.args[0]
    assert published.data["percent"] == 75
    assert published.data["current"] == 75
    assert published.data["total"] == 100


# ---------------------------------------------------------------------------
# emit_safe() convenience function
# ---------------------------------------------------------------------------


async def test_emit_safe_calls_emit_successfully():
    """emit_safe() delegates to emit() and completes without error."""
    from core.events import emit_safe

    with patch("core.events.emit", new_callable=AsyncMock) as mock_emit:
        await emit_safe(
            EventType.GALLERY_UPDATED,
            actor_user_id=3,
            resource_type="gallery",
            resource_id=7,
        )

    mock_emit.assert_awaited_once()
    call_kwargs = mock_emit.call_args
    assert call_kwargs.args[0] == EventType.GALLERY_UPDATED
    assert call_kwargs.kwargs["actor_user_id"] == 3
    assert call_kwargs.kwargs["resource_type"] == "gallery"
    assert call_kwargs.kwargs["resource_id"] == 7


async def test_emit_safe_swallows_exceptions():
    """emit_safe() catches exceptions from emit() and does not re-raise."""
    from core.events import emit_safe

    with patch("core.events.emit", new_callable=AsyncMock) as mock_emit:
        mock_emit.side_effect = RuntimeError("Redis connection refused")
        # Must not raise — emit_safe swallows all errors
        await emit_safe(EventType.SYSTEM_ALERT)

    mock_emit.assert_awaited_once()


async def test_emit_safe_passes_all_kwargs():
    """emit_safe() forwards all keyword arguments to emit()."""
    from core.events import emit_safe

    with patch("core.events.emit", new_callable=AsyncMock) as mock_emit:
        await emit_safe(
            EventType.DOWNLOAD_PROGRESS,
            actor_user_id=5,
            resource_id="job-abc",
            percent=50,
            current=50,
            total=100,
        )

    mock_emit.assert_awaited_once()
    call_kwargs = mock_emit.call_args
    assert call_kwargs.args[0] == EventType.DOWNLOAD_PROGRESS
    assert call_kwargs.kwargs["actor_user_id"] == 5
    assert call_kwargs.kwargs["resource_id"] == "job-abc"
    assert call_kwargs.kwargs["percent"] == 50
    assert call_kwargs.kwargs["total"] == 100
