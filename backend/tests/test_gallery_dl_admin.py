"""
Integration tests for the gallery-dl admin router (/api/admin/gallery-dl/*).

Uses the `client` fixture (authenticated as admin user_id=1).
External functions (get_current_version, get_latest_pypi_version,
_previous_version_dir) and core.queue.enqueue are mocked.

Covers previously uncovered lines: 25-28, 38-40, 49-54.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# GET /api/admin/gallery-dl/version (lines 25-28)
# ---------------------------------------------------------------------------


async def test_get_gallery_dl_version_returns_current_and_latest(client):
    """GET /version should return current and latest versions from mocked helpers."""
    with (
        patch(
            "worker.gallery_dl_venv.get_current_version",
            new_callable=AsyncMock,
            return_value="1.26.0",
        ),
        patch(
            "worker.gallery_dl_venv.get_latest_pypi_version",
            new_callable=AsyncMock,
            return_value="1.27.1",
        ),
    ):
        resp = await client.get("/api/admin/gallery-dl/version")

    assert resp.status_code == 200
    data = resp.json()
    assert data["current"] == "1.26.0"
    assert data["latest"] == "1.27.1"


async def test_get_gallery_dl_version_propagates_none_values(client):
    """Version endpoint tolerates None when version cannot be determined."""
    with (
        patch(
            "worker.gallery_dl_venv.get_current_version",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "worker.gallery_dl_venv.get_latest_pypi_version",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        resp = await client.get("/api/admin/gallery-dl/version")

    assert resp.status_code == 200
    data = resp.json()
    assert data["current"] is None
    assert data["latest"] is None


# ---------------------------------------------------------------------------
# POST /api/admin/gallery-dl/upgrade (lines 38-40)
# ---------------------------------------------------------------------------


async def test_upgrade_gallery_dl_with_version_enqueues_job(client):
    """POST /upgrade with a version body must enqueue job with that version."""
    mock_job = MagicMock()
    mock_job.key = "job-upgrade-001"
    mock_enqueue = AsyncMock(return_value=mock_job)

    with patch("core.queue.enqueue", mock_enqueue):
        resp = await client.post(
            "/api/admin/gallery-dl/upgrade",
            json={"version": "1.2.3"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "job-upgrade-001"
    mock_enqueue.assert_called_once_with("gdl_upgrade_job", version="1.2.3")


async def test_upgrade_gallery_dl_without_body_passes_none_version(client):
    """POST /upgrade with no body must enqueue job with version=None."""
    mock_job = MagicMock()
    mock_job.key = "job-upgrade-002"
    mock_enqueue = AsyncMock(return_value=mock_job)

    with patch("core.queue.enqueue", mock_enqueue):
        resp = await client.post("/api/admin/gallery-dl/upgrade")

    assert resp.status_code == 200
    mock_enqueue.assert_called_once_with("gdl_upgrade_job", version=None)


async def test_upgrade_gallery_dl_enqueue_returns_none_uses_unknown(client):
    """When enqueue returns None, job_id should fall back to 'unknown'."""
    with patch("core.queue.enqueue", AsyncMock(return_value=None)):
        resp = await client.post(
            "/api/admin/gallery-dl/upgrade",
            json={"version": "1.0.0"},
        )

    assert resp.status_code == 200
    assert resp.json()["job_id"] == "unknown"


# ---------------------------------------------------------------------------
# POST /api/admin/gallery-dl/rollback (lines 49-54)
# ---------------------------------------------------------------------------


async def test_rollback_gallery_dl_no_previous_version_returns_409(client):
    """When _previous_version_dir() returns None, rollback must return 409."""
    with patch(
        "worker.gallery_dl_venv._previous_version_dir",
        return_value=None,
    ):
        resp = await client.post("/api/admin/gallery-dl/rollback")

    assert resp.status_code == 409
    assert "rollback" in resp.json()["detail"].lower()


async def test_rollback_gallery_dl_with_previous_version_enqueues_job(client):
    """When a previous version exists, rollback must enqueue gdl_rollback_job."""
    mock_job = MagicMock()
    mock_job.key = "job-rollback-001"
    mock_enqueue = AsyncMock(return_value=mock_job)

    with (
        patch(
            "worker.gallery_dl_venv._previous_version_dir",
            return_value=Path("/opt/gallery-dl/prev"),
        ),
        patch("core.queue.enqueue", mock_enqueue),
    ):
        resp = await client.post("/api/admin/gallery-dl/rollback")

    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "job-rollback-001"
    mock_enqueue.assert_called_once_with("gdl_rollback_job")


async def test_rollback_gallery_dl_enqueue_returns_none_uses_unknown(client):
    """When enqueue returns None after rollback, job_id should be 'unknown'."""
    with (
        patch(
            "worker.gallery_dl_venv._previous_version_dir",
            return_value=Path("/opt/gallery-dl/prev"),
        ),
        patch("core.queue.enqueue", AsyncMock(return_value=None)),
    ):
        resp = await client.post("/api/admin/gallery-dl/rollback")

    assert resp.status_code == 200
    assert resp.json()["job_id"] == "unknown"
