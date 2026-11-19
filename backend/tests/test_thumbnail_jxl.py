"""
Regression test for JPEG XL thumbnail generation.

Incident 2026-11-19 (Weibo JXL under .jpg, gallery weibo/3944967175): Pillow had
no JXL decoder, so a JXL blob could never get a thumbnail, phash or thumbhash.
"""

from pathlib import Path

import pytest
from PIL import Image as PILImage

SHA = "e" * 64


@pytest.fixture
def jxl_source(tmp_path: Path) -> Path:
    """A real JXL file, wider than the smallest tier."""
    import pillow_jxl  # noqa: F401

    src = tmp_path / "photo.jxl"
    PILImage.new("RGB", (640, 480), (200, 80, 40)).save(src, format="JXL")
    assert src.read_bytes()[:2] == b"\xff\x0a" or src.read_bytes()[4:8] == b"JXL "
    return src


def test_image_codecs_register_is_callable_twice() -> None:
    """The shared registration module exists and is idempotent."""
    from services.image_codecs import register_image_codecs

    register_image_codecs()
    register_image_codecs()


def test_jxl_source_generates_thumbnail_and_hashes(
    jxl_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A JXL blob must decode via the shared codec registration in worker.thumbnail."""
    import services.image_codecs as codecs
    from worker.thumbnail import _generate_single_thumbnail_sync

    assert callable(codecs.register_image_codecs)
    monkeypatch.setattr("worker.thumbnail.thumb_dir", lambda sha: tmp_path / "thumbs" / sha)

    result = _generate_single_thumbnail_sync(SHA, "image", jxl_source)

    assert result is not None
    assert (result.width, result.height) == (640, 480)
    assert result.thumbhash
    assert list((tmp_path / "thumbs" / SHA).glob("thumb_*.webp"))
