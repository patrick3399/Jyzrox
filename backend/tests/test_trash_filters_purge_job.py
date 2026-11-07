"""Trash P2: list/summary filters, queued purge (bug C), chunked hard delete and purge job."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import RedisError
from sqlalchemy import text

MEMBER_ID = 2
OTHER_ID = 3


async def _ensure_users(db_session) -> None:
    for uid, role in ((1, "admin"), (MEMBER_ID, "member"), (OTHER_ID, "member")):
        await db_session.execute(
            text("INSERT OR IGNORE INTO users (id, username, password_hash, role) VALUES (:id, :u, 'x', :r)"),
            {"id": uid, "u": f"purge_user_{uid}", "r": role},
        )
    await db_session.commit()


async def _gallery(
    db_session,
    source_id: str,
    *,
    owner: int | None = 1,
    trashed: bool = True,
    deleted_at: datetime | None = None,
    **extra,
) -> int:
    cols = {
        "source": "local",
        "source_id": source_id,
        "title": f"T {source_id}",
        "download_status": "completed",
        "tags_array": "[]",
        "created_by_user_id": owner,
        "visibility": "public",
        "deleted_at": (deleted_at or datetime.now(UTC)) if trashed else None,
        **extra,
    }
    names = ", ".join(cols)
    params = ", ".join(f":{k}" for k in cols)
    res = await db_session.execute(text(f"INSERT INTO galleries ({names}) VALUES ({params}) RETURNING id"), cols)
    await db_session.commit()
    return res.scalar_one()


async def _image(db_session, gallery_id: int, sha: str, *, size: int = 1000, storage: str = "cas", page: int = 1):
    await db_session.execute(
        text("INSERT OR IGNORE INTO blobs (sha256, file_size, extension, storage) VALUES (:sha, :sz, 'jpg', :st)"),
        {"sha": sha, "sz": size, "st": storage},
    )
    await db_session.execute(
        text("INSERT INTO images (gallery_id, page_num, filename, blob_sha256) VALUES (:g, :p, 'a.jpg', :sha)"),
        {"g": gallery_id, "p": page, "sha": sha},
    )
    await db_session.commit()


async def _exists(db_session, gid: int) -> bool:
    db_session.expire_all()
    row = (await db_session.execute(text("SELECT 1 FROM galleries WHERE id = :i"), {"i": gid})).first()
    return row is not None


async def _deleted_at(db_session, gid: int):
    db_session.expire_all()
    return (await db_session.execute(text("SELECT deleted_at FROM galleries WHERE id = :i"), {"i": gid})).scalar_one()


# ---------------------------------------------------------------------------
# Empty / purge endpoints
# ---------------------------------------------------------------------------


async def test_empty_trash_enqueues_job_instead_of_deleting_in_request(client, db_session, mock_redis):
    """Bug C: Empty hard-deleted every trashed gallery inside the HTTP request (proxy timeout risk)."""
    await _ensure_users(db_session)
    ids = [await _gallery(db_session, f"c{i}") for i in range(3)]
    enqueue = AsyncMock()
    with patch("routers.library.get_redis", return_value=mock_redis), patch("core.queue.enqueue", enqueue):
        resp = await client.post("/api/library/trash/empty")
    assert resp.status_code == 202
    assert resp.json() == {"status": "queued", "total": 3}
    for gid in ids:
        assert await _exists(db_session, gid)
    enqueue.assert_awaited_once()
    assert enqueue.await_args.args[0] == "trash_purge_job"
    assert sorted(enqueue.await_args.kwargs["gallery_ids"]) == sorted(ids)
    assert enqueue.await_args.kwargs["user_id"] == 1
    assert enqueue.await_args.kwargs["role"] == "admin"
    mock_redis.set.assert_awaited_once()
    assert mock_redis.set.await_args.args[0] == "trash:purge:1"
    assert mock_redis.set.await_args.kwargs["nx"] is True
    assert mock_redis.set.await_args.kwargs["ex"] == 300


async def test_empty_trash_with_filter_snapshots_only_matching_ids(client, db_session, mock_redis):
    await _ensure_users(db_session)
    match = await _gallery(db_session, "f_match", title="needle one", deleted_reason="user")
    await _gallery(db_session, "f_other_title", title="haystack", deleted_reason="user")
    await _gallery(db_session, "f_other_reason", title="needle two", deleted_reason="merged")
    enqueue = AsyncMock()
    with patch("routers.library.get_redis", return_value=mock_redis), patch("core.queue.enqueue", enqueue):
        resp = await client.post("/api/library/trash/empty?q=needle&reason=user")
    assert resp.status_code == 202
    assert resp.json()["total"] == 1
    assert enqueue.await_args.kwargs["gallery_ids"] == [match]


async def test_empty_trash_returns_409_when_purge_guard_held(client, db_session, mock_redis):
    await _ensure_users(db_session)
    await _gallery(db_session, "g409")
    mock_redis.set = AsyncMock(return_value=None)  # SET NX lost
    enqueue = AsyncMock()
    with patch("routers.library.get_redis", return_value=mock_redis), patch("core.queue.enqueue", enqueue):
        resp = await client.post("/api/library/trash/empty")
    assert resp.status_code == 409
    enqueue.assert_not_awaited()


async def test_empty_trash_returns_503_when_guard_redis_errors(client, db_session, mock_redis):
    await _ensure_users(db_session)
    await _gallery(db_session, "g503")
    mock_redis.set = AsyncMock(side_effect=RedisError("down"))
    enqueue = AsyncMock()
    with patch("routers.library.get_redis", return_value=mock_redis), patch("core.queue.enqueue", enqueue):
        resp = await client.post("/api/library/trash/empty")
    assert resp.status_code == 503
    enqueue.assert_not_awaited()


async def test_empty_trash_enqueue_failure_releases_guard_and_returns_503(client, db_session, mock_redis):
    await _ensure_users(db_session)
    await _gallery(db_session, "gq503")
    enqueue = AsyncMock(side_effect=RuntimeError("queue down"))
    with patch("routers.library.get_redis", return_value=mock_redis), patch("core.queue.enqueue", enqueue):
        resp = await client.post("/api/library/trash/empty")
    assert resp.status_code == 503
    mock_redis.delete.assert_awaited_with("trash:purge:1")


# ---------------------------------------------------------------------------
# hard_delete_in_chunks
# ---------------------------------------------------------------------------


def _counting_factory(session_ids_per_call: list):
    """Session factory returning mock sessions; records the number of sessions opened."""

    @asynccontextmanager
    async def factory():
        s = AsyncMock()
        r = MagicMock()
        r.scalars.return_value.all.return_value = [MagicMock(id=i) for i in session_ids_per_call[len(opened)]]
        s.execute = AsyncMock(return_value=r)
        opened.append(s)
        yield s

    opened: list = []
    return factory, opened


async def test_purge_job_deletes_in_chunks_and_commits_each_chunk():
    """chunk_size=2 over 5 ids opens 3 sessions (one transaction per chunk) and reports progress."""
    from services.gallery_lifecycle import hard_delete_in_chunks

    chunks = [[1, 2], [3, 4], [5]]
    factory, opened = _counting_factory(chunks)
    progress: list = []

    async def on_chunk(done, total):
        progress.append((done, total))

    with patch(
        "services.gallery_lifecycle.hard_delete_galleries",
        new_callable=AsyncMock,
        side_effect=lambda session, galleries: {"affected": len(galleries), "deleted_dirs": 0},
    ) as hd:
        result = await hard_delete_in_chunks(factory, [1, 2, 3, 4, 5], chunk_size=2, on_chunk=on_chunk)

    assert len(opened) == 3
    assert hd.await_count == 3
    assert [c.args[0] for c in hd.await_args_list] == opened  # each chunk used its own session
    assert result == {"affected": 5, "deleted_dirs": 0, "failed_chunks": 0}
    assert progress == [(2, 5), (4, 5), (5, 5)]


async def test_purge_job_skips_gallery_restored_after_snapshot(db_session, db_session_factory, mock_redis):
    from services.gallery_lifecycle import hard_delete_in_chunks

    await _ensure_users(db_session)
    still = await _gallery(db_session, "sk_still")
    restored = await _gallery(db_session, "sk_restored", trashed=False)  # restored after the snapshot
    with patch("services.gallery_lifecycle.get_redis", return_value=mock_redis):
        result = await hard_delete_in_chunks(db_session_factory, [still, restored], chunk_size=1)
    assert result["affected"] == 1
    assert not await _exists(db_session, still)
    assert await _exists(db_session, restored)
    assert await _deleted_at(db_session, restored) is None


async def test_hard_delete_in_chunks_failed_chunk_is_counted_and_next_chunk_runs():
    from services.gallery_lifecycle import hard_delete_in_chunks

    factory, opened = _counting_factory([[1], [2]])
    calls = {"n": 0}

    async def flaky(session, galleries):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {"affected": len(galleries), "deleted_dirs": 0}

    with patch("services.gallery_lifecycle.hard_delete_galleries", side_effect=flaky):
        result = await hard_delete_in_chunks(factory, [1, 2], chunk_size=1)
    assert result["failed_chunks"] == 1
    assert result["affected"] == 1
    opened[0].rollback.assert_awaited_once()


async def test_purge_job_releases_guard_after_failure(mock_redis):
    from worker.trash import trash_purge_job

    with (
        patch("worker.trash.get_redis", return_value=mock_redis),
        patch("worker.trash.emit_safe", new_callable=AsyncMock),
        patch("worker.trash.hard_delete_in_chunks", new_callable=AsyncMock, side_effect=RuntimeError("db gone")),
    ):
        with pytest.raises(RuntimeError, match="db gone"):
            await trash_purge_job({}, user_id=MEMBER_ID, role="member", gallery_ids=[1, 2])
    mock_redis.delete.assert_awaited_with(f"trash:purge:{MEMBER_ID}")


async def test_purge_job_emits_progress_and_cleaned_with_actor(db_session, db_session_factory, mock_redis):
    from core.events import EventType
    from worker.trash import trash_purge_job

    await _ensure_users(db_session)
    ids = [await _gallery(db_session, f"ev{i}", owner=MEMBER_ID) for i in range(3)]
    emit = AsyncMock()
    with (
        patch("worker.trash.AsyncSessionLocal", db_session_factory),
        patch("worker.trash.get_redis", return_value=mock_redis),
        patch("worker.trash.emit_safe", emit),
        patch("services.gallery_lifecycle.get_redis", return_value=mock_redis),
    ):
        result = await trash_purge_job({}, user_id=MEMBER_ID, role="member", gallery_ids=ids)
    assert result["affected"] == 3
    progress = [c for c in emit.await_args_list if c.args[0] == EventType.TRASH_PURGE_PROGRESS]
    assert progress, "expected at least one trash.purge_progress event"
    for c in progress:
        assert c.kwargs["actor_user_id"] == MEMBER_ID
    assert (progress[-1].kwargs["done"], progress[-1].kwargs["total"]) == (3, 3)
    cleaned = [c for c in emit.await_args_list if c.args[0] == EventType.TRASH_CLEANED]
    assert len(cleaned) == 1
    assert cleaned[0].kwargs["actor_user_id"] == MEMBER_ID
    assert cleaned[0].kwargs["deleted"] == 3
    mock_redis.delete.assert_awaited_with(f"trash:purge:{MEMBER_ID}")


async def test_trash_gc_uses_chunked_delete_and_keeps_zero_retention_guard(db_session, db_session_factory, mock_redis):
    """retention=0 falls back to 30 days: only the 40-day-old gallery is hard-deleted, via chunks."""
    from services.gallery_lifecycle import hard_delete_in_chunks
    from worker.trash import trash_gc_job

    await _ensure_users(db_session)
    old = await _gallery(db_session, "gc_old", deleted_at=datetime.now(UTC) - timedelta(days=40))
    fresh = await _gallery(db_session, "gc_fresh", deleted_at=datetime.now(UTC) - timedelta(days=1))
    with (
        patch("worker.trash.AsyncSessionLocal", db_session_factory),
        patch("worker.trash.get_toggle", new_callable=AsyncMock, return_value=True),
        patch("worker.trash.get_int_setting", new_callable=AsyncMock, return_value=0),
        patch("worker.trash.emit_safe", new_callable=AsyncMock),
        patch("services.gallery_lifecycle.get_redis", return_value=mock_redis),
        patch(
            "worker.trash.hard_delete_in_chunks",
            wraps=hard_delete_in_chunks,
        ) as chunked,
    ):
        result = await trash_gc_job({})
    chunked.assert_awaited_once()
    assert result["affected"] == 1
    assert not await _exists(db_session, old)
    assert await _exists(db_session, fresh)


# ---------------------------------------------------------------------------
# List filters / sort
# ---------------------------------------------------------------------------


async def test_list_trash_q_filters_by_title(client, db_session):
    await _ensure_users(db_session)
    await _gallery(db_session, "q1", title="Alpha needle")
    await _gallery(db_session, "q2", title="Beta")
    resp = await client.get("/api/library/trash?q=needle")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert [g["source_id"] for g in data["galleries"]] == ["q1"]


async def test_list_trash_source_filter(client, db_session):
    await _ensure_users(db_session)
    await _gallery(db_session, "s1", source="alpha")
    await _gallery(db_session, "s2", source="beta")
    data = (await client.get("/api/library/trash?source=beta")).json()
    assert data["total"] == 1
    assert data["galleries"][0]["source_id"] == "s2"


async def test_list_trash_reason_unknown_matches_null_reason(client, db_session):
    await _ensure_users(db_session)
    await _gallery(db_session, "r_null")
    await _gallery(db_session, "r_user", deleted_reason="user")
    data = (await client.get("/api/library/trash?reason=unknown")).json()
    assert [g["source_id"] for g in data["galleries"]] == ["r_null"]
    data = (await client.get("/api/library/trash?reason=user")).json()
    assert [g["source_id"] for g in data["galleries"]] == ["r_user"]


async def test_list_trash_sort_size_asc_orders_by_logical_bytes(client, db_session):
    await _ensure_users(db_session)
    big = await _gallery(db_session, "z_big")
    small = await _gallery(db_session, "z_small")
    mid = await _gallery(db_session, "z_mid")
    await _image(db_session, big, "b1" * 32, size=9000)
    await _image(db_session, small, "b2" * 32, size=10)
    await _image(db_session, mid, "b3" * 32, size=500)
    data = (await client.get("/api/library/trash?sort=size&direction=asc")).json()
    assert [g["id"] for g in data["galleries"]] == [small, mid, big]
    data = (await client.get("/api/library/trash?sort=size&direction=desc")).json()
    assert [g["id"] for g in data["galleries"]] == [big, mid, small]


async def test_list_trash_bad_sort_returns_422(client):
    assert (await client.get("/api/library/trash?sort=bogus")).status_code == 422
    assert (await client.get("/api/library/trash?direction=sideways")).status_code == 422
    assert (await client.get("/api/library/trash?reason=nope")).status_code == 422


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


async def test_summary_reclaimable_excludes_blob_shared_with_live_gallery_and_external(client, db_session):
    await _ensure_users(db_session)
    live = await _gallery(db_session, "sm_live", trashed=False)
    trashed = await _gallery(db_session, "sm_trashed")
    await _image(db_session, trashed, "c1" * 32, size=100, page=1)  # exclusive CAS -> reclaimable
    await _image(db_session, trashed, "c2" * 32, size=200, page=2)  # shared with live -> not reclaimable
    await _image(db_session, live, "c2" * 32, size=200, page=1)
    await _image(db_session, trashed, "c3" * 32, size=400, page=3, storage="external")  # external -> not reclaimable
    resp = await client.get("/api/library/trash/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["logical_bytes"] == 700
    assert data["reclaimable_bytes"] == 100


async def test_summary_next_expiry_is_oldest_deleted_at_plus_retention(client, db_session):
    await _ensure_users(db_session)
    oldest = datetime.now(UTC) - timedelta(days=5)
    await _gallery(db_session, "ne_old", deleted_at=oldest)
    await _gallery(db_session, "ne_new", deleted_at=datetime.now(UTC) - timedelta(days=1))
    with patch("routers.library._get_int_setting", new=AsyncMock(return_value=10)):
        data = (await client.get("/api/library/trash/summary")).json()
    got = datetime.fromisoformat(data["next_expiry_at"]).replace(tzinfo=None)
    assert abs(got - (oldest + timedelta(days=10)).replace(tzinfo=None)) < timedelta(seconds=5)


async def test_summary_empty_trash_has_null_next_expiry(client):
    data = (await client.get("/api/library/trash/summary")).json()
    assert data["count"] == 0
    assert data["next_expiry_at"] is None
    assert data["purge"] is None


async def test_summary_sources_ignore_filters(client, db_session):
    await _ensure_users(db_session)
    await _gallery(db_session, "so1", source="alpha")
    await _gallery(db_session, "so2", source="beta")
    data = (await client.get("/api/library/trash/summary?source=alpha")).json()
    assert data["count"] == 1
    assert data["sources"] == ["alpha", "beta"]


async def test_summary_purge_reflects_guard_json(client, mock_redis):
    mock_redis.get = AsyncMock(return_value=json.dumps({"done": 50, "total": 200}))
    with patch("routers.library.get_redis", return_value=mock_redis):
        data = (await client.get("/api/library/trash/summary")).json()
    assert data["purge"] == {"done": 50, "total": 200}


# ---------------------------------------------------------------------------
# Restore filters
# ---------------------------------------------------------------------------


async def test_restore_all_with_reason_filter_restores_only_matching(client, db_session):
    await _ensure_users(db_session)
    merged = await _gallery(db_session, "rf_merged", deleted_reason="merged")
    user = await _gallery(db_session, "rf_user", deleted_reason="user")
    resp = await client.post("/api/library/trash/restore", json={"all": True, "reason": "merged"})
    assert resp.status_code == 200
    assert resp.json()["affected"] == 1
    assert await _deleted_at(db_session, merged) is None
    assert await _deleted_at(db_session, user) is not None


async def test_restore_body_with_unknown_field_returns_422(client):
    resp = await client.post("/api/library/trash/restore", json={"all": True, "bogus": 1})
    assert resp.status_code == 422


async def test_restore_filters_without_all_returns_422(client):
    resp = await client.post("/api/library/trash/restore", json={"gallery_ids": [1], "q": "x"})
    assert resp.status_code == 422
