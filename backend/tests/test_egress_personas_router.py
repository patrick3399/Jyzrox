"""Admin router /api/admin/personas (ADR 0022)."""

from unittest.mock import patch

import pytest

from db.models import Credential


@pytest.fixture(autouse=True)
def _persona_db(db_session_factory):
    with (
        patch("services.egress_persona.AsyncSessionLocal", db_session_factory),
        patch("services.credential.AsyncSessionLocal", db_session_factory),
    ):
        yield


async def test_create_persona_rejects_browser_and_user_agent_together(client):
    resp = await client.post(
        "/api/admin/personas", json={"name": "gw11", "user_agent": "UA", "browser_profile": "chrome"}
    )
    assert resp.status_code == 422


async def test_binding_same_account_to_second_persona_is_conflict(client, db_session):
    db_session.add(Credential(source="twitter", account="alt1", credential_type="cookies", is_active=True))
    await db_session.commit()
    a = (await client.post("/api/admin/personas", json={"name": "gw11", "proxy_url": "http://egress-11:8888"})).json()
    b = (await client.post("/api/admin/personas", json={"name": "gw12", "proxy_url": "http://egress-12:8888"})).json()

    ok = await client.put(f"/api/admin/personas/{a['id']}/accounts/twitter", json={"account": "alt1"})
    dup = await client.put(f"/api/admin/personas/{b['id']}/accounts/twitter", json={"account": "alt1"})

    assert ok.status_code == 200
    assert ok.json()["accounts"] == [{"source": "twitter", "account": "alt1"}]
    assert dup.status_code == 409


async def test_binding_unknown_credential_account_is_404(client):
    p = (await client.post("/api/admin/personas", json={"name": "gw13"})).json()
    resp = await client.put(f"/api/admin/personas/{p['id']}/accounts/twitter", json={"account": "nope"})
    assert resp.status_code == 404


async def test_patch_enabled_null_is_rejected_not_reported_as_name_conflict(client):
    p = (await client.post("/api/admin/personas", json={"name": "gw15"})).json()
    resp = await client.patch(f"/api/admin/personas/{p['id']}", json={"enabled": None})
    assert resp.status_code == 422


async def test_duplicate_persona_name_is_conflict(client):
    await client.post("/api/admin/personas", json={"name": "gw14"})
    resp = await client.post("/api/admin/personas", json={"name": "gw14"})
    assert resp.status_code == 409


async def test_persona_endpoints_reject_non_admin(make_client):
    async with make_client(user_id=2, role="member") as ac:
        assert (await ac.get("/api/admin/personas")).status_code == 403
        assert (await ac.post("/api/admin/personas", json={"name": "x"})).status_code == 403
        assert (await ac.post("/api/admin/personas/1/test")).status_code == 403
