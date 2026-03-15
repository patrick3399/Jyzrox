"""
Unit tests for worker/thumbnail.py.

Covers:
- _ffprobe_metadata: valid video, missing video stream, subprocess failure
- generate_single_thumbnail: non-existent file, video blob, image blob,
  existing thumbnails skipped, OSError on PIL save, phash stored to blob
- thumbnail_job: gallery with no images, blob without source, normal processing
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SHA = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"


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


def _ffprobe_stdout(width=1920, height=1080, duration=120.0):
    """Return JSON string that mimics ffprobe -print_format json output."""
    data = {
        "streams": [
            {"codec_type": "video", "width": width, "height": height}
        ],
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
    mock_rgb.copy.return_value = MagicMock()

    mock_rgba = MagicMock()
    mock_rgba.size = (min(width, 100), min(height, 100))
    mock_rgba.tobytes.return_value = b"\x00" * (
        mock_rgba.size[0] * mock_rgba.size[1] * 4
    )

    mock_pil_img.convert = MagicMock(
        side_effect=lambda m: mock_rgb if m == "RGB" else mock_rgba
    )

    mock_image_cls = MagicMock()
    mock_image_cls.open.return_value = mock_pil_img
    mock_image_cls.LANCZOS = MagicMock()

    mock_pil_module = MagicMock()
    mock_pil_module.Image = mock_image_cls

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
    mock_mod.rgba_to_thumbhash.return_value = b"\x01\x02\x03"
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
            patch.dict("sys.modules", {
                "PIL": mock_pil_module,
                "PIL.Image": mock_pil_module.Image,
                "imagehash": mock_imagehash,
                "thumbhash": mock_thumbhash,
            }),
            patch("os.rename"),
        ):
            result = await generate_single_thumbnail(blob, src, session)

        assert result is True
        assert blob.width == 800
        assert blob.height == 600
        assert blob.phash == "aabbccddeeff0011"

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
            patch.dict("sys.modules", {
                "PIL": mock_pil_module,
                "PIL.Image": mock_pil_module.Image,
                "imagehash": mock_imagehash,
                "thumbhash": mock_thumbhash,
            }),
            patch("os.rename"),
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

        _, mock_pil_module = _make_pil_mocks(100, 100)
        mock_imagehash = _make_imagehash_mock("0000000000000000")
        mock_thumbhash = _make_thumbhash_mock()
        session = AsyncMock()

        with (
            patch("worker.thumbnail.thumb_dir", return_value=td),
            patch.dict("sys.modules", {
                "PIL": mock_pil_module,
                "PIL.Image": mock_pil_module.Image,
                "imagehash": mock_imagehash,
                "thumbhash": mock_thumbhash,
            }),
            patch("os.rename") as mock_rename,
        ):
            result = await generate_single_thumbnail(blob, src, session)

        assert result is True
        mock_rename.assert_not_called()

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
            patch.dict("sys.modules", {
                "PIL": mock_pil_module,
                "PIL.Image": mock_pil_module.Image,
                "imagehash": mock_imagehash,
            }),
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
            patch.dict("sys.modules", {
                "PIL": mock_pil_module,
                "PIL.Image": mock_pil_module.Image,
                "imagehash": mock_imagehash,
                "thumbhash": mock_thumbhash,
            }),
            patch("os.rename"),
        ):
            await generate_single_thumbnail(blob, src, session)

        assert blob.phash == "0000000000000001"
        assert blob.phash_int == 1


# ---------------------------------------------------------------------------
# TestThumbnailJob
# ---------------------------------------------------------------------------


def _make_mock_session_ctx(images):
    """Return a mock AsyncSessionLocal context manager yielding a session."""
    session = AsyncMock()

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

        session = _make_mock_session_ctx(images=[img])
        ctx = {}

        fake_src = MagicMock(spec=Path)

        with (
            patch("worker.thumbnail.AsyncSessionLocal", return_value=session),
            patch("worker.thumbnail.resolve_blob_path", return_value=fake_src),
            patch(
                "worker.thumbnail.generate_single_thumbnail",
                new_callable=AsyncMock,
                return_value=False,
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
        img2 = MagicMock()
        img2.blob = blob2

        # img3 has no blob — must be skipped
        img3 = MagicMock()
        img3.blob = None

        session = _make_mock_session_ctx(images=[img1, img2, img3])
        ctx = {}

        fake_src = MagicMock(spec=Path)

        with (
            patch("worker.thumbnail.AsyncSessionLocal", return_value=session),
            patch("worker.thumbnail.resolve_blob_path", return_value=fake_src),
            patch(
                "worker.thumbnail.generate_single_thumbnail",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await thumbnail_job(ctx, gallery_id=99)

        assert result["status"] == "done"
        assert result["processed"] == 2
