"""Regression coverage for Redis control-plane memory safety (HR-001)."""

import re
from pathlib import Path
from unittest.mock import AsyncMock


async def test_sample_redis_memory_reports_policy_pressure_and_evictions():
    from worker.redis_memory import sample_redis_memory

    redis = AsyncMock()
    redis.info.side_effect = [
        {"used_memory": 85, "maxmemory": 100, "maxmemory_policy": "noeviction"},
        {"evicted_keys": 0},
    ]

    assert await sample_redis_memory(redis) == {
        "used_bytes": 85,
        "limit_bytes": 100,
        "pct": 85.0,
        "policy": "noeviction",
        "evicted_keys": 0,
    }


async def test_memory_monitor_alerts_for_redis_before_maxmemory(monkeypatch):
    import worker
    from core import events

    monkeypatch.setattr("worker.memory.read_container_memory", lambda: None)
    monkeypatch.setattr(
        "worker.redis_memory.sample_redis_memory",
        AsyncMock(
            return_value={
                "used_bytes": 90,
                "limit_bytes": 100,
                "pct": 90.0,
                "policy": "noeviction",
                "evicted_keys": 0,
            }
        ),
    )
    emit = AsyncMock()
    monkeypatch.setattr(events, "emit_safe", emit)

    result = await worker.memory_monitor_job({"redis": AsyncMock()})

    assert result == {"status": "high", "redis_status": "high"}
    emit.assert_awaited_once()
    assert emit.await_args.args[0] == events.EventType.SYSTEM_MEMORY_HIGH
    assert emit.await_args.kwargs["resource_type"] == "redis"


async def test_memory_monitor_alerts_when_runtime_policy_drifts(monkeypatch):
    import worker
    from core import events

    monkeypatch.setattr("worker.memory.read_container_memory", lambda: None)
    monkeypatch.setattr(
        "worker.redis_memory.sample_redis_memory",
        AsyncMock(
            return_value={
                "used_bytes": 10,
                "limit_bytes": 100,
                "pct": 10.0,
                "policy": "allkeys-lru",
                "evicted_keys": 4,
            }
        ),
    )
    emit = AsyncMock()
    monkeypatch.setattr(events, "emit_safe", emit)

    result = await worker.memory_monitor_job({"redis": AsyncMock()})

    assert result == {"status": "high", "redis_status": "unsafe_policy"}
    assert emit.await_args.kwargs["maxmemory_policy"] == "allkeys-lru"
    assert emit.await_args.kwargs["evicted_keys"] == 4


async def test_memory_monitor_alerts_when_maxmemory_is_disabled(monkeypatch):
    import worker
    from core import events

    monkeypatch.setattr("worker.memory.read_container_memory", lambda: None)
    monkeypatch.setattr(
        "worker.redis_memory.sample_redis_memory",
        AsyncMock(
            return_value={
                "used_bytes": 10,
                "limit_bytes": 0,
                "pct": 0.0,
                "policy": "noeviction",
                "evicted_keys": 0,
            }
        ),
    )
    emit = AsyncMock()
    monkeypatch.setattr(events, "emit_safe", emit)

    result = await worker.memory_monitor_job({"redis": AsyncMock()})

    assert result == {"status": "high", "redis_status": "unbounded"}
    emit.assert_awaited_once()


def test_compose_redis_uses_non_evicting_policy():
    compose = (Path(__file__).parents[2] / "docker-compose.yml").read_text()
    match = re.search(
        r"(?m)^  redis:\n    image: redis:8-alpine\n    command: (?P<command>.+)$",
        compose,
    )

    assert match is not None
    assert "--maxmemory-policy noeviction" in match.group("command")
    assert "--maxmemory-policy allkeys-lru" not in match.group("command")
