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
        text("INSERT INTO galleries (source, source_id, title, tags_array) VALUES ('local', :sid, :title, :tags)"),
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
                "INSERT OR IGNORE INTO blobs (sha256, file_size, extension, storage) VALUES (:sha, :fs, '.jpg', 'cas')"
            ),
            {"sha": sha, "fs": _3gb},
        )
        await db_session.execute(
            text("INSERT INTO images (gallery_id, page_num, filename, blob_sha256) VALUES (:gid, 1, 'huge.jpg', :sha)"),
            {"gid": gid, "sha": sha},
        )
        await db_session.commit()

        with patch("routers.export.async_session", db_session_factory):
            resp = await client.get(f"/api/export/kohya/{gid}")

        assert resp.status_code == 413
        assert "too large" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Regression: AIT-001 — Kohya caption format must follow trainer conventions
# ---------------------------------------------------------------------------


class TestExportCaptionFormat:
    """Caption .txt files must strip namespaces, filter non-trainable
    namespaces, and be deterministically sorted — AIT-001."""

    async def _export_caption(self, client, db_session, db_session_factory, gallery_tags, image_tags, query=""):
        """Insert a one-image gallery and return the caption .txt content."""
        gid = await _insert_gallery(db_session, title=f"Caption {gallery_tags}", tags_array=gallery_tags)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
            tmp_path = f.name

        try:
            await _insert_image(
                db_session,
                gid,
                page_num=1,
                filename="page_001.jpg",
                file_path=tmp_path,
                tags_array=image_tags,
            )
            with patch("routers.export.async_session", db_session_factory):
                resp = await client.get(f"/api/export/kohya/{gid}{query}")

            assert resp.status_code == 200
            buf = io.BytesIO(resp.content)
            with zipfile.ZipFile(buf) as zf:
                txt_names = [n for n in zf.namelist() if n.endswith(".txt")]
                assert len(txt_names) == 1
                return zf.read(txt_names[0]).decode()
        finally:
            os.unlink(tmp_path)

    async def test_caption_strips_namespace_prefix_and_sorts_stably(self, client, db_session, db_session_factory):
        """'namespace:name' tags must be written as bare names, sorted alphabetically.

        Before the fix, raw 'general:1girl' strings were joined in set() iteration
        order, producing captions trainers cannot use.
        """
        caption = await self._export_caption(
            client,
            db_session,
            db_session_factory,
            gallery_tags='["general:zebra", "character:alice"]',
            image_tags='["artist:bob"]',
        )
        assert caption == "alice, bob, zebra"

    async def test_caption_excludes_rating_language_metadata_namespaces_by_default(
        self, client, db_session, db_session_factory
    ):
        """rating:/language:/metadata: tags are not trainable concepts and must be
        excluded from captions by default."""
        caption = await self._export_caption(
            client,
            db_session,
            db_session_factory,
            gallery_tags='["rating:questionable", "language:japanese", "metadata:translated", "general:1girl"]',
            image_tags="[]",
        )
        assert caption == "1girl"

    async def test_caption_exclude_namespaces_override_keeps_all(self, client, db_session, db_session_factory):
        """Passing an empty exclude_namespaces query param disables filtering."""
        caption = await self._export_caption(
            client,
            db_session,
            db_session_factory,
            gallery_tags='["rating:safe", "general:1girl"]',
            image_tags="[]",
            query="?exclude_namespaces=",
        )
        assert caption == "1girl, safe"

    async def test_caption_underscores_to_spaces_option(self, client, db_session, db_session_factory):
        """underscores_to_spaces=true converts booru underscores to spaces."""
        caption = await self._export_caption(
            client,
            db_session,
            db_session_factory,
            gallery_tags='["general:long_hair"]',
            image_tags="[]",
            query="?underscores_to_spaces=true",
        )
        assert caption == "long hair"

    async def test_caption_bare_tags_without_namespace_are_kept(self, client, db_session, db_session_factory):
        """Tags without a ':' separator pass through unchanged (deduplicated with
        stripped namespaced twins)."""
        caption = await self._export_caption(
            client,
            db_session,
            db_session_factory,
            gallery_tags='["1girl", "general:1girl"]',
            image_tags="[]",
        )
        assert caption == "1girl"


# ---------------------------------------------------------------------------
# Regression: AIT-003 — export must exclude non-trainable file formats
# ---------------------------------------------------------------------------


