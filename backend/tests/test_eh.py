"""
Tests for E-Hentai proxy endpoints (/api/eh/*).

External EH network calls are mocked via unittest.mock.patch on
_make_client and services.cache helpers.  The `client` fixture (from
conftest) already patches routers.eh.async_session to the SQLite test
engine, so blocked-tag filtering is fully testable with DB data.

Auth requirement for every endpoint is verified with `unauthed_client`.
"""

from unittest.mock import AsyncMock, patch

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Shared fake results
# ---------------------------------------------------------------------------

_FAKE_GALLERY_META = {
    "gid": 12345,
    "token": "abcdef",
    "title": "Test Gallery",
    "title_jpn": "テストギャラリー",
    "category": "Doujinshi",
    "pages": 30,
    "rating": 4.5,
    "tags": ["artist:test_artist", "language:english"],
    "thumb": "https://ehgt.org/thumb/001.jpg",
    "uploader": "tester",
    "posted": "2024-01-01T00:00:00",
}

_FAKE_SEARCH_RESULT = {
    "galleries": [
        {
            "gid": 11111,
            "token": "aaa",
            "title": "Search Result 1",
            "tags": ["general:blue_hair"],
            "thumb": "https://ehgt.org/thumb/a.jpg",
        },
        {
            "gid": 22222,
            "token": "bbb",
            "title": "Search Result 2",
            "tags": ["general:red_eyes"],
            "thumb": "https://ehgt.org/thumb/b.jpg",
        },
    ],
    "total": 2,
    "page": 0,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_user(db_session, user_id=1):
    """Insert a test user so FK constraints on blocked_tags can reference it."""
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash) "
            "VALUES (:id, 'testuser', 'x')"
        ),
        {"id": user_id},
    )
    await db_session.commit()


async def _insert_blocked_tag(db_session, namespace, name, user_id=1):
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO blocked_tags (user_id, namespace, name) "
            "VALUES (:uid, :ns, :n)"
        ),
        {"uid": user_id, "ns": namespace, "n": name},
    )
    await db_session.commit()


def _make_eh_client_mock(search_result=None, gallery_meta=None, comments=None):
    """Return an async context-manager mock for EhClient."""
    mock = AsyncMock()
    mock.search = AsyncMock(return_value=search_result or _FAKE_SEARCH_RESULT)
    mock.get_gallery_metadata = AsyncMock(return_value=gallery_meta or _FAKE_GALLERY_META)
    mock.get_comments = AsyncMock(return_value=comments or [])
    mock.get_popular = AsyncMock(return_value={"galleries": [], "total": 0})
    mock.get_toplist = AsyncMock(return_value={"galleries": [], "total": 0})
    mock.get_previews = AsyncMock(return_value={1: "https://ehgt.org/p/001.jpg"})
    mock.get_image_tokens = AsyncMock(return_value=({"1": "pt_abc"}, {1: "https://ehgt.org/p/001.jpg"}))
    mock.get_favorites = AsyncMock(return_value={"galleries": [], "total": 0})
    mock.add_favorite = AsyncMock(return_value=None)
    mock.remove_favorite = AsyncMock(return_value=None)
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestEhSearch:
    """GET /api/eh/search"""

    async def test_search_returns_results(self, client):
        """Should return search results from EH client."""
        eh_mock = _make_eh_client_mock()

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_json", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/eh/search", params={"q": "blue hair"})

        assert resp.status_code == 200
        data = resp.json()
        assert "galleries" in data
        assert len(data["galleries"]) == 2

    async def test_search_returns_cached_result(self, client):
        """Should return cached result when cache key exists."""
        cached = _FAKE_SEARCH_RESULT.copy()

        with patch("services.cache.get_json", new_callable=AsyncMock, return_value=cached):
            resp = await client.get("/api/eh/search", params={"q": "cached query"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["galleries"][0]["gid"] == 11111

    async def test_search_filters_blocked_tags(self, client, db_session):
        """Blocked tags should filter out galleries whose tags match."""
        await _insert_user(db_session)
        await _insert_blocked_tag(db_session, "general", "blue_hair")

        eh_mock = _make_eh_client_mock()

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_json", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/eh/search", params={"q": "test"})

        assert resp.status_code == 200
        data = resp.json()
        # The gallery tagged "general:blue_hair" should be filtered out
        for gallery in data["galleries"]:
            assert "general:blue_hair" not in gallery.get("tags", [])

    async def test_search_with_language_filter(self, client):
        """Language filter should be prepended to the effective query."""
        eh_mock = _make_eh_client_mock()

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_json", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/eh/search", params={"q": "test", "language": "japanese"})

        assert resp.status_code == 200
        assert "galleries" in resp.json()

    async def test_search_permission_error_returns_403(self, client):
        """Sad Panda / 509 PermissionError should return 403."""
        eh_mock = _make_eh_client_mock()
        eh_mock.search = AsyncMock(side_effect=PermissionError("Sad Panda"))

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("plugins.builtin.ehentai.browse.push_system_alert", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/eh/search")

        assert resp.status_code == 403

    async def test_search_value_error_returns_503(self, client):
        """Scraping failure (ValueError) should return 503."""
        eh_mock = _make_eh_client_mock()
        eh_mock.search = AsyncMock(side_effect=ValueError("scrape failed"))

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
        ):
            resp = await client.get("/api/eh/search")

        assert resp.status_code == 503

    async def test_search_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/eh/search")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Gallery metadata
