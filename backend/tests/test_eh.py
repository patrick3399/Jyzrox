"""
Tests for E-Hentai proxy endpoints (/api/eh/*).

External EH network calls are mocked via unittest.mock.patch on
_make_client and services.cache helpers.  The `client` fixture (from
conftest) already patches routers.eh.async_session to the SQLite test
engine, so blocked-tag filtering is fully testable with DB data.

Auth requirement for every endpoint is verified with `unauthed_client`.
"""

from unittest.mock import AsyncMock, MagicMock, patch

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
        text("INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (:id, 'testuser', 'x')"),
        {"id": user_id},
    )
    await db_session.commit()


async def _insert_blocked_tag(db_session, namespace, name, user_id=1):
    await db_session.execute(
        text("INSERT OR IGNORE INTO blocked_tags (user_id, namespace, name) VALUES (:uid, :ns, :n)"),
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


# ===========================================================================
# EhClient unit tests — direct service layer, no HTTP server involved.
# Each test instantiates EhClient, replaces its internal _http / _img_http
# with MagicMock/AsyncMock objects, and exercises the actual parsing logic.
# ===========================================================================


def _make_http_response(
    status_code: int = 200,
    text: str = "",
    content: bytes = b"",
    headers: dict | None = None,
) -> MagicMock:
    """Build a minimal mock that looks like an httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.content = content
    resp.headers = headers or {}
    # raise_for_status: no-op by default; raise on 4xx/5xx if requested
    if status_code >= 400:
        import httpx

        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status = MagicMock(return_value=None)
    return resp


def _build_eh_client(cookies: dict | None = None, use_ex: bool = False):
    """Return an EhClient with its internal HTTP clients pre-attached as mocks."""
    from services.eh_client import EhClient

    client = EhClient(cookies or {}, use_ex=use_ex)
    client._http = AsyncMock()
    client._img_http = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# TestGalleryMetadataParsing
# ---------------------------------------------------------------------------


class TestGalleryMetadataParsing:
    """Unit tests for EhClient.get_gallery_metadata / _gdata / _parse_gmetadata."""

    async def test_parse_gmetadata_full_fields(self):
        """_parse_gmetadata should map every API field to the internal dict."""
        from services.eh_client import _parse_gmetadata

        raw = {
            "gid": "99999",
            "token": "abc1234567",
            "title": "My Gallery",
            "title_jpn": "マイギャラリー",
            "category": "Manga",
            "thumb": "https://ehgt.org/t/00/001.jpg",
            "uploader": "painter",
            "posted": "1700000000",
            "filecount": "42",
            "rating": "4.75",
            "tags": ["artist:painter", "language:japanese"],
            "expunged": False,
        }
        result = _parse_gmetadata(raw)

        assert result["gid"] == 99999
        assert result["token"] == "abc1234567"
        assert result["title"] == "My Gallery"
        assert result["title_jpn"] == "マイギャラリー"
        assert result["category"] == "Manga"
        assert result["pages"] == 42
        assert result["rating"] == 4.75
        assert result["uploader"] == "painter"
        assert result["tags"] == ["artist:painter", "language:japanese"]
        assert result["expunged"] is False
        assert result["posted_at"] == 1700000000

    async def test_parse_gmetadata_missing_optional_fields(self):
        """_parse_gmetadata should use safe defaults for missing optional fields."""
        from services.eh_client import _parse_gmetadata

        raw = {"gid": "1", "token": "tok"}
        result = _parse_gmetadata(raw)

        assert result["title"] == ""
        assert result["title_jpn"] == ""
        assert result["category"] == ""
        assert result["pages"] == 0
        assert result["rating"] == 0.0
        assert result["tags"] == []
        assert result["expunged"] is False

    async def test_get_gallery_metadata_returns_parsed_dict(self):
        """get_gallery_metadata should return a parsed dict for a valid gallery."""
        client = _build_eh_client()

        api_response = {
            "gmetadata": [
                {
                    "gid": "12345",
                    "token": "abcdef1234",
                    "title": "Test Gallery",
                    "title_jpn": "",
                    "category": "Doujinshi",
                    "thumb": "https://ehgt.org/t.jpg",
                    "uploader": "uploader1",
                    "posted": "1609459200",
                    "filecount": "30",
                    "rating": "4.5",
                    "tags": ["artist:test_artist"],
                    "expunged": False,
                }
            ]
        }
        client._http.post = AsyncMock(return_value=_make_http_response(200, text="", content=b""))
        client._http.post.return_value.json = MagicMock(return_value=api_response)

        result = await client.get_gallery_metadata(12345, "abcdef1234")

        assert result["gid"] == 12345
        assert result["title"] == "Test Gallery"
        assert result["pages"] == 30

    async def test_get_gallery_metadata_raises_on_expunged(self):
        """get_gallery_metadata should raise ValueError when gallery is expunged."""
        import pytest

        client = _build_eh_client()

        api_response = {
            "gmetadata": [
                {
                    "gid": "777",
                    "token": "expungedtok",
                    "title": "Gone",
                    "title_jpn": "",
                    "category": "Manga",
                    "thumb": "",
                    "uploader": "",
                    "posted": "0",
                    "filecount": "0",
                    "rating": "0",
                    "tags": [],
                    "expunged": True,
                }
            ]
        }
        client._http.post = AsyncMock(return_value=_make_http_response(200))
        client._http.post.return_value.json = MagicMock(return_value=api_response)

        with pytest.raises(ValueError, match="expunged"):
            await client.get_gallery_metadata(777, "expungedtok")

    async def test_get_gallery_metadata_raises_on_not_found(self):
        """get_gallery_metadata should raise ValueError when gmetadata is empty."""
        import pytest

        client = _build_eh_client()

        api_response = {"gmetadata": []}
        client._http.post = AsyncMock(return_value=_make_http_response(200))
        client._http.post.return_value.json = MagicMock(return_value=api_response)

        with pytest.raises(ValueError, match="not found"):
            await client.get_gallery_metadata(9999, "notfound123")


# ---------------------------------------------------------------------------
# TestImageTokenParsing
# ---------------------------------------------------------------------------


class TestImageTokenParsing:
    """Unit tests for EhClient._parse_detail_html and get_image_tokens."""

    async def test_parse_detail_html_extracts_ptokens(self):
        """_parse_detail_html should extract pToken → page number mapping."""
        from services.eh_client import EhClient

        # Minimal HTML fragment containing two /s/ preview links
        html = """
        <div>
          <a href="/s/aabbcc1122/54321-1"><div style="width:100px;height:140px;background:transparent url(https://ehgt.org/p/001.jpg) 0px 0 no-repeat"></div></a>
          <a href="/s/ddeeff3344/54321-2"><div style="width:100px;height:140px;background:transparent url(https://ehgt.org/p/002.jpg) -100px 0 no-repeat"></div></a>
        </div>
        """
        client = EhClient.__new__(EhClient)
        token_map, _ = client._parse_detail_html(html)

        assert token_map[1] == "aabbcc1122"
        assert token_map[2] == "ddeeff3344"

    async def test_get_image_tokens_single_detail_page(self):
        """get_image_tokens with ≤20 pages should make exactly one HTTP request."""
        client = _build_eh_client()

        html = "\n".join(
            f'<a href="/s/{i:010x}/99999-{i}"><div style="width:100px;height:140px;background:transparent url(https://ehgt.org/p/{i:03d}.jpg) 0px 0 no-repeat"></div></a>'
            for i in range(1, 6)
        )
        client._http.get = AsyncMock(return_value=_make_http_response(200, text=html))

        token_map, preview_map = await client.get_image_tokens(99999, "tok9999abcd", 5)

        assert client._http.get.call_count == 1
        assert len(token_map) == 5

    async def test_get_image_tokens_multiple_detail_pages(self):
        """get_image_tokens with 21 pages should make two HTTP requests."""
        client = _build_eh_client()

        # 21 pages → requires detail pages p=0 and p=1
        html_p0 = "\n".join(
            f'<a href="/s/{i:010x}/11111-{i}"><div style="width:100px;height:140px;background:transparent url(https://ehgt.org/p/{i:03d}.jpg) 0px 0 no-repeat"></div></a>'
            for i in range(1, 21)
        )
        html_p1 = '<a href="/s/0000000015/11111-21"><div style="width:100px;height:140px;background:transparent url(https://ehgt.org/p/021.jpg) 0px 0 no-repeat"></div></a>'

        client._http.get = AsyncMock(
            side_effect=[
                _make_http_response(200, text=html_p0),
                _make_http_response(200, text=html_p1),
            ]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            token_map, _ = await client.get_image_tokens(11111, "tok1111abcd", 21)

        assert client._http.get.call_count == 2
        assert 21 in token_map

    async def test_get_image_tokens_empty_gallery(self):
        """get_image_tokens with total_pages=0 should return empty maps immediately."""
        client = _build_eh_client()

        token_map, preview_map = await client.get_image_tokens(22222, "emptytok123", 0)

        client._http.get.assert_not_called()
        assert token_map == {}
        assert preview_map == {}

    async def test_parse_detail_html_malformed_html_returns_empty(self):
        """_parse_detail_html on garbage HTML should return empty maps without raising."""
        from services.eh_client import EhClient

        client = EhClient.__new__(EhClient)
        token_map, preview_map = client._parse_detail_html("<html><body>no previews here at all</body></html>")

        assert token_map == {}
        assert preview_map == {}


# ---------------------------------------------------------------------------
# TestRateLimitDetection
# ---------------------------------------------------------------------------


class TestRateLimitDetection:
    """Unit tests for EhClient._check_auth (509 / Sad Panda / access denied)."""

    async def test_check_auth_raises_on_509_gif(self):
        """_check_auth should raise PermissionError when HTML contains /509.gif."""
        import pytest

        from services.eh_client import EhClient

        client = EhClient.__new__(EhClient)
        with pytest.raises(PermissionError, match="509"):
            client._check_auth(
                '<html><img src="/509.gif"></html>',
                _make_http_response(200, text="<html><img src='/509.gif'></html>"),
            )

    async def test_check_auth_raises_on_sad_panda(self):
        """_check_auth should raise PermissionError for tiny non-HTML response (Sad Panda)."""
        import pytest

        from services.eh_client import EhClient

        client = EhClient.__new__(EhClient)
        # ExHentai returns a very short non-HTML body for unauthenticated users
        tiny_body = "no html here"
        resp = _make_http_response(200, text=tiny_body)
        with pytest.raises(PermissionError, match="Sad Panda"):
            client._check_auth(tiny_body, resp)

    async def test_check_auth_passes_for_normal_response(self):
        """_check_auth should not raise for a normal gallery HTML page."""
        from services.eh_client import EhClient

        client = EhClient.__new__(EhClient)
        normal_html = (
            "<html><head><title>E-Hentai Galleries</title></head>"
            "<body><div class='gm'>Gallery content here</div></body></html>"
        )
        resp = _make_http_response(200, text=normal_html)
        # Should complete without raising
        client._check_auth(normal_html, resp)


# ---------------------------------------------------------------------------
# TestCookieHandling
# ---------------------------------------------------------------------------


class TestCookieHandling:
    """Unit tests for EhClient cookie initialisation and check_cookies."""

    async def test_cookies_injected_with_nw_1(self):
        """__aenter__ should merge user cookies with nw=1."""
        import httpx

        from services.eh_client import EhClient

        user_cookies = {"ipb_member_id": "123456", "ipb_pass_hash": "abcdef"}
        client = EhClient(user_cookies)

        with patch.object(httpx, "AsyncClient") as mock_ac:
            mock_instance = AsyncMock()
            mock_ac.return_value = mock_instance
            await client.__aenter__()

        # httpx.AsyncClient should have been called with cookies that include nw=1
        call_kwargs = mock_ac.call_args_list[0].kwargs
        assert call_kwargs["cookies"].get("nw") == "1"
        assert call_kwargs["cookies"].get("ipb_member_id") == "123456"

    async def test_check_cookies_returns_true_when_credits_present(self):
        """check_cookies should return True if 'Credits' appears in home.php."""
        client = _build_eh_client()
        client._http.get = AsyncMock(return_value=_make_http_response(200, text="<html>1,234 Credits available</html>"))

        result = await client.check_cookies()

        assert result is True

    async def test_check_cookies_returns_false_on_network_error(self):
        """check_cookies should return False when the HTTP request raises."""
        import httpx

        client = _build_eh_client()
        client._http.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

        result = await client.check_cookies()

        assert result is False


# ---------------------------------------------------------------------------
# TestErrorResponses
# ---------------------------------------------------------------------------


class TestErrorResponses:
    """Unit tests for EhClient error-path behaviour (404, 503, timeout)."""

    async def test_get_previews_raises_value_error_on_404(self):
        """get_previews should raise ValueError when gallery page returns 404."""
        import pytest

        client = _build_eh_client()
        resp_404 = _make_http_response(404)
        client._http.get = AsyncMock(return_value=resp_404)

        with pytest.raises(ValueError, match="not found"):
            await client.get_previews(99999, "deadbeef12")

    async def test_get_image_tokens_raises_value_error_on_404(self):
        """get_image_tokens should raise ValueError for a 404 detail page."""
        import pytest

        client = _build_eh_client()
        resp_404 = _make_http_response(404)
        client._http.get = AsyncMock(return_value=resp_404)

        with pytest.raises(ValueError, match="not found"):
            await client.get_image_tokens(33333, "deadbeef56", 5)

    async def test_api_raises_value_error_on_error_field(self):
        """_api should raise ValueError when the JSON response contains 'error'."""
        import pytest

        client = _build_eh_client()
        resp = _make_http_response(200)
        resp.json = MagicMock(return_value={"error": "gallery not found"})
        client._http.post = AsyncMock(return_value=resp)

        with pytest.raises(ValueError, match="E-H API error"):
            await client._api({"method": "gdata", "gidlist": [[1, "tok"]], "namespace": 1})


# ---------------------------------------------------------------------------
# TestArchiveDownload
# ---------------------------------------------------------------------------


class TestArchiveDownload:
    """Unit tests for EhClient.download_image_with_retry and showpage API parsing."""

    async def test_download_image_with_retry_succeeds_on_first_attempt(self):
        """download_image_with_retry should return image data when first attempt succeeds."""

        client = _build_eh_client()

        # PNG magic bytes (8 bytes) + padding to exceed the 100-byte minimum
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200

        showpage_resp = {
            "i3": '<img id="img" src="https://cdn.example.com/001.png" style="max-width:100%">',
            "i6": "",
        }
        api_resp = _make_http_response(200)
        api_resp.json = MagicMock(return_value=showpage_resp)
        client._http.post = AsyncMock(return_value=api_resp)

        img_resp = _make_http_response(200, content=png_bytes)
        client._img_http.get = AsyncMock(return_value=img_resp)

        image_data, media_type, ext = await client.download_image_with_retry(
            showkey="testshowkey1", gid=12345, page=1, imgkey="abcdef1234"
        )

        assert image_data == png_bytes
        assert media_type == "image/png"
        assert ext == "png"

    async def test_download_image_with_retry_raises_image509_error(self):
        """download_image_with_retry should raise Image509Error immediately for 509 URLs."""
        import pytest

        from services.eh_client import Image509Error

        client = _build_eh_client()

        showpage_resp = {
            "i3": '<img id="img" src="https://cdn.example.com/509.gif" style="max-width:100%">',
            "i6": "",
        }
        api_resp = _make_http_response(200)
        api_resp.json = MagicMock(return_value=showpage_resp)
        client._http.post = AsyncMock(return_value=api_resp)

        with pytest.raises(Image509Error, match="509"):
            await client.download_image_with_retry(showkey="testshowkey2", gid=12345, page=1, imgkey="abcdef1234")


# ---------------------------------------------------------------------------
# TestEhGalleryPreviews
# ---------------------------------------------------------------------------


class TestEhGalleryPreviews:
    """GET /api/eh/gallery/{gid}/{token}/previews"""

    async def test_gallery_previews_returns_thumbnails(self, client):
        """Should return preview thumbnail URLs indexed by page number."""
        eh_mock = _make_eh_client_mock()

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_preview_cache", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_preview_cache", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/eh/gallery/12345/abcdef/previews")

        assert resp.status_code == 200
        data = resp.json()
        assert data["gid"] == 12345
        assert "previews" in data
        assert "1" in data["previews"]

    async def test_gallery_previews_sad_panda_returns_403(self, client):
        """Sad Panda PermissionError during preview fetch should return 403."""
        eh_mock = _make_eh_client_mock()
        eh_mock.get_previews = AsyncMock(side_effect=PermissionError("Sad Panda"))

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_preview_cache", new_callable=AsyncMock, return_value=None),
            patch("plugins.builtin.ehentai.browse.push_system_alert", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/eh/gallery/12345/abcdef/previews")

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# TestEhGalleryImages
# ---------------------------------------------------------------------------


class TestEhGalleryImages:
    """GET /api/eh/gallery/{gid}/{token}/images"""

    async def test_gallery_images_returns_token_map(self, client):
        """Should return image token map and preview URLs for a gallery."""
        eh_mock = _make_eh_client_mock()

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_imagelist_cache", new_callable=AsyncMock, return_value=None),
            patch("services.cache.set_imagelist_cache", new_callable=AsyncMock),
            patch("services.cache.get_gallery_cache", new_callable=AsyncMock, return_value=_FAKE_GALLERY_META),
            patch("services.cache.get_preview_cache", new_callable=AsyncMock, return_value={}),
            patch("services.cache.set_preview_cache", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/eh/gallery/12345/abcdef/images")

        assert resp.status_code == 200
        data = resp.json()
        assert data["gid"] == 12345
        assert "images" in data
        assert "1" in data["images"]

    async def test_gallery_images_cache_hit_returns_without_client_call(self, client):
        """Cached image token list should be returned without calling EH client."""
        cached_tokens = {"1": "pt_abc", "2": "pt_def"}

        with (
            patch("services.cache.get_imagelist_cache", new_callable=AsyncMock, return_value=cached_tokens),
            patch("services.cache.get_preview_cache", new_callable=AsyncMock, return_value={}),
        ):
            resp = await client.get("/api/eh/gallery/12345/abcdef/images")

        assert resp.status_code == 200
        data = resp.json()
        assert data["gid"] == 12345
        assert data["images"] == cached_tokens


# ---------------------------------------------------------------------------
# TestEhGalleryImagesPaginated
# ---------------------------------------------------------------------------


class TestEhGalleryImagesPaginated:
    """GET /api/eh/gallery/{gid}/{token}/images-paginated"""

    async def test_gallery_images_paginated_cache_hit_returns_result(self, client):
        """When gallery and detail page are cached, returns window without EH HTTP calls."""
        gallery_cache = _FAKE_GALLERY_META.copy()  # pages=30
        cached_detail_page = {
            "tokens": {"1": "tok001", "2": "tok002"},
            "previews": {"1": "https://ehgt.org/p/001.jpg", "2": "https://ehgt.org/p/002.jpg"},
        }

        with (
            patch("services.cache.get_gallery_cache", new_callable=AsyncMock, return_value=gallery_cache),
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=cached_detail_page),
            patch("services.cache.set_json", new_callable=AsyncMock),
            patch("services.cache.get_imagelist_cache", new_callable=AsyncMock, return_value={}),
            patch("services.cache.set_imagelist_cache", new_callable=AsyncMock),
            patch("services.cache.get_preview_cache", new_callable=AsyncMock, return_value={}),
            patch("services.cache.set_preview_cache", new_callable=AsyncMock),
        ):
            resp = await client.get(
                "/api/eh/gallery/12345/abcdef/images-paginated",
                params={"start_page": 0, "count": 2},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["gid"] == 12345
        assert "images" in data
        assert "has_more" in data
        assert data["total"] == 30

    async def test_gallery_images_paginated_out_of_range_returns_empty(self, client):
        """start_page >= total_pages should return empty image list immediately."""
        gallery_cache = _FAKE_GALLERY_META.copy()  # pages=30

        with patch("services.cache.get_gallery_cache", new_callable=AsyncMock, return_value=gallery_cache):
            resp = await client.get(
                "/api/eh/gallery/12345/abcdef/images-paginated",
                params={"start_page": 100, "count": 20},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["images"] == []
        assert data["has_more"] is False
        assert data["total"] == 30


# ---------------------------------------------------------------------------
# TestEhImageProxy
# ---------------------------------------------------------------------------


class TestEhImageProxy:
    """GET /api/eh/image-proxy/{gid}/{page}"""

    async def test_image_proxy_serves_cached_image(self, client):
        """Should return cached image bytes without making any EH requests."""
        fake_jpeg = b"\xff\xd8\xff" + b"\x00" * 100

        with patch("services.cache.get_proxied_image", new_callable=AsyncMock, return_value=fake_jpeg):
            resp = await client.get("/api/eh/image-proxy/12345/1")

        assert resp.status_code == 200
        assert resp.content == fake_jpeg

    async def test_image_proxy_missing_imagelist_returns_404(self, client):
        """If image token map is not in cache, should return 404 instructing caller to fetch /images first."""
        with (
            patch("services.cache.get_proxied_image", new_callable=AsyncMock, return_value=None),
            patch("services.cache.get_imagelist_cache", new_callable=AsyncMock, return_value=None),
        ):
            resp = await client.get("/api/eh/image-proxy/12345/1")

        assert resp.status_code == 404
        assert "images" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# TestEhErrorParsing
# ---------------------------------------------------------------------------


class TestEhErrorParsing:
    """Test EH-specific PermissionError → HTTP status code mapping."""

    async def test_toplist_509_bandwidth_error_returns_403(self, client):
        """PermissionError with '509' on toplist endpoint should return 403 (bandwidth exceeded)."""
        eh_mock = _make_eh_client_mock()
        eh_mock.get_toplist = AsyncMock(side_effect=PermissionError("bandwidth 509 exceeded"))

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("plugins.builtin.ehentai.browse.push_system_alert", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/eh/toplists", params={"tl": 11})

        assert resp.status_code == 403

    async def test_toplist_sad_panda_returns_403(self, client):
        """PermissionError with 'Sad Panda' on toplist endpoint should return 403 (access denied)."""
        eh_mock = _make_eh_client_mock()
        eh_mock.get_toplist = AsyncMock(side_effect=PermissionError("Sad Panda"))

        with (
            patch("plugins.builtin.ehentai.browse._make_client", return_value=eh_mock),
            patch("services.cache.get_json", new_callable=AsyncMock, return_value=None),
            patch("plugins.builtin.ehentai.browse.push_system_alert", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/eh/toplists", params={"tl": 11})

        assert resp.status_code == 403
