"""
Unit tests for services/pixiv_client.py.

Tests cover token management, normalisation helpers, API wrapper methods,
and error handling.  pixivpy3 calls and Redis are fully mocked — no external
network traffic.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_api():
    """Return a MagicMock that looks like a pixivpy3 AppPixivAPI instance."""
    api = MagicMock()
    api.additional_headers = {}
    api.set_auth = MagicMock()
    api.auth = MagicMock()
    return api


def _make_mock_redis(cached_token=None):
    """Return an AsyncMock Redis with optional cached token."""
    r = AsyncMock()
    r.get = AsyncMock(return_value=cached_token)
    r.set = AsyncMock(return_value=True)
    r.setex = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    r.pipeline = MagicMock(return_value=AsyncMock())
    return r


def _make_token_response(access_token="test_access_token"):
    """Return a fake pixivpy3 token response object."""
    resp = MagicMock()
    resp.access_token = access_token
    return resp


def _build_pixiv_client(refresh_token="test_refresh_token"):
    """Return a PixivClient with mocked internals (not yet entered)."""
    from services.pixiv_client import PixivClient

    client = PixivClient(refresh_token)
    client._api = _make_mock_api()
    client._img_http = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------


class TestTokenManagement:
    """Tests for PixivClient._ensure_token and _refresh_token."""

    async def test_ensure_token_uses_cached_token(self):
        """_ensure_token should use Redis-cached token and call set_auth."""
        from services.pixiv_client import PixivClient

        client = PixivClient("my_refresh_token")
        client._api = _make_mock_api()

        mock_redis = _make_mock_redis(cached_token=b"cached_access_token")

        with patch("services.pixiv_client.get_redis", return_value=mock_redis):
            await client._ensure_token()

        client._api.set_auth.assert_called_once_with(
            "cached_access_token", "my_refresh_token"
        )

    async def test_ensure_token_refreshes_when_no_cache(self):
        """_ensure_token should call auth() and cache result when no token in Redis."""
        from services.pixiv_client import PixivClient

        client = PixivClient("my_refresh_token")
        client._api = _make_mock_api()

        token_resp = _make_token_response("fresh_token")

        mock_redis = _make_mock_redis(cached_token=None)
        # Lock not acquired on second call → allow refresh
        mock_redis.set = AsyncMock(return_value=True)  # lock acquired

        with (
            patch("services.pixiv_client.get_redis", return_value=mock_redis),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=token_resp),
        ):
            await client._ensure_token()

        mock_redis.setex.assert_called_once()

    async def test_refresh_token_raises_on_failed_auth(self):
        """_refresh_token should raise PermissionError when pixivpy3 auth fails."""
        from services.pixiv_client import PixivClient

        client = PixivClient("bad_token")
        client._api = _make_mock_api()
        mock_redis = _make_mock_redis()

        with (
            patch("services.pixiv_client.get_redis", return_value=mock_redis),
            patch(
                "asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=Exception("invalid_grant"),
            ),
        ):
            with pytest.raises(PermissionError, match="Pixiv token invalid"):
                await client._refresh_token()

    async def test_refresh_token_raises_when_no_access_token_attr(self):
        """_refresh_token raises when token response has no access_token."""
        from services.pixiv_client import PixivClient

        client = PixivClient("my_refresh")
        client._api = _make_mock_api()
        mock_redis = _make_mock_redis()

        # auth returns something without access_token attribute
        bad_resp = MagicMock(spec=[])  # no attributes

        with (
            patch("services.pixiv_client.get_redis", return_value=mock_redis),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=bad_resp),
        ):
            with pytest.raises(PermissionError, match="Pixiv token invalid"):
                await client._refresh_token()

    async def test_ensure_token_waits_for_lock_then_uses_cache(self):
        """When lock not acquired, _ensure_token polls until cached token appears."""
        from services.pixiv_client import PixivClient

        client = PixivClient("ref_tok")
        client._api = _make_mock_api()

        # Lock not acquired (set returns False), then cache appears on second get
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=False)  # lock not acquired
        mock_redis.get = AsyncMock(side_effect=[None, b"polled_token"])

        with (
            patch("services.pixiv_client.get_redis", return_value=mock_redis),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await client._ensure_token()

        client._api.set_auth.assert_called_once_with("polled_token", "ref_tok")


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


class TestNormalisationHelpers:
    """Unit tests for PixivClient static normalisation methods."""

    def test_normalize_illust_extracts_basic_fields(self):
        """_normalize_illust should map all basic fields from illust dict."""
        from services.pixiv_client import PixivClient

        illust = {
            "id": 12345,
            "title": "Test Illustration",
            "type": "illust",
            "caption": "A test caption",
            "create_date": "2024-01-15T12:00:00+09:00",
            "page_count": 1,
            "width": 1920,
            "height": 1080,
            "sanity_level": 2,
            "total_view": 5000,
            "total_bookmarks": 200,
            "is_bookmarked": False,
            "image_urls": {
                "square_medium": "https://pximg.net/sm.jpg",
                "medium": "https://pximg.net/m.jpg",
                "large": "https://pximg.net/l.jpg",
            },
            "meta_single_page": {"original_image_url": "https://pximg.net/orig.jpg"},
            "meta_pages": [],
            "user": {
                "id": 99,
                "name": "TestArtist",
                "account": "test_artist",
                "profile_image_urls": {"medium": "https://pximg.net/prof.jpg"},
            },
            "tags": [
                {"name": "blue_hair", "translated_name": "blue hair"},
                {"name": "original", "translated_name": None},
            ],
        }

        result = PixivClient._normalize_illust(illust)

        assert result["id"] == 12345
        assert result["title"] == "Test Illustration"
        assert result["page_count"] == 1
        assert result["width"] == 1920
        assert result["height"] == 1080
        assert result["user"]["name"] == "TestArtist"
        assert len(result["tags"]) == 2
        assert result["tags"][0]["name"] == "blue_hair"
        assert result["image_urls"]["large"] == "https://pximg.net/l.jpg"
        assert result["image_urls"]["original"] == "https://pximg.net/orig.jpg"

    def test_normalize_illust_multi_page_uses_first_page_original(self):
        """_normalize_illust with meta_pages uses first page's original URL."""
        from services.pixiv_client import PixivClient

        illust = {
            "id": 9999,
            "title": "Multi Page",
            "image_urls": {"square_medium": "", "medium": "", "large": ""},
            "meta_single_page": {},
            "meta_pages": [
                {"image_urls": {"original": "https://pximg.net/p1_orig.jpg"}},
                {"image_urls": {"original": "https://pximg.net/p2_orig.jpg"}},
            ],
            "user": {"id": 1, "name": "", "account": "", "profile_image_urls": {}},
            "tags": [],
        }

        result = PixivClient._normalize_illust(illust)

        assert result["image_urls"]["original"] == "https://pximg.net/p1_orig.jpg"

    def test_normalize_illust_handles_object_with_dict_attr(self):
        """_normalize_illust should handle objects with __dict__ (pixivpy3 objects)."""
        from services.pixiv_client import PixivClient

        # Simulate pixivpy3 returning an object rather than a plain dict
        illust_obj = MagicMock()
        illust_obj.__dict__ = {
            "id": 42,
            "title": "Object Illust",
            "type": "manga",
            "caption": "",
            "create_date": "",
            "page_count": 5,
            "width": 800,
            "height": 1200,
            "sanity_level": 4,
            "total_view": 0,
            "total_bookmarks": 0,
            "is_bookmarked": False,
            "image_urls": {},
            "meta_single_page": {},
            "meta_pages": [],
            "user": {"id": 1, "name": "ArtistObj", "account": "ao", "profile_image_urls": {}},
            "tags": [],
        }

        result = PixivClient._normalize_illust(illust_obj)

        assert result["id"] == 42
        assert result["page_count"] == 5

    def test_normalize_user_extracts_all_fields(self):
        """_normalize_user should map user_detail response to our format."""
        from services.pixiv_client import PixivClient

        user_detail = {
            "user": {
                "id": 77,
                "name": "Famous Artist",
                "account": "famous_artist",
                "comment": "I draw things",
                "is_followed": True,
                "profile_image_urls": {"medium": "https://pximg.net/icon.jpg"},
            },
            "profile": {
                "total_illusts": 150,
                "total_manga": 10,
                "total_novels": 0,
            },
        }

        result = PixivClient._normalize_user(user_detail)

        assert result["id"] == 77
        assert result["name"] == "Famous Artist"
        assert result["total_illusts"] == 150
        assert result["total_manga"] == 10
        assert result["is_followed"] is True
        assert result["profile_image"] == "https://pximg.net/icon.jpg"

    def test_next_offset_extracts_from_next_url(self):
        """_next_offset should extract offset from next_url query string."""
        from services.pixiv_client import PixivClient

        response = {
            "illusts": [],
            "next_url": "https://app-api.pixiv.net/v1/illust/follow?restrict=public&offset=30",
        }

        result = PixivClient._next_offset(response)

        assert result == 30

    def test_next_offset_returns_none_when_no_next_url(self):
        """_next_offset should return None when next_url is absent."""
        from services.pixiv_client import PixivClient

        result = PixivClient._next_offset({"illusts": [], "next_url": None})

        assert result is None

    def test_next_offset_returns_max_bookmark_id(self):
        """_next_offset handles max_bookmark_id parameter for bookmarks."""
        from services.pixiv_client import PixivClient

        response = {
            "illusts": [],
            "next_url": "https://app-api.pixiv.net/v1/user/bookmarks/illust?max_bookmark_id=9999",
        }

        result = PixivClient._next_offset(response)

        assert result == 9999

    def test_image_urls_single_page(self):
        """_image_urls should extract all URL variants from a single-page illust."""
        from services.pixiv_client import PixivClient

        illust = {
            "image_urls": {
                "square_medium": "https://pximg.net/sm.jpg",
                "medium": "https://pximg.net/m.jpg",
                "large": "https://pximg.net/l.jpg",
            },
            "meta_single_page": {"original_image_url": "https://pximg.net/orig.jpg"},
            "meta_pages": [],
        }

        result = PixivClient._image_urls(illust)

        assert result["square_medium"] == "https://pximg.net/sm.jpg"
        assert result["original"] == "https://pximg.net/orig.jpg"


