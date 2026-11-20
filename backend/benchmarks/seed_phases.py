"""Benchmark seed phases (one asyncpg COPY per table group)."""

import random
from datetime import timedelta

import asyncpg

from benchmarks.seed_data import (
    _MEDIA_EXTS,
    _WORDS,
    BLOB_COUNT,
    FAVORITE_COUNT,
    GALLERY_COUNT,
    GALLERY_TAGS_PER_GALLERY_MAX,
    GALLERY_TAGS_PER_GALLERY_MIN,
    IMAGES_PER_GALLERY_MAX,
    IMAGES_PER_GALLERY_MIN,
    RATING_COUNT,
    TAG_COUNT,
    _blob_sha,
    _phash_quarters,
    _rand_added_at,
    _rand_media_type,
    _rand_namespace,
    _rand_source,
    _rand_visibility,
)

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
        columns=[
            "sha256",
            "file_size",
            "media_type",
            "width",
            "height",
            "phash_int",
            "phash_q0",
            "phash_q1",
            "phash_q2",
            "phash_q3",
            "extension",
            "storage",
            "ref_count",
        ],
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

        records.append(
            (
                source,
                source_id,
                title,
                pages,
                rating,
                False,  # favorited
                "completed",  # download_status
                added_at,
                visibility,
                user_id,
                deleted_at,
                tags_array_val,
            )
        )

    await conn.copy_records_to_table(
        "galleries",
        records=records,
        columns=[
            "source",
            "source_id",
            "title",
            "pages",
            "rating",
            "favorited",
            "download_status",
            "added_at",
            "visibility",
            "created_by_user_id",
            "deleted_at",
            "tags_array",
        ],
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
