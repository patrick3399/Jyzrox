"""
Integration tests for the dedup router (/api/dedup/*).

Uses the `client` fixture (authenticated as admin user_id=1).
Patches routers.dedup.async_session and core.redis_client.get_redis
so all DB and Redis calls use the SQLite test engine and AsyncMock Redis.
"""

import pytest
from sqlalchemy import text
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_user(db_session):
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
            "VALUES (1, 'admin', 'hash', 'admin')"
        )
    )
    await db_session.commit()


async def _insert_blob(db_session, sha: str, phash_int: int | None = 12345):
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO blobs (sha256, file_size, extension, phash_int) "
            "VALUES (:sha, 1024, 'jpg', :phash_int)"
        ),
        {"sha": sha, "phash_int": phash_int},
    )
    await db_session.commit()


async def _insert_relationship(
    db_session,
    sha_a: str,
    sha_b: str,
    relationship: str = "quality_conflict",
    hamming_dist: int = 3,
) -> int:
    await db_session.execute(
        text(
            "INSERT INTO blob_relationships "
            "(sha_a, sha_b, hamming_dist, relationship) "
            "VALUES (:a, :b, :dist, :rel)"
        ),
        {"a": sha_a, "b": sha_b, "dist": hamming_dist, "rel": relationship},
    )
    await db_session.commit()
    row = await db_session.execute(
        text(
            "SELECT id FROM blob_relationships WHERE sha_a=:a AND sha_b=:b"
        ),
        {"a": sha_a, "b": sha_b},
    )
    return row.scalar_one()


# ---------------------------------------------------------------------------
# Tests — stats
# ---------------------------------------------------------------------------


async def test_dedup_stats_empty_db_returns_zero_counts(
    client, db_session, db_session_factory
):
    await _insert_user(db_session)
    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.get("/api/dedup/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_blobs"] == 0
    assert data["needs_t2"] == 0
    assert data["pending_review"] == 0
    assert data["whitelisted"] == 0
    assert data["resolved"] == 0


async def test_dedup_stats_with_blob_relationships_returns_correct_counts(
    client, db_session, db_session_factory
):
    await _insert_user(db_session)
    await _insert_blob(db_session, "aaa111", phash_int=1)
    await _insert_blob(db_session, "bbb222", phash_int=2)
    await _insert_blob(db_session, "ccc333", phash_int=3)
    await _insert_blob(db_session, "ddd444", phash_int=4)
    await _insert_blob(db_session, "eee555", phash_int=None)  # no phash — not counted
    await _insert_relationship(db_session, "aaa111", "bbb222", "quality_conflict")
    await _insert_relationship(db_session, "ccc333", "ddd444", "variant")

    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.get("/api/dedup/stats")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_blobs"] == 4  # eee555 excluded (no phash_int)
    assert data["pending_review"] == 2  # quality_conflict + variant
    assert data["needs_t2"] == 0


# ---------------------------------------------------------------------------
# Tests — review
# ---------------------------------------------------------------------------


async def test_dedup_review_empty_returns_empty_items(
    client, db_session, db_session_factory
):
    await _insert_user(db_session)
    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.get("/api/dedup/review")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["next_cursor"] is None


async def test_dedup_review_with_data_returns_items(
    client, db_session, db_session_factory
):
    await _insert_user(db_session)
    await _insert_blob(db_session, "sha_a1")
    await _insert_blob(db_session, "sha_b1")
    await _insert_relationship(db_session, "sha_a1", "sha_b1", "quality_conflict")

    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.get("/api/dedup/review")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["relationship"] == "quality_conflict"
    assert "blob_a" in item
    assert "blob_b" in item
    assert item["blob_a"]["sha256"] == "sha_a1"
    assert item["blob_b"]["sha256"] == "sha_b1"


async def test_dedup_review_filter_by_relationship_type(
    client, db_session, db_session_factory
):
    await _insert_user(db_session)
    await _insert_blob(db_session, "sha_q1")
    await _insert_blob(db_session, "sha_q2")
    await _insert_blob(db_session, "sha_v1")
    await _insert_blob(db_session, "sha_v2")
    await _insert_relationship(db_session, "sha_q1", "sha_q2", "quality_conflict")
    await _insert_relationship(db_session, "sha_v1", "sha_v2", "variant")

    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.get("/api/dedup/review?relationship=variant")

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["relationship"] == "variant"


