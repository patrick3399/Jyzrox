"""
Tests for the OPDS Atom feed router (/opds/*).

Endpoint coverage:
  GET /opds/                  — Root navigation feed
  GET /opds/all               — All galleries, paginated
  GET /opds/recent            — Last 50 galleries (no pagination links)
  GET /opds/favorites         — Favorited galleries only
  GET /opds/search?q=...      — Title search
  GET /opds/opensearch.xml    — OpenSearch descriptor
  GET /opds/gallery/{id}      — OPDS-PSE page list for one gallery
  Auth tests                  — 401 without credentials / wrong password

Auth is exercised through the `opds_client` fixture (require_opds_auth bypassed)
and the `unauthed_opds_client` fixture (real require_opds_auth logic runs).
"""

import base64
import xml.etree.ElementTree as ET

import bcrypt
import pytest
from sqlalchemy import text

# ── XML namespace helpers ──────────────────────────────────────────────────────

ATOM = "{http://www.w3.org/2005/Atom}"
PSE = "{http://vaemendis.net/opds-pse/ns}"
OPDS = "{http://opds-spec.org/2010/catalog}"
OS = "{http://a9.com/-/spec/opensearch/1.1/}"


def _parse(response) -> ET.Element:
    """Parse response body as XML and return root element."""
    return ET.fromstring(response.content)


def _entries(root: ET.Element) -> list[ET.Element]:
    """Return all <entry> elements directly under a feed root."""
    return root.findall(f"{ATOM}entry")


def _link_rels(element: ET.Element) -> dict[str, str]:
    """Map rel → href for all <link> children of element."""
    return {
        link.get("rel"): link.get("href")
        for link in element.findall(f"{ATOM}link")
    }


# ── Helpers for inserting test data ───────────────────────────────────────────


async def _insert_gallery(
    db_session,
    *,
    source: str = "test",
    source_id: str = "1",
    title: str = "Test Gallery",
    favorited: int = 0,
    pages: int = 5,
    language: str | None = None,
    category: str | None = None,
) -> int:
    """Insert one gallery; return its auto-generated id."""
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, pages, favorited, language, category) "
            "VALUES (:source, :sid, :title, :pages, :fav, :lang, :cat)"
        ),
        {
            "source": source,
            "sid": source_id,
            "title": title,
            "pages": pages,
            "fav": favorited,
            "lang": language,
            "cat": category,
        },
    )
    await db_session.commit()
    result = await db_session.execute(text("SELECT last_insert_rowid()"))
    return result.scalar()


async def _insert_image(
    db_session,
    gallery_id: int,
    page_num: int = 1,
    filename: str = "001.jpg",
) -> int:
    """Insert one image (no blob); return its auto-generated id."""
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename) "
            "VALUES (:gid, :pnum, :fn)"
        ),
        {"gid": gallery_id, "pnum": page_num, "fn": filename},
    )
    await db_session.commit()
    result = await db_session.execute(text("SELECT last_insert_rowid()"))
    return result.scalar()


async def _insert_user(db_session, username: str = "testuser", password: str = "testpass") -> int:
    """Insert a user with bcrypt-hashed password; return its id."""
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    await db_session.execute(
        text(
            "INSERT INTO users (username, password_hash) VALUES (:uname, :phash)"
        ),
        {"uname": username, "phash": pw_hash},
    )
    await db_session.commit()
    result = await db_session.execute(text("SELECT last_insert_rowid()"))
    return result.scalar()


def _basic_auth_header(username: str, password: str) -> str:
    """Encode username:password as HTTP Basic Auth header value."""
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"


# ── Root navigation feed ───────────────────────────────────────────────────────


