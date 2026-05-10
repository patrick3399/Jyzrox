"""Tests for services/gallery_lifecycle.py."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

_backend = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(_backend) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend))


def _make_session():
    """Return AsyncMock session with two execute() call behaviours."""
    session = AsyncMock()
    session.delete = AsyncMock()
    session.commit = AsyncMock()

    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        scalars = MagicMock()
        # First call: load images — return empty list
        # Second call: zero-ref blob sha256s — return empty set
        scalars.all.return_value = []
        result.scalars.return_value = scalars
        return result

    session.execute = execute_side_effect
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_gallery(gallery_id: int = 1):
    g = MagicMock()
    g.id = gallery_id
    g.source = "test_source"
    g.source_id = f"src_{gallery_id}"
    return g


class TestHardDeleteGalleries:
    async def test_empty_list_returns_zero_immediately(self):
        from services.gallery_lifecycle import hard_delete_galleries

        session = AsyncMock()
        result = await hard_delete_galleries(session, [])
        assert result == {"affected": 0, "deleted_dirs": 0}
        session.commit.assert_not_awaited()

    async def test_deletes_each_gallery_row_and_commits(self):
        from services.gallery_lifecycle import hard_delete_galleries

        galleries = [_make_gallery(1), _make_gallery(2)]
        session = _make_session()
        with (
            patch("services.gallery_lifecycle.decrement_ref_count", new_callable=AsyncMock),
            patch("services.gallery_lifecycle.invalidate_sources_cache", new_callable=AsyncMock),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=0),
        ):
            result = await hard_delete_galleries(session, galleries)
        assert result["affected"] == 2
        assert session.delete.await_count == 2
        session.commit.assert_awaited_once()

    async def test_invalidates_sources_cache_after_commit(self):
        from services.gallery_lifecycle import hard_delete_galleries

        galleries = [_make_gallery(1)]
        session = _make_session()
        mock_invalidate = AsyncMock()
        with (
            patch("services.gallery_lifecycle.decrement_ref_count", new_callable=AsyncMock),
            patch("services.gallery_lifecycle.invalidate_sources_cache", mock_invalidate),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=0),
        ):
            await hard_delete_galleries(session, galleries)
        mock_invalidate.assert_awaited_once()

    async def test_returns_affected_count(self):
        from services.gallery_lifecycle import hard_delete_galleries

        galleries = [_make_gallery(i) for i in range(5)]
        session = _make_session()
        with (
            patch("services.gallery_lifecycle.decrement_ref_count", new_callable=AsyncMock),
            patch("services.gallery_lifecycle.invalidate_sources_cache", new_callable=AsyncMock),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=3),
        ):
            result = await hard_delete_galleries(session, galleries)
        assert result["affected"] == 5
        assert result["deleted_dirs"] == 3


class TestInvalidateSourcesCache:
    async def test_deletes_redis_key(self):
        from services.gallery_lifecycle import invalidate_sources_cache

        redis = AsyncMock()
        redis.delete = AsyncMock()
        with patch("services.gallery_lifecycle.get_redis", return_value=redis):
            await invalidate_sources_cache()
        redis.delete.assert_awaited_once_with("library:sources")

    async def test_swallows_redis_error(self):
        from services.gallery_lifecycle import invalidate_sources_cache

        redis = AsyncMock()
        redis.delete = AsyncMock(side_effect=ConnectionError("Redis down"))
        with patch("services.gallery_lifecycle.get_redis", return_value=redis):
            await invalidate_sources_cache()  # Must not raise
