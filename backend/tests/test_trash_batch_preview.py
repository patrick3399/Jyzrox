"""Trash batch restore/purge, preview, reason recording and regressions B/D/E."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import text

MEMBER_ID = 2
OTHER_ID = 3


async def _ensure_users(db_session) -> None:
    for uid, role in ((1, "admin"), (MEMBER_ID, "member"), (OTHER_ID, "member")):
        await db_session.execute(
            text("INSERT OR IGNORE INTO users (id, username, password_hash, role) VALUES (:id, :u, 'x', :r)"),
            {"id": uid, "u": f"trash_user_{uid}", "r": role},
        )
    await db_session.commit()


async def _gallery(
    db_session,
    source_id: str,
    *,
    owner: int | None = 1,
    trashed: bool = True,
    visibility: str = "public",
    download_status: str = "completed",
    last_scanned_at: datetime | None = None,
    **extra,
) -> int:
    cols = {
        "source": "local",
        "source_id": source_id,
        "title": f"T {source_id}",
        "download_status": download_status,
        "tags_array": "[]",
        "created_by_user_id": owner,
        "visibility": visibility,
        "deleted_at": datetime.now(UTC) if trashed else None,
        "last_scanned_at": last_scanned_at,
        **extra,
    }
    names = ", ".join(cols)
    params = ", ".join(f":{k}" for k in cols)
    res = await db_session.execute(text(f"INSERT INTO galleries ({names}) VALUES ({params}) RETURNING id"), cols)
    await db_session.commit()
    return res.scalar_one()


async def _image(db_session, gallery_id: int, sha: str, page_num: int = 1) -> None:
    await db_session.execute(
        text("INSERT OR IGNORE INTO blobs (sha256, file_size, extension) VALUES (:sha, 1000, 'jpg')"),
        {"sha": sha},
    )
    await db_session.execute(
        text("INSERT INTO images (gallery_id, page_num, filename, blob_sha256) VALUES (:g, :p, 'a.jpg', :sha)"),
        {"g": gallery_id, "p": page_num, "sha": sha},
    )
    await db_session.commit()


async def _row(db_session, gid: int):
    db_session.expire_all()
    return (
        await db_session.execute(
            text(
                "SELECT deleted_at, deleted_reason, deleted_by_user_id, merged_into_gallery_id "
                "FROM galleries WHERE id = :id"
            ),
            {"id": gid},
        )
    ).one_or_none()


# ---------------------------------------------------------------------------
# Regressions B / D / E
# ---------------------------------------------------------------------------


async def test_restore_invalidates_sources_cache(client, db_session, mock_redis):
    """Bug B: single restore must drop the cached sources list."""
    await _ensure_users(db_session)
    await _gallery(db_session, "b1")
    with patch("services.gallery_lifecycle.get_redis", return_value=mock_redis):
        resp = await client.post("/api/library/galleries/local/b1/restore")
    assert resp.status_code == 200
    mock_redis.delete.assert_any_await("library:sources")


async def test_restore_missing_link_gallery_restarts_hold_so_scan_does_not_retrash(client, db_session):
    """Bug D: a restored 'missing' link gallery got re-trashed by the next scan at once."""
    from db.models import Gallery
    from worker.scan import _hold_vanished_link_gallery

    await _ensure_users(db_session)
    gid = await _gallery(
        db_session,
        "d1",
        download_status="missing",
        last_scanned_at=datetime.now(UTC) - timedelta(days=40),
        deleted_reason="source_missing",
    )
    resp = await client.post("/api/library/galleries/local/d1/restore")
    assert resp.status_code == 200
    db_session.expire_all()
    g = await db_session.get(Gallery, gid)
    assert g.deleted_at is None
    assert _hold_vanished_link_gallery(g) != "trashed"
    assert g.deleted_at is None


async def test_trash_list_includes_cover_thumb(client, db_session):
    """Bug E: trash list items always had cover_thumb null."""
    await _ensure_users(db_session)
    gid = await _gallery(db_session, "e1")
    await _image(db_session, gid, "e1" * 32)
    with patch("core.gallery_helpers._existing_thumb_url", side_effect=lambda sha: f"/thumbs/{sha}.webp"):
        resp = await client.get("/api/library/trash")
    assert resp.status_code == 200
    item = next(g for g in resp.json()["galleries"] if g["id"] == gid)
    assert item["cover_thumb"] is not None


# ---------------------------------------------------------------------------
# List: deleted_by / merged_into visibility
# ---------------------------------------------------------------------------


async def test_trash_list_hides_merge_target_invisible_to_member(client, make_client, db_session):
    await _ensure_users(db_session)
    private_target = await _gallery(db_session, "mt_priv", owner=OTHER_ID, trashed=False, visibility="private")
    visible_target = await _gallery(db_session, "mt_pub", owner=OTHER_ID, trashed=False, visibility="public")
    await _gallery(
        db_session,
        "src_priv",
        owner=MEMBER_ID,
        deleted_reason="merged",
        merged_into_gallery_id=private_target,
        deleted_by_user_id=MEMBER_ID,
    )
    await _gallery(
        db_session, "src_pub", owner=MEMBER_ID, deleted_reason="merged", merged_into_gallery_id=visible_target
    )
    async with make_client(user_id=MEMBER_ID, role="member") as ac:
        resp = await ac.get("/api/library/trash")
    assert resp.status_code == 200
    by_sid = {g["source_id"]: g for g in resp.json()["galleries"]}
    assert by_sid["src_priv"]["merged_into"] is None
    assert by_sid["src_pub"]["merged_into"]["source_id"] == "mt_pub"
    assert by_sid["src_priv"]["deleted_by"] == {"id": MEMBER_ID, "username": f"trash_user_{MEMBER_ID}"}
    assert by_sid["src_priv"]["deleted_reason"] == "merged"


async def test_trash_list_merge_target_itself_trashed_is_null(client, db_session):
    await _ensure_users(db_session)
    target = await _gallery(db_session, "mt_trashed")
    await _gallery(db_session, "src_x", deleted_reason="merged", merged_into_gallery_id=target)
    resp = await client.get("/api/library/trash")
    item = next(g for g in resp.json()["galleries"] if g["source_id"] == "src_x")
    assert item["merged_into"] is None


# ---------------------------------------------------------------------------
# Batch restore / purge
# ---------------------------------------------------------------------------


async def test_batch_restore_member_cannot_restore_other_users_gallery(make_client, db_session):
    await _ensure_users(db_session)
    mine = await _gallery(db_session, "br_mine", owner=MEMBER_ID)
    theirs = await _gallery(db_session, "br_theirs", owner=OTHER_ID)
    async with make_client(user_id=MEMBER_ID, role="member") as ac:
        resp = await ac.post("/api/library/trash/restore", json={"gallery_ids": [mine, theirs]})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "affected": 1}
    assert (await _row(db_session, mine)).deleted_at is None
    assert (await _row(db_session, theirs)).deleted_at is not None


async def test_batch_restore_all_restores_only_scoped_rows(make_client, db_session):
    await _ensure_users(db_session)
    mine = await _gallery(db_session, "ra_mine", owner=MEMBER_ID)
    unowned = await _gallery(db_session, "ra_unowned", owner=None)
    theirs = await _gallery(db_session, "ra_theirs", owner=OTHER_ID)
    live = await _gallery(db_session, "ra_live", owner=MEMBER_ID, trashed=False)
    async with make_client(user_id=MEMBER_ID, role="member") as ac:
        resp = await ac.post("/api/library/trash/restore", json={"all": True})
    assert resp.status_code == 200
    assert resp.json()["affected"] == 2
    assert (await _row(db_session, mine)).deleted_at is None
    assert (await _row(db_session, unowned)).deleted_at is None
    assert (await _row(db_session, theirs)).deleted_at is not None
    assert (await _row(db_session, live)).deleted_at is None


async def test_batch_restore_clears_reason_actor_and_merge_target(client, db_session):
    await _ensure_users(db_session)
    target = await _gallery(db_session, "rc_target", trashed=False)
    gid = await _gallery(
        db_session, "rc1", deleted_reason="merged", deleted_by_user_id=MEMBER_ID, merged_into_gallery_id=target
    )
    resp = await client.post("/api/library/trash/restore", json={"gallery_ids": [gid]})
    assert resp.status_code == 200
    row = await _row(db_session, gid)
    assert (row.deleted_at, row.deleted_reason, row.deleted_by_user_id, row.merged_into_gallery_id) == (
        None,
        None,
        None,
        None,
    )


async def test_batch_restore_rejects_both_ids_and_all(client):
    resp = await client.post("/api/library/trash/restore", json={"gallery_ids": [1], "all": True})
    assert resp.status_code == 422


async def test_batch_restore_rejects_neither_ids_nor_all(client):
    resp = await client.post("/api/library/trash/restore", json={})
    assert resp.status_code == 422


async def test_batch_restore_rejects_more_than_500_ids(client):
    resp = await client.post("/api/library/trash/restore", json={"gallery_ids": list(range(1, 502))})
    assert resp.status_code == 422


async def test_batch_purge_rejects_more_than_500_ids(client):
    resp = await client.post("/api/library/trash/purge", json={"gallery_ids": list(range(1, 502))})
    assert resp.status_code == 422


async def test_batch_purge_hard_deletes_only_trashed_scoped_rows(make_client, db_session):
    await _ensure_users(db_session)
    mine = await _gallery(db_session, "pg_mine", owner=MEMBER_ID)
    theirs = await _gallery(db_session, "pg_theirs", owner=OTHER_ID)
    live = await _gallery(db_session, "pg_live", owner=MEMBER_ID, trashed=False)
    with patch("services.gallery_lifecycle.get_redis", return_value=AsyncMock()):
        async with make_client(user_id=MEMBER_ID, role="member") as ac:
            resp = await ac.post("/api/library/trash/purge", json={"gallery_ids": [mine, theirs, live]})
    assert resp.status_code == 200
    assert resp.json()["affected"] == 1
    assert await _row(db_session, mine) is None
    assert await _row(db_session, theirs) is not None
    live_row = await _row(db_session, live)
    assert live_row is not None and live_row.deleted_at is None


async def test_batch_restore_viewer_forbidden(make_client, db_session):
    async with make_client(user_id=MEMBER_ID, role="viewer") as ac:
        resp = await ac.post("/api/library/trash/restore", json={"all": True})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


async def test_preview_404_for_live_gallery(client, db_session):
    await _ensure_users(db_session)
    gid = await _gallery(db_session, "pv_live", trashed=False)
    resp = await client.get(f"/api/library/trash/{gid}/preview")
    assert resp.status_code == 404


async def test_preview_404_for_other_users_trashed_gallery_as_member(make_client, db_session):
    await _ensure_users(db_session)
    gid = await _gallery(db_session, "pv_other", owner=OTHER_ID)
    async with make_client(user_id=MEMBER_ID, role="member") as ac:
        resp = await ac.get(f"/api/library/trash/{gid}/preview")
    assert resp.status_code == 404


async def test_preview_returns_thumbs_without_file_path(client, db_session):
    await _ensure_users(db_session)
    gid = await _gallery(db_session, "pv1")
    sha_a, sha_b = "aa" * 32, "bb" * 32
    await _image(db_session, gid, sha_a, 1)
    await _image(db_session, gid, sha_b, 2)
    with patch("routers.library.existing_base_thumbs", new=AsyncMock(return_value={sha_a})):
        resp = await client.get(f"/api/library/trash/{gid}/preview?page=1&limit=60")
    assert resp.status_code == 200
    data = resp.json()
    assert data["images_total"] == 2
    assert data["page"] == 1
    assert data["gallery"]["id"] == gid
    assert set(data["media"]) == {"total_size", "counts"}
    assert set(data["media"]["counts"]) == {"image", "gif", "video"}
    assert len(data["images"]) == 2
    for img in data["images"]:
        assert "file_path" not in img
    by_page = {i["page_num"]: i for i in data["images"]}
    assert by_page[1]["thumb_path"]
    assert by_page[2]["thumb_path"] is None


async def test_preview_pages_images_by_limit(client, db_session):
    await _ensure_users(db_session)
    gid = await _gallery(db_session, "pv_page")
    for n in range(1, 4):
        await _image(db_session, gid, f"{n:02d}" * 32, n)
    resp = await client.get(f"/api/library/trash/{gid}/preview?page=2&limit=2")
    data = resp.json()
    assert data["images_total"] == 3
    assert [i["page_num"] for i in data["images"]] == [3]


# ---------------------------------------------------------------------------
# Reason recording
# ---------------------------------------------------------------------------


async def test_delete_gallery_records_user_reason_and_actor(client, db_session):
    await _ensure_users(db_session)
    gid = await _gallery(db_session, "rd1", trashed=False)
    with patch("routers.library._get_toggle", new=AsyncMock(return_value=True)):
        resp = await client.delete("/api/library/galleries/local/rd1")
    assert resp.status_code == 200
    row = await _row(db_session, gid)
    assert row.deleted_at is not None
    assert row.deleted_reason == "user"
    assert row.deleted_by_user_id == 1


async def test_batch_delete_records_user_reason_and_actor(client, db_session):
    await _ensure_users(db_session)
    gid = await _gallery(db_session, "rd2", trashed=False)
    resp = await client.post("/api/library/galleries/batch", json={"gallery_ids": [gid], "action": "delete"})
    assert resp.status_code == 200
    row = await _row(db_session, gid)
    assert row.deleted_reason == "user"
    assert row.deleted_by_user_id == 1


async def test_vanished_link_gallery_after_grace_records_source_missing_without_actor(db_session):
    from db.models import Gallery
    from worker.scan import _hold_vanished_link_gallery

    gid = await _gallery(
        db_session,
        "rd3",
        trashed=False,
        download_status="missing",
        last_scanned_at=datetime.now(UTC) - timedelta(days=40),
    )
    g = await db_session.get(Gallery, gid)
    assert _hold_vanished_link_gallery(g) == "trashed"
    await db_session.commit()
    row = await _row(db_session, gid)
    assert row.deleted_at is not None
    assert row.deleted_reason == "source_missing"
    assert row.deleted_by_user_id is None


async def test_mark_trashed_merged_records_target_and_actor(db_session):
    from db.models import Gallery
    from services.gallery_lifecycle import mark_trashed

    src = await _gallery(db_session, "rd4_src", trashed=False)
    target = await _gallery(db_session, "rd4_tgt", trashed=False)
    g = await db_session.get(Gallery, src)
    stamp = mark_trashed([g], reason="merged", actor_user_id=7, merged_into_gallery_id=target)
    await db_session.commit()
    assert g.deleted_at is not None and stamp is not None
    assert (g.deleted_reason, g.deleted_by_user_id, g.merged_into_gallery_id) == ("merged", 7, target)
