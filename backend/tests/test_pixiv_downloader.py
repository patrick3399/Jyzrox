"""
Tests for services.pixiv_downloader — download_pixiv_illust() and
download_pixiv_user_works().

Strategy:
- Mock PixivClient (context manager) at the services.pixiv_downloader import
  site so no real HTTP or Redis connections are made.
- Use tmp_path (pytest built-in) for output_dir.
- Patch get_typed_download_delay to return 0 so tests run without sleeping.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_SINGLE_PAGE_DETAIL = {
    "id": 111111,
    "title": "Single Page Artwork",
    "type": "illust",
    "caption": "A fine piece",
    "page_count": 1,
    "create_date": "2026-01-20T10:00:00+09:00",
    "image_urls": {
        "square_medium": "https://i.pximg.net/sq/111111.jpg",
        "medium": "https://i.pximg.net/med/111111.jpg",
        "large": "https://i.pximg.net/lg/111111.jpg",
        "original": "https://i.pximg.net/orig/111111_p0.jpg",
    },
    "meta_pages": [],
    "tags": [
        {"name": "solo", "translated_name": None},
        {"name": "オリジナル", "translated_name": "original"},
    ],
    "user": {"id": 22222, "name": "PixivArtist"},
    "total_bookmarks": 500,
    "total_view": 10000,
    "sanity_level": 2,
    "width": 1200,
    "height": 1800,
}

_MULTI_PAGE_DETAIL = {
    **_SINGLE_PAGE_DETAIL,
    "id": 222222,
    "title": "Multi Page Manga",
    "type": "manga",
    "page_count": 3,
    "image_urls": {
        "square_medium": "https://i.pximg.net/sq/222222.jpg",
        "medium": "https://i.pximg.net/med/222222.jpg",
        "large": "https://i.pximg.net/lg/222222.jpg",
        "original": "https://i.pximg.net/orig/222222_p0.jpg",
    },
    "meta_pages": [
        {"image_urls": {"original": "https://i.pximg.net/orig/222222_p0.jpg"}},
        {"image_urls": {"original": "https://i.pximg.net/orig/222222_p1.jpg"}},
        {"image_urls": {"original": "https://i.pximg.net/orig/222222_p2.jpg"}},
    ],
}

_UGOIRA_DETAIL = {
    **_SINGLE_PAGE_DETAIL,
    "id": 333333,
    "title": "Animated Ugoira",
    "type": "ugoira",
    "page_count": 1,
    "image_urls": {
        "square_medium": "https://i.pximg.net/sq/333333.jpg",
        "medium": "https://i.pximg.net/med/333333.jpg",
        "large": "https://i.pximg.net/lg/333333.jpg",
        "original": "https://i.pximg.net/orig/333333_ugoira600x600.zip",
    },
    "meta_pages": [],
}

_FAKE_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # minimal PNG header


def _make_pixiv_client_mock(detail: dict | None = None):
    """Return a PixivClient async context manager mock."""
    if detail is None:
        detail = _SINGLE_PAGE_DETAIL

    mock_client = AsyncMock()
    mock_client.illust_detail = AsyncMock(return_value=detail)
    mock_client.download_image = AsyncMock(return_value=(_FAKE_IMAGE_BYTES, "image/png"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ---------------------------------------------------------------------------
# TestPixivDownloaderSinglePage
# ---------------------------------------------------------------------------


class TestPixivDownloaderSinglePage:
    """Tests for download_pixiv_illust with a single-page illustration."""

    async def test_download_single_page_status_done(self, tmp_path):
        """Single-page illustration should download 1 file and return status 'done'."""
        from services.pixiv_downloader import download_pixiv_illust

        mock_client = _make_pixiv_client_mock(_SINGLE_PAGE_DETAIL)

        with (
            patch("services.pixiv_downloader.PixivClient", return_value=mock_client),
            patch("services.pixiv_downloader.get_typed_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_pixiv_illust(
                illust_id=111111,
                refresh_token="valid_token",
                output_dir=tmp_path,
            )

        assert result["status"] == "done"
        assert result["downloaded"] == 1
        assert result["total"] == 1
        assert result["failed_pages"] == []

    async def test_download_single_page_creates_image_file(self, tmp_path):
        """A .png file should be written to the output directory."""
        from services.pixiv_downloader import download_pixiv_illust

        mock_client = _make_pixiv_client_mock(_SINGLE_PAGE_DETAIL)

        with (
            patch("services.pixiv_downloader.PixivClient", return_value=mock_client),
            patch("services.pixiv_downloader.get_typed_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            await download_pixiv_illust(
                illust_id=111111,
                refresh_token="valid_token",
                output_dir=tmp_path,
            )

        # Expect exactly one image file (0001.png) plus metadata.json
        image_files = [f for f in tmp_path.iterdir() if f.suffix in (".jpg", ".png", ".gif", ".webp")]
        assert len(image_files) == 1
        # Extension is derived from the URL (.jpg in _SINGLE_PAGE_DETAIL)
        assert image_files[0].name == "0001.jpg"

    async def test_download_single_page_creates_metadata_json(self, tmp_path):
        """metadata.json should be written with category='pixiv' and correct illust id."""
        from services.pixiv_downloader import download_pixiv_illust

        mock_client = _make_pixiv_client_mock(_SINGLE_PAGE_DETAIL)

        with (
            patch("services.pixiv_downloader.PixivClient", return_value=mock_client),
            patch("services.pixiv_downloader.get_typed_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            await download_pixiv_illust(
                illust_id=111111,
                refresh_token="valid_token",
                output_dir=tmp_path,
            )

        meta_path = tmp_path / "metadata.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["category"] == "pixiv"
        assert meta["id"] == "111111"
        assert meta["title"] == "Single Page Artwork"
        assert "solo" in meta["tags"]

    async def test_download_single_page_progress_callback_called(self, tmp_path):
        """on_progress should be called with (0, 1) then (1, 1)."""
        from services.pixiv_downloader import download_pixiv_illust

        progress_calls: list[tuple[int, int]] = []

        async def _on_progress(done: int, total: int) -> None:
            progress_calls.append((done, total))

        mock_client = _make_pixiv_client_mock(_SINGLE_PAGE_DETAIL)

        with (
            patch("services.pixiv_downloader.PixivClient", return_value=mock_client),
            patch("services.pixiv_downloader.get_typed_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            await download_pixiv_illust(
                illust_id=111111,
                refresh_token="valid_token",
                output_dir=tmp_path,
                on_progress=_on_progress,
            )

        assert (0, 1) in progress_calls
        assert (1, 1) in progress_calls


# ---------------------------------------------------------------------------
# TestPixivDownloaderMultiPage
# ---------------------------------------------------------------------------


class TestPixivDownloaderMultiPage:
    """Tests for download_pixiv_illust with a multi-page illustration."""

    async def test_download_multi_page_downloads_all_pages(self, tmp_path):
        """3-page manga should produce 3 image files and status 'done'."""
        from services.pixiv_downloader import download_pixiv_illust

        mock_client = _make_pixiv_client_mock(_MULTI_PAGE_DETAIL)

        with (
            patch("services.pixiv_downloader.PixivClient", return_value=mock_client),
            patch("services.pixiv_downloader.get_typed_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_pixiv_illust(
                illust_id=222222,
                refresh_token="valid_token",
                output_dir=tmp_path,
            )

        assert result["status"] == "done"
        assert result["downloaded"] == 3
        assert result["total"] == 3
        assert result["failed_pages"] == []

        image_files = sorted(f for f in tmp_path.iterdir() if f.suffix in (".jpg", ".png", ".gif", ".webp"))
        assert len(image_files) == 3
        # Extension is derived from the URL (.jpg in _MULTI_PAGE_DETAIL)
        assert image_files[0].name == "0001.jpg"
        assert image_files[2].name == "0003.jpg"

    async def test_download_multi_page_metadata_page_count(self, tmp_path):
        """metadata.json page_count should match the illustration's page_count."""
        from services.pixiv_downloader import download_pixiv_illust

        mock_client = _make_pixiv_client_mock(_MULTI_PAGE_DETAIL)

        with (
            patch("services.pixiv_downloader.PixivClient", return_value=mock_client),
            patch("services.pixiv_downloader.get_typed_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            await download_pixiv_illust(
                illust_id=222222,
                refresh_token="valid_token",
                output_dir=tmp_path,
            )

        meta = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
        assert meta["page_count"] == 3


# ---------------------------------------------------------------------------
# TestPixivDownloaderUgoira
# ---------------------------------------------------------------------------


class TestPixivDownloaderUgoira:
    """Tests for ugoira (animated) illustrations."""

    async def test_download_ugoira_treats_as_single_page(self, tmp_path):
        """Ugoira with page_count=1 should be downloaded as a single file."""
        from services.pixiv_downloader import download_pixiv_illust

        mock_client = _make_pixiv_client_mock(_UGOIRA_DETAIL)
        # Ugoira zip bytes (pretend it's valid content)
        mock_client.download_image = AsyncMock(return_value=(b"PK\x03\x04" + b"\x00" * 50, "application/zip"))

        with (
            patch("services.pixiv_downloader.PixivClient", return_value=mock_client),
            patch("services.pixiv_downloader.get_typed_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_pixiv_illust(
                illust_id=333333,
                refresh_token="valid_token",
                output_dir=tmp_path,
            )

        assert result["downloaded"] == 1
        assert result["total"] == 1

        meta = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
        assert meta["pixiv_illust_type"] == "ugoira"


# ---------------------------------------------------------------------------
# TestPixivDownloaderCancellation
# ---------------------------------------------------------------------------


class TestPixivDownloaderCancellation:
    """Tests for cancel_check integration."""

    async def test_download_cancelled_before_first_page(self, tmp_path):
        """cancel_check returning True before the first page should return status 'cancelled'."""
        from services.pixiv_downloader import download_pixiv_illust

        mock_client = _make_pixiv_client_mock(_SINGLE_PAGE_DETAIL)

        async def _always_cancel() -> bool:
            return True

        with (
            patch("services.pixiv_downloader.PixivClient", return_value=mock_client),
            patch("services.pixiv_downloader.get_typed_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_pixiv_illust(
                illust_id=111111,
                refresh_token="valid_token",
                output_dir=tmp_path,
                cancel_check=_always_cancel,
            )

        assert result["status"] == "cancelled"
        assert result["downloaded"] == 0

    async def test_download_cancelled_mid_multi_page(self, tmp_path):
        """cancel_check flips to True after first page download, remaining pages skipped."""
        from services.pixiv_downloader import download_pixiv_illust

        download_count = 0
        cancelled_after = 1  # cancel after this many downloads

        mock_client = _make_pixiv_client_mock(_MULTI_PAGE_DETAIL)

        original_download = mock_client.download_image

        async def _download_with_cancel_after_first(url: str):
            nonlocal download_count
            result = await original_download(url)
            download_count += 1
            return result

        mock_client.download_image = _download_with_cancel_after_first

        call_count = 0

        async def _cancel_after_one() -> bool:
            return call_count > cancelled_after

        # We patch cancel_check to flip after second check (first page completes, then cancelled)
        check_calls = 0

        async def _cancel_after_first_page() -> bool:
            nonlocal check_calls
            check_calls += 1
            return check_calls > 2  # allow first iteration, cancel afterwards

        with (
            patch("services.pixiv_downloader.PixivClient", return_value=mock_client),
            patch("services.pixiv_downloader.get_typed_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_pixiv_illust(
                illust_id=222222,
                refresh_token="valid_token",
                output_dir=tmp_path,
                cancel_check=_cancel_after_first_page,
            )

        assert result["status"] == "cancelled"
        # Some pages were downloaded before cancellation
        assert result["downloaded"] < 3


# ---------------------------------------------------------------------------
# TestPixivDownloaderErrorHandling
# ---------------------------------------------------------------------------


class TestPixivDownloaderErrorHandling:
    """Tests for error paths: illust not found, network failures, permission errors."""

    async def test_download_illust_not_found_returns_failed(self, tmp_path):
        """When illust_detail raises ValueError, status should be 'failed'."""
        from services.pixiv_downloader import download_pixiv_illust

        mock_client = _make_pixiv_client_mock()
        mock_client.illust_detail = AsyncMock(side_effect=ValueError("Illust 999 not found"))

        with (
            patch("services.pixiv_downloader.PixivClient", return_value=mock_client),
            patch("services.pixiv_downloader.get_typed_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_pixiv_illust(
                illust_id=999,
                refresh_token="valid_token",
                output_dir=tmp_path,
            )

        assert result["status"] == "failed"
        assert result["downloaded"] == 0
        assert "999" in result.get("error", "") or "not found" in result.get("error", "").lower()

    async def test_download_permission_error_returns_failed(self, tmp_path):
        """When illust_detail raises PermissionError (auth failure), status should be 'failed'."""
        from services.pixiv_downloader import download_pixiv_illust

        mock_client = _make_pixiv_client_mock()
        mock_client.illust_detail = AsyncMock(side_effect=PermissionError("Pixiv token invalid"))

        with (
            patch("services.pixiv_downloader.PixivClient", return_value=mock_client),
            patch("services.pixiv_downloader.get_typed_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_pixiv_illust(
                illust_id=111111,
                refresh_token="bad_token",
                output_dir=tmp_path,
            )

        assert result["status"] == "failed"
        assert "token" in result.get("error", "").lower() or "pixiv" in result.get("error", "").lower()

    async def test_download_network_error_on_image_records_failed_page(self, tmp_path):
        """When download_image raises a network exception, the page is added to failed_pages."""
        from services.pixiv_downloader import download_pixiv_illust

        mock_client = _make_pixiv_client_mock(_SINGLE_PAGE_DETAIL)
        mock_client.download_image = AsyncMock(side_effect=ConnectionError("Network unreachable"))

        with (
            patch("services.pixiv_downloader.PixivClient", return_value=mock_client),
            patch("services.pixiv_downloader.get_typed_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_pixiv_illust(
                illust_id=111111,
                refresh_token="valid_token",
                output_dir=tmp_path,
            )

        assert 1 in result["failed_pages"]
        assert result["downloaded"] == 0

    async def test_download_partial_failure_multi_page(self, tmp_path):
        """When one of three pages fails, the others should succeed and status should be 'done'."""
        from services.pixiv_downloader import download_pixiv_illust

        call_count = 0
        mock_client = _make_pixiv_client_mock(_MULTI_PAGE_DETAIL)

        async def _fail_second_page(url: str):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise IOError("Server returned 404 for page 2")
            return (_FAKE_IMAGE_BYTES, "image/png")

        mock_client.download_image = _fail_second_page

        with (
            patch("services.pixiv_downloader.PixivClient", return_value=mock_client),
            patch("services.pixiv_downloader.get_typed_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_pixiv_illust(
                illust_id=222222,
                refresh_token="valid_token",
                output_dir=tmp_path,
            )

        # Partial success: 2 of 3 pages downloaded, still reported as 'done'
        assert result["downloaded"] == 2
        assert result["total"] == 3
        assert 2 in result["failed_pages"]
        assert result["status"] == "done"

    async def test_download_on_file_callback_called_per_page(self, tmp_path):
        """on_file callback should be invoked once per successfully downloaded file."""
        from services.pixiv_downloader import download_pixiv_illust

        file_paths: list[Path] = []

        async def _on_file(path: Path) -> None:
            file_paths.append(path)

        mock_client = _make_pixiv_client_mock(_MULTI_PAGE_DETAIL)

        with (
            patch("services.pixiv_downloader.PixivClient", return_value=mock_client),
            patch("services.pixiv_downloader.get_typed_download_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await download_pixiv_illust(
                illust_id=222222,
                refresh_token="valid_token",
                output_dir=tmp_path,
                on_file=_on_file,
            )

        assert result["downloaded"] == 3
        assert len(file_paths) == 3
        # All reported paths should actually exist on disk
        for p in file_paths:
            assert p.exists()
