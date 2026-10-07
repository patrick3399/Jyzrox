"""API contract for pending link pages (ADR 0015, Task 6).

A pending page is an ``images`` row with ``blob_sha256 IS NULL`` and a non-null
``external_path``: the file is registered from stat data but not hashed yet.
"""

import json
from datetime import UTC, datetime
from unittest.mock import patch

from sqlalchemy import text

PENDING_SIZE = 1234
THUMB_DIR_PATCH = "routers.library.thumb_dir"


async def _gallery(db, sid: str = "pend", *, pages: int = 2, import_mode: str = "link", source: str = "local") -> int:
    await db.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, import_mode, download_status, pages, added_at) "
            "VALUES (:src, :sid, 'Pending Gallery', :mode, 'importing', :pages, :now)"
        ),
        {"src": source, "sid": sid, "mode": import_mode, "pages": pages, "now": datetime.now(UTC)},
    )
    await db.commit()
    return (await db.execute(text("SELECT id FROM galleries WHERE source_id=:sid"), {"sid": sid})).scalar_one()


async def _blob(db, sha: str, *, size: int = 500, media_type: str = "image", phash: str | None = None) -> None:
    await db.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, media_type, width, height, extension, storage, ref_count, phash) "
            "VALUES (:sha, :size, :mt, 10, 20, '.jpg', 'cas', 1, :phash)"
        ),
        {"sha": sha, "size": size, "mt": media_type, "phash": phash},
    )
    await db.commit()


async def _pending(
    db, gallery_id: int, page: int, filename: str, *, added_at: datetime | None = None, visibility: str = "active"
) -> int:
    await db.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, external_path, source_size, source_mtime_ns, "
            "added_at, visibility) VALUES (:gid, :pn, :fn, :ep, :sz, 1, :added, :vis)"
        ),
        {
            "gid": gallery_id,
            "pn": page,
            "fn": filename,
            "ep": f"/mnt/lib/g{gallery_id}/{filename}",
            "sz": PENDING_SIZE,
            "added": added_at or datetime.now(UTC),
            "vis": visibility,
        },
    )
    await db.commit()
    return (
        await db.execute(
            text("SELECT id FROM images WHERE gallery_id=:g AND filename=:f"), {"g": gallery_id, "f": filename}
        )
    ).scalar_one()


