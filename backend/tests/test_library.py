"""
Tests for library CRUD endpoints (/api/library/*).

Uses the `client` fixture (pre-authenticated). Gallery/image data is inserted
directly into the SQLite test DB.

Note: PostgreSQL-specific features (ARRAY contains, GIN index, pg_insert ON CONFLICT)
are not available in SQLite. Tests that would exercise those features are structured
to work with the basic query paths or are noted as SQLite-limited.
"""

import pytest
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_gallery(db_session, **overrides):
    """Insert a gallery into the test DB and return its id."""
    defaults = {
        "source": "ehentai",
        "source_id": "12345",
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
            "INSERT INTO galleries (source, source_id, title, title_jpn, category, "
            "language, pages, rating, favorited, download_status, tags_array) "
            "VALUES (:source, :source_id, :title, :title_jpn, :category, "
            ":language, :pages, :rating, :favorited, :download_status, :tags_array)"
        ),
        defaults,
    )
    await db_session.commit()
    result = await db_session.execute(text("SELECT last_insert_rowid()"))
    return result.scalar()


async def _insert_image(db_session, gallery_id, page_num=1, filename="001.jpg"):
    """Insert an image record for a gallery."""
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, width, height) "
            "VALUES (:gid, :pn, :fn, 1280, 1800)"
        ),
        {"gid": gallery_id, "pn": page_num, "fn": filename},
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Gallery list
# ---------------------------------------------------------------------------

class TestListGalleries:
    """GET /api/library/galleries — paginated gallery listing."""

    async def test_empty_library(self, client):
        """Empty library should return total=0 and empty list."""
        resp = await client.get("/api/library/galleries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["galleries"] == []

    async def test_list_returns_galleries(self, client, db_session):
        """Should return inserted galleries."""
        await _insert_gallery(db_session, source_id="1", title="Gallery A")
        await _insert_gallery(db_session, source_id="2", title="Gallery B")

        resp = await client.get("/api/library/galleries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["galleries"]) == 2

    async def test_pagination(self, client, db_session):
        """Pagination parameters should limit results correctly."""
        for i in range(5):
            await _insert_gallery(db_session, source_id=str(i), title=f"Gallery {i}")

        resp = await client.get("/api/library/galleries", params={"page": 0, "limit": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["galleries"]) == 2

    async def test_title_search(self, client, db_session):
        """Title search with ?q= should filter galleries."""
        await _insert_gallery(db_session, source_id="1", title="Naruto Doujin")
        await _insert_gallery(db_session, source_id="2", title="One Piece Fan Art")

        resp = await client.get("/api/library/galleries", params={"q": "naruto"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["galleries"][0]["title"] == "Naruto Doujin"

    async def test_favorited_filter(self, client, db_session):
        """?favorited=true should only return favorited galleries."""
        await _insert_gallery(db_session, source_id="1", title="Fav", favorited=1)
        await _insert_gallery(db_session, source_id="2", title="Not fav", favorited=0)

        resp = await client.get("/api/library/galleries", params={"favorited": "true"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["galleries"][0]["title"] == "Fav"

    async def test_source_filter(self, client, db_session):
        """?source= should filter by source."""
        await _insert_gallery(db_session, source="pixiv", source_id="1", title="Pixiv Art")
        await _insert_gallery(db_session, source="ehentai", source_id="2", title="EH Gallery")

        resp = await client.get("/api/library/galleries", params={"source": "pixiv"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["galleries"][0]["source"] == "pixiv"


# ---------------------------------------------------------------------------
# Single gallery
# ---------------------------------------------------------------------------

class TestGetGallery:
    """GET /api/library/galleries/{id}"""

    async def test_get_existing_gallery(self, client, db_session):
        """Should return gallery details for a valid id."""
        gid = await _insert_gallery(db_session, title="My Gallery")

        resp = await client.get(f"/api/library/galleries/{gid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == gid
        assert data["title"] == "My Gallery"
        assert "source" in data
        assert "rating" in data

    async def test_gallery_not_found(self, client):
        """Non-existent gallery id should return 404."""
        resp = await client.get("/api/library/galleries/99999")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Gallery images
# ---------------------------------------------------------------------------

class TestGetGalleryImages:
    """GET /api/library/galleries/{id}/images"""

    async def test_get_images(self, client, db_session):
        """Should return images ordered by page_num."""
        gid = await _insert_gallery(db_session)
        await _insert_image(db_session, gid, page_num=1, filename="001.jpg")
        await _insert_image(db_session, gid, page_num=2, filename="002.jpg")

        resp = await client.get(f"/api/library/galleries/{gid}/images")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gallery_id"] == gid
        assert len(data["images"]) == 2
        assert data["images"][0]["page_num"] == 1
        assert data["images"][1]["page_num"] == 2

    async def test_images_gallery_not_found(self, client):
        """Should return 404 when gallery doesn't exist."""
        resp = await client.get("/api/library/galleries/99999/images")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Gallery update (PATCH)
# ---------------------------------------------------------------------------

class TestUpdateGallery:
    """PATCH /api/library/galleries/{id}"""

    async def test_update_favorited(self, client, db_session):
        """Should toggle the favorited flag."""
        gid = await _insert_gallery(db_session, favorited=0)

        resp = await client.patch(
            f"/api/library/galleries/{gid}",
            json={"favorited": True},
        )
        assert resp.status_code == 200
        assert resp.json()["favorited"] is True

    async def test_update_rating(self, client, db_session):
        """Should update the rating."""
        gid = await _insert_gallery(db_session, rating=0)

        resp = await client.patch(
            f"/api/library/galleries/{gid}",
            json={"rating": 5},
        )
        assert resp.status_code == 200
        assert resp.json()["rating"] == 5

    async def test_update_nonexistent(self, client):
        """Updating a non-existent gallery should return 404."""
        resp = await client.patch(
            "/api/library/galleries/99999",
            json={"rating": 3},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Read progress
# ---------------------------------------------------------------------------

class TestReadProgress:
    """GET/POST /api/library/galleries/{id}/progress"""

    async def test_get_progress_default(self, client, db_session):
        """No progress saved should return last_page=0."""
        gid = await _insert_gallery(db_session)

        resp = await client.get(f"/api/library/galleries/{gid}/progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gallery_id"] == gid
        assert data["last_page"] == 0

    async def test_save_and_get_progress(self, client, db_session):
        """Saving progress should be retrievable."""
        gid = await _insert_gallery(db_session)

        # Save progress — note: this uses pg_insert ON CONFLICT which won't work
        # with SQLite. We test the GET path instead using direct DB insert.
        await db_session.execute(
            text("INSERT INTO read_progress (gallery_id, last_page) VALUES (:gid, :lp)"),
            {"gid": gid, "lp": 15},
        )
        await db_session.commit()

        resp = await client.get(f"/api/library/galleries/{gid}/progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_page"] == 15
        assert data["gallery_id"] == gid