class TestOPDSRoot:
    async def test_root_returns_200(self, opds_client):
        """GET /opds/ should return HTTP 200."""
        resp = await opds_client.get("/opds/")
        assert resp.status_code == 200

    async def test_root_content_type_is_atom_xml(self, opds_client):
        """Response Content-Type should be application/atom+xml."""
        resp = await opds_client.get("/opds/")
        assert "application/atom+xml" in resp.headers["content-type"]

    async def test_root_is_valid_atom_xml(self, opds_client):
        """Response body should parse as valid XML with an Atom feed root."""
        resp = await opds_client.get("/opds/")
        root = _parse(resp)
        assert root.tag == f"{ATOM}feed"

    async def test_root_has_feed_title(self, opds_client):
        """Feed title element should contain 'Jyzrox'."""
        resp = await opds_client.get("/opds/")
        root = _parse(resp)
        title_el = root.find(f"{ATOM}title")
        assert title_el is not None
        assert "Jyzrox" in title_el.text

    async def test_root_has_four_navigation_entries(self, opds_client):
        """Root navigation feed should contain exactly 4 entries: all/recent/favorites/search."""
        resp = await opds_client.get("/opds/")
        entries = _entries(_parse(resp))
        assert len(entries) == 4

    async def test_root_entry_ids_are_correct(self, opds_client):
        """Each navigation entry should have the expected URN id."""
        resp = await opds_client.get("/opds/")
        root = _parse(resp)
        ids = {e.findtext(f"{ATOM}id") for e in _entries(root)}
        expected = {
            "urn:jyzrox:opds:all",
            "urn:jyzrox:opds:recent",
            "urn:jyzrox:opds:favorites",
            "urn:jyzrox:opds:search",
        }
        assert ids == expected

    async def test_root_has_opensearch_link(self, opds_client):
        """Root feed should contain a link with rel=search pointing to opensearch.xml."""
        resp = await opds_client.get("/opds/")
        root = _parse(resp)
        links = root.findall(f"{ATOM}link")
        search_links = [l for l in links if l.get("rel") == "search"]
        assert len(search_links) == 1
        assert "opensearch.xml" in search_links[0].get("href", "")

    async def test_root_has_start_link(self, opds_client):
        """Root feed should have a link with rel=start."""
        resp = await opds_client.get("/opds/")
        root = _parse(resp)
        links = root.findall(f"{ATOM}link")
        start_links = [l for l in links if l.get("rel") == "start"]
        assert len(start_links) == 1


# ── All galleries feed ─────────────────────────────────────────────────────────


class TestOPDSAll:
    async def test_all_returns_200(self, opds_client):
        """GET /opds/all should return HTTP 200."""
        resp = await opds_client.get("/opds/all")
        assert resp.status_code == 200

    async def test_all_empty_returns_no_entries(self, opds_client):
        """With no galleries in DB, feed should have zero entries."""
        resp = await opds_client.get("/opds/all")
        entries = _entries(_parse(resp))
        assert entries == []

    async def test_all_returns_inserted_gallery(self, opds_client, db_session):
        """Inserted gallery should appear as an entry in the feed."""
        await _insert_gallery(db_session, source_id="10", title="My Gallery")
        resp = await opds_client.get("/opds/all")
        entries = _entries(_parse(resp))
        assert len(entries) == 1
        title = entries[0].findtext(f"{ATOM}title")
        assert title == "My Gallery"

    async def test_all_entry_has_subsection_link(self, opds_client, db_session):
        """Each gallery entry must have a subsection link to /opds/gallery/{id}."""
        gid = await _insert_gallery(db_session, source_id="20")
        resp = await opds_client.get("/opds/all")
        entries = _entries(_parse(resp))
        assert len(entries) == 1
        rels = _link_rels(entries[0])
        assert "subsection" in rels
        assert f"/opds/gallery/{gid}" in rels["subsection"]

    async def test_all_entry_has_urn_id(self, opds_client, db_session):
        """Gallery entry id should be formatted as urn:jyzrox:gallery:{id}."""
        gid = await _insert_gallery(db_session, source_id="21")
        resp = await opds_client.get("/opds/all")
        entries = _entries(_parse(resp))
        entry_id = entries[0].findtext(f"{ATOM}id")
        assert entry_id == f"urn:jyzrox:gallery:{gid}"

    async def test_all_pagination_next_link_present(self, opds_client, db_session):
        """When there are more galleries than limit, a next link should be included."""
        for i in range(6):
            await _insert_gallery(db_session, source_id=str(100 + i), title=f"Gallery {i}")

        resp = await opds_client.get("/opds/all?page=0&limit=5")
        root = _parse(resp)
        links = root.findall(f"{ATOM}link")
        next_links = [l for l in links if l.get("rel") == "next"]
        assert len(next_links) == 1
        assert "page=1" in next_links[0].get("href", "")

    async def test_all_pagination_no_next_on_last_page(self, opds_client, db_session):
        """When all results fit in one page, no next link should be present."""
        for i in range(3):
            await _insert_gallery(db_session, source_id=str(200 + i))

        resp = await opds_client.get("/opds/all?page=0&limit=10")
        root = _parse(resp)
        links = root.findall(f"{ATOM}link")
        next_links = [l for l in links if l.get("rel") == "next"]
        assert next_links == []

    async def test_all_page1_has_previous_link(self, opds_client, db_session):
        """Requesting page=1 should include a previous link pointing to page=0."""
        for i in range(6):
            await _insert_gallery(db_session, source_id=str(300 + i))

        resp = await opds_client.get("/opds/all?page=1&limit=5")
        root = _parse(resp)
        links = root.findall(f"{ATOM}link")
        prev_links = [l for l in links if l.get("rel") == "previous"]
        assert len(prev_links) == 1
        assert "page=0" in prev_links[0].get("href", "")

    async def test_all_page0_has_no_previous_link(self, opds_client, db_session):
        """First page (page=0) should not have a previous link."""
        await _insert_gallery(db_session, source_id="401")
        resp = await opds_client.get("/opds/all?page=0&limit=10")
        root = _parse(resp)
        links = root.findall(f"{ATOM}link")
        prev_links = [l for l in links if l.get("rel") == "previous"]
        assert prev_links == []

    async def test_all_entry_pse_count_attribute(self, opds_client, db_session):
        """Gallery entry should carry pse:count equal to the gallery's pages value."""
        await _insert_gallery(db_session, source_id="500", pages=42)
        resp = await opds_client.get("/opds/all")
        entries = _entries(_parse(resp))
        pse_count = entries[0].get(f"{PSE}count")
        assert pse_count == "42"

    async def test_all_entry_summary_contains_pages(self, opds_client, db_session):
        """Gallery entry summary should mention page count."""
        await _insert_gallery(db_session, source_id="501", pages=10)
        resp = await opds_client.get("/opds/all")
        entries = _entries(_parse(resp))
        summary = entries[0].findtext(f"{ATOM}summary")
        assert summary is not None
        assert "10 pages" in summary


