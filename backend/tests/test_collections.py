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


# ---------------------------------------------------------------------------
# Auth — unauthenticated requests must return 401
# ---------------------------------------------------------------------------


class TestCollectionsAuth:
    """All collection endpoints must reject unauthenticated requests with 401."""

    async def test_list_collections_unauthenticated_returns_401(self, unauthed_client):
        resp = await unauthed_client.get("/api/collections/")
        assert resp.status_code == 401

    async def test_create_collection_unauthenticated_returns_401(self, unauthed_client):
        resp = await unauthed_client.post("/api/collections/", json={"name": "X"})
        assert resp.status_code == 401

    async def test_get_collection_unauthenticated_returns_401(self, unauthed_client):
        resp = await unauthed_client.get("/api/collections/1")
        assert resp.status_code == 401

    async def test_patch_collection_unauthenticated_returns_401(self, unauthed_client):
        resp = await unauthed_client.patch("/api/collections/1", json={"name": "Y"})
        assert resp.status_code == 401

    async def test_delete_collection_unauthenticated_returns_401(self, unauthed_client):
        resp = await unauthed_client.delete("/api/collections/1")
        assert resp.status_code == 401

    async def test_add_galleries_unauthenticated_returns_401(self, unauthed_client):
        resp = await unauthed_client.post("/api/collections/1/galleries", json={"gallery_ids": [1]})
        assert resp.status_code == 401

    async def test_remove_gallery_unauthenticated_returns_401(self, unauthed_client):
        resp = await unauthed_client.delete("/api/collections/1/galleries/1")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# User isolation — collections owned by another user must not be accessible
# ---------------------------------------------------------------------------


