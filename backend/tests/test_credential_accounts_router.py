"""Admin endpoints for per-source credential accounts (ADR 0019)."""

from unittest.mock import AsyncMock, patch

import pytest

from services import credential as cred

_BASE = "/api/settings/credentials"


@pytest.fixture
def cred_db(db_session_factory):
    with patch("services.credential.AsyncSessionLocal", db_session_factory):
        yield db_session_factory


@pytest.fixture
def purge():
    with patch("routers.credential_accounts.purge_account_scoped_cache", new_callable=AsyncMock) as mock:
        yield mock


async def _seed_two_accounts(source: str = "ehentai") -> None:
    await cred.set_credential(source, "value-a", "cookie")
    await cred.set_credential(source, "value-b", "cookie", account="b")


class TestAccountEndpoints:
    async def test_list_accounts_never_exposes_values(self, client, cred_db):
        await _seed_two_accounts()

        resp = await client.get(f"{_BASE}/ehentai/accounts")

        assert resp.status_code == 200
        assert resp.json() == {
            "source": "ehentai",
            "accounts": [
                {"account": "default", "credential_type": "cookie", "is_active": True},
                {"account": "b", "credential_type": "cookie", "is_active": False},
            ],
        }
        assert "value-a" not in resp.text and "value-b" not in resp.text

    async def test_activate_account_switches_active_and_purges_account_cache(self, client, cred_db, purge):
        await _seed_two_accounts()

        resp = await client.post(f"{_BASE}/ehentai/active", json={"account": "b"})

        assert resp.status_code == 200
        assert await cred.get_credential("ehentai") == "value-b"
        purge.assert_awaited_once_with("ehentai")

    async def test_activate_unknown_account_returns_404_and_does_not_purge(self, client, cred_db, purge):
        await _seed_two_accounts()

        resp = await client.post(f"{_BASE}/ehentai/active", json={"account": "ghost"})

        assert resp.status_code == 404
        assert await cred.get_credential("ehentai") == "value-a"
        purge.assert_not_awaited()

    async def test_delete_active_account_with_other_accounts_returns_409(self, client, cred_db):
        await _seed_two_accounts()

        resp = await client.delete(f"{_BASE}/ehentai/accounts/default")

        assert resp.status_code == 409
        assert await cred.get_credential("ehentai") == "value-a"

    async def test_delete_inactive_account_keeps_active(self, client, cred_db):
        await _seed_two_accounts()

        resp = await client.delete(f"{_BASE}/ehentai/accounts/b")

        assert resp.status_code == 200
        assert [a["account"] for a in await cred.list_accounts("ehentai")] == ["default"]

    async def test_account_endpoints_reject_non_admin(self, make_client, cred_db):
        async with make_client(user_id=2, role="member") as ac:
            assert (await ac.get(f"{_BASE}/ehentai/accounts")).status_code == 403
            assert (await ac.post(f"{_BASE}/ehentai/active", json={"account": "b"})).status_code == 403
            assert (await ac.delete(f"{_BASE}/ehentai/accounts/b")).status_code == 403

    async def test_account_endpoints_require_login(self, unauthed_client):
        assert (await unauthed_client.get(f"{_BASE}/ehentai/accounts")).status_code == 401


class TestExistingCredentialEndpointsWithAccounts:
    async def test_save_passes_named_account_to_the_service(self, client):
        with patch("routers.settings.set_credential", new_callable=AsyncMock, return_value="alt") as mock_set:
            resp = await client.post(
                f"{_BASE}/site", json={"source": "twitter", "cookies": "auth_token=abc", "account": "alt"}
            )

        assert resp.status_code == 200
        assert mock_set.call_args.kwargs["account"] == "alt"

    async def test_save_without_account_targets_the_active_account(self, client):
        with patch("routers.settings.set_credential", new_callable=AsyncMock, return_value="default") as mock_set:
            resp = await client.post(f"{_BASE}/site", json={"source": "twitter", "cookies": "auth_token=abc"})

        assert resp.status_code == 200
        assert mock_set.call_args.kwargs["account"] is None

    async def test_save_rejects_invalid_account_name(self, client):
        with patch("routers.settings.set_credential", new_callable=AsyncMock) as mock_set:
            resp = await client.post(
                f"{_BASE}/site", json={"source": "twitter", "cookies": "auth_token=abc", "account": "bad name"}
            )

        assert resp.status_code == 422
        mock_set.assert_not_awaited()

    async def test_delete_credential_with_several_accounts_returns_409(self, client, cred_db):
        await _seed_two_accounts("twitter")

        resp = await client.delete(f"{_BASE}/twitter")

        assert resp.status_code == 409
        assert len(await cred.list_accounts("twitter")) == 2

    async def test_list_credentials_reports_active_account_and_count(self, client, cred_db):
        await _seed_two_accounts("twitter")

        resp = await client.get(_BASE)

        assert resp.json() == {"twitter": {"configured": True, "account": "default", "accounts": 2}}
