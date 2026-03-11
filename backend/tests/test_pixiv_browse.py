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
