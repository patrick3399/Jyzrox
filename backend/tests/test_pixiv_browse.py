"""
Tests for Pixiv browse endpoints (/api/pixiv/*).

Covers:
- GET /api/pixiv/ranking — no Pixiv credentials required; uses httpx directly
- GET /api/pixiv/image-proxy — anonymous fallback when no Pixiv credentials
- Auth requirements for all endpoints
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_httpx_response(json_data: dict, status_code: int = 200):
    """Create a mock httpx Response object."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


_FAKE_RANKING_RESPONSE = {
    "contents": [
        {
            "title": "Popular Artwork 1",
            "illust_id": 111111,
            "user_name": "artist_a",
            "rank": 1,
        },
        {
            "title": "Popular Artwork 2",
            "illust_id": 222222,
            "user_name": "artist_b",
            "rank": 2,
        },
    ],
    "date": "20260311",
    "mode": "daily",
    "content": "all",
    "page": 1,
}


# ---------------------------------------------------------------------------
# GET /api/pixiv/ranking
# ---------------------------------------------------------------------------


class TestPixivRanking:
    """GET /api/pixiv/ranking — public ranking endpoint (no Pixiv auth needed)."""

    async def test_ranking_returns_data_without_pixiv_credentials(self, client):
        """Should fetch and return ranking data using direct httpx (no Pixiv credentials)."""
        mock_resp = _make_httpx_response(_FAKE_RANKING_RESPONSE)

        with (
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_json", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_httpx_cls,
        ):
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_http

            resp = await client.get("/api/pixiv/ranking")

        assert resp.status_code == 200
        data = resp.json()
        assert "contents" in data or "mode" in data or "date" in data  # pixiv ranking keys

    async def test_ranking_returns_cached_result_when_available(self, client):
        """Should return cached result without calling httpx."""
        with patch("services.cache.get_json", new_callable=AsyncMock, return_value=_FAKE_RANKING_RESPONSE):
            resp = await client.get("/api/pixiv/ranking")

        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == "20260311"
        assert data["mode"] == "daily"

    async def test_ranking_accepts_mode_parameter(self, client):
        """Should accept 'mode' query parameter."""
        with (
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_json", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_httpx_cls,
        ):
            mock_resp = _make_httpx_response({**_FAKE_RANKING_RESPONSE, "mode": "weekly"})
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_http

            resp = await client.get("/api/pixiv/ranking", params={"mode": "weekly"})

        assert resp.status_code == 200

    async def test_ranking_accepts_content_parameter(self, client):
        """Should accept 'content' query parameter."""
        with (
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_json", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_httpx_cls,
        ):
            mock_resp = _make_httpx_response({**_FAKE_RANKING_RESPONSE, "content": "illust"})
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_http

            resp = await client.get("/api/pixiv/ranking", params={"content": "illust"})

        assert resp.status_code == 200

    async def test_ranking_accepts_date_parameter(self, client):
        """Should accept 'date' query parameter in YYYYMMDD format."""
        with (
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_json", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_httpx_cls,
        ):
            mock_resp = _make_httpx_response({**_FAKE_RANKING_RESPONSE, "date": "20260301"})
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_http

            resp = await client.get("/api/pixiv/ranking", params={"date": "20260301"})

        assert resp.status_code == 200

    async def test_ranking_accepts_page_parameter(self, client):
        """Should accept 'page' query parameter (min 1)."""
        with (
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_json", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_httpx_cls,
        ):
            mock_resp = _make_httpx_response({**_FAKE_RANKING_RESPONSE, "page": 2})
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_http

            resp = await client.get("/api/pixiv/ranking", params={"page": 2})

        assert resp.status_code == 200

    async def test_ranking_page_zero_rejected(self, client):
        """page=0 should be rejected (min is 1)."""
        resp = await client.get("/api/pixiv/ranking", params={"page": 0})
        assert resp.status_code == 422

    async def test_ranking_stores_result_in_cache(self, client):
        """Successful ranking fetch should store result in cache."""
        mock_resp = _make_httpx_response(_FAKE_RANKING_RESPONSE)

        with (
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_json", new_callable=AsyncMock) as mock_set_json,
            patch("httpx.AsyncClient") as mock_httpx_cls,
        ):
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_http

            resp = await client.get("/api/pixiv/ranking")

        assert resp.status_code == 200
        mock_set_json.assert_called_once()
        # Verify TTL is 300 seconds (5min)
        call_args = mock_set_json.call_args
        assert call_args[0][2] == 300

    async def test_ranking_httpx_error_returns_502(self, client):
        """httpx failure during ranking fetch should return 502."""
        import httpx

        with (
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("httpx.AsyncClient") as mock_httpx_cls,
        ):
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=httpx.RequestError("timeout", request=MagicMock()))
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_http

            resp = await client.get("/api/pixiv/ranking")

        assert resp.status_code == 502

    async def test_ranking_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/pixiv/ranking")
        assert resp.status_code == 401

    async def test_ranking_cache_key_includes_all_params(self, client):
        """Different params should produce different cache keys."""
        cache_keys_seen = []

        original_get_json = AsyncMock(return_value=None)
        original_set_json = AsyncMock()
        mock_resp = _make_httpx_response(_FAKE_RANKING_RESPONSE)

        def capture_get_json(key):
            cache_keys_seen.append(key)
            return None

        async_get = AsyncMock(side_effect=capture_get_json)

        with (
            patch("services.cache.get_json", async_get),
            patch("services.cache.set_json", original_set_json),
            patch("httpx.AsyncClient") as mock_httpx_cls,
        ):
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_http

            await client.get("/api/pixiv/ranking", params={"mode": "daily", "content": "all"})
            await client.get("/api/pixiv/ranking", params={"mode": "weekly", "content": "illust"})

        assert len(cache_keys_seen) == 2
        assert cache_keys_seen[0] != cache_keys_seen[1]