# ── Recent feed ────────────────────────────────────────────────────────────────


class TestOPDSRecent:
    async def test_recent_returns_200(self, opds_client):
        """GET /opds/recent should return HTTP 200."""
        resp = await opds_client.get("/opds/recent")
        assert resp.status_code == 200

    async def test_recent_empty_returns_no_entries(self, opds_client):
        """With empty DB, recent feed should have no entries."""
        resp = await opds_client.get("/opds/recent")
        assert _entries(_parse(resp)) == []

    async def test_recent_returns_inserted_galleries(self, opds_client, db_session):
        """All inserted galleries (up to 50) should appear in the recent feed."""
        await _insert_gallery(db_session, source_id="r1", title="Recent A")
        await _insert_gallery(db_session, source_id="r2", title="Recent B")
        resp = await opds_client.get("/opds/recent")
        entries = _entries(_parse(resp))
        titles = {e.findtext(f"{ATOM}title") for e in entries}
        assert "Recent A" in titles
        assert "Recent B" in titles

    async def test_recent_has_no_pagination_links(self, opds_client, db_session):
        """Recent feed should never include next/previous pagination links."""
        for i in range(3):
            await _insert_gallery(db_session, source_id=f"rp{i}")
        resp = await opds_client.get("/opds/recent")
        root = _parse(resp)
        links = root.findall(f"{ATOM}link")
        paginating = [l for l in links if l.get("rel") in ("next", "previous")]
        assert paginating == []


# ── Favorites feed ─────────────────────────────────────────────────────────────