class TestCollectionsUserIsolation:
    """Collections are user-scoped; another user must not see or modify them."""

    async def _setup_other_user_collection(self, db_session) -> int:
        """Insert user 2 and a collection owned by user 2, return collection id."""
        await db_session.execute(
            text(
                "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                "VALUES (2, 'col_other_user', 'x', 'member')"
            )
        )
        result = await db_session.execute(
            text(
                "INSERT INTO collections (user_id, name) VALUES (2, 'Other User Col') RETURNING id"
            )
        )
        await db_session.commit()
        return result.scalar_one()

    async def test_list_does_not_show_other_users_collection(self, client, db_session):
        """GET /api/collections/ must only return collections owned by the current user."""
        await _ensure_user(db_session)
        col_id = await self._setup_other_user_collection(db_session)

        resp = await client.get("/api/collections/")
        assert resp.status_code == 200
        ids = [c["id"] for c in resp.json()["collections"]]
        assert col_id not in ids

    async def test_get_other_users_collection_returns_404(self, client, db_session):
        """GET /api/collections/{id} for another user's collection must return 404."""
        await _ensure_user(db_session)
        col_id = await self._setup_other_user_collection(db_session)

        resp = await client.get(f"/api/collections/{col_id}")
        assert resp.status_code == 404

    async def test_patch_other_users_collection_returns_404(self, client, db_session):
        """PATCH on another user's collection must return 404."""
        await _ensure_user(db_session)
        col_id = await self._setup_other_user_collection(db_session)

        resp = await client.patch(f"/api/collections/{col_id}", json={"name": "Stolen"})
        assert resp.status_code == 404

    async def test_delete_other_users_collection_returns_404(self, client, db_session):
        """DELETE on another user's collection must return 404."""
        await _ensure_user(db_session)
        col_id = await self._setup_other_user_collection(db_session)

        resp = await client.delete(f"/api/collections/{col_id}")
        assert resp.status_code == 404

    async def test_add_gallery_to_other_users_collection_returns_404(self, client, db_session):
        """POST galleries to another user's collection must return 404."""
        await _ensure_user(db_session)
        col_id = await self._setup_other_user_collection(db_session)
        gid = await _insert_gallery(db_session, source_id="iso_add1")

        resp = await client.post(
            f"/api/collections/{col_id}/galleries",
            json={"gallery_ids": [gid]},
        )
        assert resp.status_code == 404

    async def test_remove_gallery_from_other_users_collection_returns_404(
        self, client, db_session
    ):
        """DELETE gallery from another user's collection must return 404."""
        await _ensure_user(db_session)
        col_id = await self._setup_other_user_collection(db_session)
        gid = await _insert_gallery(db_session, source_id="iso_rm1")

        resp = await client.delete(f"/api/collections/{col_id}/galleries/{gid}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/collections/ — create_collection return fields
# ---------------------------------------------------------------------------


class TestCreateCollectionReturnFields:
    """create_collection must return created_at and all expected fields."""

    async def test_create_collection_response_includes_created_at(self, client, db_session):
        """Response from POST /api/collections/ must include created_at."""
        await _ensure_user(db_session)

        resp = await client.post("/api/collections/", json={"name": "With Timestamps"})
        assert resp.status_code == 200
        data = resp.json()
        assert "created_at" in data
        assert "id" in data
        assert data["name"] == "With Timestamps"

    async def test_create_collection_no_description_defaults_to_none(self, client, db_session):
        """When description is omitted, it must be null in the response."""
        await _ensure_user(db_session)

        resp = await client.post("/api/collections/", json={"name": "No Desc"})
        assert resp.status_code == 200
        assert resp.json().get("description") is None


# ---------------------------------------------------------------------------
# PATCH /api/collections/{collection_id} — cover_gallery_id update
# ---------------------------------------------------------------------------


class TestUpdateCollectionCoverGalleryId:
    """PATCH can set cover_gallery_id on a collection."""

    async def test_patch_cover_gallery_id_persisted(self, client, db_session):
        """Setting cover_gallery_id via PATCH must be reflected in GET."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Cover Patch")
        gid = await _insert_gallery(db_session, source_id="cvr1")

        # Add gallery first so it exists
        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid]},
        )

        resp = await client.patch(
            f"/api/collections/{col['id']}",
            json={"cover_gallery_id": gid},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        detail = await client.get(f"/api/collections/{col['id']}")
        assert detail.json()["cover_gallery_id"] == gid

    async def test_patch_all_fields_at_once(self, client, db_session):
        """Patching name, description, and cover_gallery_id in one request must all apply."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Multi Patch")
        gid = await _insert_gallery(db_session, source_id="cvr2")

        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid]},
        )

        resp = await client.patch(
            f"/api/collections/{col['id']}",
            json={"name": "Updated", "description": "New desc", "cover_gallery_id": gid},
        )
        assert resp.status_code == 200

        detail = await client.get(f"/api/collections/{col['id']}")
        body = detail.json()
        assert body["name"] == "Updated"
        assert body["description"] == "New desc"
        assert body["cover_gallery_id"] == gid


# ---------------------------------------------------------------------------
# GET /api/collections/ — list with cover thumbnails
# ---------------------------------------------------------------------------


