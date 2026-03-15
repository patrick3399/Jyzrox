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