class TestOPDSFavorites:
    async def test_favorites_returns_200(self, opds_client):
        """GET /opds/favorites should return HTTP 200."""
        resp = await opds_client.get("/opds/favorites")
        assert resp.status_code == 200

    async def test_favorites_empty_returns_no_entries(self, opds_client):
        """With no favorited galleries, favorites feed should have zero entries."""
        resp = await opds_client.get("/opds/favorites")
        assert _entries(_parse(resp)) == []

    async def test_favorites_returns_only_favorited(self, opds_client, db_session):
        """Only galleries in user_favorites (for user_id=1) should appear in the favorites feed.

        The OPDS favorites endpoint JOINs the user_favorites table; the legacy
        gallery.favorited column is not used for filtering.
        """
        fav_gid = await _insert_gallery(db_session, source_id="f1", title="Favorited One", favorited=1)
        await _insert_gallery(db_session, source_id="f2", title="Not Favorite", favorited=0)
        # Insert into user_favorites for user_id=1 (opds_client auth override)
        await db_session.execute(
            text("INSERT INTO user_favorites (user_id, gallery_id) VALUES (1, :gid)"),
            {"gid": fav_gid},
        )
        await db_session.commit()
        resp = await opds_client.get("/opds/favorites")
        entries = _entries(_parse(resp))
        assert len(entries) == 1
        assert entries[0].findtext(f"{ATOM}title") == "Favorited One"

    async def test_favorites_excludes_non_favorited(self, opds_client, db_session):
        """Non-favorited galleries must never appear in the favorites feed."""
        await _insert_gallery(db_session, source_id="f3", title="Skip Me", favorited=0)
        resp = await opds_client.get("/opds/favorites")
        titles = {e.findtext(f"{ATOM}title") for e in _entries(_parse(resp))}
        assert "Skip Me" not in titles

    async def test_favorites_pagination_next_link(self, opds_client, db_session):
        """When favorited galleries exceed limit, a next link should be present.

        The OPDS favorites endpoint JOINs user_favorites; must insert rows there.
        """
        gids = []
        for i in range(6):
            gid = await _insert_gallery(db_session, source_id=f"fav_pg{i}", favorited=1)
            gids.append(gid)
        # Insert all 6 into user_favorites for user_id=1
        for gid in gids:
            await db_session.execute(
                text("INSERT INTO user_favorites (user_id, gallery_id) VALUES (1, :gid)"),
                {"gid": gid},
            )
        await db_session.commit()
        resp = await opds_client.get("/opds/favorites?page=0&limit=5")
        root = _parse(resp)
        links = root.findall(f"{ATOM}link")
        next_links = [l for l in links if l.get("rel") == "next"]
        assert len(next_links) == 1


# ── Search feed ────────────────────────────────────────────────────────────────


class TestOPDSSearch:
    async def test_search_returns_200(self, opds_client):
        """GET /opds/search should return HTTP 200."""
        resp = await opds_client.get("/opds/search")
        assert resp.status_code == 200

    async def test_search_no_query_returns_all(self, opds_client, db_session):
        """Search without a q parameter should return all galleries."""
        await _insert_gallery(db_session, source_id="s1", title="Alpha")
        await _insert_gallery(db_session, source_id="s2", title="Beta")
        resp = await opds_client.get("/opds/search")
        entries = _entries(_parse(resp))
        assert len(entries) == 2

    async def test_search_by_title_keyword(self, opds_client, db_session):
        """Search with q= should filter galleries by title substring."""
        await _insert_gallery(db_session, source_id="sq1", title="Dragon Ball Z")
        await _insert_gallery(db_session, source_id="sq2", title="Sailor Moon")
        await _insert_gallery(db_session, source_id="sq3", title="Naruto Dragon")
        resp = await opds_client.get("/opds/search?q=Dragon")
        entries = _entries(_parse(resp))
        titles = {e.findtext(f"{ATOM}title") for e in entries}
        assert "Dragon Ball Z" in titles
        assert "Naruto Dragon" in titles
        assert "Sailor Moon" not in titles

    async def test_search_no_results(self, opds_client, db_session):
        """Search with a term that matches nothing should return an empty feed."""
        await _insert_gallery(db_session, source_id="sq4", title="One Piece")
        resp = await opds_client.get("/opds/search?q=xyznotexisting")
        entries = _entries(_parse(resp))
        assert entries == []

    async def test_search_feed_title_includes_query(self, opds_client, db_session):
        """Feed title should include the search query term."""
        await _insert_gallery(db_session, source_id="sq5", title="Bleach")
        resp = await opds_client.get("/opds/search?q=Bleach")
        root = _parse(resp)
        title_el = root.findtext(f"{ATOM}title")
        assert "Bleach" in title_el

    async def test_search_case_insensitive(self, opds_client, db_session):
        """Title search should be case-insensitive (ILIKE behaviour)."""
        await _insert_gallery(db_session, source_id="sq6", title="Hunter x Hunter")
        # SQLite LIKE is case-insensitive for ASCII; this verifies lowercase match
        resp = await opds_client.get("/opds/search?q=hunter")
        entries = _entries(_parse(resp))
        titles = {e.findtext(f"{ATOM}title") for e in entries}
        assert "Hunter x Hunter" in titles


