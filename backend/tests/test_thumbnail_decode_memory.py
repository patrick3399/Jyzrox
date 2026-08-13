"""
Regression tests for thumbnail decode memory behaviour.

Incident 2026-08-13: an 8660x11547 source (gallery 523409, 119 such images)
peaked at a measured 1284 MB per image because every derivation ran at full
source resolution. It OOM-killed the 2 GB worker container twice (2026-08-12
00:16 and 2026-08-13 02:02), and the second kill stranded four local imports in
`download_status='importing'`.

The full-resolution allocations were:
- ``ImageOps.exif_transpose(image)`` returning ``image.copy()`` when there is no
  orientation tag to apply
- ``encode_pil_thumbhash`` converting to RGB before shrinking to 100x100
- ``pil.convert("RGB")`` for the tier source
- ``_resize_width_tier`` copying before ``Image.thumbnail()``, once per tier

phash deliberately still runs at source resolution: it feeds dedup Tier-1 and
existing rows must stay comparable. It converts to mode "L" (1 byte/px), the
cheapest of the full-size derivations, so these tests allow it.
"""

from pathlib import Path

import pytest
from PIL import Image as PILImage

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64

# Comfortably wider than the largest thumbnail tier, small enough to stay fast.
SOURCE_SIZE = (2000, 2500)


@pytest.fixture
def large_source(tmp_path: Path) -> Path:
    """A source image wider than every thumbnail tier, with no EXIF orientation."""
    src = tmp_path / "large.png"
    PILImage.new("RGB", SOURCE_SIZE, (120, 30, 200)).save(src)
    return src


def test_generate_thumbnail_does_not_allocate_at_source_resolution(
    large_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Source-resolution convert()/copy() is what crossed the 2 GB worker cap.

    Anything wider than the largest tier converting to a 3-4 byte/px mode, or
    copied at all, is the regression. A 100 MP source makes each such buffer
    300-400 MB.
    """
    from services.cas import THUMBNAIL_SIZES
    from worker.thumbnail import _generate_single_thumbnail_sync

    max_tier = max(THUMBNAIL_SIZES)
    oversized: list[tuple[str, tuple[int, int]]] = []

    original_convert = PILImage.Image.convert
    original_copy = PILImage.Image.copy

    def spy_convert(self, mode=None, *args, **kwargs):
        if self.size[0] > max_tier and mode in ("RGB", "RGBA"):
            oversized.append((f"convert:{mode}", self.size))
        return original_convert(self, mode, *args, **kwargs)

    def spy_copy(self, *args, **kwargs):
        if self.size[0] > max_tier:
            oversized.append(("copy", self.size))
        return original_copy(self, *args, **kwargs)

    monkeypatch.setattr(PILImage.Image, "convert", spy_convert)
    monkeypatch.setattr(PILImage.Image, "copy", spy_copy)
    monkeypatch.setattr("worker.thumbnail.thumb_dir", lambda sha: tmp_path / "thumbs" / sha)

    result = _generate_single_thumbnail_sync(SHA_A, "image", large_source)

    assert result is not None
    assert oversized == [], f"source-resolution allocations still happening: {oversized}"


def test_generate_thumbnail_records_original_source_dimensions(
    large_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Downscaling for derivation must not leak into the recorded blob dimensions.

    `blobs.width`/`height` describe the stored file. If they came from the
    downscaled working image, the DB row would disagree with the filesystem.
    """
    from worker.thumbnail import _generate_single_thumbnail_sync

    monkeypatch.setattr("worker.thumbnail.thumb_dir", lambda sha: tmp_path / "thumbs" / sha)

    result = _generate_single_thumbnail_sync(SHA_B, "image", large_source)

    assert result is not None
    assert (result.width, result.height) == SOURCE_SIZE


def test_generate_thumbnail_writes_every_tier(
    large_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chaining tiers off the downscaled base must not drop or mis-size a tier.

    `thumbnails_complete_at()` treats a missing tier file as "needs work", so a
    dropped tier would silently re-queue the gallery forever.
    """
    from services.cas import THUMBNAIL_SIZES
    from worker.thumbnail import _generate_single_thumbnail_sync

    thumbs = tmp_path / "thumbs"
    monkeypatch.setattr("worker.thumbnail.thumb_dir", lambda sha: thumbs / sha)

    _generate_single_thumbnail_sync(SHA_C, "image", large_source)

    for size in THUMBNAIL_SIZES:
        dest = thumbs / SHA_C / f"thumb_{size}.webp"
        assert dest.is_file(), f"missing tier {size}"
        with PILImage.open(dest) as written:
            assert written.size[0] == size, f"tier {size} written at width {written.size[0]}"
