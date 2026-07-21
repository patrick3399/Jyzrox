"""
Unit tests for worker/thumbnail.py.

Covers:
- _ffprobe_metadata: valid video, missing video stream, subprocess failure
- generate_single_thumbnail: non-existent file, video blob, image blob,
  existing thumbnails skipped, OSError on PIL save, phash stored to blob
- thumbnail_job: gallery with no images, blob without source, normal processing
"""

import asyncio
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SHA = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"


def test_ugoira_zip_preview_builds_bounded_concat_manifest(tmp_path):
    from worker.thumbnail import _generate_zip_preview

    archive = tmp_path / "ugoira.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("0001.jpg", b"frame-one")
        output.writestr("nested/0002.png", b"frame-two")
        output.writestr("ignore.txt", b"not-a-frame")
    destination = tmp_path / "preview.webm"
    captured: dict[str, str] = {}

    def capture(manifest, output, *, concat=False):
        captured["manifest"] = manifest.read_text(encoding="utf-8")
        captured["destination"] = str(output)
        captured["concat"] = str(concat)

    with patch("worker.thumbnail._encode_preview", side_effect=capture):
        _generate_zip_preview(archive, destination)

    assert "000000.jpg" in captured["manifest"]
    assert "000001.png" in captured["manifest"]
    assert "duration 0.083333" in captured["manifest"]
    assert captured["destination"] == str(destination)
    assert captured["concat"] == "True"


def _make_blob(media_type="image", extension=".jpg", sha256=SHA):
    blob = MagicMock()
    blob.sha256 = sha256
    blob.extension = extension
    blob.media_type = media_type
    blob.width = None
    blob.height = None
    blob.duration = None
    blob.phash = None
    blob.phash_int = None
    blob.phash_q0 = None
    blob.phash_q1 = None
    blob.phash_q2 = None
    blob.phash_q3 = None
    blob.thumbhash = None
    return blob


def _make_gallery(source="local"):
    gallery = MagicMock()
    gallery.source = source
    return gallery


def _make_thumbnail_image(page_num: int, sha256: str):
    blob = _make_blob(sha256=sha256)
    img = MagicMock()
    img.page_num = page_num
    img.blob = blob
    return img


def _ffprobe_stdout(width=1920, height=1080, duration=120.0):
    """Return JSON string that mimics ffprobe -print_format json output."""
    data = {
        "streams": [{"codec_type": "video", "width": width, "height": height}],
        "format": {"duration": str(duration)},
    }
    return json.dumps(data)


def _make_completed_process(stdout="", returncode=0):
    cp = MagicMock()
    cp.stdout = stdout
    cp.returncode = returncode
    return cp


def _make_pil_mocks(width=100, height=100):
    """
    Build a cohesive set of PIL mock objects.

    Returns (mock_pil_img, mock_pil_module) where mock_pil_module can be
    injected via patch.dict(sys.modules, {"PIL": ..., "PIL.Image": ...}).

    The mock_pil_img mimics a context-manager PIL image with .size, .convert,
    and supports the thumbhash path (RGBA -> tobytes).
    """
    mock_pil_img = MagicMock()
    mock_pil_img.__enter__ = MagicMock(return_value=mock_pil_img)
    mock_pil_img.__exit__ = MagicMock(return_value=False)
    mock_pil_img.size = (width, height)

    mock_rgb = MagicMock()
    mock_rgb.height = height
    mock_thumb = MagicMock()
    mock_thumb.height = height
    mock_rgb.copy.return_value = mock_thumb

    mock_rgba = MagicMock()
    mock_rgba.size = (min(width, 100), min(height, 100))
    mock_rgba.width = mock_rgba.size[0]
    mock_rgba.height = mock_rgba.size[1]
    mock_rgba.tobytes.return_value = b"\x00" * (mock_rgba.size[0] * mock_rgba.size[1] * 4)

    mock_pil_img.convert = MagicMock(side_effect=lambda m: mock_rgb if m == "RGB" else mock_rgba)

    mock_image_cls = MagicMock()
    mock_image_cls.open.return_value = mock_pil_img
    mock_image_cls.LANCZOS = MagicMock()

    mock_pil_module = MagicMock()
    mock_pil_module.Image = mock_image_cls
    mock_pil_module.ImageOps.exif_transpose.side_effect = lambda image: image

    return mock_pil_img, mock_pil_module