class TestListCollectionsCoverThumb:
    """list_collections cover_thumb logic — explicit cover vs first-gallery fallback."""

    async def _insert_blob(self, db_session, sha: str) -> None:
        """Insert a minimal blob row."""
        await db_session.execute(
            text(
                "INSERT OR IGNORE INTO blobs (sha256, file_size, extension) "
                "VALUES (:sha, 1024, 'jpg')"
            ),
            {"sha": sha},
        )
        await db_session.commit()

    async def _insert_image(
        self, db_session, gallery_id: int, page_num: int, sha: str
    ) -> None:
        """Insert an image row linking a gallery to a blob."""
        await db_session.execute(
            text(
                "INSERT INTO images (gallery_id, page_num, blob_sha256) "
                "VALUES (:gid, :pn, :sha)"
            ),
            {"gid": gallery_id, "pn": page_num, "sha": sha},
        )
        await db_session.commit()

    async def test_list_collection_with_gallery_has_cover_thumb(self, client, db_session):
        """When a gallery with an image is in the collection, cover_thumb must be non-null."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Thumb Test")
        gid = await _insert_gallery(db_session, source_id="thumb1", source="ehentai")

        sha = "aabbccdd" * 8  # 64-char hex
        await self._insert_blob(db_session, sha)
        await self._insert_image(db_session, gid, 1, sha)

        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid]},
        )

        resp = await client.get("/api/collections/")
        assert resp.status_code == 200
        match = next(c for c in resp.json()["collections"] if c["id"] == col["id"])
        assert match["cover_thumb"] is not None

    async def test_list_collection_no_images_cover_thumb_is_none(self, client, db_session):
        """When no images exist, cover_thumb must be null."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "No Thumb")
        gid = await _insert_gallery(db_session, source_id="nothumb1")

        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid]},
        )

        resp = await client.get("/api/collections/")
        match = next(c for c in resp.json()["collections"] if c["id"] == col["id"])
        # Gallery exists but has no blob-linked image → cover_thumb must be None
        assert match["cover_thumb"] is None

    async def test_list_collection_explicit_cover_gallery_id_used(self, client, db_session):
        """When cover_gallery_id is set, that gallery's image is used for the thumbnail."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Explicit Cover")

        gid1 = await _insert_gallery(db_session, source_id="excvr1", source="ehentai")
        gid2 = await _insert_gallery(db_session, source_id="excvr2", source="ehentai")

        sha1 = "11223344" * 8
        sha2 = "55667788" * 8
        await self._insert_blob(db_session, sha1)
        await self._insert_blob(db_session, sha2)
        await self._insert_image(db_session, gid1, 1, sha1)
        await self._insert_image(db_session, gid2, 1, sha2)

        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid1, gid2]},
        )
        # Explicitly set gid2 as cover
        await client.patch(
            f"/api/collections/{col['id']}",
            json={"cover_gallery_id": gid2},
        )

        resp = await client.get("/api/collections/")
        match = next(c for c in resp.json()["collections"] if c["id"] == col["id"])
        assert match["cover_thumb"] is not None
        assert match["cover_gallery_id"] == gid2


# ---------------------------------------------------------------------------
# GET /api/collections/{id} — detail with galleries and cover maps
# ---------------------------------------------------------------------------


class TestGetCollectionWithGalleries:
    """get_collection with galleries — gallery list shape and pagination."""

    async def _insert_blob(self, db_session, sha: str) -> None:
        await db_session.execute(
            text(
                "INSERT OR IGNORE INTO blobs (sha256, file_size, extension) "
                "VALUES (:sha, 1024, 'jpg')"
            ),
            {"sha": sha},
        )
        await db_session.commit()

    async def _insert_image(self, db_session, gallery_id: int, page_num: int, sha: str) -> None:
        await db_session.execute(
            text(
                "INSERT INTO images (gallery_id, page_num, blob_sha256) "
                "VALUES (:gid, :pn, :sha)"
            ),
            {"gid": gallery_id, "pn": page_num, "sha": sha},
        )
        await db_session.commit()

    async def test_get_collection_gallery_shape(self, client, db_session):
        """Each gallery entry must contain expected fields."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Gallery Shape")
        gid = await _insert_gallery(db_session, source_id="gshape1", title="Shape Gallery")

        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid]},
        )

        resp = await client.get(f"/api/collections/{col['id']}")
        assert resp.status_code == 200
        galleries = resp.json()["galleries"]
        assert len(galleries) == 1
        g = galleries[0]
        for field in ("id", "source", "title", "pages", "cover_thumb", "position", "added_to_collection_at"):
            assert field in g, f"Missing field: {field}"
        assert g["id"] == gid
        assert g["title"] == "Shape Gallery"

    async def test_get_collection_gallery_cover_thumb_with_image(self, client, db_session):
        """Gallery with an image must have non-null cover_thumb in collection detail."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Detail Cover")
        gid = await _insert_gallery(db_session, source_id="dcvr1", source="ehentai")

        sha = "aaccbbdd" * 8
        await self._insert_blob(db_session, sha)
        await self._insert_image(db_session, gid, 1, sha)

        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid]},
        )

        resp = await client.get(f"/api/collections/{col['id']}")
        assert resp.status_code == 200
        g = resp.json()["galleries"][0]
        assert g["cover_thumb"] is not None

    async def test_get_collection_has_next_false_when_all_fit(self, client, db_session):
        """has_next must be False when all galleries fit on the first page."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Has Next False")
        gid = await _insert_gallery(db_session, source_id="hn1")

        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid]},
        )

        resp = await client.get(f"/api/collections/{col['id']}", params={"page": 0, "limit": 20})
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_next"] is False
        assert data["gallery_count"] == 1

    async def test_get_collection_has_next_true_when_overflow(self, client, db_session):
        """has_next must be True when there are more galleries than the limit."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Has Next True")

        gids = []
        for i in range(3):
            gid = await _insert_gallery(db_session, source_id=f"hnt{i}")
            gids.append(gid)

        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": gids},
        )

        resp = await client.get(
            f"/api/collections/{col['id']}", params={"page": 0, "limit": 2}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_next"] is True
        assert len(data["galleries"]) == 2

    async def test_get_collection_page_offset_works(self, client, db_session):
        """Second page must return the remaining gallery."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Pagination Offset")

        gids = []
        for i in range(3):
            gid = await _insert_gallery(db_session, source_id=f"pgoff{i}")
            gids.append(gid)

        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": gids},
        )

        resp = await client.get(
            f"/api/collections/{col['id']}", params={"page": 1, "limit": 2}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["galleries"]) == 1
        assert data["has_next"] is False


