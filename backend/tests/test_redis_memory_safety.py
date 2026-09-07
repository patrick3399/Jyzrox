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


def _redis_service_block() -> str:
    """Return the redis service body from docker-compose.yml.

    Matching keys individually rather than as adjacent lines keeps the assertions
    working when comments or extra keys are added inside the service.
    """
    compose = (Path(__file__).parents[2] / "docker-compose.yml").read_text()
    for block in re.finditer(r"(?m)^  redis:\n(?P<body>(?:(?:    .*)?\n)*)", compose):
        if "image: redis:8-alpine" in block.group("body"):
            return block.group("body")
    raise AssertionError("redis service block not found in docker-compose.yml")


def _redis_command() -> str:
    match = re.search(r"(?m)^    command: (?P<command>.+)$", _redis_service_block())
    assert match is not None
    return match.group("command")


def test_compose_redis_uses_non_evicting_policy():
    assert "image: redis:8-alpine" in _redis_service_block()
    command = _redis_command()

    assert "--maxmemory-policy noeviction" in command
    assert "--maxmemory-policy allkeys-lru" not in command


def test_compose_redis_disables_automatic_rdb_snapshots_but_keeps_aof():
    """Default save points rewrite the whole dataset every ~5 minutes.

    Recovery loads the AOF, never dump.rdb, so the snapshots bought nothing while
    the image cache made each one ~161 MB (~46 GB/day of disk writes). Dropping
    `--save ""` brings the default `save 3600 1 300 100 60 10000` back; dropping
    `--appendonly yes` alongside it would leave nothing durable at all.
    """
    command = _redis_command()

    assert '--save ""' in command
    assert "--appendonly yes" in command


def test_backup_script_authenticates_redis_bgsave():
    """With automatic save points off, backup.sh's BGSAVE is the only writer of
    dump.rdb. An unauthenticated redis-cli fails with NOAUTH, which would archive
    an arbitrarily stale dump instead of a fresh one.
    """
    script = (Path(__file__).parents[2] / "scripts" / "backup.sh").read_text()

    assert 'REDIS_CLI+=(-a "$REDIS_PASSWORD")' in script
    for line in script.splitlines():
        if "redis-cli" in line and not line.lstrip().startswith("#"):
            assert "--no-auth-warning" in line, line
    # The copy must be gated on a successful BGSAVE, not run unconditionally.
    assert "skipping stale dump.rdb copy" in script