def _make_imagehash_mock(phash_hex="aabbccddeeff0011"):
    """Return an imagehash module mock whose .phash() returns a mock hash."""
    mock_val = MagicMock()
    mock_val.__str__ = MagicMock(return_value=phash_hex)
    mock_mod = MagicMock()
    mock_mod.phash.return_value = mock_val
    return mock_mod


def _make_thumbhash_mock():
    mock_mod = MagicMock()
    mock_mod.rgba_to_thumb_hash.return_value = list(b"thumbhash-value")
    return mock_mod


# ---------------------------------------------------------------------------
# TestFfprobeMetadata
# ---------------------------------------------------------------------------


class TestFfprobeMetadata:
    """Tests for _ffprobe_metadata(src)."""

    def test_valid_video_returns_width_height_duration(self):
        """Valid ffprobe output should populate all three keys."""
        from worker.thumbnail import _ffprobe_metadata

        cp = _make_completed_process(stdout=_ffprobe_stdout(1280, 720, 60.5))
        with patch("subprocess.run", return_value=cp):
            result = _ffprobe_metadata(Path("/fake/video.mp4"))

        assert result["width"] == 1280
        assert result["height"] == 720
        assert result["duration"] == pytest.approx(60.5)

    def test_missing_video_stream_returns_none_values(self):
        """If no 'video' codec_type stream exists, width/height should be None."""
        from worker.thumbnail import _ffprobe_metadata

        data = {
            "streams": [{"codec_type": "audio"}],
            "format": {"duration": "10.0"},
        }
        cp = _make_completed_process(stdout=json.dumps(data))
        with patch("subprocess.run", return_value=cp):
            result = _ffprobe_metadata(Path("/fake/audio_only.mp4"))

        assert result["width"] is None
        assert result["height"] is None
        assert result["duration"] == pytest.approx(10.0)

    def test_ffprobe_not_found_raises_and_propagates(self):
        """FileNotFoundError from subprocess.run should propagate out of the function."""
        from worker.thumbnail import _ffprobe_metadata

        with patch("subprocess.run", side_effect=FileNotFoundError("ffprobe not found")):
            with pytest.raises(FileNotFoundError):
                _ffprobe_metadata(Path("/fake/video.mp4"))


# ---------------------------------------------------------------------------
# TestGenerateSingleThumbnail
# ---------------------------------------------------------------------------


