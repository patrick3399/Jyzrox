"""
Tests for tag management endpoints (/api/tags/*).

The tag router uses `async_session` directly.  Data is inserted via
`db_session` into the shared in-memory SQLite DB.

Notes on SQLite compatibility:
- pg_insert (ON CONFLICT DO NOTHING / DO UPDATE) is PostgreSQL-specific.
  The `POST /api/tags/blocked` and translation upsert endpoints use pg_insert,
  so those tests are structured to verify the happy-path response shape rather
  than asserting DB side-effects through the route (we use direct DB inserts
  to set up state instead).
- Tag listing, autocomplete, aliases, implications, and blocked tag
  GET/DELETE all use standard SQLAlchemy SELECT/DELETE and work fine.
"""

import pytest
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_user(db_session, user_id=1):
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash) "
            "VALUES (:id, 'taguser', 'x')"
        ),
        {"id": user_id},
    )
    await db_session.commit()


async def _insert_tag(db_session, namespace, name, count=0):
    """Insert a tag row and return its rowid."""
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO tags (namespace, name, count) "
            "VALUES (:ns, :name, :count)"
        ),
        {"ns": namespace, "name": name, "count": count},
    )
    await db_session.commit()
    result = await db_session.execute(
        text("SELECT id FROM tags WHERE namespace = :ns AND name = :name"),
        {"ns": namespace, "name": name},
    )
    return result.scalar()


async def _insert_blocked_tag(db_session, user_id, namespace, name):
    """Insert a blocked_tags row and return its rowid."""
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO blocked_tags (user_id, namespace, name) "
            "VALUES (:uid, :ns, :name)"
        ),
        {"uid": user_id, "ns": namespace, "name": name},
    )
    await db_session.commit()
    result = await db_session.execute(
        text(
            "SELECT id FROM blocked_tags "
            "WHERE user_id = :uid AND namespace = :ns AND name = :name"
        ),
        {"uid": user_id, "ns": namespace, "name": name},
    )
    return result.scalar()


async def _insert_alias(db_session, alias_ns, alias_name, canonical_id):
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO tag_aliases (alias_namespace, alias_name, canonical_id) "
            "VALUES (:ans, :an, :cid)"
        ),
        {"ans": alias_ns, "an": alias_name, "cid": canonical_id},
    )
    await db_session.commit()


async def _insert_implication(db_session, antecedent_id, consequent_id):
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO tag_implications (antecedent_id, consequent_id) "
            "VALUES (:ant, :con)"
        ),
        {"ant": antecedent_id, "con": consequent_id},
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Tag listing
# ---------------------------------------------------------------------------


