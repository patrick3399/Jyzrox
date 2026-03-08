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