class TestExportExtensionFilter:
    """Only trainer-usable image formats (jpg/png/webp) may enter the ZIP;
    everything else is excluded and recorded in manifest.json — AIT-003."""

    async def test_export_excludes_gif_and_records_manifest(self, client, db_session, db_session_factory):
        """A .gif page must not enter the ZIP (trainers reject it) and must be
        listed in manifest.json instead.

        Before the fix, gif/video/avif/heic files were zipped as-is.
        """
        import json

        gid = await _insert_gallery(db_session, title="Ext Filter Gallery", tags_array='["general:1girl"]')

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
            jpg_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as f:
            f.write(b"GIF89a" + b"\x00" * 100)
            gif_path = f.name

        try:
            await _insert_image(db_session, gid, page_num=1, filename="001.jpg", file_path=jpg_path)
            await _insert_image(db_session, gid, page_num=2, filename="002.gif", file_path=gif_path)

            with patch("routers.export.async_session", db_session_factory):
                resp = await client.get(f"/api/export/kohya/{gid}")

            assert resp.status_code == 200
            buf = io.BytesIO(resp.content)
            with zipfile.ZipFile(buf) as zf:
                names = zf.namelist()
                assert any(n.endswith("001.jpg") for n in names)
                assert not any(n.endswith("002.gif") for n in names), "gif must be excluded from export"
                assert not any(n.endswith("002.txt") for n in names), "excluded image must not get a caption"
                assert "manifest.json" in names
                manifest = json.loads(zf.read("manifest.json"))
                excluded = manifest["excluded"]
                assert len(excluded) == 1
                assert excluded[0]["filename"] == "002.gif"
                assert excluded[0]["reason"] == "unsupported_extension"
        finally:
            os.unlink(jpg_path)
            os.unlink(gif_path)

    async def test_export_all_trainable_formats_has_no_manifest(self, client, db_session, db_session_factory):
        """When every page is a trainable format, no manifest.json is emitted."""
        gid = await _insert_gallery(db_session, title="Clean Ext Gallery")

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
            tmp_path = f.name

        try:
            await _insert_image(db_session, gid, page_num=1, filename="001.jpg", file_path=tmp_path)

            with patch("routers.export.async_session", db_session_factory):
                resp = await client.get(f"/api/export/kohya/{gid}")

            assert resp.status_code == 200
            buf = io.BytesIO(resp.content)
            with zipfile.ZipFile(buf) as zf:
                assert "manifest.json" not in zf.namelist()
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Regression: edge case #129 — export ZIP arcname path traversal
# ---------------------------------------------------------------------------


class TestExportArcnameSanitization:
    """Export ZIP arcnames must not contain path components — edge case #129."""

    async def test_export_filename_with_path_traversal_is_sanitized(self, client, db_session, db_session_factory):
        """Image filename containing '../' must be sanitized in the ZIP arcname — edge case #129.

        Before the fix, img.filename was used as-is in zipfile.write(), allowing
        a crafted filename like '../../etc/passwd' to write outside the intended dir.
        """
        import re

        gid = await _insert_gallery(db_session, title="Traversal Test")

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
            tmp_path = f.name

        try:
            dangerous_filename = "../../etc/passwd.jpg"
            await db_session.execute(
                text(
                    "INSERT INTO blobs (sha256, file_size, extension, storage, external_path)"
                    " VALUES ('sha_traversal', 100, '.jpg', 'external', :fp)"
                ),
                {"fp": tmp_path},
            )
            await db_session.execute(
                text(
                    "INSERT INTO images (gallery_id, page_num, filename, blob_sha256)"
                    " VALUES (:gid, 1, :fn, 'sha_traversal')"
                ),
                {"gid": gid, "fn": dangerous_filename},
            )
            await db_session.commit()

            with patch("routers.export.async_session", db_session_factory):
                resp = await client.get(f"/api/export/kohya/{gid}")

            assert resp.status_code == 200
            buf = io.BytesIO(resp.content)
            with zipfile.ZipFile(buf) as zf:
                for name in zf.namelist():
                    assert ".." not in name, f"arcname '{name}' contains path traversal"
                    assert "/" not in name, f"arcname '{name}' contains directory separator"
                    assert re.match(r"^[\w.\-]+$", name), f"arcname '{name}' contains unsafe chars"
        finally:
            os.unlink(tmp_path)
