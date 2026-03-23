"""
Benchmark data seeder for Jyzrox.

Generates synthetic data at scale using asyncpg COPY for maximum throughput.
All random operations use a fixed seed (42) for reproducibility.

Scale targets:
  users:        3
  tags:         10,000
  blobs:        200,000
  galleries:    10,000
  images:       ~1,000,000 (50-200 per gallery)
  gallery_tags: ~100,000 (5-15 per gallery, deduplicated)
  image_tags:   ~2,000,000 (1-3 per image)
  favorites:    ~1,000
  ratings:      ~2,000
"""

import hashlib
import random
import time
from datetime import datetime, timedelta, timezone

import asyncpg

random.seed(42)

# ---------------------------------------------------------------------------
# Scale constants
# ---------------------------------------------------------------------------

GALLERY_COUNT = 10_000
TAG_COUNT = 10_000
BLOB_COUNT = 200_000
IMAGES_PER_GALLERY_MIN = 50
IMAGES_PER_GALLERY_MAX = 200
IMAGE_TAGS_PER_IMAGE = 3  # average; actual 1-3
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
    "azure", "crimson", "shadow", "light", "storm", "bloom", "drift",
    "spiral", "echo", "prism", "tide", "frost", "ember", "glow", "flux",
    "veil", "arc", "peak", "hollow", "surge",
]

_NOW = datetime.now(tz=timezone.utc)


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


# ---------------------------------------------------------------------------
# Phase implementations
# ---------------------------------------------------------------------------


async def _phase_users(conn: asyncpg.Connection) -> int:
    """Insert 3 users: admin, member, viewer."""
    import hashlib as _h

    def _pw(name: str) -> str:
        # bcrypt-like placeholder — real bcrypt not needed for benchmarks
        return "$2b$12$" + _h.sha256(f"bench-{name}".encode()).hexdigest()[:53]

    await conn.executemany(
        """
        INSERT INTO users (id, username, email, password_hash, role, avatar_style, locale)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (username) DO NOTHING
        """,
        [
            (1, "admin", "admin@bench.local", _pw("admin"), "admin", "gravatar", "en"),
            (2, "member", "member@bench.local", _pw("member"), "member", "gravatar", "en"),
            (3, "viewer", "viewer@bench.local", _pw("viewer"), "viewer", "gravatar", "en"),
        ],
    )
    # Reset sequence so future inserts start at 4
    await conn.execute("SELECT setval('users_id_seq', 3, true)")
    return 3


async def _phase_tags(conn: asyncpg.Connection) -> int:
    """Generate 10K tags via COPY."""
    records = []
    for i in range(TAG_COUNT):
        ns = _rand_namespace()
        name = f"{ns}_{i:05d}"
        count = random.randint(0, 500)
        records.append((ns, name, count))

    await conn.copy_records_to_table(
        "tags",
        records=records,
        columns=["namespace", "name", "count"],
    )
    return TAG_COUNT


async def _phase_blobs(conn: asyncpg.Connection) -> tuple[int, list[str]]:
    """Generate 200K blobs via COPY. Returns (count, sha_list) for downstream phases."""
    records = []
    sha_list: list[str] = []
    for i in range(BLOB_COUNT):
        sha = _blob_sha(i)
        sha_list.append(sha)
        phash_int = random.getrandbits(63)  # positive signed BIGINT
        q0, q1, q2, q3 = _phash_quarters(phash_int)
        width = random.randint(800, 4000)
        height = random.randint(1000, 5000)
        file_size = width * height * 3 // 10  # rough JPEG byte estimate
        media_type = _rand_media_type()
        ext = _MEDIA_EXTS[media_type]
        records.append((sha, file_size, media_type, width, height, phash_int, q0, q1, q2, q3, ext, "cas", 0))

    await conn.copy_records_to_table(
        "blobs",
        records=records,
        columns=["sha256", "file_size", "media_type", "width", "height",
                 "phash_int", "phash_q0", "phash_q1", "phash_q2", "phash_q3", "extension",
                 "storage", "ref_count"],
    )
    return BLOB_COUNT, sha_list


