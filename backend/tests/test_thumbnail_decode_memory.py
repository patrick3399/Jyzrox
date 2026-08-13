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

``encode_pil_thumbhash`` itself is unchanged: it is now handed an
already-downscaled image, and its only other caller
(``worker/thumbhash_backfill.py``) passes a 160 px thumbnail, so no
full-resolution path reaches it.

phash deliberately still runs at source resolution: it feeds dedup Tier-1 and
existing rows must stay comparable. It converts to mode "L" (1 byte/px), the
cheapest of the full-size derivations, so these tests allow it.
"""

import asyncio
import threading
import time
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


async def test_decodes_stay_within_thumbnail_workers_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Peak memory follows arena count, and arena count follows thread count.

    `asyncio.to_thread` dispatches to the process-wide default executor, which
    also serves file hashing and every other worker `to_thread` call, so
    decodes land on arbitrary threads. glibc gives each thread its own arena
    and `MALLOC_ARENA_MAX=2` then retains two full-size arenas even though the
    THUMBNAIL_WORKERS semaphore permitted only one decode at a time. That is
    why THUMBNAIL_WORKERS=1 still OOM-killed a one-off container on
    2026-08-13 after only five of gallery 523409's images.
    """
    from worker import thumbnail as thumbnail_module

    monkeypatch.setenv("THUMBNAIL_WORKERS", "2")
    monkeypatch.setattr(thumbnail_module, "_thumbnail_semaphore", None)
    monkeypatch.setattr(thumbnail_module, "_thumbnail_semaphore_size", None)
    monkeypatch.setattr(thumbnail_module, "_thumbnail_executor", None, raising=False)
    monkeypatch.setattr(thumbnail_module, "_thumbnail_executor_size", None, raising=False)

    seen: set[str] = set()
    lock = threading.Lock()

    def fake_sync(*args):
        with lock:
            seen.add(threading.current_thread().name)
        # Hold the slot long enough that a wider pool would visibly fan out.
        time.sleep(0.02)
        return None

    monkeypatch.setattr(thumbnail_module, "_generate_single_thumbnail_sync", fake_sync)

    # Grow the default executor first. Without this the shared pool may happen
    # to hold exactly THUMBNAIL_WORKERS threads and the count assertion below
    # would pass while still using the wrong pool.
    await asyncio.gather(*[asyncio.to_thread(time.sleep, 0.02) for _ in range(8)])

    await asyncio.gather(
        *[thumbnail_module._run_thumbnail_in_thread(SHA_A, "image", Path("unused")) for _ in range(24)]
    )

    # Deterministic: names come from the dedicated pool's thread_name_prefix,
    # so this fails whatever the scheduler does with the shared executor.
    assert all(name.startswith("thumbnail") for name in seen), (
        f"decodes ran outside the dedicated thumbnail pool: {sorted(seen)}"
    )
    assert len(seen) <= 2, f"decodes spread across {len(seen)} threads (= glibc arenas)"
