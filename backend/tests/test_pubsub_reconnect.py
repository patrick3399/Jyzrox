"""Regression coverage for Pub/Sub listeners surviving a Redis restart.

A Redis restart drops every subscription and redis-py does not resubscribe on its
own. The long-lived listeners used to treat that as terminal — they logged a
warning and the coroutine returned — so a single restart left the process
permanently deaf with no error surfaced afterwards.
"""

import asyncio
import json
import logging
import time
from unittest.mock import AsyncMock, patch

import pytest

from core.site_config import DownloadParams, SiteConfigService


class FakePubSub:
    """Pub/Sub double whose connection can be broken on demand.

    `break_now` makes the in-flight `listen()` raise, exactly like a Redis restart
    resetting the connection. The event is cleared as it fires so the listener's
    next attempt blocks instead of spinning.
    """

    def __init__(self) -> None:
        self.subscribe_calls = 0
        self.channels: list[str] = []
        self.closed = 0
        self.break_now = asyncio.Event()
        self.queue: asyncio.Queue = asyncio.Queue()

    async def subscribe(self, channel: str) -> None:
        self.subscribe_calls += 1
        self.channels.append(channel)

    async def unsubscribe(self, channel: str) -> None:
        pass

    async def aclose(self) -> None:
        self.closed += 1

    async def deliver(self, data) -> None:
        await self.queue.put({"type": "message", "data": data})

    async def listen(self):
        breaker = asyncio.ensure_future(self.break_now.wait())
        try:
            while True:
                nxt = asyncio.ensure_future(self.queue.get())
                done, _ = await asyncio.wait([breaker, nxt], return_when=asyncio.FIRST_COMPLETED)
                if breaker in done:
                    nxt.cancel()
                    self.break_now.clear()
                    raise ConnectionError("Error while reading from redis:6379")
                yield nxt.result()
        finally:
            breaker.cancel()


async def wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


@pytest.fixture
def fast_backoff(monkeypatch):
    """Keep the reconnect delay out of the test runtime."""
    import core.redis_client as redis_client

    monkeypatch.setattr(redis_client, "_PUBSUB_RETRY_START", 0.01)
    monkeypatch.setattr(redis_client, "_PUBSUB_RETRY_MAX", 0.01)


# ── site_config invalidation listener ────────────────────────────────


@pytest.mark.asyncio
async def test_site_config_listener_resubscribes_after_connection_error(fast_backoff):
    """A dropped connection must not end the listener for the life of the process."""
    svc = SiteConfigService()
    pubsub = FakePubSub()

    with patch("core.redis_client.get_pubsub", return_value=pubsub):
        await svc.start_listener()
        assert await wait_for(lambda: pubsub.subscribe_calls == 1)

        pubsub.break_now.set()

        assert await wait_for(lambda: pubsub.subscribe_calls >= 2)
        await svc.stop_listener()

    assert pubsub.channels[:2] == ["site_config:invalidate"] * 2


@pytest.mark.asyncio
async def test_site_config_listener_drops_cache_on_resubscribe(fast_backoff):
    """Reconnecting is not enough: invalidations published while the connection
    was down are gone forever, so cache entries held across the gap are stale."""
    svc = SiteConfigService()
    pubsub = FakePubSub()

    with patch("core.redis_client.get_pubsub", return_value=pubsub):
        await svc.start_listener()
        assert await wait_for(lambda: pubsub.subscribe_calls == 1)

        # Populate the cache while the listener is connected and idle.
        svc._cache["ehentai"] = (DownloadParams(), time.time())
        svc._batch_cache = ({"ehentai": DownloadParams()}, time.time())

        pubsub.break_now.set()
        assert await wait_for(lambda: pubsub.subscribe_calls >= 2)
        await svc.stop_listener()

    assert svc._cache == {}
    assert svc._batch_cache is None


@pytest.mark.asyncio
async def test_site_config_listener_still_invalidates_after_reconnect(fast_backoff):
    """The resubscribed connection must actually deliver messages."""
    svc = SiteConfigService()
    pubsub = FakePubSub()

    with patch("core.redis_client.get_pubsub", return_value=pubsub):
        await svc.start_listener()
        assert await wait_for(lambda: pubsub.subscribe_calls == 1)

        pubsub.break_now.set()
        assert await wait_for(lambda: pubsub.subscribe_calls >= 2)

        svc._cache["pixiv"] = (DownloadParams(), time.time())
        await pubsub.deliver(b"pixiv")

        assert await wait_for(lambda: "pixiv" not in svc._cache)
        await svc.stop_listener()


