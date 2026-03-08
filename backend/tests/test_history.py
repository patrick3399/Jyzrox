"""
Tests for browse history endpoints (/api/history/*).

History routes use require_auth (overridden to user_id=1) and call
async_session directly. The `hist_client` fixture (defined in conftest.py)
patches routers.history.async_session to use the SQLite test engine.
"""

import uuid

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_user(db_session, user_id: int = 1) -> None:
    """Insert the user if not already present (required for FK constraints)."""
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash) "
            "VALUES (:id, :u, :p)"
        ),
        {"id": user_id, "u": f"hist_user_{user_id}", "p": "x"},
    )
    await db_session.commit()


async def _insert_history(
    db_session,
    user_id: int = 1,
    source: str = "ehentai",
    source_id: str | None = None,
    title: str = "Test Gallery",
) -> int:
    """Insert a browse_history row and return its id."""
    sid = source_id or uuid.uuid4().hex[:8]
    result = await db_session.execute(
        text(
            "INSERT INTO browse_history (user_id, source, source_id, title) "
            "VALUES (:uid, :s, :si, :t) RETURNING id"
        ),
        {"uid": user_id, "s": source, "si": sid, "t": title},
    )
    await db_session.commit()
    return result.scalar_one()


# ---------------------------------------------------------------------------
# GET /api/history/
# ---------------------------------------------------------------------------