# ---------------------------------------------------------------------------
# GET /api/pixiv/image-proxy — anonymous fallback
# ---------------------------------------------------------------------------


class TestPixivImageProxyAnonymousFallback:
    """GET /api/pixiv/image-proxy — anonymous fallback when no Pixiv credentials."""

    _VALID_PXIMG_URL = "https://i.pximg.net/img-original/img/2024/01/01/00/00/00/12345_p0.jpg"

    async def test_image_proxy_anonymous_fallback_when_no_credentials(self, client):
        """When Pixiv credentials are not configured, falls back to direct httpx with Referer."""
        fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # fake PNG bytes

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = fake_image
        mock_resp.raise_for_status = MagicMock()

        with (
            patch("services.cache.get_pixiv_image_cache", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_pixiv_image_cache", new_callable=AsyncMock),
            patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
            # No credentials → _make_client raises HTTPException → triggers fallback
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("httpx.AsyncClient") as mock_httpx_cls,
        ):
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_http

            resp = await client.get(
                "/api/pixiv/image-proxy",
                params={"url": self._VALID_PXIMG_URL},
            )

        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("image/")

    async def test_image_proxy_anonymous_fallback_sends_pixiv_referer(self, client):
        """Anonymous fallback must send Referer: https://www.pixiv.net/."""
        fake_image = b"\xff\xd8\xff" + b"\x00" * 100  # fake JPEG bytes

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = fake_image
        mock_resp.raise_for_status = MagicMock()

        with (
            patch("services.cache.get_pixiv_image_cache", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_pixiv_image_cache", new_callable=AsyncMock),
            patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("httpx.AsyncClient") as mock_httpx_cls,
        ):
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_http

            await client.get(
                "/api/pixiv/image-proxy",
                params={"url": self._VALID_PXIMG_URL},
            )

            # Verify referer header was sent
            mock_http.get.assert_called_once()
            call_kwargs = mock_http.get.call_args.kwargs
            assert call_kwargs.get("headers", {}).get("Referer") == "https://www.pixiv.net/"

    async def test_image_proxy_serves_cached_bytes_when_available(self, client):
        """Should return cached bytes without hitting httpx."""
        fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50  # fake PNG

        with (
            patch("services.cache.get_pixiv_image_cache", new_callable=AsyncMock, return_value=fake_image),
            patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
        ):
            resp = await client.get(
                "/api/pixiv/image-proxy",
                params={"url": self._VALID_PXIMG_URL},
            )

        assert resp.status_code == 200
        assert resp.content == fake_image

    async def test_image_proxy_rejects_non_pximg_domain(self, client):
        """URL from non-allowed domain should return 403."""
        with patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock):
            resp = await client.get(
                "/api/pixiv/image-proxy",
                params={"url": "https://evil.example.com/image.jpg"},
            )
        assert resp.status_code == 403

    async def test_image_proxy_rejects_non_http_scheme(self, client):
        """Non-http(s) URL scheme should return 400."""
        with patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock):
            resp = await client.get(
                "/api/pixiv/image-proxy",
                params={"url": "ftp://i.pximg.net/image.jpg"},
            )
        assert resp.status_code == 400

    async def test_image_proxy_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get(
            "/api/pixiv/image-proxy",
            params={"url": self._VALID_PXIMG_URL},
        )
        assert resp.status_code == 401

    async def test_image_proxy_anonymous_fallback_httpx_error_returns_502(self, client):
        """When anonymous httpx fetch fails, should return 502."""
        import httpx

        with (
            patch("services.cache.get_pixiv_image_cache", new_callable=AsyncMock, return_value=None),
            patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("httpx.AsyncClient") as mock_httpx_cls,
        ):
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                side_effect=httpx.RequestError("connection refused", request=MagicMock())
            )
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_http

            resp = await client.get(
                "/api/pixiv/image-proxy",
                params={"url": self._VALID_PXIMG_URL},
            )

        assert resp.status_code == 502

    async def test_image_proxy_with_credentials_uses_pixiv_client(self, client):
        """When Pixiv credentials exist, image-proxy should use PixivClient (not anonymous httpx)."""
        fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        mock_pixiv_client = AsyncMock()
        mock_pixiv_client.download_image = AsyncMock(return_value=(fake_image, "image/png"))
        mock_pixiv_client.__aenter__ = AsyncMock(return_value=mock_pixiv_client)
        mock_pixiv_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("services.cache.get_pixiv_image_cache", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_pixiv_image_cache", new_callable=AsyncMock),
            patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value="valid_refresh_token",
            ),
            patch(
                "plugins.builtin.pixiv._browse.PixivClient",
                return_value=mock_pixiv_client,
            ),
        ):
            resp = await client.get(
                "/api/pixiv/image-proxy",
                params={"url": self._VALID_PXIMG_URL},
            )

        assert resp.status_code == 200
        mock_pixiv_client.download_image.assert_called_once_with(self._VALID_PXIMG_URL)


