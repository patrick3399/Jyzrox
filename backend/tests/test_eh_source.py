"""
Tests for EhSourcePlugin (plugins/builtin/ehentai/source.py).

Covers:
- requires_credentials() returns False
- download() with credentials=None falls back to empty cookies (no credential gate failure)
- download() with malformed credential string returns failed DownloadResult
- download() with dict credentials uses them directly
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

# ---------------------------------------------------------------------------
# Plugin instantiation helper
# ---------------------------------------------------------------------------


def _make_plugin():
    """Return a fresh EhSourcePlugin instance."""
    from plugins.builtin.ehentai.source import EhSourcePlugin

    return EhSourcePlugin()


# ---------------------------------------------------------------------------
# requires_credentials
# ---------------------------------------------------------------------------


class TestEhSourceRequiresCredentials:
    """EhSourcePlugin.requires_credentials() should return False."""

    def test_requires_credentials_returns_false(self):
        """E-Hentai plugin does not require credentials for download."""
        plugin = _make_plugin()
        assert plugin.requires_credentials() is False

    def test_requires_credentials_is_bool(self):
        """Return value must be a bool (not truthy/falsy other type)."""
        plugin = _make_plugin()
        result = plugin.requires_credentials()
        assert isinstance(result, bool)
        assert result is False


def test_parse_import_preserves_authoritative_source_page_count(tmp_path):
    """EH metadata page totals must survive into the importer contract."""
    plugin = _make_plugin()

    data = plugin.parse_import(
        tmp_path,
        {
            "gid": 123,
            "title": "Partial source",
            "pages": 20,
            "tags": [],
        },
    )

    assert data.page_count == 20


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


class TestEhSourceCanHandle:
    """EhSourcePlugin.can_handle() URL matching."""

    async def test_can_handle_e_hentai(self):
        plugin = _make_plugin()
        assert await plugin.can_handle("https://e-hentai.org/g/123456/abcdef1234/") is True

    async def test_can_handle_exhentai(self):
        plugin = _make_plugin()
        assert await plugin.can_handle("https://exhentai.org/g/123456/abcdef1234/") is True

    async def test_cannot_handle_pixiv(self):
        plugin = _make_plugin()
        assert await plugin.can_handle("https://www.pixiv.net/artworks/12345") is False

    async def test_cannot_handle_unknown(self):
        plugin = _make_plugin()
        assert await plugin.can_handle("https://example.com/gallery/1") is False

    async def test_tag_search_url_not_claimed_so_gallery_dl_fallback_applies(self):
        """Regression: can_handle matched ANY e-hentai URL, but download() only
        parses /g/{gid}/{token}/ — an artist tag URL was claimed by this plugin,
        failed with 'Cannot parse EH gallery URL', and never reached the
        gallery-dl fallback (which supports EH tag/search extractors).
        """
        plugin = _make_plugin()
        assert await plugin.can_handle("https://e-hentai.org/tag/artist:someone") is False

    async def test_search_url_not_claimed(self):
        plugin = _make_plugin()
        assert await plugin.can_handle("https://e-hentai.org/?f_search=language%3Achinese") is False

    async def test_favorites_url_not_claimed(self):
        plugin = _make_plugin()
        assert await plugin.can_handle("https://exhentai.org/favorites.php") is False

    async def test_can_handle_gallery_url_without_trailing_slash(self):
        """Regression: GALLERY_URL_RE required a trailing slash, but every manual
        download job stores normalize_download_url(url), which rstrips it. The EH
        plugin therefore never claimed manually queued galleries — they fell through
        to the gallery-dl fallback and were titled from the URL path prefix ("g").
        """
        plugin = _make_plugin()
        assert await plugin.can_handle("https://e-hentai.org/g/3238806/00f58dcf94") is True
        assert await plugin.can_handle("https://exhentai.org/g/3238806/00f58dcf94") is True

    async def test_can_handle_survives_download_url_normalization(self):
        """The exact URL the worker receives must be claimable by this plugin."""
        from core.utils import normalize_download_url

        plugin = _make_plugin()
        normalized = normalize_download_url("https://e-hentai.org/g/3238806/00f58dcf94/")
        assert normalized == "https://e-hentai.org/g/3238806/00f58dcf94"
        assert await plugin.can_handle(normalized) is True

    async def test_can_handle_rejects_over_length_token(self):
        """Making the trailing slash optional must not let a longer hex token match
        by truncation — token identity has to stay exactly 10 hex chars.
        """
        plugin = _make_plugin()
        assert await plugin.can_handle("https://e-hentai.org/g/3238806/00f58dcf94ab") is False


# ---------------------------------------------------------------------------
# download() with no credentials
# ---------------------------------------------------------------------------


class TestEhSourceDownloadNoCredentials:
    """download() with credentials=None should not fail at credential gate.

    It should fall back to empty cookies and attempt the download.
    The actual network call is mocked via download_eh_gallery.
    """

    async def test_download_with_none_credentials_uses_empty_cookies(self):
        """credentials=None should result in empty cookies dict passed to downloader."""
        plugin = _make_plugin()

        mock_result = {
            "status": "done",
            "downloaded": 10,
            "total": 10,
            "failed_pages": [],
            "error": None,
        }

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # no Redis override for use_ex

        with (
            patch(
                "services.eh_downloader.download_eh_gallery", new_callable=AsyncMock, return_value=mock_result
            ) as mock_dl,
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings") as mock_settings,
        ):
            mock_settings.eh_use_ex = False
            mock_settings.eh_download_concurrency = 3

            result = await plugin.download(
                url="https://e-hentai.org/g/123456/abcdef1234/",
                dest_dir=Path("/tmp/test_eh"),
                credentials=None,
            )

            # Verify download was attempted (not blocked by credential gate)
            mock_dl.assert_called_once()
            call_kwargs = mock_dl.call_args.kwargs
            # Cookies should be empty dict (anonymous fallback)
            assert call_kwargs["cookies"] == {}
            # use_ex should be False for anonymous access
            assert call_kwargs["use_ex"] is False

        assert result.status == "done"
        assert result.downloaded == 10

    async def test_download_with_none_credentials_sets_use_ex_false(self):
        """Anonymous download (no credentials) must use e-hentai.org, not exhentai."""
        plugin = _make_plugin()

        mock_result = {"status": "done", "downloaded": 5, "total": 5, "failed_pages": [], "error": None}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with (
            patch(
                "services.eh_downloader.download_eh_gallery", new_callable=AsyncMock, return_value=mock_result
            ) as mock_dl,
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings") as mock_settings,
        ):
            mock_settings.eh_use_ex = True  # would be True by config, but should be overridden
            mock_settings.eh_download_concurrency = 3

            await plugin.download(
                url="https://e-hentai.org/g/999/deadbeef12/",
                dest_dir=Path("/tmp/test_eh"),
                credentials=None,
            )

            call_kwargs = mock_dl.call_args.kwargs
            # Even if settings say use_ex=True, anonymous must be False
            assert call_kwargs["use_ex"] is False

    async def test_download_with_none_credentials_returns_done_result(self):
        """A successful anonymous download returns DownloadResult with status=done."""
        plugin = _make_plugin()

        mock_result = {"status": "done", "downloaded": 20, "total": 20, "failed_pages": [], "error": None}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with (
            patch("services.eh_downloader.download_eh_gallery", new_callable=AsyncMock, return_value=mock_result),
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings") as mock_settings,
        ):
            mock_settings.eh_use_ex = False
            mock_settings.eh_download_concurrency = 3

            result = await plugin.download(
                url="https://e-hentai.org/g/123456/abcdef1234/",
                dest_dir=Path("/tmp/test_eh"),
                credentials=None,
            )

        assert result.status == "done"
        assert result.downloaded == 20
        assert result.total == 20
        assert result.error is None

    async def test_download_partial_status_is_not_coerced_to_failed(self):
        """A 'partial' downloader result must survive the plugin status whitelist.

        DownloadResult already permits "partial", but the whitelist here listed
        only done/cancelled/failed, so a partial run would be rewritten to
        "failed" — throwing away the downloaded count's meaning and mislabelling
        a run that did retrieve most of its pages.
        """
        plugin = _make_plugin()

        mock_result = {"status": "partial", "downloaded": 18, "total": 20, "failed_pages": [7, 12], "error": None}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with (
            patch("services.eh_downloader.download_eh_gallery", new_callable=AsyncMock, return_value=mock_result),
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings") as mock_settings,
        ):
            mock_settings.eh_use_ex = False
            mock_settings.eh_download_concurrency = 3

            result = await plugin.download(
                url="https://e-hentai.org/g/123456/abcdef1234/",
                dest_dir=Path("/tmp/test_eh"),
                credentials=None,
            )

        assert result.status == "partial"
        assert result.downloaded == 18
        assert result.failed_pages == [7, 12]

    async def test_download_unknown_status_still_coerced_to_failed(self):
        """Widening the whitelist must not let arbitrary statuses through."""
        plugin = _make_plugin()

        mock_result = {"status": "weird", "downloaded": 0, "total": 20, "failed_pages": [], "error": None}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with (
            patch("services.eh_downloader.download_eh_gallery", new_callable=AsyncMock, return_value=mock_result),
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings") as mock_settings,
        ):
            mock_settings.eh_use_ex = False
            mock_settings.eh_download_concurrency = 3

            result = await plugin.download(
                url="https://e-hentai.org/g/123456/abcdef1234/",
                dest_dir=Path("/tmp/test_eh"),
                credentials=None,
            )

        assert result.status == "failed"


# ---------------------------------------------------------------------------
# download() with invalid URL
# ---------------------------------------------------------------------------


class TestEhSourceDownloadInvalidUrl:
    """download() with unparseable URL returns failed DownloadResult."""

    async def test_download_invalid_url_returns_failed(self):
        """A URL that doesn't match the EH gallery pattern should fail cleanly."""
        plugin = _make_plugin()

        result = await plugin.download(
            url="https://e-hentai.org/tag/doujinshi",  # not a gallery URL
            dest_dir=Path("/tmp/test_eh"),
            credentials=None,
        )

        assert result.status == "failed"
        assert result.downloaded == 0
        assert "Cannot parse" in (result.error or "")


