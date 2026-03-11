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
            patch("services.eh_downloader.download_eh_gallery", new_callable=AsyncMock, return_value=mock_result) as mock_dl,
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
            patch("services.eh_downloader.download_eh_gallery", new_callable=AsyncMock, return_value=mock_result) as mock_dl,
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
            patch("services.eh_downloader.download_eh_gallery", new_callable=AsyncMock, return_value=mock_result) as mock_dl,
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
            patch("services.eh_downloader.download_eh_gallery", new_callable=AsyncMock, return_value=mock_result) as mock_dl,
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
