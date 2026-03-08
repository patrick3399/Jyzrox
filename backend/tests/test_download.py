"""
Tests for download endpoints (/api/download/*).

Uses the `client` fixture (pre-authenticated). ARQ pool is mocked via
app.state.arq. Download jobs are stored in SQLite test DB.
"""

import uuid

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_job(db_session, url="https://e-hentai.org/g/123/abc/", status="queued", source="ehentai"):
    """Insert a download job directly via raw SQL (SQLite-compatible)."""
    job_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO download_jobs (id, url, source, status, progress) "
            "VALUES (:id, :url, :source, :status, :progress)"
        ),
        {"id": job_id, "url": url, "source": source, "status": status, "progress": "{}"},
    )
    await db_session.commit()
    return job_id


# ---------------------------------------------------------------------------
# Source auto-detection (unit tests — no HTTP needed)
# ---------------------------------------------------------------------------


class TestDetectSource:
    """Unit tests for _detect_source helper."""

    def test_pixiv_url(self):
        """pixiv.net URLs should be detected as 'pixiv'."""
        from routers.download import _detect_source

        assert _detect_source("https://www.pixiv.net/artworks/12345") == "pixiv"
        assert _detect_source("https://pixiv.net/en/artworks/67890") == "pixiv"

    def test_ehentai_url(self):
        """e-hentai.org URLs should be detected as 'ehentai'."""
        from routers.download import _detect_source

        assert _detect_source("https://e-hentai.org/g/123456/abcdef/") == "ehentai"

    def test_exhentai_url(self):
        """exhentai.org URLs should be detected as 'ehentai'."""
        from routers.download import _detect_source

        assert _detect_source("https://exhentai.org/g/123456/abcdef/") == "ehentai"

    def test_unknown_url(self):
        """Unrecognized domains should return 'unknown'."""
        from routers.download import _detect_source

        assert _detect_source("https://example.com/gallery/123") == "unknown"
        assert _detect_source("https://danbooru.donmai.us/posts/12345") == "unknown"


# ---------------------------------------------------------------------------
# Enqueue download
# ---------------------------------------------------------------------------


class TestEnqueueDownload:
    """POST /api/download/ — create a download job.

    Note: The enqueue endpoint uses ORM DownloadJob model with UUID and JSONB
    columns. SQLite doesn't natively support these PostgreSQL types, so the
    ORM INSERT may fail. These tests verify the route logic / validation;
    full integration requires PostgreSQL.
    """

    async def test_enqueue_missing_url(self, client):
        """Missing URL should return 422 validation error."""
        resp = await client.post("/api/download/", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# List jobs
# ---------------------------------------------------------------------------


class TestListJobs:
    """GET /api/download/jobs — paginated job listing."""

    async def test_empty_queue(self, client):
        """No jobs should return total=0."""
        resp = await client.get("/api/download/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["jobs"] == []

    async def test_list_returns_jobs(self, client, db_session):
        """Should return all inserted jobs."""
        await _insert_job(db_session, url="https://e-hentai.org/g/1/a/", status="queued")
        await _insert_job(db_session, url="https://pixiv.net/artworks/2", status="completed", source="pixiv")

        resp = await client.get("/api/download/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["jobs"]) == 2

    async def test_filter_by_status(self, client, db_session):
        """?status= should filter jobs by status."""
        await _insert_job(db_session, status="queued")
        await _insert_job(db_session, status="completed")

        resp = await client.get("/api/download/jobs", params={"status": "queued"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["jobs"][0]["status"] == "queued"

    async def test_pagination(self, client, db_session):
        """Pagination should limit results."""
        for i in range(5):
            await _insert_job(db_session, url=f"https://e-hentai.org/g/{i}/a/")

        resp = await client.get("/api/download/jobs", params={"page": 0, "limit": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["jobs"]) == 2


# ---------------------------------------------------------------------------
# Get / Cancel single job — raw SQL queries work for listing but ORM .get()
# uses UUID type matching which doesn't work on SQLite. These tests are
# marked as expected to require PostgreSQL for full integration.
# ---------------------------------------------------------------------------


class TestGetJob:
    """GET /api/download/jobs/{job_id}"""

    async def test_get_nonexistent_job(self, client):
        """Should return 404 for unknown job id."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/download/jobs/{fake_id}")
        assert resp.status_code == 404


class TestCancelJob:
    """DELETE /api/download/jobs/{job_id}"""

    async def test_cancel_nonexistent_job(self, client):
        """Should return 404 for unknown job id."""
        fake_id = str(uuid.uuid4())
        resp = await client.delete(f"/api/download/jobs/{fake_id}")
        assert resp.status_code == 404