class TestListHistory:
    """GET /api/history/ — list browse history."""

    async def test_list_history_empty(self, hist_client, db_session):
        """No history entries → empty items list with total=0."""
        await _ensure_user(db_session)

        resp = await hist_client.get("/api/history/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_list_history_returns_entries(self, hist_client, db_session):
        """Inserted entries appear in GET /api/history/."""
        await _ensure_user(db_session)
        await _insert_history(db_session, title="Gallery A")
        await _insert_history(db_session, title="Gallery B")

        resp = await hist_client.get("/api/history/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        titles = {item["title"] for item in data["items"]}
        assert "Gallery A" in titles
        assert "Gallery B" in titles

    async def test_list_history_pagination_limit(self, hist_client, db_session):
        """?limit= constrains result count."""
        await _ensure_user(db_session)
        for i in range(5):
            await _insert_history(db_session, title=f"Gallery {i}")

        resp = await hist_client.get("/api/history/", params={"limit": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 2

    async def test_list_history_response_shape(self, hist_client, db_session):
        """Response must include total, limit, offset, and items fields."""
        await _ensure_user(db_session)

        resp = await hist_client.get("/api/history/")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert "items" in data


# ---------------------------------------------------------------------------
# POST /api/history/
# ---------------------------------------------------------------------------


class TestRecordHistory:
    """POST /api/history/ — record a browse history entry."""

    async def test_record_history_creates_entry(self, hist_client, db_session):
        """POST with valid body → 201 and entry appears on GET."""
        await _ensure_user(db_session)

        payload = {
            "source": "ehentai",
            "source_id": "999",
            "title": "Posted Gallery",
            "gid": 999,
            "token": "abcdef",
        }
        resp = await hist_client.post("/api/history/", json=payload)
        assert resp.status_code == 201
        assert resp.json()["status"] == "ok"

        # Verify it appears in listing
        list_resp = await hist_client.get("/api/history/")
        assert list_resp.status_code == 200
        items = list_resp.json()["items"]
        source_ids = [i["source_id"] for i in items]
        assert "999" in source_ids

    async def test_record_history_upserts_on_conflict(self, hist_client, db_session):
        """Re-posting same (source, source_id) updates rather than duplicates."""
        await _ensure_user(db_session)

        payload = {"source": "pixiv", "source_id": "upsert1", "title": "Original"}
        await hist_client.post("/api/history/", json=payload)

        payload["title"] = "Updated"
        resp = await hist_client.post("/api/history/", json=payload)
        assert resp.status_code == 201

        list_resp = await hist_client.get("/api/history/")
        pixiv_items = [
            i for i in list_resp.json()["items"]
            if i["source"] == "pixiv" and i["source_id"] == "upsert1"
        ]
        # Must be exactly one record (upsert)
        assert len(pixiv_items) == 1
        assert pixiv_items[0]["title"] == "Updated"

    async def test_record_history_missing_required_fields(self, hist_client, db_session):
        """POST without required fields → 422."""
        await _ensure_user(db_session)

        # Missing source_id
        resp = await hist_client.post("/api/history/", json={"source": "ehentai"})
        assert resp.status_code == 422

    async def test_record_history_optional_fields_accepted(self, hist_client, db_session):
        """POST with only required fields (title/thumb/gid/token absent) → 201."""
        await _ensure_user(db_session)

        resp = await hist_client.post(
            "/api/history/",
            json={"source": "pixiv", "source_id": "minimal_test"},
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# DELETE /api/history/{id}
# ---------------------------------------------------------------------------


class TestDeleteHistoryEntry:
    """DELETE /api/history/{id} — delete single entry."""

    async def test_delete_history_entry_success(self, hist_client, db_session):
        """Delete existing entry → 200 with status=ok."""
        await _ensure_user(db_session)
        entry_id = await _insert_history(db_session, title="To Delete")

        resp = await hist_client.delete(f"/api/history/{entry_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Verify entry is gone
        list_resp = await hist_client.get("/api/history/")
        ids = [i["id"] for i in list_resp.json()["items"]]
        assert entry_id not in ids

    async def test_delete_history_entry_not_found(self, hist_client, db_session):
        """Delete non-existent entry → 404."""
        await _ensure_user(db_session)

        resp = await hist_client.delete("/api/history/99999")
        assert resp.status_code == 404

    async def test_delete_history_entry_wrong_user(self, hist_client, db_session):
        """Delete entry belonging to a different user → 404 (not exposed)."""
        await _ensure_user(db_session, user_id=1)
        # Insert entry for user 2
        await db_session.execute(
            text(
                "INSERT OR IGNORE INTO users (id, username, password_hash) "
                "VALUES (2, 'other_user', 'x')"
            )
        )
        await db_session.commit()
        entry_id = await _insert_history(db_session, user_id=2, title="Other User Entry")

        # Authenticated as user 1 — must not see user 2's entry
        resp = await hist_client.delete(f"/api/history/{entry_id}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/history/
# ---------------------------------------------------------------------------


class TestClearHistory:
    """DELETE /api/history/ — clear all history for the current user."""

    async def test_clear_history_success(self, hist_client, db_session):
        """Clearing history removes all entries for the user."""
        await _ensure_user(db_session)
        await _insert_history(db_session, title="Entry 1")
        await _insert_history(db_session, title="Entry 2")

        resp = await hist_client.delete("/api/history/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["deleted"] >= 2

        # Verify entries are gone
        list_resp = await hist_client.get("/api/history/")
        assert list_resp.json()["total"] == 0

    async def test_clear_history_empty_returns_ok(self, hist_client, db_session):
        """Clearing an already-empty history → 200 with deleted=0."""
        await _ensure_user(db_session)

        resp = await hist_client.delete("/api/history/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["deleted"] == 0

    async def test_clear_history_only_affects_own_user(self, hist_client, db_session):
        """Clearing history must not delete entries of other users."""
        await _ensure_user(db_session, user_id=1)
        await db_session.execute(
            text(
                "INSERT OR IGNORE INTO users (id, username, password_hash) "
                "VALUES (2, 'other_clear', 'x')"
            )
        )
        await db_session.commit()

        # One entry for user 1, one for user 2
        await _insert_history(db_session, user_id=1, title="User1 Entry")
        await _insert_history(db_session, user_id=2, title="User2 Entry")

        resp = await hist_client.delete("/api/history/")
        assert resp.status_code == 200

        # User 2's entry must still exist
        remaining = await db_session.execute(
            text("SELECT COUNT(*) FROM browse_history WHERE user_id = 2")
        )
        assert remaining.scalar_one() == 1