class TestGenerateSingleThumbnail:
    """Tests for generate_single_thumbnail(blob, src, session)."""

    def _thumb_dir(self, tmp_path):
        return tmp_path / "thumbs" / SHA[:2] / SHA[2:4] / SHA

    async def test_long_image_variants_use_fixed_width_tiers(self, tmp_path):
        """Long images must not collapse below their advertised srcset width."""
        from PIL import Image as PILImage

        from worker.thumbnail import generate_single_thumbnail

        blob = _make_blob(media_type="image")
        src = tmp_path / "long.png"
        PILImage.new("RGB", (100, 1000), "white").save(src)
        td = self._thumb_dir(tmp_path)

        with patch("worker.thumbnail.thumb_dir", return_value=td):
            assert await generate_single_thumbnail(blob, src) is True

        with PILImage.open(td / "thumb_160.webp") as thumbnail:
            assert thumbnail.size == (100, 1000)  # small originals are never upscaled

        larger_src = tmp_path / "larger-long.png"
        PILImage.new("RGB", (200, 1000), "white").save(larger_src)
        other_td = tmp_path / "other-thumbs"
        other_blob = _make_blob(media_type="image")
        other_blob.sha256 = "f" * 64
        with patch("worker.thumbnail.thumb_dir", return_value=other_td):
            assert await generate_single_thumbnail(other_blob, larger_src) is True
        with PILImage.open(other_td / "thumb_160.webp") as thumbnail:
            assert thumbnail.size == (160, 800)

    async def test_nonexistent_source_file_returns_false(self, tmp_path):
        """A src path that does not exist should return False immediately."""
        from worker.thumbnail import generate_single_thumbnail

        blob = _make_blob(media_type="image")
        src = tmp_path / "nonexistent.jpg"
        session = AsyncMock()

        result = await generate_single_thumbnail(blob, src, session)

        assert result is False

    async def test_image_blob_calls_pil_and_stores_phash(self, tmp_path):
        """Image blob: PIL is used; width/height/phash are stored on the blob."""
        from worker.thumbnail import generate_single_thumbnail

        blob = _make_blob(media_type="image")
        src = tmp_path / "image.jpg"
        src.write_bytes(b"fake-image-data")

        td = self._thumb_dir(tmp_path)
        _, mock_pil_module = _make_pil_mocks(800, 600)
        mock_imagehash = _make_imagehash_mock("aabbccddeeff0011")
        mock_thumbhash = _make_thumbhash_mock()
        session = AsyncMock()

        with (
            patch("worker.thumbnail.thumb_dir", return_value=td),
            patch.dict(
                "sys.modules",
                {
                    "PIL": mock_pil_module,
                    "PIL.Image": mock_pil_module.Image,
                    "imagehash": mock_imagehash,
                    "thumbhash": mock_thumbhash,
                },
            ),
            patch("os.replace"),
        ):
            result = await generate_single_thumbnail(blob, src, session)

        assert result is True
        assert blob.width == 800
        assert blob.height == 600
        assert blob.phash == "aabbccddeeff0011"
        assert blob.thumbhash == "dGh1bWJoYXNoLXZhbHVl"
        mock_thumbhash.rgba_to_thumb_hash.assert_called()

    async def test_video_blob_calls_ffprobe_and_extract_frame(self, tmp_path):
        """Video blob: _ffprobe_metadata and _extract_video_frame are called."""
        from worker.thumbnail import generate_single_thumbnail

        blob = _make_blob(media_type="video", extension=".mp4")
        src = tmp_path / "video.mp4"
        src.write_bytes(b"fake-video-data")

        td = self._thumb_dir(tmp_path)
        _, mock_pil_module = _make_pil_mocks(1280, 720)
        mock_imagehash = _make_imagehash_mock()
        mock_thumbhash = _make_thumbhash_mock()

        meta = {"width": 1280, "height": 720, "duration": 30.0}
        session = AsyncMock()

        with (
            patch("worker.thumbnail.thumb_dir", return_value=td),
            patch("worker.thumbnail._ffprobe_metadata", return_value=meta) as mock_ffprobe,
            patch("worker.thumbnail._extract_video_frame") as mock_extract,
            patch.dict(
                "sys.modules",
                {
                    "PIL": mock_pil_module,
                    "PIL.Image": mock_pil_module.Image,
                    "imagehash": mock_imagehash,
                    "thumbhash": mock_thumbhash,
                },
            ),
            patch("os.replace"),
        ):
            result = await generate_single_thumbnail(blob, src, session)

        assert result is True
        mock_ffprobe.assert_called_once_with(src)
        mock_extract.assert_called_once()
        assert blob.width == 1280
        assert blob.height == 720
        assert blob.duration == pytest.approx(30.0)

    async def test_existing_thumbnails_not_regenerated(self, tmp_path):
        """When all thumb_NNN.webp files already exist, os.rename is never called."""
        from worker.thumbnail import generate_single_thumbnail

        blob = _make_blob(media_type="image")
        src = tmp_path / "image.jpg"
        src.write_bytes(b"data")

        td = self._thumb_dir(tmp_path)
        td.mkdir(parents=True, exist_ok=True)

        # Pre-create all three thumb files so dest.exists() returns True
        for size in (160, 360, 720):
            (td / f"thumb_{size}.webp").write_bytes(b"existing")
        (td / ".thumbnail-version").write_text("2", encoding="ascii")

        _, mock_pil_module = _make_pil_mocks(100, 100)
        mock_imagehash = _make_imagehash_mock("0000000000000000")
        mock_thumbhash = _make_thumbhash_mock()
        session = AsyncMock()

        with (
            patch("worker.thumbnail.thumb_dir", return_value=td),
            patch.dict(
                "sys.modules",
                {
                    "PIL": mock_pil_module,
                    "PIL.Image": mock_pil_module.Image,
                    "imagehash": mock_imagehash,
                    "thumbhash": mock_thumbhash,
                },
            ),
            patch("os.replace") as mock_replace,
        ):
            result = await generate_single_thumbnail(blob, src, session)

        assert result is True
        mock_replace.assert_not_called()

    async def test_oserror_during_pil_open_returns_false(self, tmp_path):
        """OSError raised when PIL opens the file should cause the function to return False."""
        from worker.thumbnail import generate_single_thumbnail

        blob = _make_blob(media_type="image")
        src = tmp_path / "image.jpg"
        src.write_bytes(b"data")

        td = self._thumb_dir(tmp_path)

        mock_image_cls = MagicMock()
        mock_image_cls.open.side_effect = OSError("disk full")
        mock_pil_module = MagicMock()
        mock_pil_module.Image = mock_image_cls
        mock_imagehash = _make_imagehash_mock()
        session = AsyncMock()

        with (
            patch("worker.thumbnail.thumb_dir", return_value=td),
            patch.dict(
                "sys.modules",
                {
                    "PIL": mock_pil_module,
                    "PIL.Image": mock_pil_module.Image,
                    "imagehash": mock_imagehash,
                },
            ),
        ):
            result = await generate_single_thumbnail(blob, src, session)

        assert result is False

    async def test_phash_computed_and_stored_on_blob(self, tmp_path):
        """After a successful image run, blob.phash and blob.phash_int must be set."""
        from worker.thumbnail import generate_single_thumbnail

        blob = _make_blob(media_type="image")
        src = tmp_path / "image.jpg"
        src.write_bytes(b"data")

        td = self._thumb_dir(tmp_path)
        _, mock_pil_module = _make_pil_mocks(64, 64)
        # phash_int = int("0000000000000001", 16) = 1
        mock_imagehash = _make_imagehash_mock("0000000000000001")
        mock_thumbhash = _make_thumbhash_mock()
        session = AsyncMock()

        with (
            patch("worker.thumbnail.thumb_dir", return_value=td),
            patch.dict(
                "sys.modules",
                {
                    "PIL": mock_pil_module,
                    "PIL.Image": mock_pil_module.Image,
                    "imagehash": mock_imagehash,
                    "thumbhash": mock_thumbhash,
                },
            ),
            patch("os.replace"),
        ):
            await generate_single_thumbnail(blob, src, session)

        assert blob.phash == "0000000000000001"
        assert blob.phash_int == 1


