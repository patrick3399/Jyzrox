"""
Tests for GET /api/tags/translations/browse (tag translations full-browse endpoint).

See docs/superpowers/specs/2026-07-12-tag-translations-browse-design.md §1.

Notes on SQLite compatibility:
- ILIKE is downgraded to LIKE by SQLAlchemy on SQLite, which is
  case-insensitive for ASCII. Test data uses ASCII `name` values so
  case-insensitivity assertions are meaningful; translation text (Chinese)
  is matched via exact/contains substring, not case variance.
"""

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Helpers
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


# ---------------------------------------------------------------------------
# GET /api/tags/translations/browse
# ---------------------------------------------------------------------------


class TestTagTranslationsBrowse:
    async def test_browse_no_params_returns_all_sorted(self, client, db_session):
        """No query params should return all translations, sorted by namespace, name."""
        await _insert_translation(db_session, "general", "blue_hair", "zh", "藍髮")
        await _insert_translation(db_session, "artist", "alice", "zh", "愛麗絲")
        await _insert_translation(db_session, "general", "aqua_eyes", "zh", "水藍眼")

        resp = await client.get("/api/tags/translations/browse")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3

        # Sorted by (namespace, name)
        pairs = [(item["namespace"], item["name"]) for item in data["items"]]
        assert pairs == sorted(pairs)

    async def test_browse_q_matches_name(self, client, db_session):
        """q= should match tag name via case-insensitive contains."""
        await _insert_translation(db_session, "general", "blue_hair", "zh", "藍髮")
        await _insert_translation(db_session, "general", "red_hair", "zh", "紅髮")
        await _insert_translation(db_session, "general", "green_eyes", "zh", "綠眼")

        resp = await client.get("/api/tags/translations/browse", params={"q": "hair"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        names = {item["name"] for item in data["items"]}
        assert names == {"blue_hair", "red_hair"}

    async def test_browse_q_matches_translation(self, client, db_session):
        """q= should also match the translation text via contains."""
        await _insert_translation(db_session, "general", "blue_hair", "zh", "藍髮")
        await _insert_translation(db_session, "general", "red_hair", "zh", "紅髮")

        resp = await client.get("/api/tags/translations/browse", params={"q": "藍"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "blue_hair"

    async def test_browse_q_no_match_returns_empty(self, client, db_session):
        """q= with no matches should return empty items and total=0."""
        await _insert_translation(db_session, "general", "blue_hair", "zh", "藍髮")

        resp = await client.get("/api/tags/translations/browse", params={"q": "nonexistent_xyz"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_browse_q_percent_not_treated_as_wildcard(self, client, db_session):
        """A literal % in q= must not match everything (escape_like)."""
        await _insert_translation(db_session, "general", "normal_tag", "zh", "普通標籤")

        resp = await client.get("/api/tags/translations/browse", params={"q": "%"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_browse_q_underscore_not_treated_as_wildcard(self, client, db_session):
        """A literal _ in q= must only match a literal underscore, not any char."""
        await _insert_translation(db_session, "general", "blue_hair", "zh", "藍髮")
        await _insert_translation(db_session, "general", "blueXhair", "zh", "藍X髮")

        # "blue_hair" as a literal pattern (escaped) should only match the
        # underscore variant, not "blueXhair".
        resp = await client.get("/api/tags/translations/browse", params={"q": "blue_hair"})
        assert resp.status_code == 200
        data = resp.json()
        names = {item["name"] for item in data["items"]}
        assert "blue_hair" in names
        assert "blueXhair" not in names

    async def test_browse_namespace_filter(self, client, db_session):
        """namespace= should exactly filter by namespace."""
        await _insert_translation(db_session, "artist", "alice", "zh", "愛麗絲")
        await _insert_translation(db_session, "general", "blue_hair", "zh", "藍髮")

        resp = await client.get("/api/tags/translations/browse", params={"namespace": "artist"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["namespace"] == "artist"
        assert data["items"][0]["name"] == "alice"

    async def test_browse_language_filter(self, client, db_session):
        """language= should filter to only that DB language."""
        await _insert_translation(db_session, "general", "blue_hair", "zh", "藍髮")
        await _insert_translation(db_session, "general", "blue_hair", "ja", "青い髪")

        resp_zh = await client.get("/api/tags/translations/browse", params={"language": "zh"})
        assert resp_zh.status_code == 200
        data_zh = resp_zh.json()
        assert data_zh["total"] == 1
        assert data_zh["items"][0]["language"] == "zh"
        assert data_zh["items"][0]["translation"] == "藍髮"

        resp_ja = await client.get("/api/tags/translations/browse", params={"language": "ja"})
        assert resp_ja.status_code == 200
        data_ja = resp_ja.json()
        assert data_ja["total"] == 1
        assert data_ja["items"][0]["language"] == "ja"
        assert data_ja["items"][0]["translation"] == "青い髪"

    async def test_browse_default_language_is_zh(self, client, db_session):
        """Default language= (unset) should behave like zh, excluding other languages."""
        await _insert_translation(db_session, "general", "blue_hair", "zh", "藍髮")
        await _insert_translation(db_session, "general", "blue_hair", "ja", "青い髪")

        resp = await client.get("/api/tags/translations/browse")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["language"] == "zh"

    async def test_browse_zh_tw_output_converted_to_traditional(self, client, db_session):
        """language=zh-TW should query DB zh rows and convert output translation to traditional."""
        # DB stores simplified Chinese
        await _insert_translation(db_session, "general", "blue_hair", "zh", "蓝发")

        resp = await client.get("/api/tags/translations/browse", params={"language": "zh-TW"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["language"] == "zh-TW"
        # s2twp should convert simplified '蓝发' to traditional (Taiwan variant)
        assert item["translation"] != "蓝发"
        assert item["translation"] == "藍髮"

    async def test_browse_zh_tw_query_with_traditional_q_matches_simplified_db(self, client, db_session):
        """zh-TW: q= in traditional form should match translation stored in simplified via t2s."""
        await _insert_translation(db_session, "general", "blue_hair", "zh", "蓝发")
        await _insert_translation(db_session, "general", "red_eyes", "zh", "红眼")

        # Query with traditional characters — endpoint must t2s-convert q to
        # match the simplified translation stored in the DB.
        resp = await client.get("/api/tags/translations/browse", params={"q": "藍髮", "language": "zh-TW"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "blue_hair"
        assert data["items"][0]["translation"] == "藍髮"

    async def test_browse_pagination_limit_offset(self, client, db_session):
        """limit/offset should paginate results; total must not be affected by pagination."""
        for i in range(10):
            await _insert_translation(db_session, "general", f"tag_{i:02d}", "zh", f"標籤{i:02d}")

        resp_page1 = await client.get("/api/tags/translations/browse", params={"limit": 3, "offset": 0})
        assert resp_page1.status_code == 200
        data1 = resp_page1.json()
        assert data1["total"] == 10
        assert len(data1["items"]) == 3

        resp_page2 = await client.get("/api/tags/translations/browse", params={"limit": 3, "offset": 3})
        assert resp_page2.status_code == 200
        data2 = resp_page2.json()
        assert data2["total"] == 10
        assert len(data2["items"]) == 3

        # Pages must not overlap
        names1 = {item["name"] for item in data1["items"]}
        names2 = {item["name"] for item in data2["items"]}
        assert names1.isdisjoint(names2)

    async def test_browse_limit_out_of_range_rejected(self, client):
        """limit outside [1, 200] should be rejected with 422 (FastAPI validation)."""
        resp_too_high = await client.get("/api/tags/translations/browse", params={"limit": 201})
        assert resp_too_high.status_code == 422

        resp_too_low = await client.get("/api/tags/translations/browse", params={"limit": 0})
        assert resp_too_low.status_code == 422

    async def test_browse_negative_offset_rejected(self, client):
        """Negative offset should be rejected with 422."""
        resp = await client.get("/api/tags/translations/browse", params={"offset": -1})
        assert resp.status_code == 422

    async def test_browse_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/tags/translations/browse")
        assert resp.status_code == 401
