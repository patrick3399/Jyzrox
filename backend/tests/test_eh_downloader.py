"""
Tests for services.eh_downloader — download_eh_gallery().

Strategy:
- Fully mock EhClient (all network I/O) via patch("services.eh_downloader.EhClient").
- Fully mock services.cache (Redis-backed gallery/image-list cache).
- Use tmp_path (pytest built-in) as output_dir so real files are written to a
  temp directory and cleaned up automatically.
- Patch get_redis / get_download_delay to avoid Redis connections.
"""

from unittest.mock import AsyncMock, patch

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

    async def test_download_gallery_some_pages_failed_reports_partial_not_done(self, tmp_path):
        """Some-but-not-all pages failing must report 'partial', never 'done'.

        The status ternary read as a three-way branch but collapsed to two:
        anything short of a total wipeout returned "done", so a lossy download
        reached the caller as an unqualified success. Only `download.py`
        re-deriving partial-ness from `failed_pages` kept galleries from being
        marked complete; any other caller trusting `status` silently lost pages.
        """
        from services.eh_downloader import download_eh_gallery

        mock_client = _make_eh_client_mock()

        async def _download_page_with_failure(showkey, gid, page_num, ptoken, max_retries=3):
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

        assert result["status"] == "partial"
        assert result["failed_pages"] == [2]
        # A partial run must still report what it did retrieve.
        assert result["downloaded"] == 2

    async def test_download_gallery_509_error_returns_failed(self, tmp_path):
        """When Image509Error is raised, the download should return status 'failed' with 509 message."""
        from services.eh_client import Image509Error
        from services.eh_downloader import download_eh_gallery

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


# ---------------------------------------------------------------------------
# TestEhDownloaderSkipPages — incremental repair of a partial gallery
# ---------------------------------------------------------------------------


class TestEhDownloaderSkipPages:
    """Pages already held in the DB must not be re-fetched.

    Repairing a partial gallery used to re-download every page: the filesystem
    resume check globs `output_dir`, but progressive import moves files into CAS
    and finalize clears the staging dir, so on a repair run the directory is
    always empty. Recovering one missing page out of 336 cost 336 fetches and
    risked the E-Hentai 509 bandwidth limit.
    """

    async def test_skip_pages_fetches_only_the_missing_page(self, tmp_path):
        from services.eh_downloader import download_eh_gallery

        mock_client = _make_eh_client_mock()
        fetched: list[int] = []

        async def _record(showkey, gid, page_num, ptoken, max_retries=3):
            fetched.append(page_num)
            return (_FAKE_IMAGE_BYTES, "image/jpeg", "jpg")

        mock_client.download_image_with_retry = _record

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
                skip_pages={1, 3},
            )

        # Only the gap is fetched over the network.
        assert fetched == [2]
        # Skipped pages still count toward completeness: the gallery holds all 3.
        assert result["downloaded"] == 3
        assert result["status"] == "done"
        assert result["failed_pages"] == []
        # No file is written for a skipped page — its Image row already exists.
        assert not (tmp_path / "0001.jpg").exists()
        assert (tmp_path / "0002.jpg").exists()

    async def test_skip_pages_does_not_emit_on_file_for_skipped_pages(self, tmp_path):
        """on_file drives progressive import; firing it for a page we never
        downloaded would import a nonexistent path."""
        from services.eh_downloader import download_eh_gallery

        mock_client = _make_eh_client_mock()
        imported: list[str] = []

        async def _on_file(path):
            imported.append(path.name)

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
                skip_pages={1, 3},
                on_file=_on_file,
            )

        assert imported == ["0002.jpg"]

    async def test_skip_pages_still_reports_partial_when_the_missing_page_fails(self, tmp_path):
        """A repair that fails to recover its one gap must not report success."""
        from services.eh_downloader import download_eh_gallery

        mock_client = _make_eh_client_mock()

        async def _fail(showkey, gid, page_num, ptoken, max_retries=3):
            raise ConnectionError("Simulated connection failure")

        mock_client.download_image_with_retry = _fail

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
                skip_pages={1, 3},
            )

        assert result["status"] == "partial"
        assert result["failed_pages"] == [2]
        assert result["downloaded"] == 2

    async def test_skip_pages_covering_every_page_downloads_nothing(self, tmp_path):
        """A gallery with no gaps must issue no image requests at all."""
        from services.eh_downloader import download_eh_gallery

        mock_client = _make_eh_client_mock()
        fetched: list[int] = []

        async def _record(showkey, gid, page_num, ptoken, max_retries=3):
            fetched.append(page_num)
            return (_FAKE_IMAGE_BYTES, "image/jpeg", "jpg")

        mock_client.download_image_with_retry = _record

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
                skip_pages={1, 2, 3},
            )

        assert fetched == []
        assert result["downloaded"] == 3
        assert result["status"] == "done"

    async def test_no_skip_pages_preserves_full_download(self, tmp_path):
        """Omitting skip_pages must not change existing behaviour."""
        from services.eh_downloader import download_eh_gallery

        mock_client = _make_eh_client_mock()
        fetched: list[int] = []

        async def _record(showkey, gid, page_num, ptoken, max_retries=3):
            fetched.append(page_num)
            return (_FAKE_IMAGE_BYTES, "image/jpeg", "jpg")

        mock_client.download_image_with_retry = _record

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

        assert sorted(fetched) == [1, 2, 3]
        assert result["downloaded"] == 3
        assert result["status"] == "done"