# ---------------------------------------------------------------------------
# TestThumbnailJob
# ---------------------------------------------------------------------------


def _make_mock_session_ctx(images, gallery=None):
    """Return a mock AsyncSessionLocal context manager yielding a session."""
    session = AsyncMock()
    if gallery is None:
        gallery = _make_gallery()
    session.get = AsyncMock(return_value=gallery)

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = images
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    session.execute = AsyncMock(return_value=execute_result)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


class TestThumbnailJob:
    """Tests for thumbnail_job(ctx, gallery_id)."""

    async def test_gallery_with_no_images_returns_zero_processed(self):
        """A gallery that has no Image rows should return processed=0."""
        from worker.thumbnail import thumbnail_job

        session = _make_mock_session_ctx(images=[])
        ctx = {}

        with (
            patch("worker.thumbnail.AsyncSessionLocal", return_value=session),
            patch("worker.thumbnail.resolve_blob_path"),
            patch("worker.thumbnail.generate_single_thumbnail", new_callable=AsyncMock),
        ):
            result = await thumbnail_job(ctx, gallery_id=42)

        assert result["status"] == "done"
        assert result["processed"] == 0

    async def test_blob_without_source_file_is_skipped(self):
        """Images whose generate_single_thumbnail returns False should not be counted."""
        from worker.thumbnail import thumbnail_job

        blob = _make_blob()
        img = MagicMock()
        img.blob = blob
        img.page_num = 1

        session = _make_mock_session_ctx(images=[img])
        ctx = {}

        fake_src = MagicMock(spec=Path)

        with (
            patch("worker.thumbnail.AsyncSessionLocal", return_value=session),
            patch("worker.thumbnail.resolve_blob_path", return_value=fake_src),
            patch(
                "worker.thumbnail._run_thumbnail_in_thread",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await thumbnail_job(ctx, gallery_id=7)

        assert result["processed"] == 0

    async def test_normal_processing_counts_successes(self):
        """Successful generate_single_thumbnail calls should increment processed."""
        from worker.thumbnail import thumbnail_job

        blob1 = _make_blob(sha256="a" * 64)
        blob2 = _make_blob(sha256="b" * 64)

        img1 = MagicMock()
        img1.blob = blob1
        img1.page_num = 1
        img2 = MagicMock()
        img2.blob = blob2
        img2.page_num = 2

        # img3 has no blob — must be skipped
        img3 = MagicMock()
        img3.blob = None
        img3.page_num = 3

        session = _make_mock_session_ctx(images=[img1, img2, img3])
        ctx = {}

        fake_src = MagicMock(spec=Path)
        from worker.thumbnail import _ThumbnailResult

        with (
            patch("worker.thumbnail.AsyncSessionLocal", return_value=session),
            patch("worker.thumbnail.resolve_blob_path", return_value=fake_src),
            patch(
                "worker.thumbnail._run_thumbnail_in_thread",
                new_callable=AsyncMock,
                return_value=_ThumbnailResult(width=1, height=1),
            ),
        ):
            result = await thumbnail_job(ctx, gallery_id=99)

        assert result["status"] == "done"
        assert result["processed"] == 2

    async def test_thumbnail_job_processes_cover_image_first(self):
        """Full thumbnail job should schedule the configured cover image first."""
        from worker.thumbnail import _ThumbnailResult, thumbnail_job

        img1 = _make_thumbnail_image(1, "a" * 64)
        img2 = _make_thumbnail_image(2, "b" * 64)
        img3 = _make_thumbnail_image(3, "c" * 64)
        session = _make_mock_session_ctx(images=[img1, img2, img3], gallery=_make_gallery("last-cover-source"))

        seen: list[str] = []

        async def _fake_run(sha256, media_type, src):
            seen.append(sha256)
            return _ThumbnailResult(width=1, height=1)

        with (
            patch("worker.thumbnail.AsyncSessionLocal", return_value=session),
            patch("worker.thumbnail.resolve_blob_path", return_value=MagicMock(spec=Path)),
            patch(
                "core.source_display.get_display_config",
                return_value=SimpleNamespace(cover_page="last"),
            ),
            patch("worker.thumbnail._run_thumbnail_in_thread", side_effect=_fake_run),
        ):
            result = await thumbnail_job({}, gallery_id=99)

        assert result["processed"] == 3
        assert seen == ["c" * 64, "a" * 64, "b" * 64]

    async def test_thumbnail_job_commits_in_batches(self):
        """THUMBNAIL_COMMIT_BATCH should control DB commit cadence."""
        from worker.thumbnail import _ThumbnailResult, thumbnail_job

        images = [
            _make_thumbnail_image(1, "a" * 64),
            _make_thumbnail_image(2, "b" * 64),
            _make_thumbnail_image(3, "c" * 64),
        ]
        session = _make_mock_session_ctx(images=images)

        with (
            patch.dict("os.environ", {"THUMBNAIL_COMMIT_BATCH": "2"}),
            patch("worker.thumbnail.AsyncSessionLocal", return_value=session),
            patch("worker.thumbnail.resolve_blob_path", return_value=MagicMock(spec=Path)),
            patch(
                "worker.thumbnail._run_thumbnail_in_thread",
                new_callable=AsyncMock,
                return_value=_ThumbnailResult(width=1, height=1),
            ),
        ):
            result = await thumbnail_job({}, gallery_id=99)

        assert result["processed"] == 3
        assert session.commit.await_count == 2

    async def test_cover_thumbnail_job_only_processes_cover_image(self):
        """Cover job should process exactly the configured cover image and commit."""
        from worker.thumbnail import _ThumbnailResult, cover_thumbnail_job

        img1 = _make_thumbnail_image(1, "a" * 64)
        img2 = _make_thumbnail_image(2, "b" * 64)
        session = _make_mock_session_ctx(images=[img1, img2], gallery=_make_gallery("last-cover-source"))
        seen: list[str] = []

        async def _fake_run(sha256, media_type, src):
            seen.append(sha256)
            return _ThumbnailResult(width=1, height=1)

        with (
            patch("worker.thumbnail.AsyncSessionLocal", return_value=session),
            patch("worker.thumbnail.select_cover_image", new_callable=AsyncMock, return_value=img2),
            patch("worker.thumbnail.resolve_blob_path", return_value=MagicMock(spec=Path)),
            patch("worker.thumbnail._run_thumbnail_in_thread", side_effect=_fake_run),
        ):
            result = await cover_thumbnail_job({}, gallery_id=99)

        assert result["processed"] == 1
        assert seen == ["b" * 64]
        assert session.commit.await_count == 1

    async def test_thumbnail_workers_limits_to_thread_concurrency(self):
        """THUMBNAIL_WORKERS should bound concurrent to_thread calls."""
        from worker.thumbnail import _run_thumbnail_in_thread, _ThumbnailResult

        active = 0
        max_active = 0

        async def _fake_to_thread(func, *args):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return _ThumbnailResult(width=1, height=1)

        with (
            patch.dict("os.environ", {"THUMBNAIL_WORKERS": "2"}),
            patch("worker.thumbnail.asyncio.to_thread", new_callable=AsyncMock, side_effect=_fake_to_thread),
        ):
            results = await asyncio.gather(
                *[_run_thumbnail_in_thread("a" * 64, "image", Path("/tmp/image.jpg")) for _ in range(5)]
            )

        assert len(results) == 5
        assert max_active == 2


# ---------------------------------------------------------------------------
# TestBlobNeedsThumbnail  (STAB-005 regression)
# ---------------------------------------------------------------------------


class TestBlobNeedsThumbnail:
    """Regression tests for _blob_needs_thumbnail() skip guard (STAB-005).

    Verifies that completed blobs are correctly identified so thumbnail_job
    does not re-process them, preventing duplicate render work.
    """

    def _all_thumbs_dir(self, tmp_path):
        """Create and return a thumb dir with all three sizes present."""
        td = tmp_path / SHA[:2] / SHA[2:4] / SHA
        td.mkdir(parents=True)
        for size in (160, 360, 720):
            (td / f"thumb_{size}.webp").write_bytes(b"x")
        (td / ".thumbnail-version").write_text("2", encoding="ascii")
        return td

    def test_none_blob_returns_false(self):
        """None blob must return False without raising."""
        from worker.thumbnail import _blob_needs_thumbnail

        assert _blob_needs_thumbnail(None) is False

    def test_missing_thumb_file_returns_true(self, tmp_path):
        """Returns True when any thumb_{size}.webp is absent from disk."""
        from worker.thumbnail import _blob_needs_thumbnail

        blob = _make_blob()
        blob.width = 100
        blob.height = 100
        blob.thumbhash = "h"
        blob.phash = "0" * 16

        td = tmp_path / SHA[:2] / SHA[2:4] / SHA
        td.mkdir(parents=True)
        for size in (160, 360):  # 720 deliberately missing
            (td / f"thumb_{size}.webp").write_bytes(b"x")

        with patch("worker.thumbnail.thumb_dir", return_value=td):
            assert _blob_needs_thumbnail(blob) is True

    def test_missing_width_metadata_returns_true(self, tmp_path):
        """Returns True when all thumbs exist but blob.width is None."""
        from worker.thumbnail import _blob_needs_thumbnail

        blob = _make_blob()
        blob.width = None
        blob.height = 100
        blob.thumbhash = "h"
        blob.phash = "0" * 16

        with patch("worker.thumbnail.thumb_dir", return_value=self._all_thumbs_dir(tmp_path)):
            assert _blob_needs_thumbnail(blob) is True

    def test_image_blob_missing_phash_returns_true(self, tmp_path):
        """Returns True for non-video blob with all thumbs present but phash=None."""
        from worker.thumbnail import _blob_needs_thumbnail

        blob = _make_blob(media_type="image")
        blob.width = 100
        blob.height = 100
        blob.thumbhash = "h"
        blob.phash = None  # non-video blobs require phash

        with patch("worker.thumbnail.thumb_dir", return_value=self._all_thumbs_dir(tmp_path)):
            assert _blob_needs_thumbnail(blob) is True

    def test_complete_image_blob_returns_false(self, tmp_path):
        """Returns False when all thumbs exist and all metadata is present."""
        from worker.thumbnail import _blob_needs_thumbnail

        blob = _make_blob(media_type="image")
        blob.width = 100
        blob.height = 100
        blob.thumbhash = "h"
        blob.phash = "aabbccddeeff0011"

        with patch("worker.thumbnail.thumb_dir", return_value=self._all_thumbs_dir(tmp_path)):
            assert _blob_needs_thumbnail(blob) is False

    def test_complete_video_blob_without_phash_returns_false(self, tmp_path):
        """Returns False for video blob with complete thumbs/metadata but no phash (videos skip phash)."""
        from worker.thumbnail import _blob_needs_thumbnail

        blob = _make_blob(media_type="video")
        blob.width = 1920
        blob.height = 1080
        blob.thumbhash = "h"
        blob.phash = None  # videos are exempt from phash check

        with patch("worker.thumbnail.thumb_dir", return_value=self._all_thumbs_dir(tmp_path)):
            assert _blob_needs_thumbnail(blob) is False


# ---------------------------------------------------------------------------
# TestProcessImageBatch  (STAB-005 regression)
# ---------------------------------------------------------------------------


class TestProcessImageBatch:
    """Regression tests for _process_image_batch() complete-blob skip (STAB-005).

    Verifies that blobs returning False from _blob_needs_thumbnail() are
    excluded from the work list so _run_thumbnail_in_thread is never called.
    """

    async def test_complete_blobs_are_not_reprocessed(self):
        """_process_image_batch must skip images whose blobs need no work."""
        from worker.thumbnail import _process_image_batch

        img = MagicMock()
        img.blob = _make_blob()

        with (
            patch("worker.thumbnail._blob_needs_thumbnail", return_value=False),
            patch(
                "worker.thumbnail._run_thumbnail_in_thread",
                new_callable=AsyncMock,
            ) as mock_run,
        ):
            result = await _process_image_batch(AsyncMock(), [img])

        assert result == 0
        mock_run.assert_not_called()

    async def test_incomplete_blobs_are_processed(self):
        """_process_image_batch must process images whose blobs need thumbnails."""
        from worker.thumbnail import _process_image_batch, _ThumbnailResult

        img = MagicMock()
        img.blob = _make_blob()

        with (
            patch("worker.thumbnail._blob_needs_thumbnail", return_value=True),
            patch("worker.thumbnail.resolve_blob_path", return_value=MagicMock(spec=Path)),
            patch(
                "worker.thumbnail._run_thumbnail_in_thread",
                new_callable=AsyncMock,
                return_value=_ThumbnailResult(width=100, height=100),
            ) as mock_run,
            patch("worker.thumbnail._apply_thumbnail_result"),
        ):
            result = await _process_image_batch(AsyncMock(), [img])

        assert result == 1
        mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# Regression: edge case #110 — PIL decompression bomb limit must be set
# ---------------------------------------------------------------------------


class TestThumbnailDecompressionBombLimit:
    """_generate_single_thumbnail_sync must cap PIL.MAX_IMAGE_PIXELS — edge case #110."""

    def test_max_image_pixels_set_before_open(self):
        """After calling _generate_single_thumbnail_sync, PIL.MAX_IMAGE_PIXELS must be <= 50M.

        Before the fix there was no cap, so a crafted image with billions of pixels
        could exhaust process memory (decompression bomb).
        """
        from pathlib import Path
        from unittest.mock import MagicMock, patch

        src = MagicMock(spec=Path)
        src.exists.return_value = False  # early-return path — no actual PIL open needed

        with patch.dict("sys.modules", {"imagehash": MagicMock()}):
            from worker.thumbnail import _generate_single_thumbnail_sync

            _generate_single_thumbnail_sync("abc123", "image", src)

        # Import PIL as the production code does to read the current cap
        from PIL import Image as PILImage  # type: ignore[import]

        assert PILImage.MAX_IMAGE_PIXELS is not None
        assert PILImage.MAX_IMAGE_PIXELS <= 50_000_000, (
            f"PIL.MAX_IMAGE_PIXELS must be <= 50M, got {PILImage.MAX_IMAGE_PIXELS}"
        )