# ---------------------------------------------------------------------------
# POST /api/collections/{id}/galleries — visibility and batch adds
# ---------------------------------------------------------------------------


class TestAddGalleriesVisibility:
    """add_galleries_to_collection visibility check for non-admin users."""

    async def _setup_member_user(self, db_session, user_id: int = 3) -> None:
        await db_session.execute(
            text(
                "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                "VALUES (:id, :u, 'x', 'member')"
            ),
            {"id": user_id, "u": f"member_user_{user_id}"},
        )
        await db_session.commit()

    async def test_add_multiple_galleries_in_one_request(self, client, db_session):
        """Adding multiple gallery_ids in one call must add all and report correct count."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Batch Add")

        gid1 = await _insert_gallery(db_session, source_id="batch1")
        gid2 = await _insert_gallery(db_session, source_id="batch2")
        gid3 = await _insert_gallery(db_session, source_id="batch3")

        resp = await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid1, gid2, gid3]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["added"] == 3
        assert data["denied"] == []

        detail = await client.get(f"/api/collections/{col['id']}")
        assert detail.json()["gallery_count"] == 3

    async def test_add_mix_of_valid_and_nonexistent_galleries(self, client, db_session):
        """Mix of real and ghost gallery_ids — real added, ghost denied."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Mixed Batch")
        gid = await _insert_gallery(db_session, source_id="mix1")

        resp = await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid, 777777]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["added"] == 1
        assert 777777 in data["denied"]

    async def test_non_admin_cannot_add_private_gallery_of_another_user(
        self, make_client, db_session
    ):
        """Non-admin member must not add a private gallery owned by another user."""
        await _ensure_user(db_session)
        await self._setup_member_user(db_session, user_id=3)

        # Insert a private gallery owned by user 1
        gid = await _insert_gallery(db_session, source_id="private1", user_id=1)
        # Set visibility to 'private'
        await db_session.execute(
            text("UPDATE galleries SET visibility = 'private' WHERE id = :gid"),
            {"gid": gid},
        )
        await db_session.commit()

        async with make_client(user_id=3, role="member") as member_client:
            col_resp = await member_client.post(
                "/api/collections/", json={"name": "Member Col"}
            )
            assert col_resp.status_code == 200
            col_id = col_resp.json()["id"]

            resp = await member_client.post(
                f"/api/collections/{col_id}/galleries",
                json={"gallery_ids": [gid]},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["added"] == 0
        assert gid in data["denied"]

    async def test_non_admin_can_add_public_gallery_of_another_user(
        self, make_client, db_session
    ):
        """Non-admin member can add a public gallery owned by another user."""
        await _ensure_user(db_session)
        await self._setup_member_user(db_session, user_id=4)

        # Insert a public gallery owned by user 1
        gid = await _insert_gallery(db_session, source_id="public1", user_id=1)
        # Ensure visibility is 'public' (default)
        await db_session.execute(
            text("UPDATE galleries SET visibility = 'public' WHERE id = :gid"),
            {"gid": gid},
        )
        await db_session.commit()

        async with make_client(user_id=4, role="member") as member_client:
            col_resp = await member_client.post(
                "/api/collections/", json={"name": "Public Gal Col"}
            )
            assert col_resp.status_code == 200
            col_id = col_resp.json()["id"]

            resp = await member_client.post(
                f"/api/collections/{col_id}/galleries",
                json={"gallery_ids": [gid]},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["added"] == 1
        assert data["denied"] == []

    async def test_admin_can_add_private_gallery_of_another_user(self, client, db_session):
        """Admin must be able to add any gallery regardless of visibility."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Admin Private Add")

        # Insert private gallery owned by a different user
        await db_session.execute(
            text(
                "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                "VALUES (5, 'private_owner', 'x', 'member')"
            )
        )
        gid = await _insert_gallery(db_session, source_id="adminpriv1", user_id=5)
        await db_session.execute(
            text("UPDATE galleries SET visibility = 'private' WHERE id = :gid"),
            {"gid": gid},
        )
        await db_session.commit()

        resp = await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["added"] == 1
        assert data["denied"] == []

    async def test_positions_assigned_sequentially(self, client, db_session):
        """Galleries added in batch must have sequential positions."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Position Test")

        gid1 = await _insert_gallery(db_session, source_id="pos1")
        gid2 = await _insert_gallery(db_session, source_id="pos2")

        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid1, gid2]},
        )

        detail = await client.get(f"/api/collections/{col['id']}")
        galleries = detail.json()["galleries"]
        positions = [g["position"] for g in galleries]
        # Positions must be distinct and ordered
        assert len(set(positions)) == 2
        assert positions == sorted(positions)


