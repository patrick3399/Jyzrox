"""
Tests for collection management endpoints (/api/collections/*).

Uses the `client` fixture (pre-authenticated as admin user_id=1).
Galleries are inserted via raw SQL to satisfy FK constraints in collection_galleries.
"""

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_user(db_session, user_id: int = 1) -> None:
    """Insert the user row if not already present."""
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
            "VALUES (:id, :u, 'x', 'admin')"
        ),
        {"id": user_id, "u": f"col_user_{user_id}"},
    )
    await db_session.commit()


async def _insert_gallery(
    db_session,
    source: str = "ehentai",
    source_id: str = "1234",
    title: str = "Test Gallery",
    user_id: int = 1,
) -> int:
    """Insert a minimal gallery and return its id."""
    result = await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, created_by_user_id) "
            "VALUES (:s, :si, :t, :uid) RETURNING id"
        ),
        {"s": source, "si": source_id, "t": title, "uid": user_id},
    )
    await db_session.commit()
    return result.scalar_one()


async def _create_collection(client, name: str, description: str | None = None) -> dict:
    """POST /api/collections/ and return the JSON response body."""
    payload: dict = {"name": name}
    if description is not None:
        payload["description"] = description
    resp = await client.post("/api/collections/", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# GET /api/collections/
# ---------------------------------------------------------------------------


class TestListCollections:
    """GET /api/collections/ — list collections for the current user."""

    async def test_list_empty_returns_empty_collections(self, client, db_session):
        """No collections → empty list."""
        await _ensure_user(db_session)

        resp = await client.get("/api/collections/")
        assert resp.status_code == 200
        data = resp.json()
        assert "collections" in data
        assert data["collections"] == []

    async def test_list_after_create_shows_collection(self, client, db_session):
        """A created collection must appear in the listing."""
        await _ensure_user(db_session)
        await _create_collection(client, "My Favourites")

        resp = await client.get("/api/collections/")
        assert resp.status_code == 200
        names = [c["name"] for c in resp.json()["collections"]]
        assert "My Favourites" in names

    async def test_list_response_shape(self, client, db_session):
        """Each collection entry must include id, name, gallery_count."""
        await _ensure_user(db_session)
        await _create_collection(client, "Shape Check")

        resp = await client.get("/api/collections/")
        assert resp.status_code == 200
        col = resp.json()["collections"][0]
        for field in ("id", "name", "gallery_count"):
            assert field in col

    async def test_list_gallery_count_reflects_added_galleries(self, client, db_session):
        """gallery_count increases after adding a gallery."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Count Check")
        col_id = col["id"]
        gid = await _insert_gallery(db_session, source_id="gc1")

        await client.post(f"/api/collections/{col_id}/galleries", json={"gallery_ids": [gid]})

        resp = await client.get("/api/collections/")
        collection = next(c for c in resp.json()["collections"] if c["id"] == col_id)
        assert collection["gallery_count"] == 1


# ---------------------------------------------------------------------------
# POST /api/collections/
# ---------------------------------------------------------------------------


class TestCreateCollection:
    """POST /api/collections/ — create a new collection."""

    async def test_create_collection_returns_id_and_name(self, client, db_session):
        """Valid payload → 200 with id and name in response."""
        await _ensure_user(db_session)

        resp = await client.post("/api/collections/", json={"name": "New Collection"})
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["name"] == "New Collection"

    async def test_create_collection_with_description(self, client, db_session):
        """description is returned in the response when provided."""
        await _ensure_user(db_session)

        resp = await client.post(
            "/api/collections/",
            json={"name": "Described", "description": "A short description"},
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "A short description"

    async def test_create_collection_missing_name_returns_422(self, client, db_session):
        """Missing required name field → 422 Unprocessable Entity."""
        await _ensure_user(db_session)

        resp = await client.post("/api/collections/", json={"description": "no name"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/collections/{collection_id}
# ---------------------------------------------------------------------------


class TestGetCollection:
    """GET /api/collections/{id} — retrieve a single collection."""

    async def test_get_collection_correct_fields(self, client, db_session):
        """Returned payload must include id, name, gallery_count, galleries, page, has_next."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Detail Col")

        resp = await client.get(f"/api/collections/{col['id']}")
        assert resp.status_code == 200
        data = resp.json()
        for field in ("id", "name", "gallery_count", "galleries", "page", "has_next"):
            assert field in data
        assert data["id"] == col["id"]
        assert data["name"] == "Detail Col"

    async def test_get_nonexistent_collection_returns_404(self, client, db_session):
        """GET on a non-existent id → 404."""
        await _ensure_user(db_session)

        resp = await client.get("/api/collections/99999")
        assert resp.status_code == 404

    async def test_get_collection_gallery_list_is_empty_initially(self, client, db_session):
        """Freshly created collection has an empty galleries list."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Empty Galleries")

        resp = await client.get(f"/api/collections/{col['id']}")
        assert resp.status_code == 200
        assert resp.json()["galleries"] == []
        assert resp.json()["gallery_count"] == 0

    async def test_get_collection_pagination_params(self, client, db_session):
        """?page=0&limit=5 must be accepted and reflected in the response."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Paginated")

        resp = await client.get(f"/api/collections/{col['id']}", params={"page": 0, "limit": 5})
        assert resp.status_code == 200
        assert resp.json()["page"] == 0