async def _hashed(
    db, gallery_id: int, page: int, filename: str, sha: str, *, added_at: datetime | None = None, size: int = 500
) -> int:
    await _blob(db, sha, size=size)
    await db.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, blob_sha256, added_at, visibility) "
            "VALUES (:gid, :pn, :fn, :sha, :added, 'active')"
        ),
        {"gid": gallery_id, "pn": page, "fn": filename, "sha": sha, "added": added_at or datetime.now(UTC)},
    )
    await db.commit()
    return (
        await db.execute(
            text("SELECT id FROM images WHERE gallery_id=:g AND filename=:f"), {"g": gallery_id, "f": filename}
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# 6.1 / 6.2 serialization
# ---------------------------------------------------------------------------


async def test_pending_page_serializes_with_file_path_and_no_thumbnail(client, db_session):
    gid = await _gallery(db_session, "ser")
    await _pending(db_session, gid, 1, "clip.mp4")
    await _pending(db_session, gid, 2, "a.png")

    response = await client.get("/api/library/galleries/local/ser/images")

    assert response.status_code == 200
    images = {i["filename"]: i for i in response.json()["images"]}
    clip = images["clip.mp4"]
    print(json.dumps(clip, indent=2, sort_keys=True))
    assert clip["pending"] is True
    assert clip["file_path"] == f"/media/libraries/lib/g{gid}/clip.mp4"
    assert clip["thumb_path"] is None
    assert clip["thumb_srcset"] is None
    assert clip["media_type"] == "video"
    assert clip["file_size"] == PENDING_SIZE
    assert clip["file_hash"] is None
    assert images["a.png"]["media_type"] == "image"


async def test_hashed_page_is_not_pending(client, db_session):
    gid = await _gallery(db_session, "ser2")
    await _hashed(db_session, gid, 1, "x.jpg", "a" * 64)

    response = await client.get("/api/library/galleries/local/ser2/images")

    image = response.json()["images"][0]
    assert image["pending"] is False
    assert image["file_hash"] == "a" * 64


async def test_pending_page_in_browse_and_artist_listing_has_file_path(client, db_session):
    gid = await _gallery(db_session, "ser3")
    await db_session.execute(text("UPDATE galleries SET artist_id='artist:x' WHERE id=:g"), {"g": gid})
    await db_session.commit()
    await _pending(db_session, gid, 1, "clip.mp4")

    artist = await client.get("/api/library/artists/artist:x/images")
    assert artist.status_code == 200, artist.text
    row = artist.json()["images"][0]
    assert row["file_path"] and row["file_path"].endswith("clip.mp4")
    assert row["media_type"] == "video"
    assert row["file_size"] == PENDING_SIZE


# ---------------------------------------------------------------------------
# 6.3 cover
# ---------------------------------------------------------------------------


async def test_cover_falls_back_to_first_hashed_page_when_first_page_is_pending(db_session):
    from core.gallery_helpers import select_cover_image, select_cover_images

    gid = await _gallery(db_session, "cov")
    await _pending(db_session, gid, 1, "p1.jpg")
    hashed_id = await _hashed(db_session, gid, 2, "p2.jpg", "b" * 64)

    single = await select_cover_image(db_session, gid, "local")
    many = await select_cover_images(db_session, [gid], {gid: "local"})

    assert single is not None and single.id == hashed_id
    assert many[gid].id == hashed_id


async def test_cover_is_none_when_every_page_is_pending(db_session):
    from core.gallery_helpers import select_cover_image

    gid = await _gallery(db_session, "cov2")
    await _pending(db_session, gid, 1, "p1.jpg")

    assert await select_cover_image(db_session, gid, "local") is None


# ---------------------------------------------------------------------------
# 6.4 browse filters
# ---------------------------------------------------------------------------


async def test_image_timeline_excludes_pending_pages(client, db_session):
    gid = await _gallery(db_session, "tl")
    old = datetime(2020, 1, 1, tzinfo=UTC)
    await _hashed(db_session, gid, 1, "h.jpg", "c" * 64, added_at=old)
    await _pending(db_session, gid, 2, "p.jpg", added_at=datetime(2026, 1, 1, tzinfo=UTC))

    listing = await client.get("/api/library/images", params={"gallery_id": gid})
    percentiles = await client.get("/api/library/images/timeline_percentiles", params={"gallery_id": gid})
    time_range = await client.get("/api/library/images/time_range", params={"gallery_id": gid})

    assert [i["page_num"] for i in listing.json()["images"]] == [1]
    assert percentiles.json()["total_buckets"] == 1
    assert time_range.json()["max_at"].startswith("2020-01-01")


async def test_gallery_detail_still_lists_pending_pages(client, db_session):
    gid = await _gallery(db_session, "tl2")
    await _hashed(db_session, gid, 1, "h.jpg", "d" * 64)
    await _pending(db_session, gid, 2, "p.jpg")

    response = await client.get("/api/library/galleries/local/tl2/images", params={"page": 1, "limit": 10})

    assert response.json()["total"] == 2
    assert [i["pending"] for i in response.json()["images"]] == [False, True]


# ---------------------------------------------------------------------------
# 6.5 sizes
# ---------------------------------------------------------------------------


async def test_source_stats_counts_pending_page_size(client, db_session):
    gid = await _gallery(db_session, "sz")
    await _pending(db_session, gid, 1, "p.jpg")
    await _hashed(db_session, gid, 2, "h.jpg", "e" * 64, size=500)

    stats = (await client.get("/api/library/files/source_stats")).json()["stats"]
    row = next(s for s in stats if s["source"] == "local" and s["import_mode"] == "link")
    files = (await client.get("/api/library/files")).json()["directories"]
    directory = next(d for d in files if d["gallery_id"] == gid)

    assert row["file_count"] == 2
    assert int(row["disk_size"]) == PENDING_SIZE + 500
    assert int(directory["disk_size"]) == PENDING_SIZE + 500


# ---------------------------------------------------------------------------
# 6.6 similar
# ---------------------------------------------------------------------------


async def test_find_similar_images_on_pending_page_returns_409(client, db_session):
    gid = await _gallery(db_session, "sim")
    image_id = await _pending(db_session, gid, 1, "p.jpg")

    response = await client.get(f"/api/library/images/{image_id}/similar")

    assert response.status_code == 409
    assert response.json()["detail"] == "Image is still being processed"


# ---------------------------------------------------------------------------
# 6.8 restore excluded blob
# ---------------------------------------------------------------------------


async def test_restoring_excluded_blob_removes_the_excluded_page_row(client, db_session):
    gid = await _gallery(db_session, "rex")
    sha = "f" * 64
    await _hashed(db_session, gid, 1, "keep.jpg", "1" * 64)
    # A pending-excluded row: hash landed in excluded_blobs, row kept as 'excluded'.
    await _blob(db_session, sha)
    await db_session.execute(
        text("UPDATE blobs SET ref_count = 1 WHERE sha256=:s"),
        {"s": sha},
    )
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, blob_sha256, visibility) "
            "VALUES (:g, 2, 'gone.jpg', :s, 'excluded')"
        ),
        {"g": gid, "s": sha},
    )
    await db_session.execute(
        text("INSERT INTO excluded_blobs (gallery_id, blob_sha256) VALUES (:g, :s)"), {"g": gid, "s": sha}
    )
    await db_session.commit()

    response = await client.delete(f"/api/library/galleries/local/rex/excluded/{sha}")

    assert response.status_code == 200
    remaining = (
        (await db_session.execute(text("SELECT filename FROM images WHERE gallery_id=:g"), {"g": gid})).scalars().all()
    )
    assert remaining == ["keep.jpg"]
    assert (
        await db_session.execute(text("SELECT COUNT(*) FROM excluded_blobs WHERE gallery_id=:g"), {"g": gid})
    ).scalar_one() == 0
    assert (await db_session.execute(text("SELECT ref_count FROM blobs WHERE sha256=:s"), {"s": sha})).scalar_one() == 0