async def _phase_galleries(conn: asyncpg.Connection) -> tuple[int, list[tuple]]:
    """Generate 10K galleries via COPY. Returns (count, gallery_rows) for downstream phases."""
    gallery_rows: list[tuple] = []
    records = []
    tag_names = [f"{_rand_namespace()}_{i:05d}" for i in range(TAG_COUNT)]

    for i in range(GALLERY_COUNT):
        source = _rand_source()
        source_id = f"{source}_{i:06d}"
        words = random.sample(_WORDS, k=min(3, len(_WORDS)))
        title = f"Gallery {i:05d} - {' '.join(words)}"
        pages = random.randint(IMAGES_PER_GALLERY_MIN, IMAGES_PER_GALLERY_MAX)
        rating = random.choices([0, 1, 2, 3, 4, 5], weights=[50, 10, 10, 10, 10, 10])[0]
        added_at = _rand_added_at()
        visibility = _rand_visibility()
        user_id = random.randint(1, 3)
        deleted_at = None if random.random() < 0.95 else (_rand_added_at())
        # tags_array: 5-15 random tag strings in namespace:name format
        n_tags = random.randint(GALLERY_TAGS_PER_GALLERY_MIN, GALLERY_TAGS_PER_GALLERY_MAX)
        picked = random.sample(tag_names, k=n_tags)
        # t is like "general_00042" → "general:general_00042"
        tags_array_val = [f"{t.split('_', 1)[0]}:{t}" for t in picked]

        # Store gallery_rows for image/gallery_tag generation
        gallery_rows.append((i + 1, pages, added_at))  # (gallery_id, pages, added_at)

        records.append((
            source,
            source_id,
            title,
            pages,
            rating,
            False,           # favorited
            "completed",     # download_status
            added_at,
            visibility,
            user_id,
            deleted_at,
            tags_array_val,
        ))

    await conn.copy_records_to_table(
        "galleries",
        records=records,
        columns=["source", "source_id", "title", "pages", "rating",
                 "favorited", "download_status",
                 "added_at", "visibility", "created_by_user_id", "deleted_at", "tags_array"],
    )
    return GALLERY_COUNT, gallery_rows


async def _phase_images(
    conn: asyncpg.Connection,
    gallery_rows: list[tuple],
    blob_shas: list[str],
) -> int:
    """Generate images for all galleries via COPY in 100K-row batches."""
    batch: list[tuple] = []
    total = 0
    batch_size = 100_000

    for gallery_id, pages, added_at in gallery_rows:
        for page_num in range(pages):
            sha = random.choice(blob_shas)
            img_added_at = added_at + timedelta(hours=random.uniform(0, 24 * pages))
            filename = f"page_{page_num:04d}.jpg"
            batch.append((gallery_id, page_num, sha, img_added_at, filename, []))

            if len(batch) >= batch_size:
                await conn.copy_records_to_table(
                    "images",
                    records=batch,
                    columns=["gallery_id", "page_num", "blob_sha256", "added_at", "filename", "tags_array"],
                )
                total += len(batch)
                batch.clear()

    if batch:
        await conn.copy_records_to_table(
            "images",
            records=batch,
            columns=["gallery_id", "page_num", "blob_sha256", "added_at", "filename", "tags_array"],
        )
        total += len(batch)

    return total


async def _phase_gallery_tags(
    conn: asyncpg.Connection,
    gallery_rows: list[tuple],
) -> int:
    """Assign 5-15 tags per gallery via COPY."""
    # Fetch actual tag IDs from DB
    tag_ids: list[int] = [row["id"] for row in await conn.fetch("SELECT id FROM tags ORDER BY id")]

    records = []
    for gallery_id, _pages, _added_at in gallery_rows:
        n_tags = random.randint(GALLERY_TAGS_PER_GALLERY_MIN, GALLERY_TAGS_PER_GALLERY_MAX)
        picked_ids = random.sample(tag_ids, k=min(n_tags, len(tag_ids)))
        for tag_id in picked_ids:
            confidence = round(random.uniform(0.5, 1.0), 4)
            records.append((gallery_id, tag_id, confidence, "metadata"))

    await conn.copy_records_to_table(
        "gallery_tags",
        records=records,
        columns=["gallery_id", "tag_id", "confidence", "source"],
    )
    return len(records)