# ---------------------------------------------------------------------------
# GET /api/pixiv/search — requires Pixiv credentials
# ---------------------------------------------------------------------------


class TestPixivSearch:
    """GET /api/pixiv/search — requires Pixiv credentials."""

    async def test_search_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/pixiv/search", params={"word": "blue hair"})
        assert resp.status_code == 401

    async def test_search_without_pixiv_credentials_returns_400(self, client):
        """No Pixiv credentials configured should return 400 (pixiv_not_configured)."""
        with (
            patch("services.cache.get_pixiv_search_cache", new_callable=AsyncMock, return_value=None),
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await client.get("/api/pixiv/search", params={"word": "test"})

        assert resp.status_code == 400
        data = resp.json()
        assert data["detail"]["code"] == "pixiv_not_configured"


# ---------------------------------------------------------------------------
# PixivClient unit tests — _normalize_illust, _normalize_user, helpers
# ---------------------------------------------------------------------------


class TestPixivIllustParsing:
    """Unit tests for PixivClient normalisation helpers (no HTTP, no Redis)."""

    def _make_illust(self, **overrides) -> dict:
        """Minimal illust dict as returned by pixivpy3."""
        base = {
            "id": 99999,
            "title": "Test Illust",
            "type": "illust",
            "image_urls": {
                "square_medium": "https://i.pximg.net/sq/99999.jpg",
                "medium": "https://i.pximg.net/med/99999.jpg",
                "large": "https://i.pximg.net/lg/99999.jpg",
            },
            "caption": "A test caption",
            "user": {
                "id": 12345,
                "name": "TestArtist",
                "account": "testartist",
                "profile_image_urls": {"medium": "https://i.pximg.net/avatar/12345.jpg"},
            },
            "tags": [
                {"name": "オリジナル", "translated_name": "original"},
                {"name": "女の子", "translated_name": "girl"},
            ],
            "create_date": "2026-01-15T12:00:00+09:00",
            "page_count": 1,
            "width": 1200,
            "height": 1800,
            "sanity_level": 2,
            "total_view": 5000,
            "total_bookmarks": 300,
            "is_bookmarked": False,
            "meta_single_page": {"original_image_url": "https://i.pximg.net/orig/99999_p0.jpg"},
            "meta_pages": [],
        }
        base.update(overrides)
        return base

    def test_normalize_illust_parses_single_page_detail(self):
        """_normalize_illust should extract all fields from a single-page illust."""
        from services.pixiv_client import PixivClient

        illust = self._make_illust()
        result = PixivClient._normalize_illust(illust)

        assert result["id"] == 99999
        assert result["title"] == "Test Illust"
        assert result["type"] == "illust"
        assert result["caption"] == "A test caption"
        assert result["page_count"] == 1
        assert result["width"] == 1200
        assert result["height"] == 1800
        assert result["total_view"] == 5000
        assert result["total_bookmarks"] == 300
        assert result["is_bookmarked"] is False
        assert result["image_urls"]["original"] == "https://i.pximg.net/orig/99999_p0.jpg"
        assert result["user"]["id"] == 12345
        assert result["user"]["name"] == "TestArtist"

    def test_normalize_illust_handles_multi_page(self):
        """Multi-page illusts should take original URL from meta_pages[0]."""
        from services.pixiv_client import PixivClient

        illust = self._make_illust(
            page_count=3,
            meta_pages=[
                {"image_urls": {"original": "https://i.pximg.net/orig/99999_p0.jpg", "large": ""}},
                {"image_urls": {"original": "https://i.pximg.net/orig/99999_p1.jpg", "large": ""}},
                {"image_urls": {"original": "https://i.pximg.net/orig/99999_p2.jpg", "large": ""}},
            ],
            meta_single_page={},
        )
        result = PixivClient._normalize_illust(illust)

        assert result["page_count"] == 3
        # original should point to first page's original
        assert result["image_urls"]["original"] == "https://i.pximg.net/orig/99999_p0.jpg"
        assert len(result["meta_pages"]) == 3
        assert result["meta_pages"][2]["image_urls"]["original"] == "https://i.pximg.net/orig/99999_p2.jpg"

    def test_normalize_illust_handles_deleted_or_empty(self):
        """Minimal/empty illust dict should not raise; missing fields fall back to defaults."""
        from services.pixiv_client import PixivClient

        # Simulate a near-empty response (deleted/restricted illust has minimal data)
        illust = {"id": 0}
        result = PixivClient._normalize_illust(illust)

        assert result["id"] == 0
        assert result["title"] == ""
        assert result["type"] == "illust"
        assert result["page_count"] == 1
        assert result["tags"] == []
        assert result["meta_pages"] == []
        assert result["image_urls"]["original"] == ""

    def test_normalize_illust_parses_tags_with_translations(self):
        """Tags list should include name and translated_name for each entry."""
        from services.pixiv_client import PixivClient

        illust = self._make_illust(
            tags=[
                {"name": "blue_hair", "translated_name": "青い髪"},
                {"name": "solo", "translated_name": None},
                {"name": "safe"},  # missing translated_name key entirely
            ]
        )
        result = PixivClient._normalize_illust(illust)

        assert len(result["tags"]) == 3
        assert result["tags"][0] == {"name": "blue_hair", "translated_name": "青い髪"}
        assert result["tags"][1] == {"name": "solo", "translated_name": None}
        assert result["tags"][2]["name"] == "safe"


# ---------------------------------------------------------------------------
# PixivClient._normalize_user
# ---------------------------------------------------------------------------


class TestPixivUserProfile:
    """Unit tests for _normalize_user and related helpers."""

    def _make_user_detail(self, **overrides) -> dict:
        """Minimal user_detail response dict."""
        base = {
            "user": {
                "id": 12345,
                "name": "TestArtist",
                "account": "testartist",
                "comment": "Hello from test artist",
                "is_followed": True,
                "profile_image_urls": {"medium": "https://i.pximg.net/avatar/12345.jpg"},
            },
            "profile": {
                "total_illusts": 100,
                "total_manga": 5,
                "total_novels": 0,
            },
        }
        base.update(overrides)
        return base

    def test_normalize_user_parses_full_profile(self):
        """_normalize_user should extract all expected fields."""
        from services.pixiv_client import PixivClient

        response = self._make_user_detail()
        result = PixivClient._normalize_user(response)

        assert result["id"] == 12345
        assert result["name"] == "TestArtist"
        assert result["account"] == "testartist"
        assert result["comment"] == "Hello from test artist"
        assert result["total_illusts"] == 100
        assert result["total_manga"] == 5
        assert result["total_novels"] == 0
        assert result["is_followed"] is True
        assert "pximg.net" in result["profile_image"]

    def test_normalize_user_empty_response_returns_defaults(self):
        """Empty dict should not raise; fields default to zero / empty string."""
        from services.pixiv_client import PixivClient

        result = PixivClient._normalize_user({})

        assert result["id"] is None
        assert result["name"] == ""
        assert result["total_illusts"] == 0
        assert result["is_followed"] is False

    def test_normalize_illust_list_wraps_multiple_illusts(self):
        """_normalize_illust_list should return {illusts, next_offset} and wrap each illust."""
        from services.pixiv_client import PixivClient

        client = PixivClient.__new__(PixivClient)  # skip __init__
        raw = {
            "illusts": [
                {"id": 1, "title": "A"},
                {"id": 2, "title": "B"},
            ],
            "next_url": "https://app-api.pixiv.net/v1/search/illust?offset=30",
        }
        result = client._normalize_illust_list(raw)

        assert len(result["illusts"]) == 2
        assert result["illusts"][0]["id"] == 1
        assert result["illusts"][1]["id"] == 2
        assert result["next_offset"] == 30


# ---------------------------------------------------------------------------
# PixivClient search result parsing (unit — no HTTP)
# ---------------------------------------------------------------------------


class TestPixivSearchResultParsing:
    """Unit tests for search result parsing helpers."""

    def test_next_offset_parses_offset_from_next_url(self):
        """_next_offset should extract integer offset from next_url query string."""
        from services.pixiv_client import PixivClient

        response = {
            "illusts": [],
            "next_url": "https://app-api.pixiv.net/v1/search/illust?word=test&offset=60",
        }
        offset = PixivClient._next_offset(response)
        assert offset == 60

    def test_next_offset_returns_none_when_no_next_url(self):
        """When next_url is absent or None, _next_offset should return None."""
        from services.pixiv_client import PixivClient

        assert PixivClient._next_offset({"next_url": None}) is None
        assert PixivClient._next_offset({}) is None

    def test_normalize_illust_list_empty_illusts_returns_empty(self):
        """Empty illusts list in response should produce empty result with no next_offset."""
        from services.pixiv_client import PixivClient

        client = PixivClient.__new__(PixivClient)
        result = client._normalize_illust_list({"illusts": [], "next_url": None})

        assert result["illusts"] == []
        assert result["next_offset"] is None


# ---------------------------------------------------------------------------
# PixivClient token management (unit — Redis + pixivpy3 mocked)
# ---------------------------------------------------------------------------


class TestPixivTokenRefresh:
    """Unit tests for _ensure_token / _refresh_token flow."""

    async def test_ensure_token_uses_cached_access_token(self):
        """When Redis has a cached access_token, _ensure_token should use it without calling auth."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from services.pixiv_client import PixivClient

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"cached_access_token_abc")

        mock_api = MagicMock()
        mock_api.set_auth = MagicMock()

        client = PixivClient.__new__(PixivClient)
        client.refresh_token = "my_refresh_token"
        client._api = mock_api

        with patch("services.pixiv_client.get_redis", return_value=mock_redis):
            await client._ensure_token()

        mock_api.set_auth.assert_called_once_with("cached_access_token_abc", "my_refresh_token")
        # auth() should NOT have been called (token was cached)
        assert not hasattr(mock_api, "auth") or not mock_api.auth.called

    async def test_refresh_token_stores_access_token_in_redis(self):
        """_refresh_token should call pixivpy3.auth and store access_token in Redis."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from services.pixiv_client import PixivClient

        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        fake_token_response = MagicMock()
        fake_token_response.access_token = "new_access_token_xyz"

        mock_api = MagicMock()
        mock_api.auth = MagicMock(return_value=fake_token_response)

        client = PixivClient.__new__(PixivClient)
        client.refresh_token = "valid_refresh_token"
        client._api = mock_api

        with patch("services.pixiv_client.get_redis", return_value=mock_redis):
            await client._refresh_token()

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args[0]
        assert call_args[0] == "pixiv:access_token"
        assert call_args[2] == "new_access_token_xyz"

    async def test_refresh_token_raises_permission_error_on_auth_failure(self):
        """When pixivpy3.auth raises, _refresh_token should wrap it in PermissionError."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        import pytest

        from services.pixiv_client import PixivClient

        mock_redis = AsyncMock()

        mock_api = MagicMock()
        mock_api.auth = MagicMock(side_effect=Exception("invalid_grant"))

        client = PixivClient.__new__(PixivClient)
        client.refresh_token = "bad_refresh_token"
        client._api = mock_api

        with (
            patch("services.pixiv_client.get_redis", return_value=mock_redis),
            pytest.raises(PermissionError, match="Pixiv token invalid or expired"),
        ):
            await client._refresh_token()


# ---------------------------------------------------------------------------
# PixivClient error handling (unit)
# ---------------------------------------------------------------------------


class TestPixivClientErrorHandling:
    """Unit tests for error handling inside PixivClient._call."""

    async def test_call_retries_on_403_token_expired(self):
        """When a pixivpy3 call raises a 403 error, _call should flush Redis and retry once."""
        from unittest.mock import AsyncMock, MagicMock, call, patch

        from services.pixiv_client import PixivClient

        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        call_count = 0

        def _flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("403 Forbidden")
            return {"illusts": [], "next_url": None}

        mock_api = MagicMock()
        fake_token_response = MagicMock()
        fake_token_response.access_token = "refreshed_token"
        mock_api.auth = MagicMock(return_value=fake_token_response)

        client = PixivClient.__new__(PixivClient)
        client.refresh_token = "some_token"
        client._api = mock_api

        with patch("services.pixiv_client.get_redis", return_value=mock_redis):
            result = await client._call(_flaky_fn)

        assert call_count == 2
        mock_redis.delete.assert_called_with("pixiv:access_token")
        assert result == {"illusts": [], "next_url": None}

    async def test_call_propagates_non_auth_exception(self):
        """Non-auth exceptions from pixivpy3 should propagate directly from _call."""
        import pytest

        from services.pixiv_client import PixivClient

        def _bad_fn():
            raise ValueError("Unexpected API shape")

        client = PixivClient.__new__(PixivClient)
        client.refresh_token = "token"
        client._api = MagicMock()

        with pytest.raises(ValueError, match="Unexpected API shape"):
            await client._call(_bad_fn)


# ---------------------------------------------------------------------------
# GET /api/pixiv/search — authenticated search with credentials
# ---------------------------------------------------------------------------


class TestPixivSearchAuthenticated:
    """GET /api/pixiv/search — success and error paths with Pixiv credentials."""

    _FAKE_SEARCH_RESULT = {
        "illusts": [
            {"id": 11111, "title": "Blue Hair Art"},
            {"id": 22222, "title": "Red Eyes Art"},
        ],
        "next_url": None,
    }

    async def test_search_returns_results_with_credentials(self, client):
        """With valid Pixiv credentials, search should return illust list."""
        mock_pixiv_client = AsyncMock()
        mock_pixiv_client.search_illust = AsyncMock(return_value=self._FAKE_SEARCH_RESULT)
        mock_pixiv_client.__aenter__ = AsyncMock(return_value=mock_pixiv_client)
        mock_pixiv_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("services.cache.get_pixiv_search_cache", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_pixiv_search_cache", new_callable=AsyncMock),
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value="valid_token",
            ),
            patch("plugins.builtin.pixiv._browse.PixivClient", return_value=mock_pixiv_client),
        ):
            resp = await client.get("/api/pixiv/search", params={"word": "blue hair"})

        assert resp.status_code == 200
        data = resp.json()
        assert "illusts" in data

    async def test_search_returns_cached_result(self, client):
        """Cached search result should be returned without calling PixivClient."""
        cached = {"illusts": [{"id": 999}], "next_url": None}

        with patch("services.cache.get_pixiv_search_cache", new_callable=AsyncMock, return_value=cached):
            resp = await client.get("/api/pixiv/search", params={"word": "cached"})

        assert resp.status_code == 200
        assert resp.json() == cached

    async def test_search_missing_word_param_returns_422(self, client):
        """Missing required 'word' parameter should return 422."""
        resp = await client.get("/api/pixiv/search")
        assert resp.status_code == 422

    async def test_search_permission_error_returns_401(self, client):
        """PermissionError from PixivClient should return 401."""
        mock_pixiv_client = AsyncMock()
        mock_pixiv_client.search_illust = AsyncMock(side_effect=PermissionError("token expired"))
        mock_pixiv_client.__aenter__ = AsyncMock(return_value=mock_pixiv_client)
        mock_pixiv_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("services.cache.get_pixiv_search_cache", new_callable=AsyncMock, return_value=None),
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value="expired_token",
            ),
            patch("plugins.builtin.pixiv._browse.PixivClient", return_value=mock_pixiv_client),
        ):
            resp = await client.get("/api/pixiv/search", params={"word": "test"})

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/pixiv/illust/{illust_id}
# ---------------------------------------------------------------------------


class TestPixivIllustDetail:
    """GET /api/pixiv/illust/{illust_id} — detail endpoint."""

    _FAKE_ILLUST = {
        "id": 12345,
        "title": "Test Illust",
        "page_count": 1,
        "image_urls": {"original": "https://i.pximg.net/orig/12345_p0.jpg"},
        "meta_pages": [],
    }

    async def test_illust_detail_returns_data_with_credentials(self, client):
        """With credentials, should return illust detail from PixivClient."""
        mock_pixiv_client = AsyncMock()
        mock_pixiv_client.illust_detail = AsyncMock(return_value=self._FAKE_ILLUST)
        mock_pixiv_client.__aenter__ = AsyncMock(return_value=mock_pixiv_client)
        mock_pixiv_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("services.cache.get_pixiv_illust_cache", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_pixiv_illust_cache", new_callable=AsyncMock),
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value="valid_token",
            ),
            patch("plugins.builtin.pixiv._browse.PixivClient", return_value=mock_pixiv_client),
        ):
            resp = await client.get("/api/pixiv/illust/12345")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 12345

    async def test_illust_detail_uses_cached_result(self, client):
        """Cached illust should be returned without hitting PixivClient."""
        with patch("services.cache.get_pixiv_illust_cache", new_callable=AsyncMock, return_value=self._FAKE_ILLUST):
            resp = await client.get("/api/pixiv/illust/12345")

        assert resp.status_code == 200
        assert resp.json()["id"] == 12345

    async def test_illust_detail_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/pixiv/illust/12345")
        assert resp.status_code == 401

    async def test_illust_pages_returns_page_list_from_cache(self, client):
        """GET /illust/{id}/pages should build page list from cached illust."""
        cached = {
            "id": 12345,
            "page_count": 2,
            "meta_pages": [
                {"image_urls": {"original": "https://i.pximg.net/orig/12345_p0.jpg", "large": ""}},
                {"image_urls": {"original": "https://i.pximg.net/orig/12345_p1.jpg", "large": ""}},
            ],
            "image_urls": {},
        }

        with patch("services.cache.get_pixiv_illust_cache", new_callable=AsyncMock, return_value=cached):
            resp = await client.get("/api/pixiv/illust/12345/pages")

        assert resp.status_code == 200
        data = resp.json()
        assert data["page_count"] == 2
        assert len(data["pages"]) == 2
        assert data["pages"][0]["page_num"] == 1

    async def test_illust_pages_single_page_illust(self, client):
        """Single-page illust (no meta_pages) returns one page entry from image_urls."""
        cached = {
            "id": 99,
            "page_count": 1,
            "meta_pages": [],
            "image_urls": {"original": "https://i.pximg.net/orig/99_p0.jpg"},
        }

        with patch("services.cache.get_pixiv_illust_cache", new_callable=AsyncMock, return_value=cached):
            resp = await client.get("/api/pixiv/illust/99/pages")

        assert resp.status_code == 200
        data = resp.json()
        assert data["page_count"] == 1
        assert data["pages"][0]["url"] == "https://i.pximg.net/orig/99_p0.jpg"


# ---------------------------------------------------------------------------
# GET /api/pixiv/user/{user_id}
# ---------------------------------------------------------------------------


class TestPixivUserDetail:
    """GET /api/pixiv/user/{user_id} — user profile endpoint."""

    async def test_user_detail_returns_profile_and_recent_illusts(self, client):
        """Should return user info and recent_illusts from PixivClient."""
        fake_user_info = {"id": 555, "name": "Artist"}
        fake_recent = {"illusts": [{"id": 101}, {"id": 102}]}

        mock_pixiv_client = AsyncMock()
        mock_pixiv_client.user_detail = AsyncMock(return_value=fake_user_info)
        mock_pixiv_client.user_illusts = AsyncMock(return_value=fake_recent)
        mock_pixiv_client.__aenter__ = AsyncMock(return_value=mock_pixiv_client)
        mock_pixiv_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("services.cache.get_pixiv_user_cache", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_pixiv_user_cache", new_callable=AsyncMock),
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value="valid_token",
            ),
            patch("plugins.builtin.pixiv._browse.PixivClient", return_value=mock_pixiv_client),
        ):
            resp = await client.get("/api/pixiv/user/555")

        assert resp.status_code == 200
        data = resp.json()
        assert "user" in data
        assert "recent_illusts" in data

    async def test_user_detail_from_cache(self, client):
        """Cached user data should be returned without calling PixivClient."""
        cached = {"user": {"id": 555, "name": "CachedArtist"}, "recent_illusts": []}

        with patch("services.cache.get_pixiv_user_cache", new_callable=AsyncMock, return_value=cached):
            resp = await client.get("/api/pixiv/user/555")

        assert resp.status_code == 200
        assert resp.json() == cached

    async def test_user_detail_no_credentials_returns_400(self, client):
        """No Pixiv credentials → 400 (pixiv_not_configured)."""
        with (
            patch("services.cache.get_pixiv_user_cache", new_callable=AsyncMock, return_value=None),
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await client.get("/api/pixiv/user/555")

        assert resp.status_code == 400

    async def test_user_detail_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/pixiv/user/555")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/pixiv/search-public
# ---------------------------------------------------------------------------


class TestPixivSearchPublic:
    """GET /api/pixiv/search-public — no Pixiv credentials required."""

    async def test_search_public_returns_illusts_from_pixiv_ajax(self, client):
        """Should parse Pixiv ajax search response and return normalized illusts."""
        ajax_response = {
            "error": False,
            "body": {
                "illustManga": {
                    "data": [
                        {
                            "id": "777",
                            "title": "Public Art",
                            "url": "https://i.pximg.net/thumb/777.jpg",
                            "userId": "55",
                            "userName": "PublicArtist",
                            "profileImageUrl": "",
                            "pageCount": 1,
                            "width": 800,
                            "height": 1200,
                            "tags": ["blue"],
                            "createDate": "2026-01-01T00:00:00+09:00",
                        }
                    ],
                    "total": 1,
                },
                "popular": {},
                "relatedTags": ["sky"],
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = ajax_response
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_json", new_callable=AsyncMock),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            resp = await client.get("/api/pixiv/search-public", params={"word": "blue"})

        assert resp.status_code == 200
        data = resp.json()
        assert "illusts" in data
        assert data["total"] == 1
        assert data["illusts"][0]["id"] == 777

    async def test_search_public_requires_word_param(self, client):
        """Missing 'word' parameter should return 422."""
        resp = await client.get("/api/pixiv/search-public")
        assert resp.status_code == 422

    async def test_search_public_returns_cached_result(self, client):
        """Cached result should be returned without making HTTP requests."""
        cached = {"illusts": [], "total": 0}

        with patch("services.cache.get_json", new_callable=AsyncMock, return_value=cached):
            resp = await client.get("/api/pixiv/search-public", params={"word": "test"})

        assert resp.status_code == 200
        assert resp.json() == cached

    async def test_search_public_pixiv_error_response_returns_502(self, client):
        """Pixiv error=True response should return 502."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"error": True, "message": "Some Pixiv error"}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            resp = await client.get("/api/pixiv/search-public", params={"word": "error"})

        assert resp.status_code == 502

    async def test_search_public_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/pixiv/search-public", params={"word": "test"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# User bookmarks
# ---------------------------------------------------------------------------


class TestPixivUserBookmarks:
    """GET /api/pixiv/user/{user_id}/bookmarks"""

    async def test_user_bookmarks_returns_data(self, client):
        """Should return bookmark list from PixivClient."""
        fake_bookmarks = {"illusts": [{"id": 500}], "next_url": None}

        mock_pixiv_client = AsyncMock()
        mock_pixiv_client.user_bookmarks = AsyncMock(return_value=fake_bookmarks)
        mock_pixiv_client.__aenter__ = AsyncMock(return_value=mock_pixiv_client)
        mock_pixiv_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("services.cache.get_pixiv_search_cache", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_pixiv_search_cache", new_callable=AsyncMock),
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value="valid_token",
            ),
            patch("plugins.builtin.pixiv._browse.PixivClient", return_value=mock_pixiv_client),
        ):
            resp = await client.get("/api/pixiv/user/555/bookmarks")

        assert resp.status_code == 200
        data = resp.json()
        assert "illusts" in data

    async def test_user_bookmarks_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/pixiv/user/555/bookmarks")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/pixiv/following/feed
