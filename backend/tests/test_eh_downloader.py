"""
Tests for services.eh_downloader — download_eh_gallery().

Strategy:
- Fully mock EhClient (all network I/O) via patch("services.eh_downloader.EhClient").
- Fully mock services.cache (Redis-backed gallery/image-list cache).
- Use tmp_path (pytest built-in) as output_dir so real files are written to a
  temp directory and cleaned up automatically.
- Patch get_redis / get_download_delay to avoid Redis connections.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

_FAKE_META = {
    "pages": 3,
    "category": "Doujinshi",
    "title": "Test Gallery",
    "title_jpn": "Test Gallery JP",
    "uploader": "test_uploader",
    "posted_at": 1700000000,
    "tags": ["artist:tester", "female:solo"],
}

_FAKE_TOKEN_MAP = {1: "aaaaaa", 2: "bbbbbb", 3: "cccccc"}

_FAKE_IMAGE_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # minimal JPEG signature


def _make_eh_client_mock():
    """Return a fully-configured async context manager mock of EhClient."""
    mock_client = AsyncMock()
    mock_client.get_gallery_metadata = AsyncMock(return_value=_FAKE_META)
    mock_client.get_image_tokens = AsyncMock(return_value=(_FAKE_TOKEN_MAP, None))
    mock_client.get_showkey = AsyncMock(return_value=("showkey123", None))
    mock_client.download_image_with_retry = AsyncMock(return_value=(_FAKE_IMAGE_BYTES, "image/jpeg", "jpg"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ---------------------------------------------------------------------------
# TestEhDownloaderHappyPath
# ---------------------------------------------------------------------------


class TestEhDownloaderHappyPath:
    """Tests for the successful download flow."""

    async def test_download_gallery_status_done_on_success(self, tmp_path):
        """All pages download successfully → status 'done', downloaded == total."""
        from services.eh_downloader import download_eh_gallery

        mock_client = _make_eh_client_mock()

        with (
            patch("services.eh_downloader.EhClient", return_value=mock_client),
            patch("services.eh_downloader.cache.get_gallery_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_gallery_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_imagelist_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_imagelist_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_proxied_image", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.get_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_eh_gallery(
                gid=12345,
                token="abc123",
                cookies={"ipb_member_id": "1", "ipb_pass_hash": "x"},
                use_ex=False,
                output_dir=tmp_path,
            )

        assert result["status"] == "done"
        assert result["downloaded"] == 3
        assert result["total"] == 3
        assert result["failed_pages"] == []

    async def test_download_gallery_creates_metadata_json(self, tmp_path):
        """After a successful download, metadata.json must exist and contain expected keys."""
        import json

        from services.eh_downloader import download_eh_gallery

        mock_client = _make_eh_client_mock()

        with (
            patch("services.eh_downloader.EhClient", return_value=mock_client),
            patch("services.eh_downloader.cache.get_gallery_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_gallery_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_imagelist_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_imagelist_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_proxied_image", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.get_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            await download_eh_gallery(
                gid=12345,
                token="abc123",
                cookies={},
                use_ex=False,
                output_dir=tmp_path,
            )

        meta_path = tmp_path / "metadata.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["category"] == "ehentai"
        assert meta["gallery_id"] == 12345
        assert meta["title"] == "Test Gallery"

    async def test_download_gallery_progress_callback_called(self, tmp_path):
        """on_progress should be called once per downloaded page."""
        from services.eh_downloader import download_eh_gallery

        progress_calls: list[tuple[int, int]] = []

        async def _on_progress(done: int, total: int) -> None:
            progress_calls.append((done, total))

        mock_client = _make_eh_client_mock()

        with (
            patch("services.eh_downloader.EhClient", return_value=mock_client),
            patch("services.eh_downloader.cache.get_gallery_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_gallery_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_imagelist_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_imagelist_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_proxied_image", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.get_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_eh_gallery(
                gid=99,
                token="tok",
                cookies={},
                use_ex=False,
                output_dir=tmp_path,
                on_progress=_on_progress,
            )

        assert result["downloaded"] == 3
        # Progress callback must have been called 3 times (once per page)
        assert len(progress_calls) == 3
        # Final call should report (3, 3)
        assert progress_calls[-1] == (3, 3)

    async def test_download_gallery_uses_cached_metadata(self, tmp_path):
        """When gallery metadata is cached, get_gallery_metadata should NOT be called."""
        from services.eh_downloader import download_eh_gallery

        mock_client = _make_eh_client_mock()

        with (
            patch("services.eh_downloader.EhClient", return_value=mock_client),
            patch("services.eh_downloader.cache.get_gallery_cache", new_callable=AsyncMock, return_value=_FAKE_META),
            patch("services.eh_downloader.cache.set_gallery_cache", new_callable=AsyncMock) as mock_set_meta,
            patch("services.eh_downloader.cache.get_imagelist_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_imagelist_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_proxied_image", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.get_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            await download_eh_gallery(
                gid=12345,
                token="abc123",
                cookies={},
                use_ex=False,
                output_dir=tmp_path,
            )

        # Metadata was in cache — no network fetch, no re-cache
        mock_client.get_gallery_metadata.assert_not_called()
        mock_set_meta.assert_not_called()

    async def test_download_gallery_uses_proxied_image_cache(self, tmp_path):
        """When a page is already in the image proxy cache, download_image_with_retry should not be called."""
        from services.eh_downloader import download_eh_gallery

        mock_client = _make_eh_client_mock()

        with (
            patch("services.eh_downloader.EhClient", return_value=mock_client),
            patch("services.eh_downloader.cache.get_gallery_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_gallery_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_imagelist_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_imagelist_cache", new_callable=AsyncMock),
            # All pages in proxy cache
            patch(
                "services.eh_downloader.cache.get_proxied_image",
                new_callable=AsyncMock,
                return_value=_FAKE_IMAGE_BYTES,
            ),
            patch("services.eh_downloader.get_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_eh_gallery(
                gid=12345,
                token="abc123",
                cookies={},
                use_ex=False,
                output_dir=tmp_path,
            )

        assert result["status"] == "done"
        mock_client.download_image_with_retry.assert_not_called()


# ---------------------------------------------------------------------------
# TestEhDownloaderCancellation
# ---------------------------------------------------------------------------


class TestEhDownloaderCancellation:
    """Tests for cancel_check behaviour."""

    async def test_download_gallery_cancel_check_stops_download(self, tmp_path):
        """When cancel_check returns True before any page, status should be 'cancelled'."""
        from services.eh_downloader import download_eh_gallery

        mock_client = _make_eh_client_mock()

        async def _always_cancel() -> bool:
            return True

        with (
            patch("services.eh_downloader.EhClient", return_value=mock_client),
            patch("services.eh_downloader.cache.get_gallery_cache", new_callable=AsyncMock, return_value=_FAKE_META),
            patch("services.eh_downloader.cache.get_imagelist_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_imagelist_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_proxied_image", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.get_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_eh_gallery(
                gid=12345,
                token="abc123",
                cookies={},
                use_ex=False,
                output_dir=tmp_path,
                cancel_check=_always_cancel,
            )

        assert result["status"] == "cancelled"


# ---------------------------------------------------------------------------
# TestEhDownloaderErrorHandling
# ---------------------------------------------------------------------------


class TestEhDownloaderErrorHandling:
    """Tests for error paths: zero pages, failed pages, 509 limit."""

    async def test_download_gallery_zero_pages_returns_failed(self, tmp_path):
        """When gallery metadata reports 0 pages, return immediately with status 'failed'."""
        from services.eh_downloader import download_eh_gallery

        mock_client = _make_eh_client_mock()
        mock_client.get_gallery_metadata = AsyncMock(return_value={**_FAKE_META, "pages": 0})

        with (
            patch("services.eh_downloader.EhClient", return_value=mock_client),
            patch("services.eh_downloader.cache.get_gallery_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_gallery_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_imagelist_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_imagelist_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_proxied_image", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.get_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_eh_gallery(
                gid=12345,
                token="abc123",
                cookies={},
                use_ex=False,
                output_dir=tmp_path,
            )

        assert result["status"] == "failed"
        assert result["downloaded"] == 0
        assert result["total"] == 0

    async def test_download_gallery_failed_page_recorded(self, tmp_path):
        """A page that raises a generic exception should be recorded in failed_pages."""
        from services.eh_downloader import download_eh_gallery

        mock_client = _make_eh_client_mock()
        # Page 2 raises a connection error
        call_count = 0

        async def _download_page_with_failure(showkey, gid, page_num, ptoken, max_retries=3):
            nonlocal call_count
            call_count += 1
            if page_num == 2:
                raise ConnectionError("Simulated connection failure")
            return (_FAKE_IMAGE_BYTES, "image/jpeg", "jpg")

        mock_client.download_image_with_retry = _download_page_with_failure

        with (
            patch("services.eh_downloader.EhClient", return_value=mock_client),
            patch("services.eh_downloader.cache.get_gallery_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_gallery_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_imagelist_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_imagelist_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_proxied_image", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.get_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_eh_gallery(
                gid=12345,
                token="abc123",
                cookies={},
                use_ex=False,
                output_dir=tmp_path,
            )

        # Page 2 failed; pages 1 and 3 succeeded
        assert 2 in result["failed_pages"]
        assert result["downloaded"] == 2

    async def test_download_gallery_509_error_returns_failed(self, tmp_path):
        """When Image509Error is raised, the download should return status 'failed' with 509 message."""
        from services.eh_downloader import download_eh_gallery
        from services.eh_client import Image509Error

        mock_client = _make_eh_client_mock()
        mock_client.download_image_with_retry = AsyncMock(side_effect=Image509Error("509"))

        with (
            patch("services.eh_downloader.EhClient", return_value=mock_client),
            patch("services.eh_downloader.cache.get_gallery_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_gallery_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_imagelist_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_imagelist_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_proxied_image", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.get_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_eh_gallery(
                gid=12345,
                token="abc123",
                cookies={},
                use_ex=False,
                output_dir=tmp_path,
            )

        assert result["status"] == "failed"
        assert "509" in result.get("error", "").lower() or "limit" in result.get("error", "").lower()

    async def test_download_gallery_empty_token_map_returns_failed(self, tmp_path):
        """When get_image_tokens returns an empty map, status should be 'failed'."""
        from services.eh_downloader import download_eh_gallery

        mock_client = _make_eh_client_mock()
        mock_client.get_image_tokens = AsyncMock(return_value=({}, None))

        with (
            patch("services.eh_downloader.EhClient", return_value=mock_client),
            patch("services.eh_downloader.cache.get_gallery_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_gallery_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_imagelist_cache", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.cache.set_imagelist_cache", new_callable=AsyncMock),
            patch("services.eh_downloader.cache.get_proxied_image", new_callable=AsyncMock, return_value=None),
            patch("services.eh_downloader.get_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_eh_gallery(
                gid=12345,
                token="abc123",
                cookies={},
                use_ex=False,
                output_dir=tmp_path,
            )

        assert result["status"] == "failed"
        assert "token" in result.get("error", "").lower()
