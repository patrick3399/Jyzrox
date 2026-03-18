"""Tests for worker/trash.py.

Covers:
- trash_gc_job: uses configured retention_days from Redis
- trash_gc_job: defaults to 30 days when Redis has no setting
- trash_gc_job: returns deleted=0 when no galleries are expired
- trash_gc_job: calls _hard_delete_galleries for expired galleries
- trash_gc_job: exception in _hard_delete_galleries propagates
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure backend is on the path
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(_backend_dir) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session(galleries: list | None = None):
    """Return a mock async context-manager session."""
    if galleries is None:
        galleries = []

    session = AsyncMock()
    session.commit = AsyncMock()

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = galleries
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    session.execute = AsyncMock(return_value=execute_result)

    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_gallery(gallery_id: int = 1):
    """Return a MagicMock representing a Gallery row."""
    g = MagicMock()
    g.id = gallery_id
    g.title = f"Gallery {gallery_id}"
    return g


def _make_redis(retention_raw=None):
    """Return an AsyncMock Redis with get returning retention_raw."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=retention_raw)
    return redis


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTrashGcJob:
    """Unit tests for trash_gc_job()."""

    async def test_no_retention_setting_defaults_to_30_days(self):
        """When Redis has no trash_retention_days key, defaults to 30."""
        from worker.trash import trash_gc_job

        redis = _make_redis(retention_raw=None)
        session = _make_mock_session(galleries=[])

        with (
            patch("worker.trash.get_redis", return_value=redis),
            patch("worker.trash.AsyncSessionLocal", return_value=session),
            patch("routers.settings._get_toggle", new_callable=AsyncMock, return_value=True),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            result = await trash_gc_job({})

        assert result["status"] == "ok"
        assert result["deleted"] == 0
        # Verify that Redis was queried for the retention setting
        redis.get.assert_awaited_once_with("setting:trash_retention_days")

    async def test_custom_retention_days_read_from_redis(self):
        """When Redis returns a retention value, it is used for the cutoff calculation."""
        from worker.trash import trash_gc_job

        # Return "7" as a bytes-like string (as Redis would)
        redis = _make_redis(retention_raw=b"7")
        session = _make_mock_session(galleries=[])

        with (
            patch("worker.trash.get_redis", return_value=redis),
            patch("worker.trash.AsyncSessionLocal", return_value=session),
            patch("routers.settings._get_toggle", new_callable=AsyncMock, return_value=True),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            result = await trash_gc_job({})

        assert result["status"] == "ok"
        assert result["deleted"] == 0

    async def test_no_galleries_to_delete_returns_zero(self):
        """When no galleries match the cutoff, returns deleted=0 without calling _hard_delete."""
        from worker.trash import trash_gc_job

        redis = _make_redis()
        session = _make_mock_session(galleries=[])

        with (
            patch("worker.trash.get_redis", return_value=redis),
            patch("worker.trash.AsyncSessionLocal", return_value=session),
            patch("routers.settings._get_toggle", new_callable=AsyncMock, return_value=True),
            patch("core.events.emit_safe", new_callable=AsyncMock),
            patch(
                "routers.library._hard_delete_galleries",
                new_callable=AsyncMock,
            ) as mock_delete,
        ):
            result = await trash_gc_job({})

        assert result["status"] == "ok"
        assert result["deleted"] == 0
        # _hard_delete_galleries should NOT be called when no galleries are found
        mock_delete.assert_not_awaited()

    async def test_expired_galleries_are_hard_deleted(self):
        """When expired galleries exist, _hard_delete_galleries is called with them."""
        from worker.trash import trash_gc_job

        galleries = [_make_gallery(1), _make_gallery(2)]
        redis = _make_redis()
        session = _make_mock_session(galleries=galleries)
        delete_result = {"affected": 2, "deleted": 2}

        with (
            patch("worker.trash.get_redis", return_value=redis),
            patch("worker.trash.AsyncSessionLocal", return_value=session),
            patch("routers.settings._get_toggle", new_callable=AsyncMock, return_value=True),
            patch("core.events.emit_safe", new_callable=AsyncMock),
            patch(
                "routers.library._hard_delete_galleries",
                new_callable=AsyncMock,
                return_value=delete_result,
            ) as mock_delete,
        ):
            result = await trash_gc_job({})

        mock_delete.assert_awaited_once_with(session, galleries)
        assert result["status"] == "ok"
        assert result["affected"] == 2

    async def test_hard_delete_exception_propagates(self):
        """If _hard_delete_galleries raises, the exception propagates out of trash_gc_job."""
        import pytest

        from worker.trash import trash_gc_job

        galleries = [_make_gallery(1)]
        redis = _make_redis()
        session = _make_mock_session(galleries=galleries)

        with (
            patch("worker.trash.get_redis", return_value=redis),
            patch("worker.trash.AsyncSessionLocal", return_value=session),
            patch("routers.settings._get_toggle", new_callable=AsyncMock, return_value=True),
            patch("core.events.emit_safe", new_callable=AsyncMock),
            patch(
                "routers.library._hard_delete_galleries",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB connection lost"),
            ),
        ):
            with pytest.raises(RuntimeError, match="DB connection lost"):
                await trash_gc_job({})