async def test_restoring_excluded_blob_keeps_active_rows_with_same_blob(client, db_session):
    """Only visibility='excluded' rows are removed; an active row sharing the blob stays."""
    gid = await _gallery(db_session, "rex2")
    sha = "9" * 64
    await _hashed(db_session, gid, 1, "active.jpg", sha)
    await db_session.execute(
        text("INSERT INTO excluded_blobs (gallery_id, blob_sha256) VALUES (:g, :s)"), {"g": gid, "s": sha}
    )
    await db_session.commit()

    response = await client.delete(f"/api/library/galleries/local/rex2/excluded/{sha}")

    assert response.status_code == 200
    remaining = (
        (await db_session.execute(text("SELECT filename FROM images WHERE gallery_id=:g"), {"g": gid})).scalars().all()
    )
    assert remaining == ["active.jpg"]


# ---------------------------------------------------------------------------
# 6.6 saucenao
# ---------------------------------------------------------------------------


async def test_saucenao_search_on_pending_page_returns_409(client, db_session, db_session_factory):
    from unittest.mock import AsyncMock

    gid = await _gallery(db_session, "sauce")
    image_id = await _pending(db_session, gid, 1, "p.jpg")

    with (
        patch("routers.saucenao.get_credential", AsyncMock(return_value="api-key")),
        patch("routers.saucenao.async_session", db_session_factory),
    ):
        response = await client.post("/api/saucenao/search", json={"image_id": image_id})

    assert response.status_code == 409
    assert response.json()["detail"] == "Image is still being processed"


