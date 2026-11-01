"""
Simplified/traditional Chinese matching in gallery search.

`zh_variants` expands a query into its simplified and traditional forms so an
ILIKE-contains match hits a title regardless of which script it was stored in.

Notes on SQLite compatibility:
- ILIKE is downgraded to LIKE by SQLAlchemy on SQLite; CJK characters are
  compared by code point, so script differences are not papered over by the
  database — which is exactly what these tests rely on.
"""

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_gallery(db_session, source_id, title, title_jpn=None, uploader=None):
    await db_session.execute(
        text(
            "INSERT INTO galleries "
            "(source, source_id, title, title_jpn, category, language, pages, rating, "
            "favorited, download_status, tags_array, uploader) "
            "VALUES ('ehentai', :sid, :title, :title_jpn, 'doujinshi', 'chinese', 10, 0, "
            "0, 'completed', '[]', :uploader)"
        ),
        {"sid": source_id, "title": title, "title_jpn": title_jpn, "uploader": uploader},
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# zh_variants
# ---------------------------------------------------------------------------


class TestZhVariants:
    def test_traditional_input_includes_simplified_form(self):
        from core.utils import zh_variants

        assert "鱼子酱" in zh_variants("魚子醬")

    def test_simplified_input_includes_traditional_form(self):
        from core.utils import zh_variants

        assert "魚子醬" in zh_variants("鱼子酱")

    def test_original_comes_first_and_variants_are_deduplicated(self):
        from core.utils import zh_variants

        variants = zh_variants("魚子醬")
        assert variants[0] == "魚子醬"
        assert len(variants) == len(set(variants))

    def test_text_without_chinese_characters_is_returned_unchanged(self):
        from core.utils import zh_variants

        assert zh_variants("Naruto 123") == ["Naruto 123"]

    def test_phrase_level_rewrites_are_not_applied(self):
        """s2twp would turn 软件 into 軟體, so a title written 軟件 would stop matching."""
        from core.utils import zh_variants

        variants = zh_variants("软件")
        assert "軟件" in variants
        assert "軟體" not in variants


# ---------------------------------------------------------------------------
# GET /api/search/
# ---------------------------------------------------------------------------


class TestSearchAcrossScripts:
    async def test_title_token_traditional_query_matches_simplified_title(self, client, db_session):
        await _insert_gallery(db_session, "z1", "鱼子酱 合集")
        await _insert_gallery(db_session, "z2", "完全無關的作品")

        resp = await client.get("/api/search/", params={"q": 'title:"魚子醬"'})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "鱼子酱 合集"

    async def test_title_token_simplified_query_matches_traditional_title(self, client, db_session):
        await _insert_gallery(db_session, "z1", "魚子醬 合集")
        await _insert_gallery(db_session, "z2", "完全無關的作品")

        resp = await client.get("/api/search/", params={"q": 'title:"鱼子酱"'})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "魚子醬 合集"

    async def test_bare_traditional_query_matches_simplified_title(self, client, db_session):
        await _insert_gallery(db_session, "z1", "鱼子酱 合集")
        await _insert_gallery(db_session, "z2", "完全無關的作品")

        resp = await client.get("/api/search/", params={"q": "魚子醬"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "鱼子酱 合集"

    async def test_bare_query_matches_title_jpn_in_the_other_script(self, client, db_session):
        await _insert_gallery(db_session, "z1", "Untitled", title_jpn="鱼子酱")

        resp = await client.get("/api/search/", params={"q": "魚子醬"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_bare_query_matches_uploader_in_the_other_script(self, client, db_session):
        await _insert_gallery(db_session, "z1", "Untitled", uploader="鱼子酱汉化组")
        await _insert_gallery(db_session, "z2", "Untitled", uploader="someone else")

        resp = await client.get("/api/search/", params={"q": "魚子醬漢化組"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["source_id"] == "z1"

    async def test_chinese_query_still_excludes_unrelated_titles(self, client, db_session):
        await _insert_gallery(db_session, "z1", "完全無關的作品")

        resp = await client.get("/api/search/", params={"q": "魚子醬"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
