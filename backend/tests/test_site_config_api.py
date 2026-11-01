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
async def test_update_site_spread_personas_persists_and_defaults_off(client):
    """PUT download.spread_personas=true is accepted and echoed (ADR 0022); default is off."""
    before = await client.get("/api/admin/sites/twitter")
    assert before.json()["download"]["spread_personas"] is False

    resp = await client.put(
        "/api/admin/sites/twitter",
        json={"download": {"spread_personas": True}},
    )
    assert resp.status_code == 200
    assert resp.json()["download"]["spread_personas"] is True

    resp2 = await client.get("/api/admin/sites/twitter")
    assert resp2.json()["download"]["spread_personas"] is True


@pytest.mark.asyncio
async def test_update_site_rejects_non_boolean_spread_personas_with_400(client):
    """PUT download.spread_personas="yes" returns 400 instead of storing a truthy string."""
    resp = await client.put(
        "/api/admin/sites/twitter",
        json={"download": {"spread_personas": "yes"}},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_rejects_invalid_concurrency(client):
    """PUT with concurrency=0 returns 400."""
    resp = await client.put(
        "/api/admin/sites/twitter",
        json={"download": {"concurrency": 0}},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_site_rejects_socks5_proxy_url_with_400_and_does_not_persist(client):
    """PUT with a socks5:// proxy_url returns 400 instead of storing a proxy no download can use."""
    resp = await client.put(
        "/api/admin/sites/twitter",
        json={"download": {"proxy_url": "socks5://127.0.0.1:1080", "retries": 9}},
    )
    assert resp.status_code == 400
    assert "SOCKS proxies are not supported" in resp.json()["detail"]

    # The whole update is refused, so the valid field next to it is not stored either.
    resp2 = await client.get("/api/admin/sites/twitter")
    assert resp2.json()["download"]["retries"] != 9


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


@pytest.mark.asyncio
async def test_reset_download_section_endpoint_returns_200(client):
    """The PWA's 'reset all' posts field_path='download'; it used to 400 (needed 'section.field')."""
    await client.put(
        "/api/admin/sites/twitter",
        json={"download": {"retries": 8, "concurrency": 3, "sleep_download": 2}},
    )

    resp = await client.post("/api/admin/sites/twitter/reset", json={"field_path": "download"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["download"]["retries"] == 4
    assert data["download"]["concurrency"] == 2
    assert data["download"]["sleep_download"] is None
    assert data["overridden"] == []


@pytest.mark.asyncio
async def test_reset_unknown_section_endpoint_returns_400(client):
    resp = await client.post("/api/admin/sites/twitter/reset", json={"field_path": "bogus"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_site_sleep_longer_than_inactivity_timeout_returns_400(client):
    resp = await client.put("/api/admin/sites/instagram", json={"download": {"sleep_download": 400}})
    assert resp.status_code == 400
    assert "inactivity_timeout" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_site_response_lists_overridden_and_defaults(client):
    """Response carries defaults (Jyzrox layer), overridden keys and the extractor_defaults hint."""
    await client.put(
        "/api/admin/sites/ehentai",
        json={"download": {"retries": 8, "sleep_download": [1, 3]}},
    )

    data = (await client.get("/api/admin/sites/ehentai")).json()

    assert data["download"]["retries"] == 8
    assert data["download"]["sleep_download"] == [1, 3]
    assert data["defaults"]["retries"] == 5  # _sites.py default, not the override
    assert data["defaults"]["sleep_download"] is None
    assert set(data["defaults"]) == set(data["download"])
    assert sorted(data["overridden"]) == ["retries", "sleep_download"]
    assert data["adaptive"] == []
    assert set(data["extractor_defaults"]) == {"sleep_request", "sleep_download"}


@pytest.mark.asyncio
async def test_site_response_without_row_has_empty_overridden_and_adaptive(client):
    data = (await client.get("/api/admin/sites/twitter")).json()

    assert data["overridden"] == []
    assert data["adaptive"] == []
    assert data["defaults"] == data["download"]
    assert "sleep_download" in data["download"]
    for entry in (await client.get("/api/admin/sites")).json():
        assert {"defaults", "overridden", "adaptive", "extractor_defaults"} <= set(entry)


def test_site_response_adaptive_excludes_overridden_fields():
    """'adaptive' = auto-tuned keys the admin has not pinned; an override wins and hides the marker."""
    from core.site_config import DownloadParams
    from db.models import SiteConfig
    from routers.site_config import _build_site_response

    row = SiteConfig(
        source_id="twitter",
        overrides={"download": {"retries": 8}},
        adaptive={"download": {"retries": 6, "concurrency": 3}},
    )
    resp = _build_site_response("twitter", DownloadParams(retries=8, concurrency=3), row)

    assert resp["overridden"] == ["retries"]
    assert resp["adaptive"] == ["concurrency"]