async def test_saucenao_search_on_missing_image_is_still_404(client, db_session_factory):
    from unittest.mock import AsyncMock

    with (
        patch("routers.saucenao.get_credential", AsyncMock(return_value="api-key")),
        patch("routers.saucenao.async_session", db_session_factory),
    ):
        response = await client.post("/api/saucenao/search", json={"image_id": 424242})

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 6.7 hide (no endpoint writes excluded_blobs for a pending page)
# ---------------------------------------------------------------------------


async def test_hiding_a_pending_page_does_not_write_an_excluded_blob(client, db_session):
    gid = await _gallery(db_session, "hide")
    image_id = await _pending(db_session, gid, 1, "p.jpg")

    response = await client.post(f"/api/library/images/{image_id}/hide")

    assert response.status_code == 200
    assert (await db_session.execute(text("SELECT COUNT(*) FROM excluded_blobs"))).scalar_one() == 0
    row = (await db_session.execute(text("SELECT visibility FROM images WHERE id=:i"), {"i": image_id})).scalar_one()
    assert row == "user_hidden"


# ---------------------------------------------------------------------------
# 6.9 OPDS
# ---------------------------------------------------------------------------


async def test_opds_gallery_lists_only_hashed_pages(opds_client, db_session):
    import xml.etree.ElementTree as ET

    gid = await _gallery(db_session, "opds", pages=2)
    await _pending(db_session, gid, 1, "p.jpg")
    hashed_id = await _hashed(db_session, gid, 2, "h.jpg", "ab" * 32)

    response = await opds_client.get("/opds/gallery/local/opds")

    assert response.status_code == 200
    root = ET.fromstring(response.content)
    ids = [e.find("{http://www.w3.org/2005/Atom}id").text for e in root.findall("{http://www.w3.org/2005/Atom}entry")]
    assert ids == [f"urn:jyzrox:image:{hashed_id}"]


async def test_opds_listing_page_count_excludes_pending_pages(opds_client, db_session):
    import xml.etree.ElementTree as ET

    gid = await _gallery(db_session, "opds2", pages=3)
    await _pending(db_session, gid, 1, "p.jpg")
    await _pending(db_session, gid, 2, "q.jpg")
    await _hashed(db_session, gid, 3, "h.jpg", "cd" * 32)

    response = await opds_client.get("/opds/all")

    root = ET.fromstring(response.content)
    entry = root.find("{http://www.w3.org/2005/Atom}entry")
    assert entry.get("{http://vaemendis.net/opds-pse/ns}count") == "1"


# ---------------------------------------------------------------------------
# 6.9 / 6.10 external API
# ---------------------------------------------------------------------------

_EXT_TOKEN = "pending-ext-token"


async def _ext_headers(db) -> dict:
    import hashlib
    import uuid

    uid = (
        await db.execute(
            text("INSERT INTO users (username, password_hash, role) VALUES (:u, 'x', 'viewer') RETURNING id"),
            {"u": f"ext_{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await db.execute(
        text("INSERT INTO api_tokens (id, user_id, token_hash) VALUES (:id, :uid, :h)"),
        {"id": str(uuid.uuid4()), "uid": uid, "h": hashlib.sha256(_EXT_TOKEN.encode()).hexdigest()},
    )
    await db.commit()
    return {"X-API-Token": _EXT_TOKEN}


async def _pending_with_file(db, gid: int, page: int, filename: str, path, payload: bytes) -> int:
    path.write_bytes(payload)
    await db.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, external_path, source_size, added_at) "
            "VALUES (:g, :p, :f, :ep, :sz, :now)"
        ),
        {"g": gid, "p": page, "f": filename, "ep": str(path), "sz": len(payload), "now": datetime.now(UTC)},
    )
    await db.commit()
    return (
        await db.execute(text("SELECT id FROM images WHERE gallery_id=:g AND page_num=:p"), {"g": gid, "p": page})
    ).scalar_one()


