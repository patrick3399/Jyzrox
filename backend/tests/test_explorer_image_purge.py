"""Explorer image purge: permanent deletion of user-hidden images.

Covers ``POST /api/explorer/galleries/{id}/images/purge`` and
``services.image_purge`` (dry run, shared blobs, ExcludedBlob twin rule,
skip categories, access / state guards, filesystem cleanup).
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text

from db.models import Blob, ExcludedBlob, Image, WorkbenchOperation
from services.cas import cas_path, library_dir

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_T = "e" * 64
SHA_X = "f" * 64


@pytest.fixture(autouse=True)
def fs(tmp_path, monkeypatch):
    """Point CAS / library / thumbs at a per-test tmp dir."""
    import services.cas as cas_module

    settings = cas_module.settings
    monkeypatch.setattr(settings, "data_cas_path", str(tmp_path / "cas"))
    monkeypatch.setattr(settings, "data_library_path", str(tmp_path / "library"))
    monkeypatch.setattr(settings, "data_thumbs_path", str(tmp_path / "thumbs"))
    return tmp_path


@pytest.fixture(autouse=True)
def _no_side_effects():
    with (
        patch("routers.explorer.invalidate_sources_cache", new_callable=AsyncMock) as invalidate,
        patch("routers.explorer.emit_safe", new_callable=AsyncMock) as emit,
    ):
        yield {"invalidate": invalidate, "emit": emit}


async def _seed_users(db) -> None:
    await db.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) VALUES "
            "(1, 'admin', 'x', 'admin'), (2, 'member2', 'x', 'member'), (3, 'viewer3', 'x', 'viewer')"
        )
    )
    await db.commit()


async def _gallery(db, gid=101, *, owner=1, visibility="public", source="local", source_id=None, deleted=False):
    await _seed_users(db)
    await db.execute(
        text(
            "INSERT INTO galleries (id, source, source_id, title, visibility, created_by_user_id, deleted_at) "
            "VALUES (:id, :source, :sid, :title, :vis, :owner, :deleted)"
        ),
        {
            "id": gid,
            "source": source,
            "sid": source_id or f"g{gid}",
            "title": f"G{gid}",
            "vis": visibility,
            "owner": owner,
            "deleted": "2026-01-01 00:00:00" if deleted else None,
        },
    )
    await db.commit()


async def _blob(db, sha, size, *, refs=1, storage="cas", ext=".jpg", write_file=True, media="image"):
    await db.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, media_type, extension, storage, ref_count) "
            "VALUES (:sha, :size, :media, :ext, :storage, :refs)"
        ),
        {"sha": sha, "size": size, "media": media, "ext": ext, "storage": storage, "refs": refs},
    )
    await db.commit()
    path = cas_path(sha, ext)
    if write_file and storage == "cas":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    return path


async def _image(
    db,
    image_id,
    gid,
    page,
    sha,
    *,
    hidden=False,
    filename=None,
    external_path=None,
    gallery_source="local",
    link=True,
    ext=".jpg",
):
    filename = filename or f"img{image_id}{ext}"
    await db.execute(
        text(
            "INSERT INTO images (id, gallery_id, page_num, filename, blob_sha256, external_path, visibility, "
            "hidden_at, source_position) VALUES (:id, :gid, :page, :fn, :sha, :ext_path, :vis, :hidden_at, :pos)"
        ),
        {
            "id": image_id,
            "gid": gid,
            "page": -image_id if hidden else page,
            "fn": filename,
            "sha": sha,
            "ext_path": external_path,
            "vis": "user_hidden" if hidden else "active",
            "hidden_at": "2026-01-01 00:00:00" if hidden else None,
            "pos": page,
        },
    )
    await db.commit()
    if link and sha and external_path is None:
        source_id = (await db.execute(text("SELECT source_id FROM galleries WHERE id=:g"), {"g": gid})).scalar_one()
        src = (await db.execute(text("SELECT source FROM galleries WHERE id=:g"), {"g": gid})).scalar_one()
        directory = library_dir(src, source_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).symlink_to(cas_path(sha, ext))
    return filename


async def _count(db, model) -> int:
    return len((await db.execute(select(model))).scalars().all())


async def _image_ids(db, gid=101) -> set[int]:
    return set((await db.execute(select(Image.id).where(Image.gallery_id == gid))).scalars().all())


def _purge(client, gid=101, **body):
    return client.post(f"/api/explorer/galleries/{gid}/images/purge", json=body)


# ---------------------------------------------------------------------------
# dry run
# ---------------------------------------------------------------------------


async def test_purge_dry_run_reports_counts_and_mutates_nothing(client, db_session, _no_side_effects):
    await _gallery(db_session, 101)
    await _gallery(db_session, 102)
    path_a = await _blob(db_session, SHA_A, 100, refs=1)
    path_b = await _blob(db_session, SHA_B, 200, refs=2)
    await _blob(db_session, SHA_C, 300, refs=1)
    await _blob(db_session, SHA_X, 400, refs=1, storage="external", write_file=False)
    await db_session.execute(
        text("INSERT INTO blob_locations (blob_sha256, external_path) VALUES (:s, '/mnt/ext/x.jpg')"), {"s": SHA_X}
    )
    await _image(db_session, 1, 101, 1, SHA_A, hidden=True)  # unshared -> reclaimable
    await _image(db_session, 2, 101, 2, SHA_B, hidden=True)  # shared with gallery 102
    await _image(db_session, 22, 102, 1, SHA_B)
    await _image(db_session, 3, 101, 3, SHA_C)  # active
    await _image(db_session, 4, 101, 4, SHA_X, hidden=True, external_path="/mnt/ext/x.jpg")  # external
    await _image(db_session, 5, 101, 5, None, hidden=True, external_path="/mnt/ext/pending.jpg")  # pending

    response = await _purge(client, image_ids=[1, 2, 3, 4, 5, 9999], dry_run=True)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is True
    assert body["purgeable"] == 2
    assert body["purged"] == 0
    assert body["reclaim_bytes"] == 100
    assert body["shared_kept"] == 1
    assert body["skipped_not_hidden"] == 1
    assert body["skipped_external"] == 1
    assert body["skipped_pending"] == 1
    assert body["skipped_missing"] == 1
    assert body["operation_id"] is None
    assert await _image_ids(db_session) == {1, 2, 3, 4, 5}
    assert await _count(db_session, ExcludedBlob) == 0
    assert await _count(db_session, WorkbenchOperation) == 0
    assert {b.sha256: b.ref_count for b in (await db_session.execute(select(Blob))).scalars()} == {
        SHA_A: 1,
        SHA_B: 2,
        SHA_C: 1,
        SHA_X: 1,
    }
    assert path_a.exists() and path_b.exists()
    assert (library_dir("local", "g101") / "img1.jpg").is_symlink()
    _no_side_effects["emit"].assert_not_awaited()
    _no_side_effects["invalidate"].assert_not_awaited()


# ---------------------------------------------------------------------------
# real purge
# ---------------------------------------------------------------------------


async def test_purge_unshared_hidden_cas_image_removes_row_blob_file_and_link(client, db_session, _no_side_effects):
    await _gallery(db_session, 101)
    path = await _blob(db_session, SHA_A, 100, refs=1)
    await _image(db_session, 1, 101, 1, SHA_A, hidden=True)
    link = library_dir("local", "g101") / "img1.jpg"
    assert link.is_symlink() and path.exists()

    response = await _purge(client, image_ids=[1])

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["purged"], body["reclaim_bytes"], body["shared_kept"], body["blobs_deleted"]) == (1, 100, 0, 1)
    assert body["operation_id"]
    await db_session.rollback()
    assert await _image_ids(db_session) == set()
    excluded = (await db_session.execute(select(ExcludedBlob))).scalars().all()
    assert [(e.gallery_id, e.blob_sha256) for e in excluded] == [(101, SHA_A)]
    assert await db_session.get(Blob, SHA_A) is None
    assert not path.exists()
    assert not link.is_symlink()
    operation = (await db_session.execute(select(WorkbenchOperation))).scalar_one()
    assert operation.kind == "purge_images" and operation.status == "completed"
    _no_side_effects["invalidate"].assert_awaited_once()
    assert _no_side_effects["emit"].await_args.kwargs["action"] == "images_purged"


async def test_purge_blob_shared_with_another_gallery_keeps_blob_and_cas_file(client, db_session):
    await _gallery(db_session, 101)
    await _gallery(db_session, 102)
    path = await _blob(db_session, SHA_B, 200, refs=2)
    await _image(db_session, 1, 101, 1, SHA_B, hidden=True)
    await _image(db_session, 2, 102, 1, SHA_B)

    response = await _purge(client, image_ids=[1])

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["purged"], body["shared_kept"], body["reclaim_bytes"], body["blobs_deleted"]) == (1, 1, 0, 0)
    await db_session.rollback()
    blob = await db_session.get(Blob, SHA_B)
    assert blob is not None and blob.ref_count == 1
    assert path.exists()
    assert await _image_ids(db_session, 101) == set()
    assert await _image_ids(db_session, 102) == {2}
    # The exclusion is per gallery: the other gallery's page is untouched.
    assert [(e.gallery_id, e.blob_sha256) for e in (await db_session.execute(select(ExcludedBlob))).scalars()] == [
        (101, SHA_B)
    ]


async def test_purge_hidden_duplicate_with_active_same_sha_twin_in_gallery_does_not_exclude_blob(client, db_session):
    """An ExcludedBlob row hides every Image of the gallery with that sha, so
    purging a hidden duplicate must not exclude a sha whose active twin remains."""
    await _gallery(db_session, 101)
    path = await _blob(db_session, SHA_T, 50, refs=2)
    await _image(db_session, 1, 101, 1, SHA_T, filename="twin_active.jpg")
    await _image(db_session, 2, 101, 2, SHA_T, hidden=True, filename="twin_hidden.jpg")

    response = await _purge(client, image_ids=[2])

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["purged"], body["shared_kept"], body["reclaim_bytes"], body["blobs_deleted"]) == (1, 1, 0, 0)
    await db_session.rollback()
    assert await _count(db_session, ExcludedBlob) == 0
    assert await _image_ids(db_session) == {1}
    assert (await db_session.get(Blob, SHA_T)).ref_count == 1
    assert path.exists()
    listing = await client.get("/api/explorer/galleries/101/images")
    assert [item["image_id"] for item in listing.json()["items"]] == [1]


async def test_purge_skips_active_external_and_pending_images_and_leaves_them_untouched(client, db_session):
    await _gallery(db_session, 101)
    active_path = await _blob(db_session, SHA_C, 300, refs=1)
    await _blob(db_session, SHA_X, 400, refs=1, storage="external", write_file=False)
    await db_session.execute(
        text("INSERT INTO blob_locations (blob_sha256, external_path) VALUES (:s, '/mnt/ext/x.jpg')"), {"s": SHA_X}
    )
    await _image(db_session, 3, 101, 3, SHA_C)
    await _image(db_session, 4, 101, 4, SHA_X, hidden=True, external_path="/mnt/ext/x.jpg")
    await _image(db_session, 5, 101, 5, None, hidden=True, external_path="/mnt/ext/pending.jpg")

    response = await _purge(client, image_ids=[3, 4, 5])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["purged"] == 0
    assert body["skipped_not_hidden"] == 1
    assert body["skipped_external"] == 1
    assert body["skipped_pending"] == 1
    assert body["operation_id"] is None
    await db_session.rollback()
    assert await _image_ids(db_session) == {3, 4, 5}
    assert await _count(db_session, ExcludedBlob) == 0
    assert active_path.exists()
    assert await db_session.get(Blob, SHA_X) is not None


async def test_purge_external_storage_hidden_image_never_touches_user_file(client, db_session, fs):
    await _gallery(db_session, 101)
    user_file = fs / "user-folder" / "mine.jpg"
    user_file.parent.mkdir()
    user_file.write_bytes(b"user-bytes")
    await _blob(db_session, SHA_X, 10, refs=1, storage="external", write_file=False)
    await db_session.execute(
        text("INSERT INTO blob_locations (blob_sha256, external_path) VALUES (:s, :p)"),
        {"s": SHA_X, "p": str(user_file)},
    )
    await _image(db_session, 4, 101, 4, SHA_X, hidden=True, external_path=str(user_file))

    response = await _purge(client, all_hidden=True)

    assert response.status_code == 200, response.text
    assert response.json()["purged"] == 0
    assert response.json()["skipped_external"] == 1
    assert user_file.read_bytes() == b"user-bytes"
    await db_session.rollback()
    assert await _image_ids(db_session) == {4}


async def test_purge_all_hidden_removes_every_hidden_image_and_keeps_active(client, db_session):
    await _gallery(db_session, 101)
    await _blob(db_session, SHA_A, 100, refs=1)
    await _blob(db_session, SHA_B, 200, refs=1)
    active_path = await _blob(db_session, SHA_C, 300, refs=1)
    await _image(db_session, 1, 101, 1, SHA_A, hidden=True)
    await _image(db_session, 2, 101, 2, SHA_B, hidden=True)
    await _image(db_session, 3, 101, 3, SHA_C)

    response = await _purge(client, all_hidden=True)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["purged"], body["reclaim_bytes"], body["blobs_deleted"]) == (2, 300, 2)
    await db_session.rollback()
    assert await _image_ids(db_session) == {3}
    assert {e.blob_sha256 for e in (await db_session.execute(select(ExcludedBlob))).scalars()} == {SHA_A, SHA_B}
    assert active_path.exists()
    assert await db_session.get(Blob, SHA_C) is not None


async def test_purge_symlink_not_pointing_at_blob_cas_path_is_not_unlinked(client, db_session, fs):
    await _gallery(db_session, 101)
    path = await _blob(db_session, SHA_A, 100, refs=1)
    await _image(db_session, 1, 101, 1, SHA_A, hidden=True, link=False)
    other = fs / "someone-elses.jpg"
    other.write_bytes(b"other")
    directory = library_dir("local", "g101")
    directory.mkdir(parents=True, exist_ok=True)
    link = directory / "img1.jpg"
    link.symlink_to(other)

    response = await _purge(client, image_ids=[1])

    assert response.status_code == 200, response.text
    assert response.json()["purged"] == 1
    assert link.is_symlink()
    assert other.read_bytes() == b"other"
    assert not path.exists()  # the CAS bytes themselves are still reclaimed


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------


async def test_purge_trashed_gallery_returns_409_and_keeps_images(client, db_session):
    await _gallery(db_session, 101, deleted=True)
    await _blob(db_session, SHA_A, 100)
    await _image(db_session, 1, 101, 1, SHA_A, hidden=True)

    response = await _purge(client, image_ids=[1])

    assert response.status_code == 409, response.text
    assert await _image_ids(db_session) == {1}


@pytest.mark.parametrize("status", ["queued", "running", "paused"])
async def test_purge_with_active_download_job_returns_409(client, db_session, status):
    await _gallery(db_session, 101)
    await _blob(db_session, SHA_A, 100)
    await _image(db_session, 1, 101, 1, SHA_A, hidden=True)
    await db_session.execute(
        text("INSERT INTO download_jobs (id, url, status, gallery_id) VALUES (:id, 'https://x/y', :st, 101)"),
        {"id": str(uuid.uuid4()), "st": status},
    )
    await db_session.commit()

    response = await _purge(client, image_ids=[1])

    assert response.status_code == 409, response.text
    assert await _image_ids(db_session) == {1}
    assert await _count(db_session, ExcludedBlob) == 0


async def test_purge_with_finished_download_job_is_allowed(client, db_session):
    await _gallery(db_session, 101)
    await _blob(db_session, SHA_A, 100)
    await _image(db_session, 1, 101, 1, SHA_A, hidden=True)
    await db_session.execute(
        text("INSERT INTO download_jobs (id, url, status, gallery_id) VALUES (:id, 'https://x/y', 'done', 101)"),
        {"id": str(uuid.uuid4())},
    )
    await db_session.commit()

    response = await _purge(client, image_ids=[1])

    assert response.status_code == 200, response.text
    assert response.json()["purged"] == 1


async def test_purge_read_only_collaborator_cannot_purge_and_gets_403(make_client, db_session):
    await _gallery(db_session, 101, owner=1, visibility="private")
    path = await _blob(db_session, SHA_A, 100)
    await _image(db_session, 1, 101, 1, SHA_A, hidden=True)
    await db_session.execute(text("INSERT INTO gallery_permissions (gallery_id, user_id, can_edit) VALUES (101, 2, 0)"))
    await db_session.commit()

    async with make_client(user_id=2, role="member") as ac:
        listing = await ac.get("/api/explorer/galleries/101/images", params={"visibility": "hidden"})
        dry = await _purge(ac, image_ids=[1], dry_run=True)
        real = await _purge(ac, image_ids=[1])

    assert listing.status_code == 200  # read access is allowed...
    assert listing.json()["can_edit"] is False
    assert dry.status_code == 403, dry.text  # ...mutation (even preview) is not
    assert real.status_code == 403, real.text
    assert await _image_ids(db_session) == {1}
    assert await _count(db_session, ExcludedBlob) == 0
    assert path.exists()


async def test_purge_collaborator_with_can_edit_is_allowed(make_client, db_session):
    await _gallery(db_session, 101, owner=1, visibility="private")
    await _blob(db_session, SHA_A, 100)
    await _image(db_session, 1, 101, 1, SHA_A, hidden=True)
    await db_session.execute(text("INSERT INTO gallery_permissions (gallery_id, user_id, can_edit) VALUES (101, 2, 1)"))
    await db_session.commit()

    async with make_client(user_id=2, role="member") as ac:
        response = await _purge(ac, image_ids=[1])

    assert response.status_code == 200, response.text
    assert response.json()["purged"] == 1


async def test_purge_other_users_private_gallery_without_permission_returns_404(make_client, db_session):
    await _gallery(db_session, 101, owner=1, visibility="private")
    await _blob(db_session, SHA_A, 100)
    await _image(db_session, 1, 101, 1, SHA_A, hidden=True)

    async with make_client(user_id=2, role="member") as ac:
        response = await _purge(ac, image_ids=[1])

    assert response.status_code == 404, response.text
    assert await _image_ids(db_session) == {1}


async def test_purge_viewer_role_returns_403(make_client, db_session):
    await _gallery(db_session, 101, owner=None)
    await _blob(db_session, SHA_A, 100)
    await _image(db_session, 1, 101, 1, SHA_A, hidden=True)

    async with make_client(user_id=3, role="viewer") as ac:
        response = await _purge(ac, image_ids=[1])

    assert response.status_code == 403, response.text
    assert await _image_ids(db_session) == {1}


async def test_purge_unauthenticated_returns_401(unauthed_client):
    response = await unauthed_client.post("/api/explorer/galleries/101/images/purge", json={"all_hidden": True})
    assert response.status_code == 401


async def test_purge_missing_gallery_returns_404(client, db_session):
    await _seed_users(db_session)
    response = await _purge(client, 9999, all_hidden=True)
    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"dry_run": True},
        {"image_ids": []},
        {"image_ids": [1], "all_hidden": True},
        {"image_ids": [], "all_hidden": False},
    ],
)
async def test_purge_neither_or_both_of_image_ids_and_all_hidden_returns_422(client, db_session, body):
    await _gallery(db_session, 101)
    await _blob(db_session, SHA_A, 100)
    await _image(db_session, 1, 101, 1, SHA_A, hidden=True)

    response = await _purge(client, **body)

    assert response.status_code == 422, response.text
    assert await _image_ids(db_session) == {1}


async def test_purge_more_than_1000_image_ids_returns_422(client, db_session):
    await _gallery(db_session, 101)
    response = await _purge(client, image_ids=list(range(1, 1002)))
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# legacy merge removal
# ---------------------------------------------------------------------------


async def test_legacy_gallery_management_merge_route_is_gone(client, db_session):
    await _gallery(db_session, 101)
    await _gallery(db_session, 102)

    response = await client.post("/api/gallery-management/galleries/101/merge", json={"source_gallery_id": 102})

    assert response.status_code in (404, 405), response.text
    assert (await db_session.execute(text("SELECT deleted_at FROM galleries WHERE id=102"))).scalar_one() is None
