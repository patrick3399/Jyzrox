from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import select, text

from core.social_order import (
    parse_social_filename,
    reorder_social_gallery_images,
    social_image_sort_key,
)
from db.models import Image, ReadProgress


def test_parse_social_filename_numeric_post_and_media_index():
    assert parse_social_filename("123456789_2.jpg") == (123456789, 2)
    assert parse_social_filename("123456789.jpg") == (123456789, 1)
    assert parse_social_filename("image_2.jpg") is None


def test_social_sort_key_orders_post_desc_media_asc():
    images = [
        SimpleNamespace(id=1, filename="100_2.jpg", source_position=1, page_num=1, added_at=None),
        SimpleNamespace(id=2, filename="101_1.jpg", source_position=2, page_num=2, added_at=None),
        SimpleNamespace(id=3, filename="100_1.jpg", source_position=3, page_num=3, added_at=None),
    ]

    assert [img.filename for img in sorted(images, key=social_image_sort_key)] == [
        "101_1.jpg",
        "100_1.jpg",
        "100_2.jpg",
    ]


def test_social_sort_key_falls_back_to_added_at_desc():
    older = SimpleNamespace(
        id=1,
        filename="alpha.jpg",
        source_position=1,
        page_num=1,
        added_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    newer = SimpleNamespace(
        id=2,
        filename="beta.jpg",
        source_position=2,
        page_num=2,
        added_at=datetime(2025, 2, 1, tzinfo=UTC),
    )

    assert [img.filename for img in sorted([older, newer], key=social_image_sort_key)] == ["beta.jpg", "alpha.jpg"]


async def _insert_blob_image(db_session, gallery_id: int, page_num: int, filename: str, *, visibility: str = "active"):
    sha = f"sha_{gallery_id}_{page_num}_{filename}".replace(".", "_")
    await db_session.execute(
        text("INSERT OR IGNORE INTO blobs (sha256, file_size, extension) VALUES (:sha, 100, 'jpg')"),
        {"sha": sha},
    )
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, blob_sha256, visibility, source_position) "
            "VALUES (:gid, :page, :filename, :sha, :visibility, :source_position)"
        ),
        {
            "gid": gallery_id,
            "page": page_num,
            "filename": filename,
            "sha": sha,
            "visibility": visibility,
            "source_position": page_num,
        },
    )
    await db_session.commit()
    return sha


async def test_reorder_social_gallery_images_latest_first_and_clamps_progress(db_session):
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, pages, tags_array) VALUES ('twitter', 'u', 'U', 3, '[]')"
        )
    )
    gallery_id = (await db_session.execute(text("SELECT last_insert_rowid()"))).scalar_one()
    await _insert_blob_image(db_session, gallery_id, 1, "100_1.jpg")
    await _insert_blob_image(db_session, gallery_id, 2, "102_1.jpg")
    await _insert_blob_image(db_session, gallery_id, 3, "101_1.jpg")
    await db_session.execute(
        text("INSERT INTO read_progress (user_id, gallery_id, last_page) VALUES (1, :gid, 99)"),
        {"gid": gallery_id},
    )
    await db_session.commit()

    changed = await reorder_social_gallery_images(db_session, gallery_id, "twitter")
    await db_session.commit()

    rows = (
        await db_session.execute(
            select(Image.filename, Image.page_num, Image.source_position)
            .where(Image.gallery_id == gallery_id)
            .order_by(Image.page_num.asc())
        )
    ).all()
    progress = await db_session.get(ReadProgress, (1, gallery_id))

    assert changed > 0
    assert [(r.filename, r.page_num, r.source_position) for r in rows] == [
        ("102_1.jpg", 1, 1),
        ("101_1.jpg", 2, 2),
        ("100_1.jpg", 3, 3),
    ]
    assert progress.last_page == 3


async def test_reorder_social_gallery_images_hidden_gets_restore_position(db_session):
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, pages, tags_array) VALUES ('twitter', 'h', 'H', 2, '[]')"
        )
    )
    gallery_id = (await db_session.execute(text("SELECT last_insert_rowid()"))).scalar_one()
    await _insert_blob_image(db_session, gallery_id, 1, "100_1.jpg")
    await _insert_blob_image(db_session, gallery_id, 2, "102_1.jpg")
    await _insert_blob_image(db_session, gallery_id, -3, "101_1.jpg", visibility="user_hidden")

    await reorder_social_gallery_images(db_session, gallery_id, "twitter")
    await db_session.commit()

    hidden = (
        await db_session.execute(select(Image).where(Image.gallery_id == gallery_id, Image.visibility == "user_hidden"))
    ).scalar_one()
    active_rows = (
        await db_session.execute(
            select(Image.filename, Image.page_num, Image.source_position)
            .where(Image.gallery_id == gallery_id, Image.visibility == "active")
            .order_by(Image.page_num.asc())
        )
    ).all()

    assert [(r.filename, r.page_num, r.source_position) for r in active_rows] == [
        ("102_1.jpg", 1, 1),
        ("100_1.jpg", 2, 2),
    ]
    assert hidden.page_num < 0
    assert hidden.source_position == 2


async def test_reorder_social_gallery_images_keeps_local_only_posts_in_sequence(db_session):
    """Force re-scan adds current remote posts without dropping local-only older posts."""
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, pages, tags_array) VALUES ('twitter', 'r', 'R', 3, '[]')"
        )
    )
    gallery_id = (await db_session.execute(text("SELECT last_insert_rowid()"))).scalar_one()

    # Existing local row whose remote post no longer appears in the force re-scan.
    await _insert_blob_image(db_session, gallery_id, 1, "101_1.jpg")
    # Items imported during the archive-bypassing force re-scan.
    await _insert_blob_image(db_session, gallery_id, 2, "103_1.jpg")
    await _insert_blob_image(db_session, gallery_id, 3, "100_1.jpg")

    await reorder_social_gallery_images(db_session, gallery_id, "twitter")
    await db_session.commit()

    rows = (
        await db_session.execute(
            select(Image.filename, Image.page_num, Image.source_position)
            .where(Image.gallery_id == gallery_id, Image.visibility == "active")
            .order_by(Image.page_num.asc())
        )
    ).all()

    assert [(r.filename, r.page_num, r.source_position) for r in rows] == [
        ("103_1.jpg", 1, 1),
        ("101_1.jpg", 2, 2),
        ("100_1.jpg", 3, 3),
    ]


async def test_reorder_social_gallery_images_ignores_non_social(db_session):
    await db_session.execute(
        text("INSERT INTO galleries (source, source_id, title, pages, tags_array) VALUES ('pixiv', 'p', 'P', 2, '[]')")
    )
    gallery_id = (await db_session.execute(text("SELECT last_insert_rowid()"))).scalar_one()
    await _insert_blob_image(db_session, gallery_id, 1, "100_1.jpg")
    await _insert_blob_image(db_session, gallery_id, 2, "102_1.jpg")

    changed = await reorder_social_gallery_images(db_session, gallery_id, "pixiv")

    rows = (
        (
            await db_session.execute(
                select(Image.filename).where(Image.gallery_id == gallery_id).order_by(Image.page_num.asc())
            )
        )
        .scalars()
        .all()
    )
    assert changed == 0
    assert rows == ["100_1.jpg", "102_1.jpg"]
