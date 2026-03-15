"""
Tests for services.eh_client — EhClient and module-level helpers.

Strategy:
- Instantiate EhClient directly without entering the async context manager.
  Set _http / _img_http manually to AsyncMock instances so no real HTTP is
  made.
- _check_auth is synchronous; call it directly.
- _parse_gmetadata / _detect_media_type are module-level functions; import and
  call directly.
- _gdata batching is tested by replacing client._api with a local async mock
  and asserting chunk sizes.
- download_image_with_retry is tested by replacing get_image_url_via_api and
  _download_image_bytes on the instance.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest


# ---------------------------------------------------------------------------
# _check_auth
# ---------------------------------------------------------------------------


class TestCheckAuth:
    """Synchronous auth-detection heuristics."""

    def _client(self):
        from services.eh_client import EhClient
        return EhClient(cookies={})

    def _resp(self, content_disposition: str = "") -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.headers = {"content-disposition": content_disposition}
        return resp

    def test_sad_panda_short_html_no_html_tag_raises(self):
        """Fewer than 100 chars with no <html> tag → Sad Panda error."""
        client = self._client()
        with pytest.raises(PermissionError, match="Sad Panda"):
            client._check_auth("tiny", self._resp())

    def test_sad_panda_content_disposition_header_raises(self):
        """content-disposition header containing 'sadpanda' → Sad Panda error."""
        client = self._client()
        # Long enough that the length check passes, but header triggers detection.
        html = "<html>" + "x" * 200
        with pytest.raises(PermissionError, match="Sad Panda"):
            client._check_auth(html, self._resp("inline; filename=sadpanda.jpg"))

    def test_509_bandwidth_limit_raises(self):
        """HTML containing '/509.gif' → 509 bandwidth error."""
        client = self._client()
        html = "<html>" + "x" * 200 + '<img src="/509.gif">'
        with pytest.raises(PermissionError, match="509"):
            client._check_auth(html, self._resp())

    def test_509s_variant_raises(self):
        """HTML containing '/509s.gif' also triggers 509 detection."""
        client = self._client()
        html = "<html>" + "x" * 200 + '<img src="/509s.gif">'
        with pytest.raises(PermissionError, match="509"):
            client._check_auth(html, self._resp())

    def test_expired_cookie_access_denied_raises(self):
        """HTML containing 'You do not have access' → expired cookie error."""
        client = self._client()
        html = "<html>" + "x" * 200 + "You do not have access to this gallery"
        with pytest.raises(PermissionError, match="expired"):
            client._check_auth(html, self._resp())

    def test_valid_html_does_not_raise(self):
        """Normal gallery HTML should pass silently."""
        client = self._client()
        html = "<html><body>" + "x" * 300 + "</body></html>"
        # Must not raise
        client._check_auth(html, self._resp())


# ---------------------------------------------------------------------------
# _parse_gmetadata
# ---------------------------------------------------------------------------


class TestParseGmetadata:
    """Module-level _parse_gmetadata normalisation."""

    def _raw(self, **overrides) -> dict:
        base = {
            "gid": 123,
            "token": "abc1234567",
            "title": "Test Title",
            "title_jpn": "テスト",
            "category": "Doujinshi",
            "thumb": "https://thumb.example.com/cover.jpg",
            "uploader": "testuser",
            "posted": "1700000000",
            "filecount": "42",
            "rating": "4.5",
            "tags": ["artist:tester", "female:solo"],
            "expunged": False,
        }
        base.update(overrides)
        return base

    def test_returns_all_expected_keys(self):
        from services.eh_client import _parse_gmetadata

        result = _parse_gmetadata(self._raw())
        assert set(result.keys()) >= {
            "gid", "token", "title", "title_jpn", "category",
            "thumb", "uploader", "posted_at", "pages", "rating",
            "tags", "expunged",
        }

    def test_type_coercions_are_correct(self):
        """filecount → int, rating → float, posted → int, expunged → bool."""
        from services.eh_client import _parse_gmetadata

        result = _parse_gmetadata(self._raw())
        assert result["gid"] == 123
        assert result["pages"] == 42
        assert result["rating"] == 4.5
        assert result["posted_at"] == 1700000000
        assert result["expunged"] is False

    def test_missing_optional_fields_use_defaults(self):
        """Fields missing from the API response default to empty/zero values."""
        from services.eh_client import _parse_gmetadata

        minimal = {"gid": 1, "token": "tok1234567"}
        result = _parse_gmetadata(minimal)
        assert result["title"] == ""
        assert result["pages"] == 0
        assert result["rating"] == 0.0
        assert result["tags"] == []
        assert result["expunged"] is False

    def test_expunged_true_propagated(self):
        from services.eh_client import _parse_gmetadata

        result = _parse_gmetadata(self._raw(expunged=True))
        assert result["expunged"] is True


# ---------------------------------------------------------------------------
# _detect_media_type
# ---------------------------------------------------------------------------


class TestDetectMediaType:
    """Module-level _detect_media_type magic-byte detection."""

    def test_png_signature_detected(self):
        from services.eh_client import _detect_media_type

        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        assert _detect_media_type(data) == "image/png"

    def test_gif87a_detected(self):
        from services.eh_client import _detect_media_type

        data = b"GIF87a" + b"\x00" * 50
        assert _detect_media_type(data) == "image/gif"

    def test_gif89a_detected(self):
        from services.eh_client import _detect_media_type

        data = b"GIF89a" + b"\x00" * 50
        assert _detect_media_type(data) == "image/gif"

    def test_webp_detected(self):
        from services.eh_client import _detect_media_type

        data = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 50
        assert _detect_media_type(data) == "image/webp"

    def test_unknown_header_falls_back_to_jpeg(self):
        """Any unrecognised header should default to image/jpeg."""
        from services.eh_client import _detect_media_type

        data = b"\xff\xd8\xff\xe0" + b"\x00" * 50
        assert _detect_media_type(data) == "image/jpeg"

    def test_random_bytes_fall_back_to_jpeg(self):
        from services.eh_client import _detect_media_type

        assert _detect_media_type(b"\xDE\xAD\xBE\xEF" * 20) == "image/jpeg"


# ---------------------------------------------------------------------------
# _gdata batching
# ---------------------------------------------------------------------------


class TestGdataBatching:
    """Verify _gdata splits large lists into ≤25-item API calls."""

    def _client(self):
        from services.eh_client import EhClient
        c = EhClient(cookies={})
        c._http = AsyncMock()
        return c

    async def test_gdata_30_items_makes_two_api_calls(self):
        """30 galleries → exactly 2 calls: chunk of 25, chunk of 5."""
        client = self._client()
        gid_list = [[i, f"tok{i:010d}"] for i in range(30)]

        call_sizes: list[int] = []

        async def _mock_api(payload: dict) -> dict:
            call_sizes.append(len(payload["gidlist"]))
            return {
                "gmetadata": [
                    {"gid": g[0], "token": g[1], "posted": "0", "filecount": "0", "rating": "0"}
                    for g in payload["gidlist"]
                ]
            }

        client._api = _mock_api
        results = await client._gdata(gid_list)

        assert call_sizes == [25, 5]
        assert len(results) == 30

    async def test_gdata_25_items_makes_one_api_call(self):
        """Exactly 25 items fits into a single chunk."""
        client = self._client()
        gid_list = [[i, f"tok{i:010d}"] for i in range(25)]

        call_count = 0

        async def _mock_api(payload: dict) -> dict:
            nonlocal call_count
            call_count += 1
            return {
                "gmetadata": [
                    {"gid": g[0], "token": g[1], "posted": "0", "filecount": "0", "rating": "0"}
                    for g in payload["gidlist"]
                ]
            }

        client._api = _mock_api
        results = await client._gdata(gid_list)

        assert call_count == 1
        assert len(results) == 25

    async def test_gdata_skips_entries_with_error_field(self):
        """API entries that have an 'error' key must be omitted from the result."""
        client = self._client()
        gid_list = [[1, "tok0000000a"], [2, "tok0000000b"]]

        async def _mock_api(payload: dict) -> dict:
            return {
                "gmetadata": [
                    {"gid": 1, "token": "tok0000000a", "posted": "0", "filecount": "1", "rating": "0"},
                    {"gid": 2, "token": "tok0000000b", "error": "expunged"},
                ]
            }

        client._api = _mock_api
        results = await client._gdata(gid_list)

        assert len(results) == 1
        assert results[0]["gid"] == 1


# ---------------------------------------------------------------------------
# _parse_detail_html
# ---------------------------------------------------------------------------


class TestParseDetailHtml:
    """HTML parsing for pTokens and preview thumbnails."""

    def _client(self):
        from services.eh_client import EhClient
        return EhClient(cookies={})

    def test_large_preview_format_extracts_ptoken_and_thumb(self):
        """Legacy large-preview format: gdtl div with img alt=N src=URL."""
        html = (
            '<div class="gdtl" style="height:270px">'
            '<a href="/s/abcdef1234/100-1">'
            '<img alt="1" src="https://thumb.example.com/img1.jpg" style="border:0">'
            '</a></div>'
        )
        client = self._client()
        token_map, preview_map = client._parse_detail_html(html, gid=100)
        assert token_map.get(1) == "abcdef1234"
        assert preview_map.get(1) == "https://thumb.example.com/img1.jpg"

    def test_normal_sprite_preview_format_stores_sprite_string(self):
        """Legacy normal-preview (gdtm) stores 'url|offsetX|width|height'."""
        # Build a minimal gdtm block whose style matches _NORMAL_PREVIEW_RE.
        html = (
            '<div class="gdtm" style="height:170px;'
            'background:transparent url(https://sprite.example.com/s.jpg) -100px 0px no-repeat;'
            'width:100px;height:143px">'
            '<a href="/s/1111111111/100-2"><img alt="2"></a>'
            '</div>'
        )
        client = self._client()
        token_map, preview_map = client._parse_detail_html(html, gid=100)
        assert token_map.get(2) == "1111111111"
        assert 2 in preview_map
        # Sprite format: url|offset|width|height
        parts = preview_map[2].split("|")
        assert len(parts) == 4
        assert "sprite.example.com" in parts[0]
        assert parts[1] == "-100"

    def test_new_2024_preview_format_stores_sprite_string(self):
        """New-format preview (2024+): <a href="FULL_URL/s/..."><div style="...url(...)..."></div></a>.

        The regex requires an absolute URL so that [^\"]+ before /s/ can match the
        base-URL portion (e.g. 'https://e-hentai.org').  Relative /s/ hrefs do not
        match — the test uses the same shape as real EH HTML.
        """
        html = (
            '<a class="gdtl" href="https://e-hentai.org/s/2222222222/200-3">'
            '<div id="imgWrap" style="width:120px;height:170px;'
            'background:transparent url(https://new.example.com/n.jpg) -240px 0 no-repeat">'
            '</div></a>'
        )
        client = self._client()
        token_map, preview_map = client._parse_detail_html(html, gid=200)
        assert token_map.get(3) == "2222222222"
        assert 3 in preview_map
        parts = preview_map[3].split("|")
        assert "new.example.com" in parts[0]
        assert parts[1] == "-240"

    def test_mismatched_gid_links_are_excluded(self):
        """Links that belong to a different gallery ID are filtered out."""
        html = (
            '<div class="gdtl" style="height:270px">'
            '<a href="/s/abcdef1234/999-1">'
            '<img alt="1" src="https://thumb.example.com/other.jpg">'
            '</a></div>'
        )
        client = self._client()
        # gid=100, but the link has gid 999
        token_map, _ = client._parse_detail_html(html, gid=100)
        assert 1 not in token_map

    def test_empty_html_returns_empty_maps(self):
        client = self._client()
        token_map, preview_map = client._parse_detail_html("", gid=1)
        assert token_map == {}
        assert preview_map == {}


# ---------------------------------------------------------------------------
# get_showkey
# ---------------------------------------------------------------------------


class TestGetShowkey:
    """get_showkey should parse showkey and optional nl param from page HTML."""

    def _client(self):
        from services.eh_client import EhClient
        c = EhClient(cookies={})
        c._http = AsyncMock()
        return c

    def _mock_page(self, html: str) -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.text = html
        resp.raise_for_status = MagicMock()
        resp.headers = {"content-disposition": ""}
        return resp

    async def test_extracts_showkey_and_nl_param(self):
        client = self._client()
        html = (
            "<html><body>"
            + "x" * 300
            + 'var showkey="abc123def456";'
            + "some more JS "
            + "return nl('mynlparam');"
            + "</body></html>"
        )
        client._http.get = AsyncMock(return_value=self._mock_page(html))

        showkey, nl_param = await client.get_showkey(100, 1, "ptoken12345")
        assert showkey == "abc123def456"
        assert nl_param == "mynlparam"

    async def test_missing_nl_param_returns_none(self):
        """When the page has no nl() call, nl_param should be None."""
        client = self._client()
        html = (
            "<html><body>"
            + "x" * 300
            + 'var showkey="xyz789";'
            + "</body></html>"
        )
        client._http.get = AsyncMock(return_value=self._mock_page(html))

        showkey, nl_param = await client.get_showkey(100, 1, "ptoken12345")
        assert showkey == "xyz789"
        assert nl_param is None

    async def test_missing_showkey_raises_value_error(self):
        """Page without showkey variable should raise ValueError."""
        client = self._client()
        html = "<html><body>" + "x" * 300 + "no showkey here</body></html>"
        client._http.get = AsyncMock(return_value=self._mock_page(html))

        with pytest.raises(ValueError, match="showkey"):
            await client.get_showkey(100, 1, "ptoken12345")


# ---------------------------------------------------------------------------
# get_image_url_via_api
# ---------------------------------------------------------------------------


class TestGetImageUrlViaApi:
    """Showpage API response parsing."""

    def _client(self):
        from services.eh_client import EhClient
        c = EhClient(cookies={}, use_ex=False)
        c._http = AsyncMock()
        return c

    def _mock_api_response(self, data: dict) -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=data)
        return resp

    async def test_parses_primary_image_url_from_i3(self):
        client = self._client()
        data = {
            "i3": '<img id="img" src="https://h.example.com/img.jpg" style="max-width:100%">',
            "i6": "",
            "i7": "",
        }
        client._http.post = AsyncMock(return_value=self._mock_api_response(data))

        result = await client.get_image_url_via_api("showkey", 100, 1, "imgkey")
        assert result.image_url == "https://h.example.com/img.jpg"

    async def test_parses_nl_param_and_other_url_from_i6(self):
        client = self._client()
        data = {
            "i3": '<img id="img" src="https://h.example.com/img.jpg" style="max-width:100%">',
            "i6": (
                "return nl('my-nl-param');"
                " onclick=\"prompt('Copy the URL below.', 'https://skip.example.com/img.jpg')\""
            ),
            "i7": "",
        }
        client._http.post = AsyncMock(return_value=self._mock_api_response(data))

        result = await client.get_image_url_via_api("showkey", 100, 1, "imgkey")
        assert result.nl_param == "my-nl-param"
        assert result.other_url == "https://skip.example.com/img.jpg"

    async def test_parses_origin_url_from_i7_when_present(self):
        client = self._client()
        data = {
            "i3": '<img id="img" src="https://h.example.com/img.jpg" style="max-width:100%">',
            "i6": "",
            "i7": '<a href="https://full.example.com/fullimgdata.jpg">Download original</a>',
        }
        client._http.post = AsyncMock(return_value=self._mock_api_response(data))

        result = await client.get_image_url_via_api("showkey", 100, 1, "imgkey")
        assert result.origin_url is not None
        assert "fullimg" in result.origin_url

    async def test_api_error_field_raises_value_error(self):
        client = self._client()
        data = {"error": "invalid showkey"}
        client._http.post = AsyncMock(return_value=self._mock_api_response(data))

        with pytest.raises(ValueError, match="showpage API error"):
            await client.get_image_url_via_api("showkey", 100, 1, "imgkey")

    async def test_missing_image_url_in_i3_raises(self):
        client = self._client()
        data = {"i3": "no img tag here", "i6": "", "i7": ""}
        client._http.post = AsyncMock(return_value=self._mock_api_response(data))

        with pytest.raises(ValueError, match="Image URL not found"):
            await client.get_image_url_via_api("showkey", 100, 1, "imgkey")


# ---------------------------------------------------------------------------
# download_image_with_retry
# ---------------------------------------------------------------------------


class TestDownloadImageWithRetry:
    """Retry logic, fallback chain, and 509 fast-path."""

    def _client(self):
        from services.eh_client import EhClient
        c = EhClient(cookies={})
        c._http = AsyncMock()
        c._img_http = AsyncMock()
        return c

    _FAKE_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # JPEG signature

    async def test_509_url_raises_image509error_without_retry(self):
        """A 509 image URL must raise Image509Error immediately — not retried."""
        from services.eh_client import Image509Error, ShowpageResult

        client = self._client()
        call_count = 0

        async def _api_returning_509(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return ShowpageResult(image_url="https://ehgt.org/509.gif")

        client.get_image_url_via_api = _api_returning_509

        with pytest.raises(Image509Error):
            await client.download_image_with_retry("sk", 100, 1, "ik", max_retries=3)

        # Only called once — 509 short-circuits the retry loop immediately
        assert call_count == 1

    async def test_primary_url_success_returns_data(self):
        """Happy path: primary URL succeeds on first attempt."""
        from services.eh_client import ShowpageResult

        client = self._client()
        client.get_image_url_via_api = AsyncMock(
            return_value=ShowpageResult(image_url="https://h.example.com/img.jpg")
        )
        client._download_image_bytes = AsyncMock(
            return_value=(self._FAKE_BYTES, "image/jpeg", "jpg")
        )

        data, media_type, ext = await client.download_image_with_retry("sk", 1, 1, "ik", max_retries=3)
        assert data == self._FAKE_BYTES
        assert media_type == "image/jpeg"
        assert ext == "jpg"

    async def test_primary_fails_fallback_to_other_url_succeeds(self):
        """When the primary URL always fails, other_url should be tried."""
        from services.eh_client import ShowpageResult

        client = self._client()
        client.get_image_url_via_api = AsyncMock(
            return_value=ShowpageResult(
                image_url="https://h.example.com/img.jpg",
                other_url="https://skip.example.com/img.jpg",
            )
        )
        download_urls: list[str] = []

        async def _download(url, gid, page, imgkey):
            download_urls.append(url)
            if "skip.example.com" in url:
                return self._FAKE_BYTES, "image/jpeg", "jpg"
            raise httpx.TimeoutException("timeout")

        client._download_image_bytes = _download

        data, _, _ = await client.download_image_with_retry("sk", 1, 1, "ik", max_retries=2)
        assert data == self._FAKE_BYTES
        assert any("skip.example.com" in u for u in download_urls)

    async def test_primary_and_other_fail_fallback_to_origin_url(self):
        """When primary and other_url both fail, origin_url is tried last."""
        from services.eh_client import ShowpageResult

        client = self._client()
        client.get_image_url_via_api = AsyncMock(
            return_value=ShowpageResult(
                image_url="https://h.example.com/img.jpg",
                other_url="https://skip.example.com/img.jpg",
                origin_url="https://full.example.com/fullimg.jpg",
            )
        )
        download_urls: list[str] = []

        async def _download(url, gid, page, imgkey):
            download_urls.append(url)
            if "full.example.com" in url:
                return self._FAKE_BYTES, "image/jpeg", "jpg"
            raise httpx.TimeoutException("timeout")

        client._download_image_bytes = _download

        data, _, _ = await client.download_image_with_retry("sk", 1, 1, "ik", max_retries=1)
        assert data == self._FAKE_BYTES
        assert any("full.example.com" in u for u in download_urls)

    async def test_all_attempts_fail_raises_runtime_error(self):
        """When primary, other_url, and origin_url all fail → RuntimeError."""
        from services.eh_client import ShowpageResult

        client = self._client()
        client.get_image_url_via_api = AsyncMock(
            return_value=ShowpageResult(
                image_url="https://h.example.com/img.jpg",
                other_url="https://skip.example.com/img.jpg",
                origin_url="https://full.example.com/fullimg.jpg",
            )
        )
        client._download_image_bytes = AsyncMock(
            side_effect=httpx.TimeoutException("always times out")
        )

        with pytest.raises(RuntimeError, match="Failed to download"):
            await client.download_image_with_retry("sk", 1, 1, "ik", max_retries=2)

    async def test_nl_param_passed_on_retry(self):
        """On retry, the nl_param from the previous ShowpageResult must be forwarded."""
        from services.eh_client import ShowpageResult

        client = self._client()
        received_nls: list[str] = []

        async def _api(showkey, gid, page, imgkey, nl=""):
            received_nls.append(nl)
            return ShowpageResult(
                image_url="https://h.example.com/img.jpg",
                nl_param="server2param",
            )

        client.get_image_url_via_api = _api
        client._download_image_bytes = AsyncMock(
            side_effect=[httpx.TimeoutException("fail"), (self._FAKE_BYTES, "image/jpeg", "jpg")]
        )

        await client.download_image_with_retry("sk", 1, 1, "ik", max_retries=2)

        # First call has empty nl, second call forwards the nl_param from the first result
        assert received_nls[0] == ""
        assert received_nls[1] == "server2param"