# ---------------------------------------------------------------------------
# download() with dict credentials
# ---------------------------------------------------------------------------


class TestEhSourceDownloadWithCredentials:
    """download() with valid dict credentials passes them as cookies."""

    async def test_download_with_dict_credentials_passes_cookies(self):
        """Dict credentials should be passed directly as cookies to the downloader."""
        plugin = _make_plugin()

        fake_cookies = {
            "ipb_member_id": "12345",
            "ipb_pass_hash": "hashvalue",
        }
        mock_result = {"status": "done", "downloaded": 8, "total": 8, "failed_pages": [], "error": None}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with (
            patch(
                "services.eh_downloader.download_eh_gallery", new_callable=AsyncMock, return_value=mock_result
            ) as mock_dl,
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings") as mock_settings,
        ):
            mock_settings.eh_use_ex = False
            mock_settings.eh_download_concurrency = 3

            result = await plugin.download(
                url="https://e-hentai.org/g/123456/abcdef1234/",
                dest_dir=Path("/tmp/test_eh"),
                credentials=fake_cookies,
            )

            call_kwargs = mock_dl.call_args.kwargs
            assert call_kwargs["cookies"] == fake_cookies

        assert result.status == "done"

    async def test_download_with_string_credentials_parses_json(self):
        """String JSON credential should be parsed and passed as cookies."""
        import json

        plugin = _make_plugin()

        fake_cookies = {"ipb_member_id": "99999", "ipb_pass_hash": "phash"}
        mock_result = {"status": "done", "downloaded": 5, "total": 5, "failed_pages": [], "error": None}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with (
            patch(
                "services.eh_downloader.download_eh_gallery", new_callable=AsyncMock, return_value=mock_result
            ) as mock_dl,
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings") as mock_settings,
        ):
            mock_settings.eh_use_ex = False
            mock_settings.eh_download_concurrency = 3

            result = await plugin.download(
                url="https://e-hentai.org/g/123456/abcdef1234/",
                dest_dir=Path("/tmp/test_eh"),
                credentials=json.dumps(fake_cookies),
            )

            call_kwargs = mock_dl.call_args.kwargs
            assert call_kwargs["cookies"] == fake_cookies

        assert result.status == "done"

    async def test_download_with_malformed_json_string_returns_failed(self):
        """Malformed JSON string credentials should return a failed DownloadResult."""
        plugin = _make_plugin()

        result = await plugin.download(
            url="https://e-hentai.org/g/123456/abcdef1234/",
            dest_dir=Path("/tmp/test_eh"),
            credentials="not-valid-json{{{",
        )

        assert result.status == "failed"
        assert "malformed" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# download() error handling
