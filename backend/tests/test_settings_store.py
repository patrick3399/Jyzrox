"""Tests for services/settings_store.py — Redis-backed boolean/int toggle reads."""

import os
import sys
from unittest.mock import AsyncMock, patch

_backend = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(_backend) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend))


class TestGetToggle:
    async def test_returns_true_when_redis_value_is_1(self):
        from services.settings_store import get_toggle

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"1")
        with patch("services.settings_store.get_redis", return_value=redis):
            assert await get_toggle("setting:foo", False) is True

    async def test_returns_false_when_redis_value_is_0(self):
        from services.settings_store import get_toggle

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"0")
        with patch("services.settings_store.get_redis", return_value=redis):
            assert await get_toggle("setting:foo", True) is False

    async def test_returns_default_when_redis_returns_none(self):
        from services.settings_store import get_toggle

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        with patch("services.settings_store.get_redis", return_value=redis):
            assert await get_toggle("setting:foo", True) is True
            assert await get_toggle("setting:bar", False) is False

    async def test_redis_key_is_passed_through(self):
        from services.settings_store import get_toggle

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        with patch("services.settings_store.get_redis", return_value=redis):
            await get_toggle("setting:trash_enabled", True)
        redis.get.assert_awaited_once_with("setting:trash_enabled")


class TestSetToggle:
    async def test_writes_1_for_true(self):
        from services.settings_store import set_toggle

        redis = AsyncMock()
        redis.set = AsyncMock()
        with patch("services.settings_store.get_redis", return_value=redis):
            result = await set_toggle("setting:foo", True)
        redis.set.assert_awaited_once_with("setting:foo", "1")
        assert result is True

    async def test_writes_0_for_false(self):
        from services.settings_store import set_toggle

        redis = AsyncMock()
        redis.set = AsyncMock()
        with patch("services.settings_store.get_redis", return_value=redis):
            result = await set_toggle("setting:foo", False)
        redis.set.assert_awaited_once_with("setting:foo", "0")
        assert result is False