@pytest.mark.asyncio
async def test_site_config_listener_retries_when_redis_is_down_at_startup(fast_backoff):
    """Startup used to subscribe before creating the task, so a Redis that was
    unavailable at boot disabled invalidation for the whole process lifetime."""
    pubsub = FakePubSub()
    attempts = {"n": 0}

    def _get_pubsub():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionError("Error 111 connecting to redis:6379")
        return pubsub

    svc = SiteConfigService()
    with patch("core.redis_client.get_pubsub", side_effect=_get_pubsub):
        await svc.start_listener()
        assert await wait_for(lambda: pubsub.subscribe_calls >= 1)
        await svc.stop_listener()


@pytest.mark.asyncio
async def test_site_config_listener_cancel_is_not_swallowed_by_retry_loop(fast_backoff):
    """The retry loop must re-raise CancelledError, or shutdown hangs on it."""
    svc = SiteConfigService()
    pubsub = FakePubSub()

    with patch("core.redis_client.get_pubsub", return_value=pubsub):
        await svc.start_listener()
        assert await wait_for(lambda: pubsub.subscribe_calls == 1)

        await asyncio.wait_for(svc.stop_listener(), timeout=2.0)

    assert svc._listener_task is None


@pytest.mark.asyncio
async def test_site_config_listener_survives_malformed_message(fast_backoff):
    """One bad payload must not tear down and resubscribe the connection."""
    svc = SiteConfigService()
    pubsub = FakePubSub()

    with patch("core.redis_client.get_pubsub", return_value=pubsub):
        await svc.start_listener()
        assert await wait_for(lambda: pubsub.subscribe_calls == 1)

        await pubsub.deliver(object())  # neither bytes nor str
        svc._cache["ehentai"] = (DownloadParams(), time.time())
        await pubsub.deliver(b"ehentai")

        assert await wait_for(lambda: "ehentai" not in svc._cache)
        await svc.stop_listener()

    assert pubsub.subscribe_calls == 1


# ── worker log level subscriber ──────────────────────────────────────


@pytest.mark.asyncio
async def test_log_level_subscriber_reapplies_level_after_reconnect(fast_backoff):
    """A level change published during the outage never arrives, and unlike the
    site_config cache there is no TTL that eventually corrects it."""
    from worker import _log_level_subscriber

    pubsub = FakePubSub()
    applied = AsyncMock(return_value="DEBUG")

    with (
        patch("core.redis_client.get_pubsub", return_value=pubsub),
        patch("core.log_handler.apply_log_level_from_redis", applied),
    ):
        task = asyncio.ensure_future(_log_level_subscriber({}))
        assert await wait_for(lambda: pubsub.subscribe_calls == 1)
        assert applied.await_count == 1

        pubsub.break_now.set()
        assert await wait_for(lambda: pubsub.subscribe_calls >= 2)
        assert await wait_for(lambda: applied.await_count >= 2)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_log_level_subscriber_applies_worker_level_from_message(fast_backoff):
    """Guard the message path itself: only the worker's own level applies."""
    from worker import _log_level_subscriber

    pubsub = FakePubSub()
    root = logging.getLogger()
    original = root.level

    try:
        with (
            patch("core.redis_client.get_pubsub", return_value=pubsub),
            patch("core.log_handler.apply_log_level_from_redis", AsyncMock()),
        ):
            task = asyncio.ensure_future(_log_level_subscriber({}))
            assert await wait_for(lambda: pubsub.subscribe_calls == 1)

            await pubsub.deliver(json.dumps({"source": "api", "level": "ERROR"}).encode())
            await pubsub.deliver(json.dumps({"source": "worker", "level": "DEBUG"}).encode())

            assert await wait_for(lambda: root.level == logging.DEBUG)

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        root.setLevel(original)


@pytest.mark.asyncio
async def test_log_level_subscriber_cancel_is_not_swallowed_by_retry_loop(fast_backoff):
    """worker shutdown() awaits this task after cancelling it."""
    from worker import _log_level_subscriber

    pubsub = FakePubSub()

    with (
        patch("core.redis_client.get_pubsub", return_value=pubsub),
        patch("core.log_handler.apply_log_level_from_redis", AsyncMock()),
    ):
        task = asyncio.ensure_future(_log_level_subscriber({}))
        assert await wait_for(lambda: pubsub.subscribe_calls == 1)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2.0)