async def test_external_image_list_omits_pending_pages(ext_client, db_session):
    gid = await _gallery(db_session, "ext1")
    await _pending(db_session, gid, 1, "p.jpg")
    hashed_id = await _hashed(db_session, gid, 2, "h.jpg", "ef" * 32)
    headers = await _ext_headers(db_session)

    response = await ext_client.get(f"/api/external/v1/galleries/{gid}/images", headers=headers)

    assert response.status_code == 200, response.text
    assert [i["id"] for i in response.json()["images"]] == [hashed_id]


async def test_external_file_endpoint_serves_pending_page_from_its_own_path(ext_client, db_session, tmp_path):
    gid = await _gallery(db_session, "ext2")
    await _pending_with_file(db_session, gid, 1, "clip.mp4", tmp_path / "clip.mp4", b"video-bytes")
    headers = await _ext_headers(db_session)

    response = await ext_client.get(f"/api/external/v1/galleries/{gid}/images/1/file", headers=headers)

    assert response.status_code == 200, response.text
    assert response.content == b"video-bytes"
    assert response.headers["content-type"].startswith("video/mp4")


async def test_external_file_endpoint_pending_page_without_file_is_404(ext_client, db_session):
    gid = await _gallery(db_session, "ext3")
    await _pending(db_session, gid, 1, "gone.jpg")
    headers = await _ext_headers(db_session)

    response = await ext_client.get(f"/api/external/v1/galleries/{gid}/images/1/file", headers=headers)

    assert response.status_code == 404


async def test_external_file_endpoint_still_checks_gallery_access(ext_client, db_session, tmp_path):
    gid = await _gallery(db_session, "ext4")
    await db_session.execute(
        text("UPDATE galleries SET visibility='private', created_by_user_id=999999 WHERE id=:g"), {"g": gid}
    )
    await db_session.commit()
    await _pending_with_file(db_session, gid, 1, "a.jpg", tmp_path / "a.jpg", b"secret")
    headers = await _ext_headers(db_session)

    response = await ext_client.get(f"/api/external/v1/galleries/{gid}/images/1/file", headers=headers)

    assert response.status_code == 404
    assert b"secret" not in response.content


async def test_public_share_image_serves_pending_page_from_its_own_path(client, db_session, tmp_path):
    gid = await _gallery(db_session, "share")
    image_id = await _pending_with_file(db_session, gid, 1, "a.png", tmp_path / "a.png", b"png-bytes")
    created = await client.post(
        f"/api/gallery-management/galleries/{gid}/shares", json={"expires_in_hours": 24, "filter_r18": False}
    )
    token = created.json()["token"]

    response = await client.get(f"/api/gallery-management/shares/{token}/images/{image_id}")

    assert response.status_code == 200, response.text
    assert response.content == b"png-bytes"


async def test_public_share_image_pending_page_of_another_gallery_is_404(client, db_session, tmp_path):
    gid = await _gallery(db_session, "share2")
    other = await _gallery(db_session, "share3")
    other_image = await _pending_with_file(db_session, other, 1, "b.png", tmp_path / "b.png", b"other")
    created = await client.post(
        f"/api/gallery-management/galleries/{gid}/shares", json={"expires_in_hours": 24, "filter_r18": False}
    )
    token = created.json()["token"]

    response = await client.get(f"/api/gallery-management/shares/{token}/images/{other_image}")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 6.11 datasets and export
# ---------------------------------------------------------------------------


async def _dataset_user(db) -> None:
    await db.execute(text("INSERT INTO users (id, username, password_hash, role) VALUES (1, 'ds', 'x', 'member')"))
    await db.commit()


