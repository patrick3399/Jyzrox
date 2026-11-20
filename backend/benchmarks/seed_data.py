"""Benchmark seed constants and random-value helpers."""

import hashlib
import random
from datetime import UTC, datetime, timedelta

random.seed(42)


# ---------------------------------------------------------------------------
# Scale constants
# ---------------------------------------------------------------------------

GALLERY_COUNT = 10_000
TAG_COUNT = 10_000
BLOB_COUNT = 200_000
IMAGES_PER_GALLERY_MIN = 50
IMAGES_PER_GALLERY_MAX = 200
GALLERY_TAGS_PER_GALLERY_MIN = 5
GALLERY_TAGS_PER_GALLERY_MAX = 15
FAVORITE_COUNT = 1_000
RATING_COUNT = 2_000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOURCES = ["ehentai", "pixiv", "local", "gallery_dl"]
_SOURCE_WEIGHTS = [0.40, 0.30, 0.20, 0.10]

_NAMESPACES = ["general", "character", "artist", "parody", "misc"]
_NAMESPACE_WEIGHTS = [0.60, 0.20, 0.10, 0.05, 0.05]

_MEDIA_TYPES = ["image/jpeg", "image/png", "image/webp"]
_MEDIA_WEIGHTS = [0.80, 0.15, 0.05]
_MEDIA_EXTS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}

_VISIBILITIES = ["public", "private", "system"]
_VIS_WEIGHTS = [0.90, 0.05, 0.05]

_WORDS = [
    "azure",
    "crimson",
    "shadow",
    "light",
    "storm",
    "bloom",
    "drift",
    "spiral",
    "echo",
    "prism",
    "tide",
    "frost",
    "ember",
    "glow",
    "flux",
    "veil",
    "arc",
    "peak",
    "hollow",
    "surge",
]

_NOW = datetime.now(tz=UTC)


def _rand_added_at() -> datetime:
    """Random datetime within the past 730 days."""
    return _NOW - timedelta(days=random.uniform(0, 730))


def _rand_source() -> str:
    return random.choices(_SOURCES, weights=_SOURCE_WEIGHTS)[0]


def _rand_visibility() -> str:
    return random.choices(_VISIBILITIES, weights=_VIS_WEIGHTS)[0]


def _rand_namespace() -> str:
    return random.choices(_NAMESPACES, weights=_NAMESPACE_WEIGHTS)[0]


def _rand_media_type() -> str:
    return random.choices(_MEDIA_TYPES, weights=_MEDIA_WEIGHTS)[0]


def _blob_sha(i: int) -> str:
    return hashlib.sha256(f"blob-{i}".encode()).hexdigest()


def _phash_quarters(phash_int: int) -> tuple[int, int, int, int]:
    """Split a 64-bit int into four 16-bit signed integers."""
    mask = 0xFFFF
    q0 = phash_int & mask
    q1 = (phash_int >> 16) & mask
    q2 = (phash_int >> 32) & mask
    q3 = (phash_int >> 48) & mask

    # Convert to signed SMALLINT range (-32768..32767)
    def _signed(v: int) -> int:
        return v if v < 32768 else v - 65536

    return _signed(q0), _signed(q1), _signed(q2), _signed(q3)


def _ts(dt: datetime) -> str:
    """Format datetime as ISO-8601 string with timezone for asyncpg COPY."""
    return dt.isoformat()