# ---------------------------------------------------------------------------
# API wrapper methods
# ---------------------------------------------------------------------------


class TestApiWrapperMethods:
    """Tests for PixivClient public async methods."""

    async def test_search_illust_returns_normalized_result(self):
        """search_illust should call _call and return normalized illust list."""
        client = _build_pixiv_client()

        raw_resp = MagicMock()
        raw_resp.__dict__ = {
            "illusts": [
                {
                    "id": 101,
                    "title": "Search Result",
                    "type": "illust",
                    "caption": "",
                    "create_date": "",
                    "page_count": 1,
                    "width": 800,
                    "height": 600,
                    "sanity_level": 2,
                    "total_view": 100,
                    "total_bookmarks": 10,
                    "is_bookmarked": False,
                    "image_urls": {},
                    "meta_single_page": {},
                    "meta_pages": [],
                    "user": {"id": 1, "name": "", "account": "", "profile_image_urls": {}},
                    "tags": [],
                }
            ],
            "next_url": None,
        }

        with patch.object(client, "_call", new_callable=AsyncMock, return_value=raw_resp):
            result = await client.search_illust("blue_hair")

        assert len(result["illusts"]) == 1
        assert result["illusts"][0]["id"] == 101
        assert result["next_offset"] is None

    async def test_illust_detail_returns_normalized_illust(self):
        """illust_detail should return a normalized single illust."""
        client = _build_pixiv_client()

        illust_data = {
            "id": 555,
            "title": "Detail Work",
            "type": "illust",
            "caption": "",
            "create_date": "",
            "page_count": 1,
            "width": 1200,
            "height": 1800,
            "sanity_level": 2,
            "total_view": 0,
            "total_bookmarks": 0,
            "is_bookmarked": False,
            "image_urls": {},
            "meta_single_page": {},
            "meta_pages": [],
            "user": {"id": 5, "name": "Author", "account": "auth", "profile_image_urls": {}},
            "tags": [],
        }
        call_resp = {"illust": illust_data}

        with patch.object(client, "_call", new_callable=AsyncMock, return_value=call_resp):
            result = await client.illust_detail(555)

        assert result["id"] == 555
        assert result["title"] == "Detail Work"

    async def test_illust_detail_raises_value_error_when_not_found(self):
        """illust_detail raises ValueError when illust is None in response."""
        client = _build_pixiv_client()

        with patch.object(client, "_call", new_callable=AsyncMock, return_value={"illust": None}):
            with pytest.raises(ValueError, match="not found"):
                await client.illust_detail(99999)

    async def test_user_detail_returns_normalized_user(self):
        """user_detail should return a normalized user dict."""
        client = _build_pixiv_client()

        user_resp = {
            "user": {
                "id": 42,
                "name": "Great Artist",
                "account": "great_artist",
                "comment": "",
                "is_followed": False,
                "profile_image_urls": {"medium": ""},
            },
            "profile": {
                "total_illusts": 88,
                "total_manga": 0,
                "total_novels": 0,
            },
        }

        with patch.object(client, "_call", new_callable=AsyncMock, return_value=user_resp):
            result = await client.user_detail(42)

        assert result["id"] == 42
        assert result["name"] == "Great Artist"
        assert result["total_illusts"] == 88

    async def test_user_illusts_returns_normalized_list(self):
        """user_illusts should return a normalized illust list."""
        client = _build_pixiv_client()

        raw_resp = {"illusts": [], "next_url": None}

        with patch.object(client, "_call", new_callable=AsyncMock, return_value=raw_resp):
            result = await client.user_illusts(42)

        assert result["illusts"] == []
        assert result["next_offset"] is None

    async def test_download_image_returns_bytes_and_media_type(self):
        """download_image should return (bytes, content_type) from the HTTP response."""
        client = _build_pixiv_client()

        mock_resp = MagicMock()
        mock_resp.content = b"\xff\xd8\xff\xe0fake_jpeg"
        mock_resp.headers = {"content-type": "image/jpeg"}
        mock_resp.raise_for_status = MagicMock()
        client._img_http.get = AsyncMock(return_value=mock_resp)

        data, ct = await client.download_image("https://pximg.net/img/test.jpg")

        assert data == b"\xff\xd8\xff\xe0fake_jpeg"
        assert ct == "image/jpeg"


