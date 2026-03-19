"""API tests for /api/admin/sites endpoints.

These tests rely on two patches that the Backend Architect adds to conftest.py:
    patch("core.site_config.AsyncSessionLocal", db_session_factory)
    patch("core.site_config.get_redis", return_value=mock_redis)

The `site_configs` table is already present in _SQLITE_SCHEMA (conftest.py).
"""

import pytest


@pytest.mark.asyncio
async def test_list_sites_returns_all_known_sources(client):
    """GET /api/admin/sites returns all sources with effective params."""
    resp = await client.get("/api/admin/sites")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # Should include at least ehentai, pixiv, twitter
    source_ids = {s["source_id"] for s in data}
    assert "ehentai" in source_ids
    assert "pixiv" in source_ids
    assert "twitter" in source_ids
    # Each entry should have download params
    for entry in data:
        assert "download" in entry
        dl = entry["download"]
        assert "retries" in dl
        assert "concurrency" in dl


@pytest.mark.asyncio
async def test_get_site_returns_effective_params(client):
    """GET /api/admin/sites/ehentai returns merged config."""
    resp = await client.get("/api/admin/sites/ehentai")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_id"] == "ehentai"
    assert data["download"]["retries"] == 5  # _sites.py default
    assert data["download"]["inactivity_timeout"] == 600


@pytest.mark.asyncio
async def test_update_site_overrides_and_persists(client):
    """PUT /api/admin/sites/twitter updates overrides."""
    resp = await client.put(
        "/api/admin/sites/twitter",
        json={"download": {"retries": 8, "concurrency": 3}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["download"]["retries"] == 8
    assert data["download"]["concurrency"] == 3

    # Verify it persisted
    resp2 = await client.get("/api/admin/sites/twitter")
    assert resp2.json()["download"]["retries"] == 8


@pytest.mark.asyncio
async def test_update_rejects_invalid_concurrency(client):
    """PUT with concurrency=0 returns 400."""
    resp = await client.put(
        "/api/admin/sites/twitter",
        json={"download": {"concurrency": 0}},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_reset_field_reverts_to_default(client):
    """POST /reset removes specific override, reverting to _sites.py default."""
    # Set an override first
    await client.put(
        "/api/admin/sites/ehentai",
        json={"download": {"retries": 99}},
    )

    # Reset it
    resp = await client.post(
        "/api/admin/sites/ehentai/reset",
        json={"field_path": "download.retries"},
    )
    assert resp.status_code == 200
    assert resp.json()["download"]["retries"] == 5  # back to _sites.py default


@pytest.mark.asyncio
async def test_non_admin_cannot_access(make_client, db_session):
    """Member role cannot access admin sites API."""
    async with make_client(user_id=2, role="member") as ac:
        resp = await ac.get("/api/admin/sites")
        assert resp.status_code == 403