# ── OpenSearch descriptor ──────────────────────────────────────────────────────


class TestOPDSOpenSearch:
    async def test_opensearch_returns_200(self, opds_client):
        """GET /opds/opensearch.xml should return HTTP 200."""
        resp = await opds_client.get("/opds/opensearch.xml")
        assert resp.status_code == 200

    async def test_opensearch_content_type(self, opds_client):
        """Content-Type should be application/opensearchdescription+xml."""
        resp = await opds_client.get("/opds/opensearch.xml")
        assert "opensearchdescription+xml" in resp.headers["content-type"]

    async def test_opensearch_is_valid_xml(self, opds_client):
        """Response body should be parseable XML."""
        resp = await opds_client.get("/opds/opensearch.xml")
        root = ET.fromstring(resp.content)
        assert root is not None

    async def test_opensearch_has_short_name(self, opds_client):
        """Descriptor should contain a ShortName element."""
        resp = await opds_client.get("/opds/opensearch.xml")
        root = ET.fromstring(resp.content)
        short_name = root.find(f"{OS}ShortName")
        assert short_name is not None
        assert short_name.text == "Jyzrox"

    async def test_opensearch_url_template_contains_search_terms(self, opds_client):
        """Url template attribute should reference {searchTerms}."""
        resp = await opds_client.get("/opds/opensearch.xml")
        root = ET.fromstring(resp.content)
        url_el = root.find(f"{OS}Url")
        assert url_el is not None
        template = url_el.get("template", "")
        assert "{searchTerms}" in template
        assert "/opds/search" in template


# ── Gallery detail (OPDS-PSE page list) ───────────────────────────────────────


class TestOPDSGalleryDetail:
    async def test_gallery_detail_returns_200(self, opds_client, db_session):
        """GET /opds/gallery/{id} for an existing gallery should return 200."""
        gid = await _insert_gallery(db_session, source_id="gd1", title="Detail Gallery")
        resp = await opds_client.get(f"/opds/gallery/{gid}")
        assert resp.status_code == 200

    async def test_gallery_not_found_returns_404(self, opds_client):
        """GET /opds/gallery/{id} for a non-existent gallery should return 404."""
        resp = await opds_client.get("/opds/gallery/999999")
        assert resp.status_code == 404

    async def test_gallery_detail_is_atom_feed(self, opds_client, db_session):
        """Gallery detail should return a valid Atom feed XML."""
        gid = await _insert_gallery(db_session, source_id="gd2")
        resp = await opds_client.get(f"/opds/gallery/{gid}")
        root = _parse(resp)
        assert root.tag == f"{ATOM}feed"

    async def test_gallery_detail_feed_title_matches_gallery(self, opds_client, db_session):
        """Feed title should match the gallery's title."""
        gid = await _insert_gallery(db_session, source_id="gd3", title="Named Gallery")
        resp = await opds_client.get(f"/opds/gallery/{gid}")
        root = _parse(resp)
        assert root.findtext(f"{ATOM}title") == "Named Gallery"

    async def test_gallery_detail_no_images_returns_empty_feed(self, opds_client, db_session):
        """Gallery with no images should return a feed with zero entries."""
        gid = await _insert_gallery(db_session, source_id="gd4")
        resp = await opds_client.get(f"/opds/gallery/{gid}")
        entries = _entries(_parse(resp))
        assert entries == []

    async def test_gallery_detail_entries_have_pse_index(self, opds_client, db_session):
        """Each image entry should carry a pse:index attribute (0-based)."""
        gid = await _insert_gallery(db_session, source_id="gd5", pages=3)
        await _insert_image(db_session, gid, page_num=1, filename="001.jpg")
        await _insert_image(db_session, gid, page_num=2, filename="002.jpg")
        await _insert_image(db_session, gid, page_num=3, filename="003.jpg")

        resp = await opds_client.get(f"/opds/gallery/{gid}")
        entries = _entries(_parse(resp))
        assert len(entries) == 3
        indices = {e.get(f"{PSE}index") for e in entries}
        # page_num 1/2/3 → pse:index 0/1/2
        assert indices == {"0", "1", "2"}

    async def test_gallery_detail_entries_have_title(self, opds_client, db_session):
        """Each image entry should have a title like 'Page N'."""
        gid = await _insert_gallery(db_session, source_id="gd6")
        await _insert_image(db_session, gid, page_num=1)
        resp = await opds_client.get(f"/opds/gallery/{gid}")
        entries = _entries(_parse(resp))
        assert entries[0].findtext(f"{ATOM}title") == "Page 1"

    async def test_gallery_detail_entries_ordered_by_page_num(self, opds_client, db_session):
        """Image entries should be ordered by page_num ascending (default for unknown sources).

        The OPDS gallery detail endpoint orders images according to per-source
        display config.  For source='test' the default image_order is 'asc',
        so pse:index values come out in ascending order: [0, 1, 2].
        """
        gid = await _insert_gallery(db_session, source_id="gd7", pages=3)
        # Insert in mixed order to confirm ordering is consistent
        await _insert_image(db_session, gid, page_num=3)
        await _insert_image(db_session, gid, page_num=1)
        await _insert_image(db_session, gid, page_num=2)

        resp = await opds_client.get(f"/opds/gallery/{gid}")
        entries = _entries(_parse(resp))
        indices = [int(e.get(f"{PSE}index")) for e in entries]
        # Unknown source defaults to image_order="asc": indices are [0, 1, 2]
        assert indices == sorted(indices)

    async def test_gallery_detail_fallback_title_when_no_title(self, opds_client, db_session):
        """When gallery title is null, feed title should fall back to 'Gallery {id}'."""
        await db_session.execute(
            text(
                "INSERT INTO galleries (source, source_id, pages, favorited) "
                "VALUES ('test', 'no-title-1', 5, 0)"
            )
        )
        await db_session.commit()
        result = await db_session.execute(text("SELECT last_insert_rowid()"))
        gid = result.scalar()

        resp = await opds_client.get(f"/opds/gallery/{gid}")
        root = _parse(resp)
        feed_title = root.findtext(f"{ATOM}title")
        assert feed_title == f"Gallery {gid}"