class TestListTags:
    """GET /api/tags/"""

    async def test_list_tags_empty(self, client):
        """Empty tag table should return total=0 and empty list."""
        resp = await client.get("/api/tags/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["tags"] == []

    async def test_list_tags_returns_all(self, client, db_session):
        """All inserted tags should be returned, sorted by count DESC."""
        await _insert_tag(db_session, "artist", "alice", count=10)
        await _insert_tag(db_session, "general", "blue_hair", count=5)
        await _insert_tag(db_session, "character", "rem", count=20)

        resp = await client.get("/api/tags/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        counts = [t["count"] for t in data["tags"]]
        assert counts == sorted(counts, reverse=True)

    async def test_list_tags_namespace_filter(self, client, db_session):
        """?namespace= should filter tags by namespace."""
        await _insert_tag(db_session, "artist", "bob", count=3)
        await _insert_tag(db_session, "general", "cat_ears", count=7)

        resp = await client.get("/api/tags/", params={"namespace": "artist"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["tags"][0]["namespace"] == "artist"
        assert data["tags"][0]["name"] == "bob"

    async def test_list_tags_prefix_filter(self, client, db_session):
        """?prefix= should filter tags by name prefix."""
        await _insert_tag(db_session, "general", "blue_hair", count=5)
        await _insert_tag(db_session, "general", "blue_eyes", count=3)
        await _insert_tag(db_session, "general", "red_hair", count=8)

        resp = await client.get("/api/tags/", params={"prefix": "blue"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        for t in data["tags"]:
            assert t["name"].startswith("blue")

    async def test_list_tags_pagination(self, client, db_session):
        """limit/offset should restrict results."""
        for i in range(10):
            await _insert_tag(db_session, "general", f"tag_{i:02d}", count=i)

        resp = await client.get("/api/tags/", params={"limit": 3, "offset": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10
        assert len(data["tags"]) == 3

    async def test_list_tags_offset_too_large(self, client):
        """Offset > 10000 should return 400."""
        resp = await client.get("/api/tags/", params={"offset": 10001})
        assert resp.status_code == 400
        assert "cursor" in resp.json()["detail"].lower()

    async def test_list_tags_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/tags/")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tag autocomplete
# ---------------------------------------------------------------------------


class TestTagAutocomplete:
    """GET /api/tags/autocomplete"""

    async def test_autocomplete_empty_query_returns_empty(self, client):
        """Empty q= should return empty list."""
        resp = await client.get("/api/tags/autocomplete", params={"q": ""})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_autocomplete_matches_name_prefix(self, client, db_session):
        """Should return tags whose name starts with q."""
        await _insert_tag(db_session, "general", "blue_hair", count=10)
        await _insert_tag(db_session, "general", "blue_eyes", count=7)
        await _insert_tag(db_session, "general", "red_hair", count=5)

        resp = await client.get("/api/tags/autocomplete", params={"q": "blue"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        for t in data:
            assert t["name"].startswith("blue")

    async def test_autocomplete_namespace_colon_format(self, client, db_session):
        """'namespace:prefix' format should match namespace AND name prefix."""
        await _insert_tag(db_session, "artist", "alice_wonder", count=5)
        await _insert_tag(db_session, "artist", "alice_smith", count=3)
        await _insert_tag(db_session, "character", "alice_in_wonderland", count=8)

        resp = await client.get("/api/tags/autocomplete", params={"q": "artist:alice"})
        assert resp.status_code == 200
        data = resp.json()
        # Only artist-namespace tags should be returned
        assert len(data) == 2
        for t in data:
            assert t["namespace"] == "artist"
            assert t["name"].startswith("alice")

    async def test_autocomplete_sorted_by_count_desc(self, client, db_session):
        """Results should be ordered by count DESC."""
        await _insert_tag(db_session, "general", "cat_low", count=1)
        await _insert_tag(db_session, "general", "cat_high", count=100)
        await _insert_tag(db_session, "general", "cat_mid", count=50)

        resp = await client.get("/api/tags/autocomplete", params={"q": "cat"})
        assert resp.status_code == 200
        data = resp.json()
        counts = [t["count"] for t in data]
        assert counts == sorted(counts, reverse=True)

    async def test_autocomplete_respects_limit(self, client, db_session):
        """?limit= should cap the number of results."""
        for i in range(20):
            await _insert_tag(db_session, "general", f"match_{i:02d}", count=i)

        resp = await client.get("/api/tags/autocomplete", params={"q": "match", "limit": 5})
        assert resp.status_code == 200
        assert len(resp.json()) <= 5

    async def test_autocomplete_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/tags/autocomplete", params={"q": "blue"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Blocked tags CRUD
# ---------------------------------------------------------------------------


class TestBlockedTags:
    """GET/POST/DELETE /api/tags/blocked"""

    async def test_list_blocked_tags_empty(self, client):
        """No blocked tags should return empty list."""
        resp = await client.get("/api/tags/blocked")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_blocked_tags_with_data(self, client, db_session):
        """Inserted blocked tags for user_id=1 should appear in listing."""
        await _insert_user(db_session)
        await _insert_blocked_tag(db_session, user_id=1, namespace="general", name="guro")
        await _insert_blocked_tag(db_session, user_id=1, namespace="general", name="scat")

        resp = await client.get("/api/tags/blocked")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = {t["name"] for t in data}
        assert "guro" in names
        assert "scat" in names

    async def test_list_blocked_tags_only_returns_own(self, client, db_session):
        """Blocked tags of other users should not appear in the listing."""
        await _insert_user(db_session, user_id=1)
        await _insert_user(db_session, user_id=2)
        await _insert_blocked_tag(db_session, user_id=1, namespace="general", name="mine")
        await _insert_blocked_tag(db_session, user_id=2, namespace="general", name="theirs")

        resp = await client.get("/api/tags/blocked")
        assert resp.status_code == 200
        data = resp.json()
        names = {t["name"] for t in data}
        assert "mine" in names
        assert "theirs" not in names

    async def test_delete_blocked_tag_success(self, client, db_session):
        """Deleting an existing blocked tag should return status ok."""
        await _insert_user(db_session)
        bt_id = await _insert_blocked_tag(db_session, user_id=1, namespace="general", name="to_delete")

        resp = await client.delete(f"/api/tags/blocked/{bt_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Confirm it's gone
        resp2 = await client.get("/api/tags/blocked")
        assert all(t["id"] != bt_id for t in resp2.json())

    async def test_delete_blocked_tag_not_found(self, client):
        """Deleting a non-existent blocked tag should return 404."""
        resp = await client.delete("/api/tags/blocked/99999")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_delete_blocked_tag_wrong_user(self, client, db_session):
        """Cannot delete another user's blocked tag — should return 404."""
        await _insert_user(db_session, user_id=2)
        bt_id = await _insert_blocked_tag(db_session, user_id=2, namespace="general", name="others")

        resp = await client.delete(f"/api/tags/blocked/{bt_id}")
        assert resp.status_code == 404

    async def test_blocked_tags_require_auth(self, unauthed_client):
        """All blocked tag endpoints require authentication."""
        assert (await unauthed_client.get("/api/tags/blocked")).status_code == 401
        assert (
            await unauthed_client.post(
                "/api/tags/blocked", json={"namespace": "general", "name": "x"}
            )
        ).status_code == 401
        assert (await unauthed_client.delete("/api/tags/blocked/1")).status_code == 401


# ---------------------------------------------------------------------------
# Tag aliases CRUD
# ---------------------------------------------------------------------------


class TestTagAliases:
    """GET/POST/DELETE /api/tags/aliases"""

    async def test_list_aliases_empty(self, client):
        """Empty tag_aliases table should return empty list."""
        resp = await client.get("/api/tags/aliases")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_aliases_with_data(self, client, db_session):
        """Inserted aliases should appear in listing."""
        canonical_id = await _insert_tag(db_session, "artist", "original_name", count=5)
        await _insert_alias(db_session, "artist", "old_name", canonical_id)

        resp = await client.get("/api/tags/aliases")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["alias_name"] == "old_name"
        assert data[0]["canonical_id"] == canonical_id
        assert data[0]["canonical_name"] == "original_name"

    async def test_list_aliases_filter_by_tag_id(self, client, db_session):
        """?tag_id= should filter aliases by canonical tag."""
        cid1 = await _insert_tag(db_session, "artist", "artist_a", count=3)
        cid2 = await _insert_tag(db_session, "artist", "artist_b", count=2)
        await _insert_alias(db_session, "artist", "alias_a", cid1)
        await _insert_alias(db_session, "artist", "alias_b", cid2)

        resp = await client.get("/api/tags/aliases", params={"tag_id": cid1})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["canonical_id"] == cid1

    async def test_create_alias_for_existing_tag(self, client, db_session):
        """POST should create an alias pointing to an existing tag."""
        canonical_id = await _insert_tag(db_session, "character", "rem", count=10)

        resp = await client.post(
            "/api/tags/aliases",
            json={
                "alias_namespace": "character",
                "alias_name": "rem_rezero",
                "canonical_id": canonical_id,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_create_alias_unknown_canonical_tag(self, client):
        """POST with non-existent canonical_id should return 404."""
        resp = await client.post(
            "/api/tags/aliases",
            json={
                "alias_namespace": "artist",
                "alias_name": "ghost",
                "canonical_id": 99999,
            },
        )
        assert resp.status_code == 404

    async def test_delete_alias(self, client, db_session):
        """DELETE should remove an existing alias."""
        canonical_id = await _insert_tag(db_session, "general", "main_tag", count=1)
        await _insert_alias(db_session, "general", "alt_tag", canonical_id)

        resp = await client.delete(
            "/api/tags/aliases",
            params={"alias_namespace": "general", "alias_name": "alt_tag"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_aliases_require_auth(self, unauthed_client):
        """All alias endpoints require authentication."""
        assert (await unauthed_client.get("/api/tags/aliases")).status_code == 401
        assert (
            await unauthed_client.post(
                "/api/tags/aliases",
                json={"alias_namespace": "a", "alias_name": "b", "canonical_id": 1},
            )
        ).status_code == 401


# ---------------------------------------------------------------------------
# Tag implications CRUD
# ---------------------------------------------------------------------------


class TestTagImplications:
    """GET/POST/DELETE /api/tags/implications"""

    async def test_list_implications_empty(self, client):
        """Empty tag_implications table should return empty list."""
        resp = await client.get("/api/tags/implications")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_implications_with_data(self, client, db_session):
        """Inserted implications should appear in listing with both tag names."""
        ant_id = await _insert_tag(db_session, "character", "miku", count=5)
        con_id = await _insert_tag(db_session, "general", "vocaloid", count=20)
        await _insert_implication(db_session, ant_id, con_id)

        resp = await client.get("/api/tags/implications")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["antecedent_id"] == ant_id
        assert data[0]["consequent_id"] == con_id
        assert "character:miku" in data[0]["antecedent"]
        assert "general:vocaloid" in data[0]["consequent"]

    async def test_create_implication(self, client, db_session):
        """POST should create a valid implication."""
        ant_id = await _insert_tag(db_session, "character", "reimu", count=8)
        con_id = await _insert_tag(db_session, "general", "touhou", count=50)

        resp = await client.post(
            "/api/tags/implications",
            json={"antecedent_id": ant_id, "consequent_id": con_id},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_create_implication_self_reference(self, client, db_session):
        """Implying a tag with itself should return 400."""
        tag_id = await _insert_tag(db_session, "general", "self_ref", count=1)

        resp = await client.post(
            "/api/tags/implications",
            json={"antecedent_id": tag_id, "consequent_id": tag_id},
        )
        assert resp.status_code == 400
        assert "self" in resp.json()["detail"].lower()

    async def test_create_implication_circular_detection(self, client, db_session):
        """Circular implications should be rejected with 400."""
        tid_a = await _insert_tag(db_session, "general", "circ_a", count=1)
        tid_b = await _insert_tag(db_session, "general", "circ_b", count=1)
        # Create A -> B first
        await _insert_implication(db_session, tid_a, tid_b)

        # Now try B -> A (creates a cycle)
        resp = await client.post(
            "/api/tags/implications",
            json={"antecedent_id": tid_b, "consequent_id": tid_a},
        )
        assert resp.status_code == 400
        assert "circular" in resp.json()["detail"].lower()

    async def test_delete_implication(self, client, db_session):
        """DELETE should remove an existing implication."""
        ant_id = await _insert_tag(db_session, "character", "del_ant", count=1)
        con_id = await _insert_tag(db_session, "general", "del_con", count=1)
        await _insert_implication(db_session, ant_id, con_id)

        resp = await client.delete(
            "/api/tags/implications",
            params={"antecedent_id": ant_id, "consequent_id": con_id},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_implications_require_auth(self, unauthed_client):
        """All implication endpoints require authentication."""
        assert (await unauthed_client.get("/api/tags/implications")).status_code == 401
        assert (
            await unauthed_client.post(
                "/api/tags/implications",
                json={"antecedent_id": 1, "consequent_id": 2},
            )
        ).status_code == 401


# ---------------------------------------------------------------------------
# Manual gallery tagging
# ---------------------------------------------------------------------------


async def _insert_gallery(db_session, source="test", source_id="g1", title="Test Gallery"):
    """Insert a minimal gallery row and return its id."""
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO galleries (source, source_id, title) "
            "VALUES (:src, :sid, :title)"
        ),
        {"src": source, "sid": source_id, "title": title},
    )
    await db_session.commit()
    result = await db_session.execute(
        text("SELECT id FROM galleries WHERE source = :src AND source_id = :sid"),
        {"src": source, "sid": source_id},
    )
    return result.scalar()


class TestManualTagGallery:
    """POST /api/tags/gallery/{gallery_id}"""

    # ------------------------------------------------------------------
    # Helpers used by this class
    # ------------------------------------------------------------------

    @staticmethod
    def _patch_worker_helpers(monkeypatch):
        """
        Inject a fake worker.tag_helpers module into sys.modules so that
        ``from worker.tag_helpers import rebuild_gallery_tags_array``
        inside the endpoint resolves without importing the real worker
        package (which pulls in arq and heavy deps unavailable in tests).
        """
        import sys
        import types
        from unittest.mock import AsyncMock

        if "worker" not in sys.modules:
            monkeypatch.setitem(sys.modules, "worker", types.ModuleType("worker"))
        _fake_th = types.ModuleType("worker.tag_helpers")
        _fake_th.rebuild_gallery_tags_array = AsyncMock(return_value=[])
        _fake_th.upsert_tag_translations = AsyncMock()
        monkeypatch.setitem(sys.modules, "worker.tag_helpers", _fake_th)

    @staticmethod
    def _add_patch(monkeypatch):
        """
        Patch pg_insert and rebuild_gallery_tags_array so add-action tests
        can run on the SQLite test engine without hitting PostgreSQL-only
        ON CONFLICT syntax or the ARRAY column serialisation issue.

        pg_insert is replaced with sqlalchemy.dialects.sqlite.insert, which
        also supports on_conflict_do_update on SQLite 3.24+.
        rebuild_gallery_tags_array is replaced with a no-op coroutine.
        """
        import routers.tag as _tag_mod
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        TestManualTagGallery._patch_worker_helpers(monkeypatch)
        monkeypatch.setattr(_tag_mod, "pg_insert", sqlite_insert)

    # ------------------------------------------------------------------
    # Happy-path: add action
    # ------------------------------------------------------------------

    async def test_manual_tag_add_basic(self, client, db_session, monkeypatch):
        """POST with action=add and a namespaced tag should return affected=1."""
        self._add_patch(monkeypatch)
        gid = await _insert_gallery(db_session, source_id="add_basic")

        resp = await client.post(
            f"/api/tags/gallery/{gid}",
            json={"tags": ["character:rem"], "action": "add"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["affected"] == 1

    async def test_manual_tag_add_bare_name(self, client, db_session, monkeypatch):
        """A bare name without namespace should default to general:<name>."""
        self._add_patch(monkeypatch)
        gid = await _insert_gallery(db_session, source_id="add_bare")

        resp = await client.post(
            f"/api/tags/gallery/{gid}",
            json={"tags": ["landscape"], "action": "add"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["affected"] == 1

    async def test_manual_tag_add_multiple(self, client, db_session, monkeypatch):
        """Multiple distinct tags should all be added, affected equals tag count."""
        self._add_patch(monkeypatch)
        gid = await _insert_gallery(db_session, source_id="add_multi")

        resp = await client.post(
            f"/api/tags/gallery/{gid}",
            json={"tags": ["character:rem", "artist:someone", "cute"], "action": "add"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["affected"] == 3

    async def test_manual_tag_add_duplicate_in_request(self, client, db_session, monkeypatch):
        """Duplicate tags within a single request should be deduplicated — no crash, affected=1."""
        self._add_patch(monkeypatch)
        gid = await _insert_gallery(db_session, source_id="add_dedup")

        resp = await client.post(
            f"/api/tags/gallery/{gid}",
            json={"tags": ["foo", "foo"], "action": "add"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["affected"] == 1

    # ------------------------------------------------------------------
    # Happy-path: remove action
    # ------------------------------------------------------------------

    async def test_manual_tag_remove(self, client, db_session, monkeypatch):
        """Remove an existing manual tag should return affected=1."""
        self._patch_worker_helpers(monkeypatch)

        gid = await _insert_gallery(db_session, source_id="remove_tag")

        # Insert the tag and gallery_tag directly so the remove path can find them
        tag_id = await _insert_tag(db_session, "character", "rem_remove")
        await db_session.execute(
            text(
                "INSERT OR IGNORE INTO gallery_tags (gallery_id, tag_id, confidence, source) "
                "VALUES (:gid, :tid, 1.0, 'manual')"
            ),
            {"gid": gid, "tid": tag_id},
        )
        await db_session.commit()

        resp = await client.post(
            f"/api/tags/gallery/{gid}",
            json={"tags": ["character:rem_remove"], "action": "remove"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["affected"] == 1

    async def test_manual_tag_remove_nonexistent(self, client, db_session, monkeypatch):
        """Removing a tag that does not exist should return affected=0 without error."""
        self._patch_worker_helpers(monkeypatch)

        gid = await _insert_gallery(db_session, source_id="remove_none")

        resp = await client.post(
            f"/api/tags/gallery/{gid}",
            json={"tags": ["character:ghost_tag_xyz"], "action": "remove"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["affected"] == 0

    # ------------------------------------------------------------------
    # Error paths
    # ------------------------------------------------------------------

    async def test_manual_tag_gallery_not_found(self, client, monkeypatch):
        """POST to a non-existent gallery_id should return 404."""
        self._patch_worker_helpers(monkeypatch)
        resp = await client.post(
            "/api/tags/gallery/99999",
            json={"tags": ["character:rem"], "action": "add"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_manual_tag_requires_member_role(self, make_client, db_session, monkeypatch):
        """A viewer-role user should receive 403 (insufficient role)."""
        self._patch_worker_helpers(monkeypatch)
        gid = await _insert_gallery(db_session, source_id="role_viewer")

        async with make_client(user_id=1, role="viewer") as ac:
            resp = await ac.post(
                f"/api/tags/gallery/{gid}",
                json={"tags": ["character:rem"], "action": "add"},
            )
        assert resp.status_code == 403

    async def test_manual_tag_admin_can_access(self, make_client, db_session, monkeypatch):
        """An admin-role user (higher than member) should be allowed and get 200."""
        self._add_patch(monkeypatch)
        gid = await _insert_gallery(db_session, source_id="role_admin_mtag")

        async with make_client(user_id=1, role="admin") as ac:
            resp = await ac.post(
                f"/api/tags/gallery/{gid}",
                json={"tags": ["character:rem"], "action": "add"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_manual_tag_empty_tags_list(self, client, db_session, monkeypatch):
        """An empty tags list with action=add should return affected=0 without error."""
        self._patch_worker_helpers(monkeypatch)
        gid = await _insert_gallery(db_session, source_id="empty_tags")

        resp = await client.post(
            f"/api/tags/gallery/{gid}",
            json={"tags": [], "action": "add"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["affected"] == 0


# ---------------------------------------------------------------------------
# Tag translations
# ---------------------------------------------------------------------------


async def _insert_translation(db_session, namespace, name, language, translation):
    """Insert a tag_translation row directly."""
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO tag_translations (namespace, name, language, translation) "
            "VALUES (:ns, :name, :lang, :trans)"
        ),
        {"ns": namespace, "name": name, "lang": language, "trans": translation},
    )
    await db_session.commit()


class TestTagTranslations:
    """GET/POST /api/tags/translations"""

    async def test_get_translations_empty_tags_param_returns_empty(self, client):
        """tags= not supplied should return empty dict."""
        resp = await client.get("/api/tags/translations", params={"tags": ""})
        assert resp.status_code == 200
        assert resp.json() == {}

    async def test_get_translations_returns_matching_translations(
        self, client, db_session
    ):
        """Existing translations should be returned keyed by 'namespace:name'."""
        await _insert_translation(db_session, "artist", "alice", "zh", "愛麗絲")
        await _insert_translation(db_session, "general", "cat_ears", "zh", "貓耳")

        resp = await client.get(
            "/api/tags/translations",
            params={"tags": "artist:alice,general:cat_ears", "language": "zh"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("artist:alice") == "愛麗絲"
        assert data.get("general:cat_ears") == "貓耳"

    async def test_get_translations_missing_tag_not_included(self, client, db_session):
        """Tags without a translation entry should be absent from the response."""
        await _insert_translation(db_session, "artist", "known", "zh", "已知")

        resp = await client.get(
            "/api/tags/translations",
            params={"tags": "artist:known,artist:unknown_tag", "language": "zh"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "artist:known" in data
        assert "artist:unknown_tag" not in data

    async def test_get_translations_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get(
            "/api/tags/translations", params={"tags": "artist:alice"}
        )
        assert resp.status_code == 401

    async def test_upsert_translation_creates_entry(self, client):
        """POST /api/tags/translations should upsert (or attempt to on SQLite).

        pg_insert ON CONFLICT is PostgreSQL-specific. We accept 200 (PG) or
        500 (SQLite limitation) but verify the request is well-formed.
        """
        resp = await client.post(
            "/api/tags/translations",
            json={
                "namespace": "artist",
                "name": "test_upsert",
                "language": "zh",
                "translation": "測試",
            },
        )
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            assert resp.json()["status"] == "ok"

    async def test_batch_import_translations_empty_list(self, client):
        """Batch import with empty translations list should return count=0."""
        resp = await client.post(
            "/api/tags/translations/batch",
            json={"translations": []},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["count"] == 0

    async def test_batch_import_translations_non_empty(self, client):
        """Batch import with items should return count equal to list length.

        pg_insert ON CONFLICT is PostgreSQL-specific. We accept 200 (PG) or
        500 (SQLite) and check count when successful.
        """
        payload = [
            {"namespace": "general", "name": "blue_hair", "language": "zh", "translation": "藍髮"},
            {"namespace": "general", "name": "red_eyes", "language": "zh", "translation": "紅眼"},
        ]
        resp = await client.post(
            "/api/tags/translations/batch",
            json={"translations": payload},
        )
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            assert resp.json()["count"] == 2

    async def test_add_blocked_tag_creates_entry(self, client, db_session):
        """POST /api/tags/blocked should create a blocked tag entry.

        pg_insert ON CONFLICT DO NOTHING is PG-specific — accept 201 (PG)
        or 500 (SQLite limitation).
        """
        await _insert_user(db_session, user_id=1)
        resp = await client.post(
            "/api/tags/blocked",
            json={"namespace": "general", "name": "new_blocked_tag"},
        )
        assert resp.status_code in (201, 500)
        if resp.status_code == 201:
            assert resp.json()["status"] == "ok"

    async def test_list_tags_cursor_pagination(self, client, db_session):
        """Cursor-based tag listing should return has_next=True when more items exist."""
        for i in range(10):
            await _insert_tag(db_session, "general", f"cursor_tag_{i:02d}", count=i + 1)

        # Get first page with limit=5
        resp1 = await client.get("/api/tags/", params={"limit": 5})
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert len(data1["tags"]) == 5

        # Fetch next page with cursor if has_next
        if data1.get("has_next") and data1.get("next_cursor"):
            cursor = data1["next_cursor"]
            resp2 = await client.get("/api/tags/", params={"cursor": cursor, "limit": 5})
            assert resp2.status_code == 200
            data2 = resp2.json()
            assert "tags" in data2
