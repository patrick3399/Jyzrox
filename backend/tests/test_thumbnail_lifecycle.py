"""Regression tests for shared thumbnail lifecycle safety."""


from sqlalchemy import text

from services.thumbnail_lifecycle import cleanup_unreferenced_thumbnails


async def _insert_blob(db_session, sha256: str, ref_count: int) -> None:
    await db_session.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, extension, storage, ref_count) "
            "VALUES (:sha, 1, '.jpg', 'cas', :ref_count)"
        ),
        {"sha": sha256, "ref_count": ref_count},
    )
    await db_session.commit()


async def test_referenced_blob_repairs_count_and_keeps_thumbnail(db_session, tmp_path):
    sha256 = "a" * 64
    await _insert_blob(db_session, sha256, ref_count=0)
    gallery_id = (
        await db_session.execute(
            text(
                "INSERT INTO galleries (source, source_id, title, pages) VALUES ('local', 'shared', 'Shared', 1) RETURNING id"
            )
        )
    ).scalar_one()
    await db_session.execute(
        text("INSERT INTO images (gallery_id, page_num, filename, blob_sha256) VALUES (:gid, 1, '1.jpg', :sha)"),
        {"gid": gallery_id, "sha": sha256},
    )
    await db_session.commit()

    directory = tmp_path / sha256
    directory.mkdir()
    (directory / "thumb_160.webp").write_bytes(b"thumb")

    removed = await cleanup_unreferenced_thumbnails(
        db_session,
        [sha256],
        directory_resolver=lambda _sha: directory,
    )

    assert removed == set()
    assert directory.exists()
    assert (
        await db_session.execute(text("SELECT ref_count FROM blobs WHERE sha256 = :sha"), {"sha": sha256})
    ).scalar_one() == 1


async def test_unreferenced_blob_repairs_count_then_removes_thumbnail(db_session, tmp_path):
    sha256 = "b" * 64
    await _insert_blob(db_session, sha256, ref_count=4)
    directory = tmp_path / sha256
    directory.mkdir()
    (directory / "thumb_160.webp").write_bytes(b"thumb")

    removed = await cleanup_unreferenced_thumbnails(
        db_session,
        [sha256],
        directory_resolver=lambda _sha: directory,
    )

    assert removed == {sha256}
    assert not directory.exists()
    assert (
        await db_session.execute(text("SELECT ref_count FROM blobs WHERE sha256 = :sha"), {"sha": sha256})
    ).scalar_one() == 0