# ---------------------------------------------------------------------------
# Error handling in _call
# ---------------------------------------------------------------------------


class TestCallErrorHandling:
    """Tests for PixivClient._call retry logic on 403/token errors."""

    async def test_call_retries_on_403_and_succeeds(self):
        """_call should flush token cache, refresh, and retry on 403 error."""
        client = _build_pixiv_client()
        mock_redis = _make_mock_redis()

        call_count = {"n": 0}

        def _side_effect(fn, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("403 Forbidden")
            return {"result": "ok"}

        token_resp = _make_token_response("new_token")

        with (
            patch("services.pixiv_client.get_redis", return_value=mock_redis),
            patch(
                "asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=[
                    Exception("403 Forbidden"),  # first _call attempt
                    token_resp,                  # _refresh_token
                    {"result": "ok"},            # retry
                ],
            ),
        ):
            result = await client._call(lambda: None)

        assert result == {"result": "ok"}

    async def test_call_raises_permission_error_when_refresh_fails_on_retry(self):
        """_call should raise PermissionError when token refresh fails after 403."""
        client = _build_pixiv_client()
        mock_redis = _make_mock_redis()

        with (
            patch("services.pixiv_client.get_redis", return_value=mock_redis),
            patch(
                "asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=[
                    Exception("invalid_grant"),   # first call fails
                    Exception("still invalid"),   # refresh also fails
                ],
            ),
        ):
            with pytest.raises(PermissionError):
                await client._call(lambda: None)

    async def test_call_raises_non_auth_errors_directly(self):
        """_call should propagate non-auth exceptions without retry."""
        client = _build_pixiv_client()

        with patch(
            "asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=Exception("network timeout"),
        ):
            with pytest.raises(Exception, match="network timeout"):
                await client._call(lambda: None)
