"""Tests for GET /api/system/events endpoint."""

import json
from unittest.mock import AsyncMock, patch

import pytest


async def test_get_recent_events_returns_events(client, mock_redis):
    """GET /api/system/events returns recent events from EventBus."""
    sample_events = [
        json.dumps({"event_type": "download.completed", "timestamp": "2024-01-01T00:00:00", "actor_user_id": 1, "resource_type": "download_job", "resource_id": "abc", "data": {}}).encode(),
        json.dumps({"event_type": "gallery.deleted", "timestamp": "2024-01-01T00:01:00", "actor_user_id": 1, "resource_type": "gallery", "resource_id": 42, "data": {}}).encode(),
    ]
    mock_redis.lrange = AsyncMock(return_value=sample_events)

    resp = await client.get("/api/system/events")
    assert resp.status_code == 200
    body = resp.json()
    assert "events" in body
    assert "count" in body
    assert body["count"] == 2
    assert body["events"][0]["event_type"] == "download.completed"
    assert body["events"][1]["event_type"] == "gallery.deleted"


async def test_get_recent_events_respects_limit_param(client, mock_redis):
    """GET /api/system/events?limit=5 passes limit to EventBus."""
    mock_redis.lrange = AsyncMock(return_value=[])

    resp = await client.get("/api/system/events?limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["events"] == []
    # Verify lrange was called with limit-1 as end index
    mock_redis.lrange.assert_called_once()
    call_args = mock_redis.lrange.call_args[0]
    assert call_args[2] == 4  # limit - 1 = 4


async def test_get_recent_events_returns_empty_when_no_events(client, mock_redis):
    """GET /api/system/events returns empty list when no events exist."""
    mock_redis.lrange = AsyncMock(return_value=[])

    resp = await client.get("/api/system/events")
    assert resp.status_code == 200
    body = resp.json()
    assert body["events"] == []
    assert body["count"] == 0


async def test_get_recent_events_validates_limit_bounds(client):
    """GET /api/system/events rejects limit outside 1-200 range."""
    resp = await client.get("/api/system/events?limit=0")
    assert resp.status_code == 422

    resp = await client.get("/api/system/events?limit=201")
    assert resp.status_code == 422


async def test_get_recent_events_requires_admin_role(make_client):
    """GET /api/system/events returns 403 for non-admin users."""
    async with make_client(user_id=2, role="member") as ac:
        resp = await ac.get("/api/system/events")
    assert resp.status_code == 403


async def test_get_recent_events_handles_redis_error_gracefully(client, mock_redis):
    """GET /api/system/events returns empty on Redis error."""
    mock_redis.lrange = AsyncMock(side_effect=ConnectionError("Redis down"))

    resp = await client.get("/api/system/events")
    assert resp.status_code == 200
    body = resp.json()
    assert body["events"] == []
    assert body["count"] == 0
