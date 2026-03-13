"""
Tests for export endpoints (/api/export/*).

Uses the `client` fixture (pre-authenticated). Export creates a ZIP in-memory
from gallery images. The tests cover:
- Auth requirement
- 404 for non-existent gallery
- 404 when gallery has no images
- Successful ZIP response with correct headers
- Size limit enforcement (413)

The export router uses `async_session` from core.database at module level.
We patch `routers.export.async_session` to redirect DB queries to the test DB.
"""

import io
import os
import tempfile
import zipfile
from unittest.mock import patch

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_gallery(db_session, title="Export Gallery", tags_array="[]"):
    """Insert a gallery and return its id."""
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, tags_array) "
            "VALUES ('local', :sid, :title, :tags)"
        ),
        {"sid": str(id(title)), "title": title, "tags": tags_array},
    )
    await db_session.commit()
    result = await db_session.execute(text("SELECT last_insert_rowid()"))
    return result.scalar()


async def _insert_image(
    db_session,
    gallery_id: int,
    page_num: int = 1,
    filename: str = "001.jpg",
    file_path: str | None = None,
    tags_array: str = "[]",
):
    """Insert a blob + image record.

    If file_path is given the blob is stored as 'external' so that
    resolve_blob_path() returns a Path pointing to that file.
    If file_path is None the blob uses 'cas' storage (file will not exist on
    disk, so the export router will skip it).
    """
    sha = f"sha_export_{page_num}_{gallery_id}_{abs(hash(file_path or ''))}"
    if file_path is not None:
        storage = "external"
        ext = os.path.splitext(file_path)[1] or ".jpg"
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 1
    else:
        storage = "cas"
        ext = ".jpg"
        file_size = 1

    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO blobs "
            "(sha256, file_size, extension, storage, external_path) "
            "VALUES (:sha, :fs, :ext, :storage, :ep)"
        ),
        {"sha": sha, "fs": file_size, "ext": ext, "storage": storage, "ep": file_path},
    )
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, blob_sha256, tags_array) "
            "VALUES (:gid, :pn, :fn, :sha, :tags)"
        ),
        {
            "gid": gallery_id,
            "pn": page_num,
            "fn": filename,
            "sha": sha,
            "tags": tags_array,
        },
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# GET /api/export/kohya/{gallery_id}
# ---------------------------------------------------------------------------


class TestExportKohya:
    """GET /api/export/kohya/{gallery_id} — Kohya-format ZIP export."""

    async def test_export_nonexistent_gallery_returns_404(self, client, db_session, db_session_factory):
        """Requesting export for a gallery that does not exist should return 404."""
        with patch("routers.export.async_session", db_session_factory):
            resp = await client.get("/api/export/kohya/99999")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_export_gallery_no_images_returns_404(self, client, db_session, db_session_factory):
        """Gallery with no images should return 404."""
        gid = await _insert_gallery(db_session, title="Empty Gallery")
        with patch("routers.export.async_session", db_session_factory):
            resp = await client.get(f"/api/export/kohya/{gid}")
        assert resp.status_code == 404
        assert "no images" in resp.json()["detail"].lower()

    async def test_export_gallery_with_images_missing_files_returns_empty_zip(
        self, client, db_session, db_session_factory
    ):
        """Gallery images whose file_path does not exist on disk yield an empty ZIP
        (the router skips missing files rather than erroring)."""
        gid = await _insert_gallery(db_session, title="Missing Files Gallery")
        await _insert_image(db_session, gid, page_num=1, filename="001.jpg", file_path="/nonexistent/001.jpg")
        await _insert_image(db_session, gid, page_num=2, filename="002.jpg", file_path="/nonexistent/002.jpg")

        with patch("routers.export.async_session", db_session_factory):
            resp = await client.get(f"/api/export/kohya/{gid}")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        # ZIP is valid but may have zero entries since files don't exist
        buf = io.BytesIO(resp.content)
        with zipfile.ZipFile(buf) as zf:
            assert isinstance(zf.namelist(), list)

    async def test_export_gallery_produces_valid_zip(self, client, db_session, db_session_factory):
        """Gallery with real image files should produce a valid ZIP with image + txt pairs."""
        gid = await _insert_gallery(db_session, title="Real Gallery", tags_array='["character:alice"]')

        # Create a temporary image file so the export can read it
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # minimal JPEG-like bytes
            tmp_path = f.name

        try:
            await _insert_image(
                db_session,
                gid,
                page_num=1,
                filename="page_001.jpg",
                file_path=tmp_path,
                tags_array='["artist:bob"]',
            )

            with patch("routers.export.async_session", db_session_factory):
                resp = await client.get(f"/api/export/kohya/{gid}")

            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/zip"
            assert f"gallery_{gid}_kohya.zip" in resp.headers.get("content-disposition", "")

            buf = io.BytesIO(resp.content)
            with zipfile.ZipFile(buf) as zf:
                names = zf.namelist()
                # Should contain the image and its companion .txt tag file
                assert "page_001.jpg" in names
                assert "page_001.txt" in names
                # Tag file should contain the tag strings
                tag_content = zf.read("page_001.txt").decode()
                assert len(tag_content) > 0
        finally:
            os.unlink(tmp_path)

    async def test_export_content_disposition_header(self, client, db_session, db_session_factory):
        """Response should set Content-Disposition attachment header with correct filename."""
        gid = await _insert_gallery(db_session)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"fake image data")
            tmp_path = f.name

        try:
            await _insert_image(
                db_session,
                gid,
                page_num=1,
                filename="img.jpg",
                file_path=tmp_path,
            )
            with patch("routers.export.async_session", db_session_factory):
                resp = await client.get(f"/api/export/kohya/{gid}")

            assert resp.status_code == 200
            cd = resp.headers.get("content-disposition", "")
            assert "attachment" in cd
            assert f"gallery_{gid}_kohya.zip" in cd
        finally:
            os.unlink(tmp_path)

    async def test_export_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/export/kohya/1")
        assert resp.status_code == 401

    async def test_export_size_limit_enforced(self, client, db_session, db_session_factory):
        """Gallery exceeding 2 GB total file size should return 413."""
        gid = await _insert_gallery(db_session)

        # Insert blob with file_size > 2 GB directly so the router's size check triggers
        _3gb = 3 * 1024 * 1024 * 1024
        sha = "sha_huge_blob_export_test"
        await db_session.execute(
            text(
                "INSERT OR IGNORE INTO blobs "
                "(sha256, file_size, extension, storage) "
                "VALUES (:sha, :fs, '.jpg', 'cas')"
            ),
            {"sha": sha, "fs": _3gb},
        )
        await db_session.execute(
            text(
                "INSERT INTO images (gallery_id, page_num, filename, blob_sha256) "
                "VALUES (:gid, 1, 'huge.jpg', :sha)"
            ),
            {"gid": gid, "sha": sha},
        )
        await db_session.commit()

        with patch("routers.export.async_session", db_session_factory):
            resp = await client.get(f"/api/export/kohya/{gid}")

        assert resp.status_code == 413
        assert "too large" in resp.json()["detail"].lower()