async def test_dedup_review_excludes_non_review_relationships(
    client, db_session, db_session_factory
):
    await _insert_user(db_session)
    await _insert_blob(db_session, "sha_r1")
    await _insert_blob(db_session, "sha_r2")
    # "resolved" is not in REVIEW_RELATIONSHIPS and should not appear
    await _insert_relationship(db_session, "sha_r1", "sha_r2", "resolved")

    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.get("/api/dedup/review")

    assert resp.status_code == 200
    assert resp.json()["items"] == []


# ---------------------------------------------------------------------------
# Tests — keep pair
# ---------------------------------------------------------------------------


async def test_dedup_keep_pair_not_found_returns_404(
    client, db_session, db_session_factory
):
    await _insert_user(db_session)
    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.post(
            "/api/dedup/review/99999/keep",
            json={"keep_sha": "nonexistent"},
        )
    assert resp.status_code == 404


async def test_dedup_keep_pair_invalid_sha_returns_400(
    client, db_session, db_session_factory
):
    await _insert_user(db_session)
    await _insert_blob(db_session, "keep_a")
    await _insert_blob(db_session, "keep_b")
    pair_id = await _insert_relationship(
        db_session, "keep_a", "keep_b", "quality_conflict"
    )

    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.post(
            f"/api/dedup/review/{pair_id}/keep",
            json={"keep_sha": "not_in_pair"},
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tests — whitelist pair
# ---------------------------------------------------------------------------


async def test_dedup_whitelist_pair_updates_relationship(
    client, db_session, db_session_factory
):
    await _insert_user(db_session)
    await _insert_blob(db_session, "wl_sha_a")
    await _insert_blob(db_session, "wl_sha_b")
    pair_id = await _insert_relationship(
        db_session, "wl_sha_a", "wl_sha_b", "quality_conflict"
    )

    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.post(f"/api/dedup/review/{pair_id}/whitelist")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    row = await db_session.execute(
        text("SELECT relationship FROM blob_relationships WHERE id=:id"),
        {"id": pair_id},
    )
    assert row.scalar_one() == "whitelisted"


async def test_dedup_whitelist_pair_not_found_returns_404(
    client, db_session, db_session_factory
):
    await _insert_user(db_session)
    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.post("/api/dedup/review/99999/whitelist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests — dismiss pair
# ---------------------------------------------------------------------------


async def test_dedup_dismiss_pair_marks_resolved(
    client, db_session, db_session_factory
):
    await _insert_user(db_session)
    await _insert_blob(db_session, "dis_sha_a")
    await _insert_blob(db_session, "dis_sha_b")
    pair_id = await _insert_relationship(
        db_session, "dis_sha_a", "dis_sha_b", "quality_conflict"
    )

    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.delete(f"/api/dedup/review/{pair_id}")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    row = await db_session.execute(
        text("SELECT relationship FROM blob_relationships WHERE id=:id"),
        {"id": pair_id},
    )
    assert row.scalar_one() == "resolved"


async def test_dedup_dismiss_pair_not_found_returns_404(
    client, db_session, db_session_factory
):
    await _insert_user(db_session)
    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.delete("/api/dedup/review/99999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests — scan progress
# ---------------------------------------------------------------------------


async def test_dedup_scan_progress_no_scan_returns_idle(client, mock_redis):
    mock_redis.get = AsyncMock(return_value=None)
    resp = await client.get("/api/dedup/scan/progress")
    assert resp.status_code == 200
    assert resp.json()["status"] == "idle"


async def test_dedup_scan_progress_running_returns_details(client, mock_redis):
    async def _redis_get(key):
        return {
            "dedup:progress:status": b"running",
            "dedup:progress:current": b"50",
            "dedup:progress:total": b"100",
            "dedup:progress:tier": b"1",
            "dedup:progress:mode": b"pending",
        }.get(key)

    mock_redis.get = AsyncMock(side_effect=_redis_get)
    resp = await client.get("/api/dedup/scan/progress")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"
    assert data["current"] == 50
    assert data["total"] == 100
    assert data["percent"] == 50


# ---------------------------------------------------------------------------
# Tests — scan start
# ---------------------------------------------------------------------------


async def test_dedup_scan_start_enqueues_job(client, mock_redis):
    mock_redis.get = AsyncMock(return_value=None)
    resp = await client.post("/api/dedup/scan/start", json={"mode": "pending"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    from main import app
    app.state.arq.enqueue_job.assert_called_once_with(
        "dedup_scan_job", "pending", _job_id="dedup_scan:singleton"
    )


async def test_dedup_scan_start_already_running_returns_409(client, mock_redis):
    mock_redis.get = AsyncMock(return_value=b"running")
    resp = await client.post("/api/dedup/scan/start", json={"mode": "pending"})
    assert resp.status_code == 409


async def test_dedup_scan_start_invalid_mode_returns_422(client, mock_redis):
    mock_redis.get = AsyncMock(return_value=None)
    resp = await client.post("/api/dedup/scan/start", json={"mode": "invalid_mode"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests — scan signal
# ---------------------------------------------------------------------------


async def test_dedup_scan_signal_sets_redis_key(client, mock_redis):
    mock_redis.get = AsyncMock(return_value=b"running")
    resp = await client.post("/api/dedup/scan/signal", json={"signal": "pause"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_redis.set.assert_called_with("dedup:progress:signal", "pause")


async def test_dedup_scan_signal_no_scan_running_returns_409(client, mock_redis):
    mock_redis.get = AsyncMock(return_value=None)
    resp = await client.post("/api/dedup/scan/signal", json={"signal": "stop"})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Tests — stats individual relationship status counts
# ---------------------------------------------------------------------------


async def test_dedup_stats_counts_each_relationship_status_independently(
    client, db_session, db_session_factory
):
    """Each relationship status (needs_t2, needs_t3, whitelisted, resolved) is counted correctly."""
    await _insert_user(db_session)
    await _insert_blob(db_session, "s_t2a")
    await _insert_blob(db_session, "s_t2b")
    await _insert_blob(db_session, "s_t3a")
    await _insert_blob(db_session, "s_t3b")
    await _insert_blob(db_session, "s_wla")
    await _insert_blob(db_session, "s_wlb")
    await _insert_blob(db_session, "s_rsa")
    await _insert_blob(db_session, "s_rsb")

    await _insert_relationship(db_session, "s_t2a", "s_t2b", "needs_t2")
    await _insert_relationship(db_session, "s_t3a", "s_t3b", "needs_t3")
    await _insert_relationship(db_session, "s_wla", "s_wlb", "whitelisted")
    await _insert_relationship(db_session, "s_rsa", "s_rsb", "resolved")

    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.get("/api/dedup/stats")

    assert resp.status_code == 200
    data = resp.json()
    assert data["needs_t2"] == 1
    assert data["needs_t3"] == 1
    assert data["whitelisted"] == 1
    assert data["resolved"] == 1
    assert data["pending_review"] == 0


async def test_dedup_stats_total_blobs_excludes_entries_without_phash(
    client, db_session, db_session_factory
):
    """total_blobs counts only blobs where phash_int IS NOT NULL."""
    await _insert_user(db_session)
    # 3 blobs with phash_int
    await _insert_blob(db_session, "ph_has1", phash_int=10)
    await _insert_blob(db_session, "ph_has2", phash_int=20)
    await _insert_blob(db_session, "ph_has3", phash_int=30)
    # 2 blobs without phash_int — must not be counted
    await _insert_blob(db_session, "ph_nil1", phash_int=None)
    await _insert_blob(db_session, "ph_nil2", phash_int=None)

    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.get("/api/dedup/stats")

    assert resp.status_code == 200
    assert resp.json()["total_blobs"] == 3


# ---------------------------------------------------------------------------
# Tests — review cursor pagination
# ---------------------------------------------------------------------------


async def test_dedup_review_pagination_limit_returns_next_cursor(
    client, db_session, db_session_factory
):
    """Fetching with limit=1 when 3 pairs exist returns next_cursor."""
    await _insert_user(db_session)
    await _insert_blob(db_session, "pag_a1")
    await _insert_blob(db_session, "pag_b1")
    await _insert_blob(db_session, "pag_a2")
    await _insert_blob(db_session, "pag_b2")
    await _insert_blob(db_session, "pag_a3")
    await _insert_blob(db_session, "pag_b3")
    await _insert_relationship(db_session, "pag_a1", "pag_b1", "quality_conflict")
    await _insert_relationship(db_session, "pag_a2", "pag_b2", "quality_conflict")
    await _insert_relationship(db_session, "pag_a3", "pag_b3", "quality_conflict")

    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.get("/api/dedup/review?limit=1")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["next_cursor"] is not None


async def test_dedup_review_pagination_next_cursor_fetches_next_page(
    client, db_session, db_session_factory
):
    """Using next_cursor from page 1 returns a different item on page 2."""
    await _insert_user(db_session)
    await _insert_blob(db_session, "pg2_a1")
    await _insert_blob(db_session, "pg2_b1")
    await _insert_blob(db_session, "pg2_a2")
    await _insert_blob(db_session, "pg2_b2")
    await _insert_blob(db_session, "pg2_a3")
    await _insert_blob(db_session, "pg2_b3")
    await _insert_relationship(db_session, "pg2_a1", "pg2_b1", "quality_conflict")
    await _insert_relationship(db_session, "pg2_a2", "pg2_b2", "quality_conflict")
    await _insert_relationship(db_session, "pg2_a3", "pg2_b3", "quality_conflict")

    with patch("routers.dedup.async_session", db_session_factory):
        page1 = await client.get("/api/dedup/review?limit=1")
        cursor = page1.json()["next_cursor"]
        assert cursor is not None

        page2 = await client.get(f"/api/dedup/review?limit=1&cursor={cursor}")

    assert page2.status_code == 200
    data2 = page2.json()
    assert len(data2["items"]) == 1
    # Page 2 must contain a different pair than page 1
    page1_id = page1.json()["items"][0]["id"]
    page2_id = data2["items"][0]["id"]
    assert page1_id != page2_id


async def test_dedup_review_pagination_invalid_cursor_returns_first_page(
    client, db_session, db_session_factory
):
    """A forged/invalid cursor is ignored and the first page is returned."""
    await _insert_user(db_session)
    await _insert_blob(db_session, "inv_a1")
    await _insert_blob(db_session, "inv_b1")
    await _insert_blob(db_session, "inv_a2")
    await _insert_blob(db_session, "inv_b2")
    await _insert_relationship(db_session, "inv_a1", "inv_b1", "quality_conflict")
    await _insert_relationship(db_session, "inv_a2", "inv_b2", "quality_conflict")

    with patch("routers.dedup.async_session", db_session_factory):
        resp_no_cursor = await client.get("/api/dedup/review?limit=2")
        resp_bad_cursor = await client.get(
            "/api/dedup/review?limit=2&cursor=totally.invalid"
        )

    assert resp_bad_cursor.status_code == 200
    # Both should return the same first-page items (invalid cursor treated as absent)
    assert resp_bad_cursor.json()["items"] == resp_no_cursor.json()["items"]


# ---------------------------------------------------------------------------
# Tests — keep success case
# ---------------------------------------------------------------------------


async def test_dedup_keep_pair_resolves_relationship_and_returns_200(
    client, db_session, db_session_factory
):
    """keep with valid sha resolves the pair relationship and returns 200."""
    await _insert_user(db_session)
    await _insert_blob(db_session, "keep_ok_a")
    await _insert_blob(db_session, "keep_ok_b")
    pair_id = await _insert_relationship(
        db_session, "keep_ok_a", "keep_ok_b", "quality_conflict"
    )

    # Insert a gallery and one image referencing each blob so the re-point
    # UPDATE has rows to operate on.
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, download_status) "
            "VALUES ('test', 'g_keep_ok', 'Keep Test', 'downloaded')"
        )
    )
    await db_session.commit()
    gid_row = await db_session.execute(
        text("SELECT id FROM galleries WHERE source_id='g_keep_ok'")
    )
    gid = gid_row.scalar_one()

    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, blob_sha256) "
            "VALUES (:gid, 1, 'keep_ok_a'), (:gid, 2, 'keep_ok_b')"
        ),
        {"gid": gid},
    )
    await db_session.commit()

    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.post(
            f"/api/dedup/review/{pair_id}/keep",
            json={"keep_sha": "keep_ok_a"},
        )

    assert resp.status_code == 200

    rel_row = await db_session.execute(
        text("SELECT relationship FROM blob_relationships WHERE id=:id"),
        {"id": pair_id},
    )
    assert rel_row.scalar_one() == "resolved"


async def test_dedup_keep_pair_remaps_images_from_discard_to_keep(
    client, db_session, db_session_factory
):
    """keep re-points images referencing the discarded blob to the kept blob."""
    await _insert_user(db_session)
    await _insert_blob(db_session, "remap_keep")
    await _insert_blob(db_session, "remap_discard")
    pair_id = await _insert_relationship(
        db_session, "remap_keep", "remap_discard", "quality_conflict"
    )

    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, download_status) "
            "VALUES ('test', 'g_remap', 'Remap Test', 'downloaded')"
        )
    )
    await db_session.commit()
    gid_row = await db_session.execute(
        text("SELECT id FROM galleries WHERE source_id='g_remap'")
    )
    gid = gid_row.scalar_one()

    # Two images reference the blob that will be discarded
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, blob_sha256) "
            "VALUES (:gid, 1, 'remap_discard'), (:gid, 2, 'remap_discard')"
        ),
        {"gid": gid},
    )
    await db_session.commit()

    with patch("routers.dedup.async_session", db_session_factory):
        resp = await client.post(
            f"/api/dedup/review/{pair_id}/keep",
            json={"keep_sha": "remap_keep"},
        )

    assert resp.status_code == 200

    # All images previously pointing to remap_discard now point to remap_keep
    row = await db_session.execute(
        text(
            "SELECT COUNT(*) FROM images WHERE gallery_id=:gid AND blob_sha256='remap_keep'"
        ),
        {"gid": gid},
    )
    assert row.scalar_one() == 2


