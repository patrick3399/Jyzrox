"""Tests for plugins/builtin/pixiv/_subscribe.py.

Covers:
- No credentials returns empty list
- Empty dict credentials (missing refresh_token) returns empty list
- PixivClient exception returns empty list
- Empty illusts list returns empty list
- Success with no last_known returns all works
- Success with last_known filters correctly (stops at matching id)
- Works with string credentials (bare refresh token)
- Image URLs extracted from nested dict
- Invalid date string handled gracefully
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


def _make_illust(illust_id: int, title: str = "Test", create_date: str = "2024-01-01T12:00:00"):
    """Return a dict mimicking a Pixiv illust object."""
    return {
        "id": illust_id,
        "title": title,
        "create_date": create_date,
        "image_urls": {
            "square_medium": f"https://i.pximg.net/sq/{illust_id}.jpg",
            "medium": f"https://i.pximg.net/md/{illust_id}.jpg",
        },
    }


def _make_pixiv_client_mock(illusts: list) -> MagicMock:
    """Build an async context-manager mock for PixivClient."""
    client = AsyncMock()
    client.user_illusts = AsyncMock(return_value={"illusts": illusts})
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckPixivNewWorks:
    """Unit tests for check_pixiv_new_works()."""

    async def test_no_credentials_returns_empty_list(self):
        """When credentials is None/falsy, returns [] without calling PixivClient."""
        from plugins.builtin.pixiv._subscribe import check_pixiv_new_works

        result = await check_pixiv_new_works("12345", last_known=None, credentials=None)

        assert result == []

    async def test_empty_dict_credentials_returns_empty_list(self):
        """When credentials dict has no refresh_token key, returns []."""
        from plugins.builtin.pixiv._subscribe import check_pixiv_new_works

        result = await check_pixiv_new_works("12345", last_known=None, credentials={})

        assert result == []

    async def test_credentials_missing_refresh_token_returns_empty_list(self):
        """Dict with other keys but no refresh_token returns []."""
        from plugins.builtin.pixiv._subscribe import check_pixiv_new_works

        result = await check_pixiv_new_works(
            "12345", last_known=None, credentials={"username": "user"}
        )

        assert result == []

    async def test_pixiv_client_exception_returns_empty_list(self):
        """When PixivClient raises an exception, logs error and returns []."""
        import services.pixiv_client as _pxclient
        from plugins.builtin.pixiv._subscribe import check_pixiv_new_works

        bad_cm = MagicMock()
        bad_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("network error"))
        bad_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(_pxclient, "PixivClient", return_value=bad_cm):
            result = await check_pixiv_new_works(
                "99999", last_known=None, credentials={"refresh_token": "tok"}
            )

        assert result == []

    async def test_empty_illusts_returns_empty_list(self):
        """When API returns empty illusts list, result is []."""
        import services.pixiv_client as _pxclient
        from plugins.builtin.pixiv._subscribe import check_pixiv_new_works

        cm = _make_pixiv_client_mock(illusts=[])

        with patch.object(_pxclient, "PixivClient", return_value=cm):
            result = await check_pixiv_new_works(
                "12345", last_known=None, credentials={"refresh_token": "tok"}
            )

        assert result == []

    async def test_success_no_last_known_returns_all_works(self):
        """With last_known=None, all returned illusts are included."""
        import services.pixiv_client as _pxclient
        from plugins.builtin.pixiv._subscribe import check_pixiv_new_works

        illusts = [_make_illust(101), _make_illust(102), _make_illust(103)]
        cm = _make_pixiv_client_mock(illusts=illusts)

        with patch.object(_pxclient, "PixivClient", return_value=cm):
            result = await check_pixiv_new_works(
                "12345", last_known=None, credentials={"refresh_token": "tok"}
            )

        assert len(result) == 3
        source_ids = [w.source_id for w in result]
        assert "101" in source_ids
        assert "102" in source_ids
        assert "103" in source_ids

    async def test_last_known_stops_at_matching_id(self):
        """When last_known matches an illust id, works before it are returned, rest ignored."""
        import services.pixiv_client as _pxclient
        from plugins.builtin.pixiv._subscribe import check_pixiv_new_works

        # Simulate newest-first ordering
        illusts = [_make_illust(200), _make_illust(199), _make_illust(198), _make_illust(197)]
        cm = _make_pixiv_client_mock(illusts=illusts)

        with patch.object(_pxclient, "PixivClient", return_value=cm):
            result = await check_pixiv_new_works(
                "12345", last_known="198", credentials={"refresh_token": "tok"}
            )

        # Should include 200 and 199 only (stop before 198)
        assert len(result) == 2
        source_ids = [w.source_id for w in result]
        assert "200" in source_ids
        assert "199" in source_ids
        assert "198" not in source_ids

    async def test_string_credentials_used_as_refresh_token(self):
        """When credentials is a bare string, it is used directly as refresh_token."""
        import services.pixiv_client as _pxclient
        from plugins.builtin.pixiv._subscribe import check_pixiv_new_works

        illusts = [_make_illust(300)]
        cm = _make_pixiv_client_mock(illusts=illusts)

        with patch.object(_pxclient, "PixivClient", return_value=cm):
            result = await check_pixiv_new_works(
                "12345", last_known=None, credentials="bare-refresh-token"
            )

        assert len(result) == 1
        assert result[0].source_id == "300"

    async def test_thumbnail_url_uses_square_medium_first(self):
        """thumbnail_url should prefer square_medium over medium."""
        import services.pixiv_client as _pxclient
        from plugins.builtin.pixiv._subscribe import check_pixiv_new_works

        illust = _make_illust(400)
        cm = _make_pixiv_client_mock(illusts=[illust])

        with patch.object(_pxclient, "PixivClient", return_value=cm):
            result = await check_pixiv_new_works(
                "12345", last_known=None, credentials={"refresh_token": "tok"}
            )

        assert len(result) == 1
        assert result[0].thumbnail_url == "https://i.pximg.net/sq/400.jpg"

    async def test_invalid_date_string_results_in_none_posted_at(self):
        """An unparseable create_date string should set posted_at to None."""
        import services.pixiv_client as _pxclient
        from plugins.builtin.pixiv._subscribe import check_pixiv_new_works

        illust = _make_illust(500, create_date="not-a-date")
        cm = _make_pixiv_client_mock(illusts=[illust])

        with patch.object(_pxclient, "PixivClient", return_value=cm):
            result = await check_pixiv_new_works(
                "12345", last_known=None, credentials={"refresh_token": "tok"}
            )

        assert len(result) == 1
        assert result[0].posted_at is None

    async def test_url_constructed_from_illust_id(self):
        """Each NewWork URL should point to the pixiv.net artworks page."""
        import services.pixiv_client as _pxclient
        from plugins.builtin.pixiv._subscribe import check_pixiv_new_works

        illust = _make_illust(600)
        cm = _make_pixiv_client_mock(illusts=[illust])

        with patch.object(_pxclient, "PixivClient", return_value=cm):
            result = await check_pixiv_new_works(
                "12345", last_known=None, credentials={"refresh_token": "tok"}
            )

        assert result[0].url == "https://www.pixiv.net/artworks/600"