async def test_dataset_selection_skips_pending_pages(db_session, make_client):
    from unittest.mock import AsyncMock

    await _dataset_user(db_session)
    gid = await _gallery(db_session, "ds1")
    pending_id = await _pending(db_session, gid, 1, "p.jpg")
    hashed_id = await _hashed(db_session, gid, 2, "h.jpg", "11" * 32)

    with patch("routers.datasets.emit_safe", new_callable=AsyncMock):
        async with make_client(user_id=1) as ac:
            response = await ac.post(
                "/api/datasets/", json={"name": "d", "gallery_ids": [gid], "image_ids": [pending_id]}
            )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["member_count"] == 1
    members = (await db_session.execute(text("SELECT image_id FROM dataset_images"))).scalars().all()
    assert members == [hashed_id]


async def test_dataset_total_matches_listed_rows(db_session, make_client):
    from unittest.mock import AsyncMock

    await _dataset_user(db_session)
    gid = await _gallery(db_session, "ds2")
    pending_id = await _pending(db_session, gid, 1, "p.jpg")
    hashed_id = await _hashed(db_session, gid, 2, "h.jpg", "22" * 32)
    with patch("routers.datasets.emit_safe", new_callable=AsyncMock):
        async with make_client(user_id=1) as ac:
            created = await ac.post("/api/datasets/", json={"name": "d", "gallery_ids": [gid]})
    dataset_id = created.json()["id"]
    # A member row that predates hashing-aware selection: pending page already in the dataset.
    await db_session.execute(
        text("INSERT INTO dataset_images (dataset_id, image_id, state, source) VALUES (:d, :i, 'included', 'manual')"),
        {"d": dataset_id, "i": pending_id},
    )
    await db_session.commit()

    async with make_client(user_id=1) as ac:
        response = await ac.get(f"/api/datasets/{dataset_id}")

    body = response.json()
    assert response.status_code == 200, response.text
    assert [i["id"] for i in body["images"]] == [hashed_id]
    assert body["total"] == len(body["images"]) == 1
    assert body["member_count"] == 1


async def test_kohya_export_reports_pending_pages(client, db_session, db_session_factory, tmp_path):
    import io
    import zipfile

    gid = await _gallery(db_session, "kohya")
    real = tmp_path / "real.jpg"
    real.write_bytes(b"jpeg-bytes")
    sha = "33" * 32
    await db_session.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, media_type, extension, storage, external_path, ref_count) "
            "VALUES (:s, 10, 'image', '.jpg', 'external', :p, 1)"
        ),
        {"s": sha, "p": str(real)},
    )
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, blob_sha256, visibility) VALUES (:g, 1, 'real.jpg', :s, 'active')"
        ),
        {"g": gid, "s": sha},
    )
    await db_session.commit()
    await _pending(db_session, gid, 2, "waiting.jpg")

    with patch("routers.export.async_session", db_session_factory):
        response = await client.get(f"/api/export/kohya/{gid}")

    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert any(n.endswith("real.jpg") for n in zf.namelist())
    assert manifest["excluded"] == [{"filename": "waiting.jpg", "reason": "pending"}]


# ---------------------------------------------------------------------------
# 6.12 cover thumbnail job
# ---------------------------------------------------------------------------


async def test_cover_thumbnail_job_picks_first_hashed_page(db_session, db_session_factory):
    from unittest.mock import AsyncMock

    from worker.thumbnail import cover_thumbnail_job

    gid = await _gallery(db_session, "covjob")
    await _pending(db_session, gid, 1, "p1.jpg")
    hashed_id = await _hashed(db_session, gid, 2, "p2.jpg", "44" * 32)
    process = AsyncMock(return_value=1)

    with (
        patch("worker.thumbnail.AsyncSessionLocal", db_session_factory),
        patch("worker.thumbnail._process_images", process),
    ):
        result = await cover_thumbnail_job({}, gid)

    assert result["processed"] == 1
    assert [img.id for img in process.await_args.args[1]] == [hashed_id]
