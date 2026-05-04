from sqlalchemy import text

from core.gallery_helpers import build_cover_sha_map


async def _gallery(db_session, source: str, source_id: str) -> int:
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, pages, tags_array) "
            "VALUES (:source, :source_id, :title, 0, '[]')"
        ),
        {"source": source, "source_id": source_id, "title": source_id},
    )
    await db_session.commit()
    return (await db_session.execute(text("SELECT last_insert_rowid()"))).scalar_one()


async def _image(db_session, gallery_id: int, page_num: int, sha: str) -> None:
    await db_session.execute(
        text("INSERT OR IGNORE INTO blobs (sha256, file_size, extension) VALUES (:sha, 100, 'jpg')"),
        {"sha": sha},
    )
    await db_session.execute(
        text("INSERT INTO images (gallery_id, page_num, filename, blob_sha256) VALUES (:gid, :page, :fn, :sha)"),
        {"gid": gallery_id, "page": page_num, "fn": f"{page_num}.jpg", "sha": sha},
    )
    await db_session.commit()


async def test_cover_sha_map_skips_excluded_first_page(db_session):
    gallery_id = await _gallery(db_session, "twitter", "cover-first")
    await _image(db_session, gallery_id, 1, "sha_first")
    await _image(db_session, gallery_id, 2, "sha_second")
    await db_session.execute(
        text("INSERT INTO excluded_blobs (gallery_id, blob_sha256) VALUES (:gid, 'sha_first')"),
        {"gid": gallery_id},
    )
    await db_session.commit()

    cover_map = await build_cover_sha_map(db_session, [gallery_id], {gallery_id: "twitter"})

    assert cover_map[gallery_id] == "sha_second"


async def test_cover_sha_map_returns_none_when_all_active_images_excluded(db_session):
    gallery_id = await _gallery(db_session, "twitter", "cover-none")
    await _image(db_session, gallery_id, 1, "sha_only")
    await db_session.execute(
        text("INSERT INTO excluded_blobs (gallery_id, blob_sha256) VALUES (:gid, 'sha_only')"),
        {"gid": gallery_id},
    )
    await db_session.commit()

    cover_map = await build_cover_sha_map(db_session, [gallery_id], {gallery_id: "twitter"})

    assert gallery_id not in cover_map


async def test_cover_sha_map_last_page_skips_excluded_tail(db_session, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "core.gallery_helpers.get_display_config",
        lambda _source: SimpleNamespace(cover_page="last"),
    )
    gallery_id = await _gallery(db_session, "custom-last", "cover-last")
    await _image(db_session, gallery_id, 1, "sha_first")
    await _image(db_session, gallery_id, 2, "sha_last")
    await db_session.execute(
        text("INSERT INTO excluded_blobs (gallery_id, blob_sha256) VALUES (:gid, 'sha_last')"),
        {"gid": gallery_id},
    )
    await db_session.commit()

    with_last_cover = {gallery_id: "custom-last"}
    cover_map = await build_cover_sha_map(db_session, [gallery_id], with_last_cover)

    assert cover_map[gallery_id] == "sha_first"
