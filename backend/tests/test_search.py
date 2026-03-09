"""
Tests for the unified search endpoint (/api/search/*) and saved searches CRUD.

Notes on SQLite compatibility:
- The search router uses PostgreSQL ARRAY operators (contains / overlap) which
  are not available in SQLite.  Tests that hit those code paths will encounter
  errors and are skipped with an explanatory mark.
- The saved-searches sub-routes (GET/POST/DELETE/PATCH /api/search/saved) use
  plain SQL and work fine with SQLite — those are fully tested.
- Basic text search (title:) and source/rating/favorited filters use standard
  SQL and work with SQLite.

The search router uses `async_session` directly (not via get_db), so the
`client` fixture's db override does not affect it.  We insert data via
`db_session` to the shared in-memory SQLite database which the router also
reads through the patched async_session.
"""

import json

import pytest
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_user(db_session, user_id=1):
    """Ensure a user row exists for FK constraints."""
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash) "
            "VALUES (:id, 'searchuser', 'x')"
        ),
        {"id": user_id},
    )
    await db_session.commit()


async def _insert_gallery(db_session, **overrides):
    """Insert a gallery and return its rowid."""
    defaults = {
        "source": "ehentai",
        "source_id": "1",
        "title": "Test Gallery",
        "title_jpn": None,
        "category": "doujinshi",
        "language": "english",
        "pages": 20,
        "rating": 0,
        "favorited": 0,
        "download_status": "completed",
        "tags_array": "[]",
    }
    defaults.update(overrides)
    await db_session.execute(
        text(
            "INSERT INTO galleries "
            "(source, source_id, title, title_jpn, category, language, pages, "
            "rating, favorited, download_status, tags_array) "
            "VALUES (:source, :source_id, :title, :title_jpn, :category, :language, "
            ":pages, :rating, :favorited, :download_status, :tags_array)"
        ),
        defaults,
    )
    await db_session.commit()
    result = await db_session.execute(text("SELECT last_insert_rowid()"))
    return result.scalar()


async def _insert_saved_search(db_session, user_id=1, name="My Search", query="test", params=None):
    """Insert a saved_searches row and return its rowid."""
    params_json = json.dumps(params or {})
    await db_session.execute(
        text(
            "INSERT INTO saved_searches (user_id, name, query, params) "
            "VALUES (:uid, :name, :query, :params)"
        ),
        {"uid": user_id, "name": name, "query": query, "params": params_json},
    )
    await db_session.commit()
    result = await db_session.execute(text("SELECT last_insert_rowid()"))
    return result.scalar()


# ---------------------------------------------------------------------------
# Search endpoint — basic paths
# ---------------------------------------------------------------------------


