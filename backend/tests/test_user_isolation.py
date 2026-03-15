"""
User isolation tests — verify that user A cannot see or modify user B's data.

Each test class covers one resource type. The pattern is:
  1. Insert test users (id=1 admin, id=2 member) into the DB.
  2. Insert data owned by user 1 directly via raw SQL.
  3. Open a client authenticated as user 2 via make_client(user_id=2).
  4. Assert that GET returns an empty list / 404, and DELETE returns 404 / 403.

The make_client fixture is a context-manager factory defined in conftest.py.
Because dependency_overrides is global, only ONE client may be open at a time.
"""

import uuid

import pytest
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _ensure_users(db_session) -> None:
    """Create test users 1 (admin) and 2 (member) if they do not exist yet."""
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
            "VALUES (:id, :u, :p, :r)"
        ),
        {"id": 1, "u": "user_one", "p": "x", "r": "admin"},
    )
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
            "VALUES (:id, :u, :p, :r)"
        ),
        {"id": 2, "u": "user_two", "p": "x", "r": "member"},
    )
    await db_session.commit()


async def _insert_gallery(db_session, source_id: str = "iso_gallery_1") -> int:
    """Insert a minimal gallery and return its id."""
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, download_status, tags_array) "
            "VALUES ('test', :sid, 'Isolation Gallery', 'proxy_only', '[]')"
        ),
        {"sid": source_id},
    )
    await db_session.commit()
    row = await db_session.execute(text("SELECT last_insert_rowid()"))
    return row.scalar()


# ---------------------------------------------------------------------------
# 1. Subscription isolation
# ---------------------------------------------------------------------------


class TestSubscriptionIsolation:
    """User 2 must not see or modify user 1's subscriptions."""

    @pytest.mark.asyncio
    async def test_list_subscriptions_does_not_leak_other_users_data(
        self, db_session, make_client
    ):
        """User 2 GET /api/subscriptions/ returns an empty list, not user 1's subscription."""
        await _ensure_users(db_session)
        await db_session.execute(
            text(
                "INSERT INTO subscriptions (user_id, url) VALUES (:uid, :url)"
            ),
            {"uid": 1, "url": "https://example.com/artist-isolation"},
        )
        await db_session.commit()

        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.get("/api/subscriptions/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["subscriptions"] == []

    @pytest.mark.asyncio
    async def test_get_subscription_returns_404_for_other_users_record(
        self, db_session, make_client
    ):
        """User 2 GET /api/subscriptions/{id} for a user-1 subscription returns 404."""
        await _ensure_users(db_session)
        await db_session.execute(
            text(
                "INSERT INTO subscriptions (user_id, url) VALUES (:uid, :url)"
            ),
            {"uid": 1, "url": "https://example.com/artist-get-404"},
        )
        await db_session.commit()
        row = await db_session.execute(text("SELECT last_insert_rowid()"))
        sub_id = row.scalar()

        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.get(f"/api/subscriptions/{sub_id}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_subscription_returns_404_for_other_users_record(
        self, db_session, make_client
    ):
        """User 2 DELETE /api/subscriptions/{id} for a user-1 subscription returns 404."""
        await _ensure_users(db_session)
        await db_session.execute(
            text(
                "INSERT INTO subscriptions (user_id, url) VALUES (:uid, :url)"
            ),
            {"uid": 1, "url": "https://example.com/artist-del-404"},
        )
        await db_session.commit()
        row = await db_session.execute(text("SELECT last_insert_rowid()"))
        sub_id = row.scalar()

        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.delete(f"/api/subscriptions/{sub_id}")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2. Collection isolation
# ---------------------------------------------------------------------------


class TestCollectionIsolation:
    """User 2 must not see or modify user 1's collections."""

    @pytest.mark.asyncio
    async def test_list_collections_does_not_leak_other_users_data(
        self, db_session, make_client
    ):
        """User 2 GET /api/collections/ returns an empty list, not user 1's collection."""
        await _ensure_users(db_session)
        await db_session.execute(
            text(
                "INSERT INTO collections (user_id, name) VALUES (:uid, :name)"
            ),
            {"uid": 1, "name": "User1 Private Collection"},
        )
        await db_session.commit()

        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.get("/api/collections/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["collections"] == []

    @pytest.mark.asyncio
    async def test_get_collection_returns_404_for_other_users_record(
        self, db_session, make_client
    ):
        """User 2 GET /api/collections/{id} for a user-1 collection returns 404."""
        await _ensure_users(db_session)
        await db_session.execute(
            text(
                "INSERT INTO collections (user_id, name) VALUES (:uid, :name)"
            ),
            {"uid": 1, "name": "User1 Secret"},
        )
        await db_session.commit()
        row = await db_session.execute(text("SELECT last_insert_rowid()"))
        coll_id = row.scalar()

        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.get(f"/api/collections/{coll_id}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_collection_returns_404_for_other_users_record(
        self, db_session, make_client
    ):
        """User 2 DELETE /api/collections/{id} for a user-1 collection returns 404."""
        await _ensure_users(db_session)
        await db_session.execute(
            text(
                "INSERT INTO collections (user_id, name) VALUES (:uid, :name)"
            ),
            {"uid": 1, "name": "User1 Delete Target"},
        )
        await db_session.commit()
        row = await db_session.execute(text("SELECT last_insert_rowid()"))
        coll_id = row.scalar()

        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.delete(f"/api/collections/{coll_id}")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3. Browse history isolation
# ---------------------------------------------------------------------------


class TestHistoryIsolation:
    """User 2 must not see or modify user 1's browse history."""

    @pytest.mark.asyncio
    async def test_list_history_does_not_leak_other_users_data(
        self, db_session, make_client
    ):
        """User 2 GET /api/history/ returns an empty list, not user 1's history."""
        await _ensure_users(db_session)
        await db_session.execute(
            text(
                "INSERT INTO browse_history (user_id, source, source_id, title) "
                "VALUES (:uid, 'ehentai', 'hist-iso-1', 'Private History')"
            ),
            {"uid": 1},
        )
        await db_session.commit()

        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.get("/api/history/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_delete_history_entry_returns_404_for_other_users_record(
        self, db_session, make_client
    ):
        """User 2 DELETE /api/history/{id} for a user-1 entry returns 404."""
        await _ensure_users(db_session)
        await db_session.execute(
            text(
                "INSERT INTO browse_history (user_id, source, source_id, title) "
                "VALUES (:uid, 'ehentai', 'hist-iso-del', 'Delete Target')"
            ),
            {"uid": 1},
        )
        await db_session.commit()
        row = await db_session.execute(text("SELECT last_insert_rowid()"))
        entry_id = row.scalar()

        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.delete(f"/api/history/{entry_id}")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. Download job isolation
# ---------------------------------------------------------------------------


class TestDownloadJobIsolation:
    """User 2 must not see user 1's download jobs."""

    @pytest.mark.asyncio
    async def test_list_jobs_does_not_include_other_users_jobs(
        self, db_session, make_client
    ):
        """User 2 GET /api/download/jobs does not contain user 1's job."""
        await _ensure_users(db_session)
        job_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO download_jobs (id, url, user_id, status) "
                "VALUES (:id, :url, :uid, 'queued')"
            ),
            {"id": job_id, "url": "https://example.com/iso-job", "uid": 1},
        )
        await db_session.commit()

        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.get("/api/download/jobs")

        assert resp.status_code == 200
        data = resp.json()
        returned_ids = [j["id"] for j in data["jobs"]]
        assert job_id not in returned_ids

    @pytest.mark.asyncio
    async def test_get_job_returns_403_for_other_users_job(
        self, db_session, make_client
    ):
        """User 2 GET /api/download/jobs/{id} for a user-1 job returns 403."""
        await _ensure_users(db_session)
        job_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO download_jobs (id, url, user_id, status) "
                "VALUES (:id, :url, :uid, 'queued')"
            ),
            {"id": job_id, "url": "https://example.com/iso-job-403", "uid": 1},
        )
        await db_session.commit()

        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.get(f"/api/download/jobs/{job_id}")

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 5. Favorite isolation
# ---------------------------------------------------------------------------