# ---------------------------------------------------------------------------
# PATCH /api/collections/{collection_id}
# ---------------------------------------------------------------------------


class TestUpdateCollection:
    """PATCH /api/collections/{id} — update a collection."""

    async def test_update_collection_name_returns_ok(self, client, db_session):
        """Patching name → 200 with status=ok."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Old Name")

        resp = await client.patch(f"/api/collections/{col['id']}", json={"name": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_update_collection_name_reflected_on_get(self, client, db_session):
        """After patching name, GET returns the updated name."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Rename Me")

        await client.patch(f"/api/collections/{col['id']}", json={"name": "Renamed"})

        resp = await client.get(f"/api/collections/{col['id']}")
        assert resp.json()["name"] == "Renamed"

    async def test_update_collection_description(self, client, db_session):
        """Patching description → 200."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Desc Update")

        resp = await client.patch(
            f"/api/collections/{col['id']}",
            json={"description": "Updated description"},
        )
        assert resp.status_code == 200

    async def test_update_nonexistent_collection_returns_404(self, client, db_session):
        """Patching a non-existent id → 404."""
        await _ensure_user(db_session)

        resp = await client.patch("/api/collections/99999", json={"name": "Ghost"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/collections/{collection_id}
# ---------------------------------------------------------------------------


class TestDeleteCollection:
    """DELETE /api/collections/{id} — remove a collection."""

    async def test_delete_collection_returns_ok(self, client, db_session):
        """Deleting an existing collection → 200 with status=ok."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "To Delete")

        resp = await client.delete(f"/api/collections/{col['id']}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_delete_collection_then_absent_from_list(self, client, db_session):
        """After deletion, the collection no longer appears in GET /api/collections/."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Gone")

        await client.delete(f"/api/collections/{col['id']}")

        resp = await client.get("/api/collections/")
        ids = [c["id"] for c in resp.json()["collections"]]
        assert col["id"] not in ids

    async def test_delete_nonexistent_collection_returns_404(self, client, db_session):
        """Deleting a non-existent id → 404."""
        await _ensure_user(db_session)

        resp = await client.delete("/api/collections/99999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/collections/{collection_id}/galleries
# ---------------------------------------------------------------------------


class TestAddGalleriesToCollection:
    """POST /api/collections/{id}/galleries — add galleries."""

    async def test_add_gallery_success_returns_ok_added_count(self, client, db_session):
        """Adding a valid gallery → 200 with added=1 and empty denied list."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Add Test")
        gid = await _insert_gallery(db_session, source_id="add1")

        resp = await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["added"] == 1
        assert data["denied"] == []

    async def test_add_nonexistent_gallery_goes_to_denied(self, client, db_session):
        """Adding a gallery_id that doesn't exist → 200, id appears in denied."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Denied Test")

        resp = await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [999999]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert 999999 in data["denied"]
        assert data["added"] == 0

    async def test_add_duplicate_gallery_counted_once(self, client, db_session):
        """Adding the same gallery twice keeps only one record."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Dup Gallery")
        gid = await _insert_gallery(db_session, source_id="dup1")

        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid]},
        )
        # Second add of the same gallery — should be silently skipped
        resp = await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid]},
        )
        assert resp.status_code == 200
        assert resp.json()["added"] == 0

        # Count must still be 1 in detail view
        detail = await client.get(f"/api/collections/{col['id']}")
        assert detail.json()["gallery_count"] == 1

    async def test_add_gallery_to_nonexistent_collection_returns_404(self, client, db_session):
        """Adding to a collection that does not exist → 404."""
        await _ensure_user(db_session)
        gid = await _insert_gallery(db_session, source_id="nf1")

        resp = await client.post(
            "/api/collections/99999/galleries",
            json={"gallery_ids": [gid]},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/collections/{collection_id}/galleries/{gallery_id}
# ---------------------------------------------------------------------------


class TestRemoveGalleryFromCollection:
    """DELETE /api/collections/{id}/galleries/{gid} — remove a gallery."""

    async def test_remove_gallery_success_returns_ok(self, client, db_session):
        """Removing an existing gallery from a collection → 200 with status=ok."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Remove Test")
        gid = await _insert_gallery(db_session, source_id="rm1")
        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid]},
        )

        resp = await client.delete(f"/api/collections/{col['id']}/galleries/{gid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_remove_gallery_then_absent_from_collection(self, client, db_session):
        """After removal, gallery no longer appears in the collection detail."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "After Remove")
        gid = await _insert_gallery(db_session, source_id="rm2")
        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid]},
        )

        await client.delete(f"/api/collections/{col['id']}/galleries/{gid}")

        detail = await client.get(f"/api/collections/{col['id']}")
        assert detail.json()["gallery_count"] == 0

    async def test_remove_gallery_not_in_collection_returns_404(self, client, db_session):
        """Removing a gallery not in the collection → 404."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Not In Col")
        gid = await _insert_gallery(db_session, source_id="nin1")

        resp = await client.delete(f"/api/collections/{col['id']}/galleries/{gid}")
        assert resp.status_code == 404