# ---------------------------------------------------------------------------
# Tests — scan signal types (resume / stop)
# ---------------------------------------------------------------------------


async def test_dedup_scan_signal_resume_when_running_returns_200(client, mock_redis):
    """Signal 'resume' while scan is running succeeds."""
    mock_redis.get = AsyncMock(return_value=b"running")
    resp = await client.post("/api/dedup/scan/signal", json={"signal": "resume"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_redis.set.assert_called_with("dedup:progress:signal", "resume")


async def test_dedup_scan_signal_stop_when_running_sets_stop_key(client, mock_redis):
    """Signal 'stop' while scan is running writes 'stop' to Redis and returns 200."""
    mock_redis.get = AsyncMock(return_value=b"running")
    resp = await client.post("/api/dedup/scan/signal", json={"signal": "stop"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_redis.set.assert_called_with("dedup:progress:signal", "stop")


# ---------------------------------------------------------------------------
# Tests — role-based access control (admin-only endpoints)
# ---------------------------------------------------------------------------


async def test_dedup_viewer_cannot_access_stats(
    make_client, db_session, db_session_factory
):
    """viewer role is rejected with 403 on GET /api/dedup/stats."""
    await _insert_user(db_session)
    async with make_client(user_id=2, role="viewer") as ac:
        with patch("routers.dedup.async_session", db_session_factory):
            resp = await ac.get("/api/dedup/stats")
    assert resp.status_code == 403


async def test_dedup_viewer_cannot_start_scan(
    make_client, db_session, db_session_factory, mock_redis
):
    """viewer role is rejected with 403 on POST /api/dedup/scan/start."""
    await _insert_user(db_session)
    async with make_client(user_id=2, role="viewer") as ac:
        with patch("routers.dedup.async_session", db_session_factory):
            resp = await ac.post("/api/dedup/scan/start", json={"mode": "pending"})
    assert resp.status_code == 403


async def test_dedup_member_cannot_access_stats(
    make_client, db_session, db_session_factory
):
    """member role is rejected with 403 on GET /api/dedup/stats."""
    await _insert_user(db_session)
    async with make_client(user_id=2, role="member") as ac:
        with patch("routers.dedup.async_session", db_session_factory):
            resp = await ac.get("/api/dedup/stats")
    assert resp.status_code == 403


async def test_dedup_member_cannot_keep_pair(
    make_client, db_session, db_session_factory
):
    """member role is rejected with 403 on POST /api/dedup/review/{id}/keep."""
    await _insert_user(db_session)
    await _insert_blob(db_session, "rbac_keep_a")
    await _insert_blob(db_session, "rbac_keep_b")
    pair_id = await _insert_relationship(
        db_session, "rbac_keep_a", "rbac_keep_b", "quality_conflict"
    )
    async with make_client(user_id=2, role="member") as ac:
        with patch("routers.dedup.async_session", db_session_factory):
            resp = await ac.post(
                f"/api/dedup/review/{pair_id}/keep",
                json={"keep_sha": "rbac_keep_a"},
            )
    assert resp.status_code == 403