class TestFavoriteIsolation:
    """User 2's favorited=true filter must not return user 1's favorited galleries."""

    @pytest.mark.asyncio
    async def test_library_favorited_filter_does_not_leak_other_users_favorites(
        self, db_session, make_client
    ):
        """User 2 GET /api/library/?favorited=true returns empty, not user 1's favorite."""
        await _ensure_users(db_session)
        gallery_id = await _insert_gallery(db_session, source_id="fav-iso-gallery")
        await db_session.execute(
            text(
                "INSERT INTO user_favorites (user_id, gallery_id) "
                "VALUES (:uid, :gid)"
            ),
            {"uid": 1, "gid": gallery_id},
        )
        await db_session.commit()

        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.get("/api/library/galleries", params={"favorited": "true"})

        assert resp.status_code == 200
        data = resp.json()
        returned_ids = [g["id"] for g in data.get("galleries", [])]
        assert gallery_id not in returned_ids


# ---------------------------------------------------------------------------
# 6. Rating isolation
# ---------------------------------------------------------------------------


class TestRatingIsolation:
    """User 2 fetching a gallery must see my_rating=null, not user 1's rating."""

    @pytest.mark.asyncio
    async def test_gallery_detail_my_rating_is_null_for_other_users_rating(
        self, db_session, make_client
    ):
        """User 2 fetching a gallery rated 5 by user 1 sees my_rating as null."""
        await _ensure_users(db_session)
        gallery_id = await _insert_gallery(db_session, source_id="rating-iso-gallery")
        await db_session.execute(
            text(
                "INSERT INTO user_ratings (user_id, gallery_id, rating) "
                "VALUES (:uid, :gid, 5)"
            ),
            {"uid": 1, "gid": gallery_id},
        )
        await db_session.commit()

        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.get(f"/api/library/galleries/test/rating-iso-gallery")

        assert resp.status_code == 200
        data = resp.json()
        assert data.get("my_rating") is None