# ---------------------------------------------------------------------------


class TestEhSourceDownloadErrorHandling:
    """download() should gracefully handle exceptions from the downloader."""

    async def test_download_permission_error_returns_failed(self):
        """PermissionError (Sad Panda / 509) should return failed DownloadResult."""
        plugin = _make_plugin()

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with (
            patch(
                "services.eh_downloader.download_eh_gallery",
                new_callable=AsyncMock,
                side_effect=PermissionError("Sad Panda"),
            ),
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings") as mock_settings,
        ):
            mock_settings.eh_use_ex = False
            mock_settings.eh_download_concurrency = 3

            result = await plugin.download(
                url="https://e-hentai.org/g/123456/abcdef1234/",
                dest_dir=Path("/tmp/test_eh"),
                credentials=None,
            )

        assert result.status == "failed"
        assert "Sad Panda" in (result.error or "")

    async def test_download_generic_exception_returns_failed(self):
        """Unexpected exception from downloader should return failed DownloadResult."""
        plugin = _make_plugin()

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with (
            patch(
                "services.eh_downloader.download_eh_gallery",
                new_callable=AsyncMock,
                side_effect=RuntimeError("network timeout"),
            ),
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings") as mock_settings,
        ):
            mock_settings.eh_use_ex = False
            mock_settings.eh_download_concurrency = 3

            result = await plugin.download(
                url="https://e-hentai.org/g/123456/abcdef1234/",
                dest_dir=Path("/tmp/test_eh"),
                credentials=None,
            )

        assert result.status == "failed"
        assert result.error is not None