class TestSearchGalleries:
    """GET /api/search/ — library search."""

    async def test_search_empty_db_returns_zero(self, client):
        """Empty DB should return total=0 and empty items list."""
        resp = await client.get("/api/search/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_search_returns_all_galleries(self, client, db_session):
        """Without filters all inserted galleries should be returned."""
        await _insert_gallery(db_session, source_id="s1", title="Alpha")
        await _insert_gallery(db_session, source_id="s2", title="Beta")

        resp = await client.get("/api/search/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    async def test_search_title_filter(self, client, db_session):
        """title:<query> token should filter by title ILIKE."""
        await _insert_gallery(db_session, source_id="t1", title="Naruto Doujin")
        await _insert_gallery(db_session, source_id="t2", title="One Piece Adventure")

        resp = await client.get("/api/search/", params={"q": 'title:"naruto"'})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Naruto Doujin"

    async def test_search_source_filter(self, client, db_session):
        """source:<value> token should filter by source column."""
        await _insert_gallery(db_session, source="pixiv", source_id="p1", title="Pixiv Art")
        await _insert_gallery(db_session, source="ehentai", source_id="e1", title="EH Gallery")

        resp = await client.get("/api/search/", params={"q": "source:pixiv"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["source"] == "pixiv"

    async def test_search_rating_filter(self, client, db_session):
        """rating:>=N token should filter galleries with rating >= N."""
        await _insert_gallery(db_session, source_id="r1", title="High Rated", rating=5)
        await _insert_gallery(db_session, source_id="r2", title="Low Rated", rating=2)

        resp = await client.get("/api/search/", params={"q": "rating:>=4"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "High Rated"

    async def test_search_favorited_filter(self, client, db_session):
        """favorited:true token should return only favorited galleries."""
        await _insert_gallery(db_session, source_id="f1", title="Fav", favorited=1)
        await _insert_gallery(db_session, source_id="f2", title="Not Fav", favorited=0)

        resp = await client.get("/api/search/", params={"q": "favorited:true"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Fav"

    async def test_search_pagination(self, client, db_session):
        """Pagination params (page, limit) should limit the response."""
        for i in range(5):
            await _insert_gallery(db_session, source_id=f"p{i}", title=f"Gallery {i}")

        resp = await client.get("/api/search/", params={"page": 1, "limit": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2

    async def test_search_excessive_page_returns_400(self, client):
        """Page depth > 500 should return 400."""
        resp = await client.get("/api/search/", params={"page": 501})
        assert resp.status_code == 400
        assert "cursor" in resp.json()["detail"].lower()

    async def test_search_sort_by_rating(self, client, db_session):
        """sort:rating token should order by rating DESC."""
        await _insert_gallery(db_session, source_id="sr1", title="Rated 3", rating=3)
        await _insert_gallery(db_session, source_id="sr2", title="Rated 5", rating=5)
        await _insert_gallery(db_session, source_id="sr3", title="Rated 1", rating=1)

        resp = await client.get("/api/search/", params={"q": "sort:rating"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        ratings = [i["rating"] for i in items]
        assert ratings == sorted(ratings, reverse=True)

    async def test_search_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/search/")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Saved searches CRUD
# ---------------------------------------------------------------------------


class TestSavedSearches:
    """GET/POST/DELETE/PATCH /api/search/saved"""

    async def test_list_saved_searches_empty(self, client):
        """Empty saved searches should return empty list."""
        resp = await client.get("/api/search/saved")
        assert resp.status_code == 200
        data = resp.json()
        assert data["searches"] == []

    async def test_list_saved_searches_with_data(self, client, db_session):
        """Inserted saved searches should appear in listing."""
        await _insert_user(db_session)
        await _insert_saved_search(db_session, name="My Favourites", query="favorited:true")
        await _insert_saved_search(db_session, name="High Rated", query="rating:>=4")

        resp = await client.get("/api/search/saved")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["searches"]) == 2
        names = {s["name"] for s in data["searches"]}
        assert "My Favourites" in names
        assert "High Rated" in names

    async def test_create_saved_search(self, client, db_session):
        """POST should create a new saved search and return it."""
        await _insert_user(db_session)

        resp = await client.post(
            "/api/search/saved",
            json={"name": "Naruto Search", "query": 'title:"naruto"', "params": {}},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Naruto Search"
        assert data["query"] == 'title:"naruto"'
        assert "id" in data

    async def test_create_saved_search_minimal(self, client, db_session):
        """POST with only name (defaults for query/params) should succeed."""
        await _insert_user(db_session)

        resp = await client.post(
            "/api/search/saved",
            json={"name": "Minimal Search"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Minimal Search"
        assert data["query"] == ""

    async def test_delete_saved_search_success(self, client, db_session):
        """DELETE should remove the saved search."""
        await _insert_user(db_session)
        ss_id = await _insert_saved_search(db_session, name="To Delete")

        resp = await client.delete(f"/api/search/saved/{ss_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Verify deletion
        resp2 = await client.get("/api/search/saved")
        assert all(s["id"] != ss_id for s in resp2.json()["searches"])

    async def test_delete_saved_search_not_found(self, client):
        """Deleting a non-existent saved search should return 404."""
        resp = await client.delete("/api/search/saved/99999")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_rename_saved_search(self, client, db_session):
        """PATCH should rename the saved search."""
        await _insert_user(db_session)
        ss_id = await _insert_saved_search(db_session, name="Old Name")

        resp = await client.patch(
            f"/api/search/saved/{ss_id}",
            json={"name": "New Name"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "New Name"
        assert data["id"] == ss_id

    async def test_rename_saved_search_not_found(self, client):
        """PATCH on non-existent saved search should return 404."""
        resp = await client.patch(
            "/api/search/saved/99999",
            json={"name": "Whatever"},
        )
        assert resp.status_code == 404

    async def test_saved_searches_require_auth(self, unauthed_client):
        """All saved search endpoints require authentication."""
        resp_list = await unauthed_client.get("/api/search/saved")
        assert resp_list.status_code == 401

        resp_create = await unauthed_client.post(
            "/api/search/saved",
            json={"name": "x"},
        )
        assert resp_create.status_code == 401

        resp_delete = await unauthed_client.delete("/api/search/saved/1")
        assert resp_delete.status_code == 401

    async def test_saved_search_belongs_to_current_user(self, client, db_session):
        """Users should only be able to delete their own saved searches."""
        # Insert a saved search owned by user_id=99 (not the authed user_id=1)
        await db_session.execute(
            text(
                "INSERT OR IGNORE INTO users (id, username, password_hash) "
                "VALUES (99, 'otheruser', 'x')"
            )
        )
        await db_session.commit()
        ss_id = await _insert_saved_search(db_session, user_id=99, name="Other User Search")

        # Authenticated as user_id=1, trying to delete user 99's search
        resp = await client.delete(f"/api/search/saved/{ss_id}")
        assert resp.status_code == 404