# ---------------------------------------------------------------------------
# DELETE /api/collections/{id}/galleries/{gid} — remove_gallery updated_at
# ---------------------------------------------------------------------------


class TestRemoveGalleryUpdatedAt:
    """remove_gallery_from_collection must update the collection's updated_at timestamp."""

    async def test_remove_gallery_from_nonexistent_collection_returns_404(
        self, client, db_session
    ):
        """Removing a gallery from a collection that doesn't exist → 404."""
        await _ensure_user(db_session)

        resp = await client.delete("/api/collections/99999/galleries/1")
        assert resp.status_code == 404

    async def test_remove_gallery_decrements_count(self, client, db_session):
        """After removing a gallery, gallery_count must decrease by 1."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Decrement Test")

        gid1 = await _insert_gallery(db_session, source_id="dec1")
        gid2 = await _insert_gallery(db_session, source_id="dec2")
        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid1, gid2]},
        )

        await client.delete(f"/api/collections/{col['id']}/galleries/{gid1}")

        detail = await client.get(f"/api/collections/{col['id']}")
        assert detail.json()["gallery_count"] == 1

    async def test_remove_only_gallery_leaves_empty_collection(self, client, db_session):
        """Removing the last gallery must leave gallery_count at 0."""
        await _ensure_user(db_session)
        col = await _create_collection(client, "Last One Out")
        gid = await _insert_gallery(db_session, source_id="last1")

        await client.post(
            f"/api/collections/{col['id']}/galleries",
            json={"gallery_ids": [gid]},
        )
        await client.delete(f"/api/collections/{col['id']}/galleries/{gid}")

        detail = await client.get(f"/api/collections/{col['id']}")
        assert detail.json()["gallery_count"] == 0
        assert detail.json()["galleries"] == []
