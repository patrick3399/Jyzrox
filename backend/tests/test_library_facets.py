"""Tests for GET /api/library/galleries/facets (Library multi-select facet counts)."""

from sqlalchemy import text


async def _gallery(db_session, source, source_id, category, import_mode=None, owner=None, visibility="public"):
    await db_session.execute(
        text(
            "INSERT INTO galleries "
            "(source, source_id, title, category, language, pages, rating, favorited, "
            "download_status, tags_array, import_mode, created_by_user_id, visibility) "
            "VALUES (:source, :source_id, :title, :category, 'english', 10, 0, 0, "
            "'completed', '[]', :import_mode, :owner, :visibility)"
        ),
        {
            "source": source,
            "source_id": source_id,
            "title": f"{source}-{source_id}",
            "category": category,
            "import_mode": import_mode,
            "owner": owner,
            "visibility": visibility,
        },
    )
    await db_session.commit()


async def _ensure_users(db_session):
    for uid in (1, 2):
        await db_session.execute(
            text("INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (:id, :u, 'x')"),
            {"id": uid, "u": f"facetuser{uid}"},
        )
    await db_session.commit()


class TestLibraryFacets:
    async def test_facets_counts_sources_by_import_mode(self, client, db_session):
        await _gallery(db_session, "local", "1", "Artist CG", "link")
        await _gallery(db_session, "local", "2", "Artist CG", "link")
        await _gallery(db_session, "local", "3", "Manga", "copy")
        await _gallery(db_session, "pixiv", "4", None)
        await _gallery(db_session, "pixiv", "5", "")
        await _gallery(db_session, "pixiv", "6", "Manga")

        resp = await client.get("/api/library/galleries/facets")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data) == {"sources", "categories", "uncategorized"}
        src = {s["value"]: s for s in data["sources"]}
        assert src["local:link"]["count"] == 2
        assert src["local:link"]["label"] == "local:link"
        assert src["local:copy"]["count"] == 1
        assert src["pixiv"]["count"] == 3
        # sorted by count DESC then label ASC
        counts = [s["count"] for s in data["sources"]]
        assert counts == sorted(counts, reverse=True)
        cats = {c["name"]: c["count"] for c in data["categories"]}
        assert cats == {"Artist CG": 2, "Manga": 2}
        assert [c["name"] for c in data["categories"]] == ["Artist CG", "Manga"]
        assert data["uncategorized"] == 2

    async def test_facets_viewer_does_not_count_private_gallery(self, make_client, db_session):
        await _ensure_users(db_session)
        await _gallery(db_session, "pixiv", "pub", "Public Cat", owner=1, visibility="public")
        await _gallery(db_session, "secret", "priv", "Secret Cat", owner=1, visibility="private")
        await _gallery(db_session, "mine", "own", "Mine Cat", owner=2, visibility="private")

        async with make_client(user_id=2, role="viewer") as ac:
            data = (await ac.get("/api/library/galleries/facets")).json()

        assert {s["value"] for s in data["sources"]} == {"pixiv", "mine"}
        assert {c["name"] for c in data["categories"]} == {"Public Cat", "Mine Cat"}

    async def test_facets_excludes_soft_deleted_galleries(self, client, db_session):
        await _gallery(db_session, "pixiv", "live", "Live")
        await _gallery(db_session, "trashed", "dead", "Dead")
        await db_session.execute(text("UPDATE galleries SET deleted_at = CURRENT_TIMESTAMP WHERE source = 'trashed'"))
        await db_session.commit()

        data = (await client.get("/api/library/galleries/facets")).json()
        assert {s["value"] for s in data["sources"]} == {"pixiv"}
        assert {c["name"] for c in data["categories"]} == {"Live"}

    async def test_facets_requires_auth(self, unauthed_client):
        resp = await unauthed_client.get("/api/library/galleries/facets")
        assert resp.status_code == 401
