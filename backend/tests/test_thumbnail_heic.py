"""
Regression test for HEIC thumbnail generation.

Incident 2026-10-04: `.heic` is in IMAGE_EXTENSIONS so imports accept it, but the
worker's Pillow had no HEIF decoder (only AVIF), so every HEIC raised
``cannot identify image file`` in the thumbnail job and the blob never got a
thumbnail, phash or thumbhash.
"""

from pathlib import Path

import pytest
from PIL import Image as PILImage

SHA = "d" * 64


@pytest.fixture
def heic_source(tmp_path: Path) -> Path:
    """A real HEIC file (ftyp brand heic), wider than the smallest tier."""
    import pillow_heif

    src = tmp_path / "photo.HEIC"
    pillow_heif.from_pillow(PILImage.new("RGB", (640, 480), (200, 80, 40))).save(src)
    assert src.read_bytes()[4:12] == b"ftypheic"
    return src


def test_heic_source_generates_thumbnail_and_hashes(
    heic_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A HEIC blob must decode, not hit the `cannot identify image file` path."""
    from worker.thumbnail import _generate_single_thumbnail_sync

    monkeypatch.setattr("worker.thumbnail.thumb_dir", lambda sha: tmp_path / "thumbs" / sha)

    result = _generate_single_thumbnail_sync(SHA, "image", heic_source)

    assert result is not None
    assert (result.width, result.height) == (640, 480)
    assert result.thumbhash
    assert list((tmp_path / "thumbs" / SHA).glob("thumb_*.webp"))