# ---------------------------------------------------------------------------
# download() forwards skip_pages for incremental repair
# ---------------------------------------------------------------------------


class TestEhSourceSkipPages:
    """The worker passes already-held page numbers through `options`."""

    async def test_download_forwards_skip_pages_option_to_downloader(self):
        """Without this the repair path silently re-downloads every page."""
        plugin = _make_plugin()

        captured = {}

        async def _fake_download(**kwargs):
            captured.update(kwargs)
            return {"status": "done", "downloaded": 20, "total": 20, "failed_pages": [], "error": None}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with (
            patch("services.eh_downloader.download_eh_gallery", new=_fake_download),
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings") as mock_settings,
        ):
            mock_settings.eh_use_ex = False
            mock_settings.eh_download_concurrency = 3

            await plugin.download(
                url="https://e-hentai.org/g/123456/abcdef1234/",
                dest_dir=Path("/tmp/test_eh"),
                credentials=None,
                options={"skip_pages": [1, 2, 5]},
            )

        assert captured.get("skip_pages") == [1, 2, 5]

    async def test_download_without_skip_pages_option_passes_none(self):
        """A first-time download must not accidentally skip anything."""
        plugin = _make_plugin()

        captured = {}

        async def _fake_download(**kwargs):
            captured.update(kwargs)
            return {"status": "done", "downloaded": 20, "total": 20, "failed_pages": [], "error": None}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with (
            patch("services.eh_downloader.download_eh_gallery", new=_fake_download),
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings") as mock_settings,
        ):
            mock_settings.eh_use_ex = False
            mock_settings.eh_download_concurrency = 3

            await plugin.download(
                url="https://e-hentai.org/g/123456/abcdef1234/",
                dest_dir=Path("/tmp/test_eh"),
                credentials=None,
                options={},
            )

        assert not captured.get("skip_pages")