# ---------------------------------------------------------------------------


class TestPixivFollowingFeed:
    """GET /api/pixiv/following/feed — following feed endpoint."""

    async def test_following_feed_returns_illusts(self, client):
        """Should return feed illusts from PixivClient.illust_follow."""
        fake_feed = {"illusts": [{"id": 888}], "next_url": None}

        mock_pixiv_client = AsyncMock()
        mock_pixiv_client.illust_follow = AsyncMock(return_value=fake_feed)
        mock_pixiv_client.__aenter__ = AsyncMock(return_value=mock_pixiv_client)
        mock_pixiv_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("services.cache.get_pixiv_search_cache", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_pixiv_search_cache", new_callable=AsyncMock),
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value="valid_token",
            ),
            patch("plugins.builtin.pixiv._browse.PixivClient", return_value=mock_pixiv_client),
        ):
            resp = await client.get("/api/pixiv/following/feed")

        assert resp.status_code == 200
        data = resp.json()
        assert "illusts" in data

    async def test_following_feed_no_credentials_returns_400(self, client):
        """No Pixiv credentials → 400."""
        with (
            patch("services.cache.get_pixiv_search_cache", new_callable=AsyncMock, return_value=None),
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await client.get("/api/pixiv/following/feed")

        assert resp.status_code == 400

    async def test_following_feed_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/pixiv/following/feed")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# R18 ranking path
# ---------------------------------------------------------------------------


class TestPixivR18Ranking:
    """GET /api/pixiv/ranking?mode=daily_r18 — requires Pixiv credentials."""

    async def test_r18_ranking_returns_data_with_credentials(self, client):
        """daily_r18 mode should use PixivClient.illust_ranking and return contents list."""
        fake_r18_result = {
            "illusts": [
                {
                    "id": 99,
                    "title": "R18 Art",
                    "user": {"name": "artist99"},
                    "image_urls": {"square_medium": "https://i.pximg.net/sq/99.jpg"},
                }
            ],
            "next_offset": None,
        }

        mock_pixiv_client = AsyncMock()
        mock_pixiv_client.illust_ranking = AsyncMock(return_value=fake_r18_result)
        mock_pixiv_client.__aenter__ = AsyncMock(return_value=mock_pixiv_client)
        mock_pixiv_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_json", new_callable=AsyncMock),
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value="valid_token",
            ),
            patch("plugins.builtin.pixiv._browse.PixivClient", return_value=mock_pixiv_client),
        ):
            resp = await client.get("/api/pixiv/ranking", params={"mode": "daily_r18"})

        assert resp.status_code == 200
        data = resp.json()
        assert "contents" in data
        assert data["mode"] == "daily_r18"

    async def test_r18_ranking_no_credentials_returns_400(self, client):
        """daily_r18 without Pixiv credentials should return 400."""
        with (
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch(
                "plugins.builtin.pixiv._browse.get_credential",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await client.get("/api/pixiv/ranking", params={"mode": "daily_r18"})

        assert resp.status_code == 400
