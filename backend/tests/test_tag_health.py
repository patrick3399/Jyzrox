"""
Tests for the Tag Health Report endpoints (/api/tags/health/*, DELETE /api/tags/{id}).

Follows the same SQLite raw-SQL insertion pattern as test_tag.py.

Redis for these endpoints is accessed via `routers.tag.get_redis`, a name
bound at import time via `from core.redis_client import get_redis`. Patching
`core.redis_client.get_redis` (done globally by the `client`/`make_client`
fixtures) does NOT affect this already-bound name, so each test that hits
Redis-backed logic patches `routers.tag.get_redis` directly.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_tag(db_session, namespace, name, count=0):
    """Insert a tag row and return its id."""
    await db_session.execute(
        text("INSERT OR IGNORE INTO tags (namespace, name, count) VALUES (:ns, :name, :count)"),
        {"ns": namespace, "name": name, "count": count},
    )
    await db_session.commit()
    result = await db_session.execute(
        text("SELECT id FROM tags WHERE namespace = :ns AND name = :name"),
        {"ns": namespace, "name": name},
    )
    return result.scalar()


async def _insert_alias(db_session, alias_ns, alias_name, canonical_id):
    await db_session.execute(
        text("INSERT OR IGNORE INTO tag_aliases (alias_namespace, alias_name, canonical_id) VALUES (:ans, :an, :cid)"),
        {"ans": alias_ns, "an": alias_name, "cid": canonical_id},
    )
    await db_session.commit()


async def _insert_implication(db_session, antecedent_id, consequent_id):
    await db_session.execute(
        text("INSERT OR IGNORE INTO tag_implications (antecedent_id, consequent_id) VALUES (:ant, :con)"),
        {"ant": antecedent_id, "con": consequent_id},
    )
    await db_session.commit()


async def _insert_gallery(db_session, source="test", source_id="g1", title="Test Gallery"):
    await db_session.execute(
        text("INSERT OR IGNORE INTO galleries (source, source_id, title) VALUES (:src, :sid, :title)"),
        {"src": source, "sid": source_id, "title": title},
    )
    await db_session.commit()
    result = await db_session.execute(
        text("SELECT id FROM galleries WHERE source = :src AND source_id = :sid"),
        {"src": source, "sid": source_id},
    )
    return result.scalar()


async def _insert_gallery_tag(db_session, gallery_id, tag_id, source="metadata"):
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO gallery_tags (gallery_id, tag_id, confidence, source) VALUES (:gid, :tid, 1.0, :src)"
        ),
        {"gid": gallery_id, "tid": tag_id, "src": source},
    )
    await db_session.commit()


async def _insert_image(db_session, gallery_id, page_num=1, filename="001.jpg"):
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO blobs (sha256, file_size, extension, storage) VALUES ('sha_health', 1, '.jpg', 'cas')"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, blob_sha256) VALUES (:gid, :page, :fn, 'sha_health')"
        ),
        {"gid": gallery_id, "page": page_num, "fn": filename},
    )
    await db_session.commit()
    result = await db_session.execute(
        text("SELECT id FROM images WHERE gallery_id = :gid AND page_num = :page"),
        {"gid": gallery_id, "page": page_num},
    )
    return result.scalar()


def _mock_redis_with_ignored(ignored_keys=None):
    """Return an AsyncMock redis client whose smembers() returns the given
    byte-encoded ignore keys (simulating real redis decode_responses=False)."""
    r = AsyncMock()
    r.smembers = AsyncMock(return_value={k.encode() for k in (ignored_keys or [])})
    r.sadd = AsyncMock(return_value=1)
    r.srem = AsyncMock(return_value=1)
    return r


# ---------------------------------------------------------------------------
# GET /api/tags/health — orphans
# ---------------------------------------------------------------------------


class TestTagHealthOrphans:
    async def test_health_orphan_includes_isolated_zero_count_tag(self, client, db_session):
        """A zero-count tag with no alias/implication references should be reported as orphan."""
        tid = await _insert_tag(db_session, "general", "isolated_orphan", count=0)

        with patch("routers.tag.get_redis", return_value=_mock_redis_with_ignored()):
            resp = await client.get("/api/tags/health")

        assert resp.status_code == 200
        data = resp.json()
        orphan_ids = {o["id"] for o in data["orphans"]}
        assert tid in orphan_ids
        assert data["orphans_total"] >= 1

    async def test_health_orphan_excludes_nonzero_count_tag(self, client, db_session):
        """A tag with count > 0 must never be reported as orphan even with no references."""
        tid = await _insert_tag(db_session, "general", "has_usages", count=5)

        with patch("routers.tag.get_redis", return_value=_mock_redis_with_ignored()):
            resp = await client.get("/api/tags/health")

        assert resp.status_code == 200
        orphan_ids = {o["id"] for o in resp.json()["orphans"]}
        assert tid not in orphan_ids

    async def test_health_orphan_excludes_alias_canonical_target(self, client, db_session):
        """A zero-count tag that is the canonical target of an alias must NOT be an orphan."""
        canonical_id = await _insert_tag(db_session, "general", "alias_target", count=0)
        await _insert_alias(db_session, "general", "alias_target_old_name", canonical_id)

        with patch("routers.tag.get_redis", return_value=_mock_redis_with_ignored()):
            resp = await client.get("/api/tags/health")

        assert resp.status_code == 200
        orphan_ids = {o["id"] for o in resp.json()["orphans"]}
        assert canonical_id not in orphan_ids

    async def test_health_orphan_excludes_implication_antecedent_and_consequent(self, client, db_session):
        """Zero-count tags participating in an implication (either side) must NOT be orphans."""
        ant_id = await _insert_tag(db_session, "general", "impl_ant", count=0)
        con_id = await _insert_tag(db_session, "general", "impl_con", count=0)
        await _insert_implication(db_session, ant_id, con_id)

        with patch("routers.tag.get_redis", return_value=_mock_redis_with_ignored()):
            resp = await client.get("/api/tags/health")

        assert resp.status_code == 200
        orphan_ids = {o["id"] for o in resp.json()["orphans"]}
        assert ant_id not in orphan_ids
        assert con_id not in orphan_ids

    async def test_health_orphan_limit_caps_list_but_not_total(self, client, db_session):
        """?limit= should cap the returned orphans list without affecting orphans_total."""
        for i in range(5):
            await _insert_tag(db_session, "general", f"orphan_limit_{i:02d}", count=0)

        with patch("routers.tag.get_redis", return_value=_mock_redis_with_ignored()):
            resp = await client.get("/api/tags/health", params={"limit": 2})

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["orphans"]) == 2
        assert data["orphans_total"] >= 5

    async def test_health_requires_admin(self, make_client):
        """A viewer-role user should receive 403 for GET /health."""
        async with make_client(user_id=1, role="viewer") as ac:
            resp = await ac.get("/api/tags/health")
        assert resp.status_code == 403

    async def test_health_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/tags/health")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/tags/health — duplicates
# ---------------------------------------------------------------------------


class TestTagHealthDuplicates:
    async def test_health_duplicates_groups_by_normalized_name(self, client, db_session):
        """Tags whose normalized name (lower + strip _/-/space) collide within the
        same namespace should be grouped, sorted by count desc within the group."""
        await _insert_tag(db_session, "general", "blue_hair", count=10)
        await _insert_tag(db_session, "general", "blue-hair", count=2)
        await _insert_tag(db_session, "general", "blue hair", count=1)

        with patch("routers.tag.get_redis", return_value=_mock_redis_with_ignored()):
            resp = await client.get("/api/tags/health")

        assert resp.status_code == 200
        data = resp.json()
        group = next((g for g in data["duplicates"] if g["key"] == "general:bluehair"), None)
        assert group is not None
        assert len(group["tags"]) == 3
        counts = [t["count"] for t in group["tags"]]
        assert counts == sorted(counts, reverse=True)

    async def test_health_duplicates_requires_at_least_two_members(self, client, db_session):
        """A namespace/normalized-name combo with only one tag must not appear as a duplicate group."""
        await _insert_tag(db_session, "general", "totally_unique_name", count=5)

        with patch("routers.tag.get_redis", return_value=_mock_redis_with_ignored()):
            resp = await client.get("/api/tags/health")

        assert resp.status_code == 200
        keys = {g["key"] for g in resp.json()["duplicates"]}
        assert "general:totallyuniquename" not in keys

    async def test_health_duplicates_respects_namespace_boundary(self, client, db_session):
        """Same normalized name in different namespaces must NOT be grouped together."""
        await _insert_tag(db_session, "general", "cat", count=5)
        await _insert_tag(db_session, "artist", "cat", count=3)

        with patch("routers.tag.get_redis", return_value=_mock_redis_with_ignored()):
            resp = await client.get("/api/tags/health")

        assert resp.status_code == 200
        keys = {g["key"] for g in resp.json()["duplicates"]}
        assert "general:cat" not in keys
        assert "artist:cat" not in keys


# ---------------------------------------------------------------------------
# GET /api/tags/health — implication cycles
# ---------------------------------------------------------------------------


class TestTagHealthImplicationCycles:
    async def test_health_cycle_self_loop_detected(self, client, db_session):
        """A self-referencing implication (a -> a) must be reported as a 1-node cycle."""
        tid = await _insert_tag(db_session, "general", "self_loop_tag", count=1)
        await _insert_implication(db_session, tid, tid)

        with patch("routers.tag.get_redis", return_value=_mock_redis_with_ignored()):
            resp = await client.get("/api/tags/health")

        assert resp.status_code == 200
        data = resp.json()
        cycle = next((c for c in data["implication_cycles"] if c["key"] == str(tid)), None)
        assert cycle is not None
        assert [n["id"] for n in cycle["path"]] == [tid]

    async def test_health_cycle_two_node_a_b_a_detected(self, client, db_session):
        """A -> B and B -> A must be reported as a single 2-node cycle, deduplicated."""
        tid_a = await _insert_tag(db_session, "general", "cycle_ab_a", count=1)
        tid_b = await _insert_tag(db_session, "general", "cycle_ab_b", count=1)
        await _insert_implication(db_session, tid_a, tid_b)
        await _insert_implication(db_session, tid_b, tid_a)

        with patch("routers.tag.get_redis", return_value=_mock_redis_with_ignored()):
            resp = await client.get("/api/tags/health")

        assert resp.status_code == 200
        expected_key = "-".join(str(x) for x in sorted([tid_a, tid_b]))
        cycles = resp.json()["implication_cycles"]
        matches = [c for c in cycles if c["key"] == expected_key]
        assert len(matches) == 1
        assert {n["id"] for n in matches[0]["path"]} == {tid_a, tid_b}

    async def test_health_cycle_three_node_chain_detected(self, client, db_session):
        """A -> B -> C -> A must be reported as a single 3-node cycle."""
        tid_a = await _insert_tag(db_session, "general", "cycle3_a", count=1)
        tid_b = await _insert_tag(db_session, "general", "cycle3_b", count=1)
        tid_c = await _insert_tag(db_session, "general", "cycle3_c", count=1)
        await _insert_implication(db_session, tid_a, tid_b)
        await _insert_implication(db_session, tid_b, tid_c)
        await _insert_implication(db_session, tid_c, tid_a)

        with patch("routers.tag.get_redis", return_value=_mock_redis_with_ignored()):
            resp = await client.get("/api/tags/health")

        assert resp.status_code == 200
        expected_key = "-".join(str(x) for x in sorted([tid_a, tid_b, tid_c]))
        matches = [c for c in resp.json()["implication_cycles"] if c["key"] == expected_key]
        assert len(matches) == 1
        assert {n["id"] for n in matches[0]["path"]} == {tid_a, tid_b, tid_c}

    async def test_health_no_cycle_reported_for_acyclic_implication(self, client, db_session):
        """A plain A -> B implication (no cycle) must not appear in implication_cycles."""
        tid_a = await _insert_tag(db_session, "general", "acyclic_a", count=1)
        tid_b = await _insert_tag(db_session, "general", "acyclic_b", count=1)
        await _insert_implication(db_session, tid_a, tid_b)

        with patch("routers.tag.get_redis", return_value=_mock_redis_with_ignored()):
            resp = await client.get("/api/tags/health")

        assert resp.status_code == 200
        for cycle in resp.json()["implication_cycles"]:
            assert not ({tid_a, tid_b} <= {n["id"] for n in cycle["path"]} and len(cycle["path"]) == 2)


# ---------------------------------------------------------------------------
# GET /api/tags/health — ignore filtering
# ---------------------------------------------------------------------------


class TestTagHealthIgnoreFiltering:
    async def test_health_ignore_filters_orphan_and_counts_it(self, client, db_session):
        """An orphan whose id is in the ignore set must be excluded and counted in ignored_count."""
        tid = await _insert_tag(db_session, "general", "ignored_orphan", count=0)

        mock_redis = _mock_redis_with_ignored([f"orphan:{tid}"])
        with patch("routers.tag.get_redis", return_value=mock_redis):
            resp = await client.get("/api/tags/health")

        assert resp.status_code == 200
        data = resp.json()
        orphan_ids = {o["id"] for o in data["orphans"]}
        assert tid not in orphan_ids
        assert data["ignored_count"] >= 1

    async def test_health_ignore_filters_duplicate_group(self, client, db_session):
        """A duplicate group whose key is ignored (dup:<key>) must be excluded from the report."""
        await _insert_tag(db_session, "general", "ign_dup_a", count=5)
        await _insert_tag(db_session, "general", "ign-dup-a", count=1)

        mock_redis = _mock_redis_with_ignored(["dup:general:igndupa"])
        with patch("routers.tag.get_redis", return_value=mock_redis):
            resp = await client.get("/api/tags/health")

        assert resp.status_code == 200
        data = resp.json()
        keys = {g["key"] for g in data["duplicates"]}
        assert "general:igndupa" not in keys
        assert data["ignored_count"] >= 1

    async def test_health_ignore_filters_cycle(self, client, db_session):
        """A cycle whose key is ignored (cycle:<key>) must be excluded from the report."""
        tid = await _insert_tag(db_session, "general", "ignored_cycle_tag", count=1)
        await _insert_implication(db_session, tid, tid)

        mock_redis = _mock_redis_with_ignored([f"cycle:{tid}"])
        with patch("routers.tag.get_redis", return_value=mock_redis):
            resp = await client.get("/api/tags/health")

        assert resp.status_code == 200
        data = resp.json()
        keys = {c["key"] for c in data["implication_cycles"]}
        assert str(tid) not in keys
        assert data["ignored_count"] >= 1


# ---------------------------------------------------------------------------
# POST/DELETE /api/tags/health/ignore, GET /api/tags/health/ignored
# ---------------------------------------------------------------------------


class TestTagHealthIgnoreEndpoints:
    async def test_post_ignore_valid_orphan_key(self, client):
        mock_redis = _mock_redis_with_ignored()
        with patch("routers.tag.get_redis", return_value=mock_redis):
            resp = await client.post("/api/tags/health/ignore", json={"key": "orphan:123"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_redis.sadd.assert_awaited_once()

    async def test_post_ignore_valid_dup_key(self, client):
        mock_redis = _mock_redis_with_ignored()
        with patch("routers.tag.get_redis", return_value=mock_redis):
            resp = await client.post("/api/tags/health/ignore", json={"key": "dup:general:bluehair"})
        assert resp.status_code == 200

    async def test_post_ignore_valid_cycle_key_single_node(self, client):
        mock_redis = _mock_redis_with_ignored()
        with patch("routers.tag.get_redis", return_value=mock_redis):
            resp = await client.post("/api/tags/health/ignore", json={"key": "cycle:5"})
        assert resp.status_code == 200

    async def test_post_ignore_valid_cycle_key_multi_node(self, client):
        mock_redis = _mock_redis_with_ignored()
        with patch("routers.tag.get_redis", return_value=mock_redis):
            resp = await client.post("/api/tags/health/ignore", json={"key": "cycle:2-5-9"})
        assert resp.status_code == 200

    @pytest.mark.parametrize(
        "bad_key",
        [
            "foo:123",
            "orphan:abc",
            "dup:onlynamespace",
            "cycle:",
            "cycle:abc",
            "orphan:",
            "",
        ],
    )
    async def test_post_ignore_invalid_key_returns_400(self, client, bad_key):
        """Any key not matching orphan:{int} / dup:{ns}:{norm} / cycle:{ids} must 400."""
        mock_redis = _mock_redis_with_ignored()
        with patch("routers.tag.get_redis", return_value=mock_redis):
            resp = await client.post("/api/tags/health/ignore", json={"key": bad_key})
        assert resp.status_code == 400
        mock_redis.sadd.assert_not_awaited()

    async def test_delete_ignore_removes_key(self, client):
        mock_redis = _mock_redis_with_ignored(["orphan:42"])
        with patch("routers.tag.get_redis", return_value=mock_redis):
            resp = await client.delete("/api/tags/health/ignore", params={"key": "orphan:42"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_redis.srem.assert_awaited_once()

    async def test_get_ignored_returns_decoded_sorted_keys(self, client):
        mock_redis = _mock_redis_with_ignored(["orphan:2", "dup:general:x", "orphan:1"])
        with patch("routers.tag.get_redis", return_value=mock_redis):
            resp = await client.get("/api/tags/health/ignored")
        assert resp.status_code == 200
        data = resp.json()
        assert data["keys"] == sorted(["orphan:2", "dup:general:x", "orphan:1"])
        assert all(isinstance(k, str) for k in data["keys"])

    async def test_post_ignore_requires_admin(self, make_client):
        async with make_client(user_id=1, role="viewer") as ac:
            resp = await ac.post("/api/tags/health/ignore", json={"key": "orphan:1"})
        assert resp.status_code == 403

    async def test_post_ignore_requires_auth(self, unauthed_client):
        resp = await unauthed_client.post("/api/tags/health/ignore", json={"key": "orphan:1"})
        assert resp.status_code == 401

    async def test_delete_ignore_requires_admin(self, make_client):
        async with make_client(user_id=1, role="viewer") as ac:
            resp = await ac.delete("/api/tags/health/ignore", params={"key": "orphan:1"})
        assert resp.status_code == 403

    async def test_get_ignored_requires_admin(self, make_client):
        async with make_client(user_id=1, role="viewer") as ac:
            resp = await ac.get("/api/tags/health/ignored")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/tags/{tag_id}
# ---------------------------------------------------------------------------


class TestDeleteTag:
    async def test_delete_tag_not_found_returns_404(self, client):
        resp = await client.delete("/api/tags/999999")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_delete_tag_in_use_by_gallery_tags_returns_409(self, client, db_session):
        """A tag still referenced by gallery_tags must be rejected with 409, not deleted."""
        gid = await _insert_gallery(db_session, source_id="del_tag_gt")
        tid = await _insert_tag(db_session, "general", "in_use_gallery_tag", count=1)
        await _insert_gallery_tag(db_session, gid, tid)

        resp = await client.delete(f"/api/tags/{tid}")
        assert resp.status_code == 409

        # Confirm it was NOT deleted
        check = (await db_session.execute(text("SELECT id FROM tags WHERE id = :id"), {"id": tid})).scalar()
        assert check == tid

    async def test_delete_tag_success_removes_aliases_and_implications(self, client, db_session):
        """Deleting an unused tag must cascade-clean tag_aliases (canonical_id) and
        tag_implications (either side), then delete the tag itself."""
        tid = await _insert_tag(db_session, "general", "deletable_tag", count=0)
        other_id = await _insert_tag(db_session, "general", "other_side_tag", count=0)

        await _insert_alias(db_session, "general", "deletable_alias", tid)
        await _insert_implication(db_session, tid, other_id)
        await _insert_implication(db_session, other_id, tid)

        resp = await client.delete(f"/api/tags/{tid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        tag_row = (await db_session.execute(text("SELECT id FROM tags WHERE id = :id"), {"id": tid})).scalar()
        assert tag_row is None

        alias_row = (
            await db_session.execute(text("SELECT * FROM tag_aliases WHERE canonical_id = :id"), {"id": tid})
        ).fetchone()
        assert alias_row is None

        impl_rows = (
            await db_session.execute(
                text("SELECT * FROM tag_implications WHERE antecedent_id = :id OR consequent_id = :id"),
                {"id": tid},
            )
        ).fetchall()
        assert impl_rows == []

    async def test_delete_tag_requires_admin(self, make_client, db_session):
        tid = await _insert_tag(db_session, "general", "role_check_tag", count=0)
        async with make_client(user_id=1, role="viewer") as ac:
            resp = await ac.delete(f"/api/tags/{tid}")
        assert resp.status_code == 403

    async def test_delete_tag_requires_auth(self, unauthed_client):
        resp = await unauthed_client.delete("/api/tags/1")
        assert resp.status_code == 401