async def _phase_image_tags(conn: asyncpg.Connection) -> int:
    """Assign 1-3 tags per image via COPY in batches."""
    tag_ids: list[int] = [row["id"] for row in await conn.fetch("SELECT id FROM tags ORDER BY id")]
    image_ids: list[int] = [row["id"] for row in await conn.fetch("SELECT id FROM images ORDER BY id")]

    batch: list[tuple] = []
    total = 0
    batch_size = 200_000

    for image_id in image_ids:
        n_tags = random.randint(1, 3)
        picked_ids = random.sample(tag_ids, k=min(n_tags, len(tag_ids)))
        for tag_id in picked_ids:
            confidence = round(random.uniform(0.3, 1.0), 4)
            batch.append((image_id, tag_id, confidence))

        if len(batch) >= batch_size:
            await conn.copy_records_to_table(
                "image_tags",
                records=batch,
                columns=["image_id", "tag_id", "confidence"],
            )
            total += len(batch)
            batch.clear()

    if batch:
        await conn.copy_records_to_table(
            "image_tags",
            records=batch,
            columns=["image_id", "tag_id", "confidence"],
        )
        total += len(batch)

    return total


async def _phase_user_data(conn: asyncpg.Connection, gallery_rows: list[tuple]) -> int:
    """Seed user_favorites and user_ratings for user_id=1."""
    gallery_ids = [g[0] for g in gallery_rows]

    fav_ids = random.sample(gallery_ids, k=min(FAVORITE_COUNT, len(gallery_ids)))
    fav_records = [(1, gid) for gid in fav_ids]
    await conn.copy_records_to_table(
        "user_favorites",
        records=fav_records,
        columns=["user_id", "gallery_id"],
    )

    # Ratings — pick a superset then sample, ensuring no overlap with favorites is fine
    # (ratings and favorites are independent)
    rated_ids = random.sample(gallery_ids, k=min(RATING_COUNT, len(gallery_ids)))
    rating_records = [(1, gid, random.randint(1, 5)) for gid in rated_ids]
    await conn.copy_records_to_table(
        "user_ratings",
        records=rating_records,
        columns=["user_id", "gallery_id", "rating"],
    )

    return len(fav_records) + len(rating_records)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def seed_all(dsn: str) -> dict[str, int]:
    """
    Seed the benchmark database at dsn with synthetic data.
    Returns a dict of {phase_name: row_count}.

    Uses a raw asyncpg connection directly (not SQLAlchemy) for maximum
    COPY throughput.
    """
    conn = await asyncpg.connect(dsn)
    counts: dict[str, int] = {}

    try:
        async def _timed(name: str, coro):
            t0 = time.perf_counter()
            result = await coro
            elapsed = time.perf_counter() - t0
            n = result[0] if isinstance(result, tuple) else result
            counts[name] = n
            print(f"  [seed] {name}: {n:,} rows in {elapsed:.1f}s")
            return result

        await _timed("users", _phase_users(conn))
        await _timed("tags", _phase_tags(conn))
        _, blob_shas = await _timed("blobs", _phase_blobs(conn))
        _, gallery_rows = await _timed("galleries", _phase_galleries(conn))

        await _timed("images", _phase_images(conn, gallery_rows, blob_shas))
        await _timed("gallery_tags", _phase_gallery_tags(conn, gallery_rows))
        await _timed("image_tags", _phase_image_tags(conn))
        await _timed("user_data", _phase_user_data(conn, gallery_rows))

    finally:
        await conn.close()

    return counts