# ---------------------------------------------------------------------------


class TestEhGalleryMetadata:
    """GET /api/eh/gallery/{gid}/{token}"""

    async def test_get_gallery_returns_metadata(self, client):
        """Should return gallery metadata from EH client."""
        eh_mock = _make_eh_client_mock()

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_gallery_cache", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_gallery_cache", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/eh/gallery/12345/abcdef")

        assert resp.status_code == 200
        data = resp.json()
        assert data["gid"] == 12345
        assert data["title"] == "Test Gallery"
        assert data["pages"] == 30

    async def test_get_gallery_returns_from_cache(self, client):
        """Cached gallery metadata should be returned without calling EH client."""
        cached = _FAKE_GALLERY_META.copy()

        with patch("services.cache.get_gallery_cache", new_callable=AsyncMock, return_value=cached):
            resp = await client.get("/api/eh/gallery/12345/abcdef")

        assert resp.status_code == 200
        assert resp.json()["gid"] == 12345

    async def test_get_gallery_sad_panda_returns_403(self, client):
        """Sad Panda PermissionError on gallery fetch should return 403."""
        eh_mock = _make_eh_client_mock()
        eh_mock.get_gallery_metadata = AsyncMock(side_effect=PermissionError("Sad Panda"))

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_gallery_cache", new_callable=AsyncMock, return_value=None),
            patch("plugins.builtin.ehentai.browse.push_system_alert", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/eh/gallery/99/badtoken")

        assert resp.status_code == 403

    async def test_get_gallery_value_error_returns_503(self, client):
        """ValueError during gallery fetch should return 503."""
        eh_mock = _make_eh_client_mock()
        eh_mock.get_gallery_metadata = AsyncMock(side_effect=ValueError("parse failed"))

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_gallery_cache", new_callable=AsyncMock, return_value=None),
        ):
            resp = await client.get("/api/eh/gallery/99/badtoken")

        assert resp.status_code == 503

    async def test_get_gallery_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/eh/gallery/12345/abcdef")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Gallery comments
# ---------------------------------------------------------------------------


class TestEhGalleryComments:
    """GET /api/eh/gallery/{gid}/{token}/comments"""

    async def test_get_comments_returns_list(self, client):
        """Should return comment list from EH client."""
        fake_comments = [{"poster": "user1", "body": "great gallery!"}]
        eh_mock = _make_eh_client_mock(comments=fake_comments)

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_json", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/eh/gallery/12345/abcdef/comments")

        assert resp.status_code == 200
        data = resp.json()
        assert data["gid"] == 12345
        assert data["comments"] == fake_comments

    async def test_get_comments_from_cache(self, client):
        """Cached comments should be returned without calling EH."""
        cached_comments = [{"poster": "cached_user", "body": "cached comment"}]

        with patch("services.cache.get_json", new_callable=AsyncMock, return_value=cached_comments):
            resp = await client.get("/api/eh/gallery/12345/abcdef/comments")

        assert resp.status_code == 200
        assert resp.json()["comments"] == cached_comments

    async def test_get_comments_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/eh/gallery/12345/abcdef/comments")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Popular / Toplists
# ---------------------------------------------------------------------------


class TestEhPopularAndToplist:
    """GET /api/eh/popular and GET /api/eh/toplists"""

    async def test_get_popular_returns_results(self, client):
        """Should return popular galleries list."""
        fake_popular = {"galleries": [{"gid": 9999, "tags": [], "title": "Popular One"}], "total": 1}
        eh_mock = _make_eh_client_mock()
        eh_mock.get_popular = AsyncMock(return_value=fake_popular)

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_json", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/eh/popular")

        assert resp.status_code == 200
        data = resp.json()
        assert "galleries" in data
        assert data["galleries"][0]["gid"] == 9999

    async def test_get_popular_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/eh/popular")
        assert resp.status_code == 401

    async def test_get_toplist_valid_tl(self, client):
        """Valid tl values should return toplist galleries."""
        eh_mock = _make_eh_client_mock()
        eh_mock.get_toplist = AsyncMock(return_value={"galleries": [], "total": 0})

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_json", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/eh/toplists", params={"tl": 11})

        assert resp.status_code == 200

    async def test_get_toplist_invalid_tl_returns_400(self, client):
        """Invalid tl value (not in {11,12,13,15}) should return 400."""
        resp = await client.get("/api/eh/toplists", params={"tl": 99})
        assert resp.status_code == 400
        assert "Invalid tl" in resp.json()["detail"]

    async def test_get_toplist_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/eh/toplists")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Thumb proxy
# ---------------------------------------------------------------------------


class TestEhThumbProxy:
    """GET /api/eh/thumb-proxy"""

    async def test_thumb_proxy_disallows_non_eh_domain(self, client):
        """Requests to non-allowed domains should return 403."""
        resp = await client.get(
            "/api/eh/thumb-proxy",
            params={"url": "https://evil.example.com/image.jpg"},
        )
        assert resp.status_code == 403

    async def test_thumb_proxy_invalid_scheme_returns_400(self, client):
        """Non-http(s) URL scheme should return 400."""
        resp = await client.get(
            "/api/eh/thumb-proxy",
            params={"url": "ftp://ehgt.org/image.jpg"},
        )
        assert resp.status_code == 400

    async def test_thumb_proxy_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get(
            "/api/eh/thumb-proxy",
            params={"url": "https://ehgt.org/test.jpg"},
        )
        assert resp.status_code == 401
