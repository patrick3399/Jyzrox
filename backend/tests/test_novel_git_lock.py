"""Regression tests for the novel git lock's hold time.

_with_git_lock took a fixed 60s TTL, but commit_and_push can chain
commit + push + fetch + rebase + push with a 30s subprocess timeout each. The
lock could therefore expire while the operation was still running and let a
second request into the same repo — release_lock is token-checked so it would
not delete the new holder's key, but nothing stopped the two from overlapping.

A fake Redis with real TTL semantics is used deliberately: an AsyncMock would
report success for every call and prove nothing about expiry.
"""

import asyncio
import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from worker.helpers import LOCK_RELEASE_LUA, LOCK_RENEW_LUA, acquire_lock


class FakeRedis:
    """Minimal Redis supporting SET NX EX, GET, and the two lock Lua scripts."""

    def __init__(self):
        self._values: dict[str, str] = {}
        self._expires: dict[str, float] = {}

    def _sweep(self) -> None:
        now = time.monotonic()
        for key in [k for k, deadline in self._expires.items() if deadline <= now]:
            self._values.pop(key, None)
            self._expires.pop(key, None)

    async def set(self, key, value, nx=False, ex=None):
        self._sweep()
        if nx and key in self._values:
            return None
        self._values[key] = value
        if ex is not None:
            self._expires[key] = time.monotonic() + ex
        return True

    async def get(self, key):
        self._sweep()
        return self._values.get(key)

    async def eval(self, script, _numkeys, key, *args):
        self._sweep()
        if script == LOCK_RELEASE_LUA:
            if self._values.get(key) == args[0]:
                self._values.pop(key, None)
                self._expires.pop(key, None)
                return 1
            return 0
        if script == LOCK_RENEW_LUA:
            if self._values.get(key) == args[0]:
                self._expires[key] = time.monotonic() + float(args[1])
                return 1
            return 0
        raise AssertionError(f"unexpected script: {script!r}")


@pytest.fixture
def fast_lock():
    """Shrink the TTL and renew interval so the test runs in about a second."""
    with (
        patch("routers.novels._GIT_LOCK_TTL", 1),
        patch("routers.novels._GIT_LOCK_RENEW_INTERVAL", 0.2),
    ):
        yield


async def test_lock_survives_an_operation_longer_than_its_ttl(fast_lock):
    """The whole point: a slow push+rebase must not drop mutual exclusion."""
    from routers import novels

    redis = FakeRedis()
    started = asyncio.Event()

    async def _slow_operation():
        started.set()
        await asyncio.sleep(1.6)  # comfortably past the 1s TTL
        return "done"

    with patch("routers.novels.get_redis", return_value=redis):
        task = asyncio.create_task(novels._with_git_lock(_slow_operation))
        await started.wait()
        await asyncio.sleep(1.3)  # past the original expiry

        # A second writer must still be refused while the first is working.
        assert await acquire_lock(redis, novels._GIT_LOCK, ttl=1) is None

        assert await task == "done"


async def test_lock_is_released_once_the_operation_finishes(fast_lock):
    """The heartbeat must not keep the key alive after the work is done."""
    from routers import novels

    redis = FakeRedis()

    async def _quick():
        return "ok"

    with patch("routers.novels.get_redis", return_value=redis):
        assert await novels._with_git_lock(_quick) == "ok"

    assert await redis.get(novels._GIT_LOCK) is None
    assert await acquire_lock(redis, novels._GIT_LOCK, ttl=1) is not None


async def test_lock_is_released_when_the_operation_raises(fast_lock):
    """A failing git op must not leave the repo locked for a whole TTL."""
    from routers import novels

    redis = FakeRedis()

    async def _boom():
        raise RuntimeError("push failed")

    with patch("routers.novels.get_redis", return_value=redis):
        with pytest.raises(RuntimeError, match="push failed"):
            await novels._with_git_lock(_boom)

    assert await redis.get(novels._GIT_LOCK) is None


async def test_second_writer_is_refused_immediately_while_held(fast_lock):
    """Concurrent request → 409, not a queue."""
    from routers import novels

    redis = FakeRedis()
    started = asyncio.Event()

    async def _hold():
        started.set()
        await asyncio.sleep(0.5)
        return "held"

    with patch("routers.novels.get_redis", return_value=redis):
        task = asyncio.create_task(novels._with_git_lock(_hold))
        await started.wait()

        async def _other():
            return "should not run"

        with pytest.raises(HTTPException) as exc:
            await novels._with_git_lock(_other)
        assert exc.value.status_code == 409

        assert await task == "held"


async def test_renewal_stops_after_the_lock_changes_hands(fast_lock):
    """Renewal is compare-and-expire: it must never revive someone else's lock."""
    from routers import novels
    from worker.helpers import renew_lock

    redis = FakeRedis()
    await redis.set(novels._GIT_LOCK, "someone-elses-token", nx=True, ex=5)

    assert await renew_lock(redis, novels._GIT_LOCK, "my-token", 60) is False
    # Their TTL is untouched, so their lock still expires on their schedule.
    assert await redis.get(novels._GIT_LOCK) == "someone-elses-token"