# ── Authentication tests ───────────────────────────────────────────────────────


class TestOPDSAuth:
    async def test_no_auth_header_returns_401(self, unauthed_opds_client):
        """Request without Authorization header should return 401."""
        resp = await unauthed_opds_client.get("/opds/")
        assert resp.status_code == 401

    async def test_no_auth_includes_www_authenticate_header(self, unauthed_opds_client):
        """401 response should include WWW-Authenticate: Basic realm header."""
        resp = await unauthed_opds_client.get("/opds/")
        www_auth = resp.headers.get("www-authenticate", "")
        assert "Basic" in www_auth
        assert "Jyzrox OPDS" in www_auth

    async def test_wrong_password_returns_401(self, unauthed_opds_client, db_session):
        """Valid username but wrong password should return 401."""
        await _insert_user(db_session, username="alice", password="correct")
        resp = await unauthed_opds_client.get(
            "/opds/",
            headers={"Authorization": _basic_auth_header("alice", "wrong")},
        )
        assert resp.status_code == 401

    async def test_nonexistent_user_returns_401(self, unauthed_opds_client):
        """Non-existent username should return 401."""
        resp = await unauthed_opds_client.get(
            "/opds/",
            headers={"Authorization": _basic_auth_header("nobody", "pass")},
        )
        assert resp.status_code == 401

    async def test_malformed_base64_returns_401(self, unauthed_opds_client):
        """Malformed Base64 in Authorization header should return 401."""
        resp = await unauthed_opds_client.get(
            "/opds/",
            headers={"Authorization": "Basic not-valid-base64!!!"},
        )
        assert resp.status_code == 401

    async def test_valid_credentials_returns_200(self, unauthed_opds_client, db_session):
        """Correct username and password should allow access (200)."""
        await _insert_user(db_session, username="bob", password="secret")
        resp = await unauthed_opds_client.get(
            "/opds/",
            headers={"Authorization": _basic_auth_header("bob", "secret")},
        )
        assert resp.status_code == 200

    async def test_all_endpoint_no_auth_returns_401(self, unauthed_opds_client):
        """Auth check should apply to /opds/all, not just root."""
        resp = await unauthed_opds_client.get("/opds/all")
        assert resp.status_code == 401

    async def test_gallery_detail_no_auth_returns_401(self, unauthed_opds_client):
        """Auth check should apply to /opds/gallery/{id} endpoint."""
        resp = await unauthed_opds_client.get("/opds/gallery/1")
        assert resp.status_code == 401
